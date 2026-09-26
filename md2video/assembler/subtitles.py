"""烧录字幕（知识区格式 P0）：timeline text cue → ASS → libass 逐段叠加。

字幕的定位是**文字的唯一载体**（知识区格式：画面 + 字幕 + 解说）。白名单
与 bundle SRT 导出一致：只上 content / appendix（标题卡与 section header
有自己的屏上位置，不走字幕）。更关键的一刀：只有**真的被朗读的段**才上字
幕——朗读事实优先取 execution-assets 的音频资产（音频按 segment_id 绑定，
不依赖列表顺序），资产缺位时回退到 plan 的 audio_request 判定。

P0 第三条选段规则（与前两条同层同性质）：**组件显示且被朗读的文本，字幕
让位**——文字载体归组件时字幕跳过该段（回退 = 朗读且无组件文字才上字幕）。
组件是否“显示了这段文字”由注册契约 `displayed_texts(payload)` 纯函数裁决；
组件未注册 / 未安装 / 未声明 → 无法回答时一律**保留字幕**（宁可重复，不可
丢字：降级路径下引擎默认渲染的朗读段不画正文，字幕是唯一文字载体）。
timeline text facts 保留不删（组件显示它也是可见事实），只在装配消费时跳过。

ASS 而非逐段 drawtext：libass 处理中文/换行/样式，文本零转义（花括号
消毒即可），一条 subtitles 滤镜叠加在全部视频滤镜之后（字幕永不被盖）。
构建是纯函数、逐字节确定；任何字幕问题都不许阻断成片（调用方降级）。
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List

# 与 bundle SRT 白名单一致：挂屏文本（标题/header）不进字幕轨
SUBTITLE_SEGMENT_TYPES = ("content", "appendix")

# v1 从简：底边居中、白字黑边；样式接管归 knowledge pack
DEFAULT_FONT_NAME = "Microsoft YaHei"
DEFAULT_FONT_SIZE_RATIO = 0.045
DEFAULT_MARGIN_V_RATIO = 0.06
DEFAULT_OUTLINE_PX = 2


def extract_subtitle_entries(
    plan,
    timeline_path: Path | None,
    execution_assets=None,
) -> List[Dict[str, Any]]:
    """timeline text facts → 字幕条目（只留被朗读的 content/appendix）。

    朗读事实：execution_assets 的音频资产优先（segment_id 绑定），缺位时
    回退 plan 的 audio_request 判定。第三条规则：组件已显示的文本让位
    （P0，判定失败一律保留字幕）。timeline 缺失/无 text 返回空表。
    """
    if not timeline_path or not Path(timeline_path).exists():
        return []
    data = json.loads(Path(timeline_path).read_text(encoding="utf-8"))
    text_facts = data.get("text", [])

    narrated_ids = _narrated_segment_ids(plan, execution_assets)
    component_displayed = _component_displayed_texts(plan)

    entries: List[Dict[str, Any]] = []
    for fact in text_facts:
        if fact.get("segment_type") not in SUBTITLE_SEGMENT_TYPES:
            continue
        segment_id = fact.get("segment_id", "")
        if segment_id not in narrated_ids:
            continue
        text = str(fact.get("text", "")).strip()
        if not text:
            continue
        # 第三条规则：该段所属场的组件把这句话画在了画面上 → 字幕让位
        if text in component_displayed.get(str(fact.get("scene_id", "")), ()):
            continue
        entries.append({
            "segment_id": segment_id,
            "text": text,
            "start": float(fact["start"]),
            "end": float(fact["end"]),
        })
    entries.sort(key=lambda e: e["start"])
    return entries


def _component_displayed_texts(plan) -> Dict[str, set]:
    """scene_id → 该场组件画上屏的文本集合（P0 字幕让位判定）。

    判定口径镜像调度层 `_scene_component_payloads` 的 resolved 条件：
    场声明了组件且**已注册 + 已安装**才作数；否则该场不进返回表（调用方
    对缺项一律保留字幕）。payload 从 plan 构造（scene shots →
    segment_ids → segments），同 id 复现的场合并（A8.1 画布语义）。任何
    异常只降级不阻断（返回表缺项 = 保留字幕）。
    """
    scenes_by_id: Dict[str, list] = {}
    for scene in plan.scenes:
        if getattr(scene, "component", None):
            scenes_by_id.setdefault(scene.id, []).append(scene)
    if not scenes_by_id:
        return {}

    from md2video.components.registry import (
        displayed_texts_for,
        get_component,
        is_installed,
    )

    segment_by_id = {seg.id: seg for seg in plan.segments}
    result: Dict[str, set] = {}
    for scene_id, entries in scenes_by_id.items():
        try:
            ref = entries[0].component
            if get_component(ref) is None or not is_installed(ref):
                continue
            seen_ids: List[str] = []
            for scene in entries:
                for shot in scene.shots:
                    for seg_id in shot.segment_ids:
                        if seg_id not in seen_ids:
                            seen_ids.append(seg_id)
            payload = [
                {
                    "segment_id": seg_id,
                    "segment_type": (
                        segment_by_id[seg_id].segment_type
                        if seg_id in segment_by_id else ""
                    ),
                    "text": (
                        segment_by_id[seg_id].text
                        if seg_id in segment_by_id else ""
                    ),
                }
                for seg_id in seen_ids
            ]
            displayed = displayed_texts_for(ref, payload)
            if displayed is None:
                continue  # 无法回答 → 保留字幕
            result[scene_id] = {str(t).strip() for t in displayed if str(t).strip()}
        except Exception as exc:  # noqa: BLE001 - 字幕问题只降级不阻断
            print(f"  Subtitle warning (component dedup skipped for {scene_id}): {exc}")
    return result


def _narrated_segment_ids(plan, execution_assets) -> set[str]:
    if execution_assets is not None:
        return {
            asset.segment_id
            for asset in execution_assets.audio_assets
            if asset.path and asset.duration > 0
        }
    return {
        segment.id
        for segment in plan.segments
        if segment.audio_request is not None
        and segment.segment_type in SUBTITLE_SEGMENT_TYPES
    }


def _ass_time(seconds: float) -> str:
    """ASS 时码 H:MM:SS.CC（厘秒）。"""
    total = max(0.0, float(seconds))
    centis = int(round(total * 100))
    hours, rem = divmod(centis, 3600 * 100)
    minutes, rem = divmod(rem, 60 * 100)
    secs, cs = divmod(rem, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"


# ===== P0-4 CJK 折行（token 化 + 均分行 + 禁则）=====
#
# 实测当前 libass（0.17.4, directwrite）对无空格中文长句**不做断行**、
# 直接水平裁边——不能指望渲染端 WrapStyle，构建期必须手动折行（见
# test_long_cjk_line_is_pre_wrapped）。旧算法等宽硬切：词中断行
# （「高/度。」）、孤字末行（「圈。」）、ASCII 词被腰斩都它导致。
# 新算法三步：①token 化（ASCII 词/数字串原子化，空格贴前词）→
# ②按总长均分行（每行长度逼近 total/n，孤行天然消失）→ ③禁则修正
# （行首避收尾标点/弱字、行尾避开括号，界标上下搬移，有界迭代）。
# 不引分词依赖（词典级避词断行挂 P0-5 复检触发器，见 TODO 决策）。

# 行首禁则：收尾标点（含 ASCII）
_CLOSING_PUNCT = set("，。、；：？！）】》…”’\"'…,;:?!)]}")
# 行首禁则：助词/量词/连词/介词（小字表；词典级避词断行不入 v1，
# 挂 P0-5 复检触发器，见 TODO 决策）
_WEAK_LINE_START = set(
    "的了着过是在和与或但而就也都把被让从向对接给比为以之其得地个及" 
    "而且只再并于给跟同将任无论不管把被从对给"
)
# 行尾禁则：开括号/开引号不能落行尾（必须与后文同行）
_OPENING_PUNCT = set("（【《「『“‘\"'([{")

# ASCII 词/数字/路径/版本号等原子（含内部分隔符），空格贴前词：
# 线性扫描、逐字确定，保证 “ffmpeg 480x854” 永不从中间断开
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-/+@#%]*")


def _tokenize(text: str) -> List[str]:
    """折行原子：ASCII 串（+尾随空格）为一个原子，其余逐字为原子。"""
    atoms: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        match = _ASCII_TOKEN_RE.match(text, i)
        if match:
            token = match.group(0)
            i = match.end()
            # 空格贴前词：断行发生在空格之后，下一行不以空格开头
            while i < n and text[i] == " ":
                token += " "
                i += 1
            atoms.append(token)
        else:
            atoms.append(text[i])
            i += 1
    return atoms


def _line_width(line: List[str]) -> int:
    return sum(len(atom) for atom in line)


def _balanced_split(atoms: List[str], per_line: int) -> List[List[str]]:
    """均分行：按均匀目标（divmod）逐行填充，行间长度均衡。

    均衡 + 孤行回填（`_repair_orphan_last`）一起把旧硬切（10+2）的
    「圈。」单占一行治掉。ASCII 原子跨目标会有溢出（宽度按全角算，
    像素上反而偏短，安全方向），溢出造成的末行挨饿由回填兜底。
    至少一行，原子不可再分。
    """
    total = _line_width(atoms)
    # 容差：总长 ≤ per_line+1 视为单行（旧行为允许 pull-up 后 11 字单行、
    # 溢出 1 字进侧边距；守住 test_wrap_pullup_never_empties_text）
    if total <= per_line + 1:
        return [atoms]
    n_lines = math.ceil(total / per_line)

    base, rem = divmod(total, n_lines)
    targets = [base + 1] * rem + [base] * (n_lines - rem)

    lines: List[List[str]] = []
    idx = 0
    for k, target in enumerate(targets):
        if k == n_lines - 1:
            lines.append(atoms[idx:])
            break
        acc = 0
        start = idx
        # 填到目标为止（CJK 原子 1 字，恰好命中）；原子跨界允许溢出，
        # 但不得吃光留给后续行的原子（每行至少 1 个）
        while idx < len(atoms) - (n_lines - k - 1) and acc < target:
            acc += len(atoms[idx])
            idx += 1
        lines.append(atoms[start:idx])
    return [line for line in lines if line]


# 末行/上一行最小宽度：短于它就算孤行，观众看着别扭（体检问题 4）
_MIN_LAST_LINE = 3


def _repair_orphan_last(lines: List[List[str]]) -> List[List[str]]:
    """孤行回填：末行过短时从上一行尾部搬原子，上一行也会变短则合并。

    与 `_fix_break_rules` 同一套头部禁则（搬下的原子做行首不得是收尾
    标点/弱字，否则禁则把它拉回去，两函数打架）；上一行搬完或搬后会
    变孤行 → 两行合并。每轮要么合并（行数减一）要么搬（上一行变短），
    有界终止。
    """
    for _ in range(64):
        if len(lines) < 2:
            break
        last = lines[-1]
        head = last[0][0] if last else ""
        head_ok = head == "" or (
            head not in _CLOSING_PUNCT and head not in _WEAK_LINE_START
        )
        if _line_width(last) >= _MIN_LAST_LINE and head_ok:
            break
        prev = lines[-2]
        if not prev:
            lines[-2:] = [prev + last]
            continue
        # 上一行只剩 1 个原子，或搬完自己会变孤行 → 合并
        if len(prev) == 1 or _line_width(prev) - len(prev[-1]) < _MIN_LAST_LINE:
            lines[-2:] = [prev + last]
            continue
        moved = prev.pop()
        lines[-1] = [moved] + last
    return [line for line in lines if line]


def _fix_break_rules(lines: List[List[str]]) -> List[List[str]]:
    """禁则修正：行首收尾标点/弱字上提，行尾开括号下压。

    界标在相邻行间搬移（零丢失由调用方不变量保证）；有界迭代（≤4 轮）
    保证终止。不产生空行（搬移前检查源行长度）。
    """
    for _ in range(4):
        changed = False
        # 行首禁则：上提到上一行尾（收尾标点到行尾是正确归宿）
        for i in range(1, len(lines)):
            while lines[i] and lines[i - 1]:
                head = lines[i][0][0]
                if head not in _CLOSING_PUNCT and head not in _WEAK_LINE_START:
                    break
                # 张字上提仅当上一行不会因此变得过长超过它自己……不再加
                # 宽度约束：估宽本身保守（ASCII 按全角算），且旧行为同样
                # 允许 pull-up 溢出一个字符（在侧边距内，不裁字）。
                lines[i - 1].append(lines[i][0])
                lines[i] = lines[i][1:]
                changed = True
        # 行尾禁则：开括号下压到下一行行首（与后文同行）
        for i in range(len(lines) - 1):
            while lines[i] and lines[i + 1]:
                tail = lines[i][-1][-1]
                if tail not in _OPENING_PUNCT:
                    break
                moved = lines[i].pop()
                lines[i + 1].insert(0, moved)
                changed = True
                if not lines[i]:
                    break
        if not changed:
            break
    return [line for line in lines if line]


def _wrap_cjk_text(
    text: str,
    video_width: int,
    font_size: int,
    side_margin: int = 40,
) -> str:
    """按像素宽度预换行（行间用 ASS 的 \\N）。P0-4 升级版。

    三步：token 化（ASCII 原子）→ 均分行（消孤行）→ 禁则修正
    （行首避收尾标点/弱字、行尾避开括号）。宽度估算按全角保守
    （ASCII 实际更窄，行更短，安全方向）。不变量：折行后文本零丢失、
    无空行、无行内硬断的 ASCII 词（单测锁定）。
    """
    usable = max(80, video_width - 2 * side_margin)
    per_line = max(4, int(usable // max(1, font_size)))
    sanitized = _sanitize_text(text)
    if len(sanitized) <= per_line:
        return sanitized

    lines = _balanced_split(_tokenize(sanitized), per_line)
    lines = _fix_break_rules(lines)
    lines = _repair_orphan_last(lines)
    lines = _fix_break_rules(lines)
    # 零丢失硬不变量：算法只搬原子不丢原子；违反 = 算法 bug，直接响亮失败
    assert "".join("".join(line) for line in lines) == sanitized, \
        "wrap must not lose text"
    return "\\N".join("".join(line) for line in lines)


def _sanitize_text(text: str) -> str:
    """ASS 文本消毒：花括号是 override 标签语法，必须换成普通括号。"""
    return str(text).replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass_file(
    entries: List[Dict[str, Any]],
    video_width: int,
    video_height: int,
    out_path: Path,
    font_name: str = DEFAULT_FONT_NAME,
    font_size_ratio: float = DEFAULT_FONT_SIZE_RATIO,
    margin_v_ratio: float = DEFAULT_MARGIN_V_RATIO,
    outline_px: int = DEFAULT_OUTLINE_PX,
) -> Path:
    """字幕条目 → ASS 文件（逐字节确定）。"""
    font_size = max(12, round(video_height * font_size_ratio))
    margin_v = max(8, round(video_height * margin_v_ratio))
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {video_width}\n"
        f"PlayResY: {video_height}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Sub,{font_name},{font_size},&H00FFFFFF,&H00FFFFFF,"
        f"&H00101010,&H96000000,0,0,0,0,100,100,0,0,1,{outline_px},1,"
        f"2,40,40,{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
    )
    lines = [header]
    for entry in entries:
        wrapped = _wrap_cjk_text(
            entry["text"], video_width, font_size, side_margin=40,
        )
        lines.append(
            f"Dialogue: 0,{_ass_time(entry['start'])},{_ass_time(entry['end'])},"
            f"Sub,,0,0,0,,{wrapped}\n"
        )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(lines), encoding="utf-8")
    return out_path


def escape_filter_path(path: Path | str) -> str:
    """文件路径 → ffmpeg 滤镜参数安全写法（Windows 盘符冒号是主要雷区）。"""
    text = str(path).replace("\\", "/").replace("'", "\\'")
    return text.replace(":", "\\:")
