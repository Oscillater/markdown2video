from pathlib import Path
import re

# ========== 辅助解析函数 ==========
def _parse_music_declaration(line):
    """
    支持格式（大小写不敏感）：
      [music: name="轻柔钢琴", src="assets/piano.mp3"]
      [music: name=bgm, src=/path/to/bgm.mp3]
      Music: name=bgm, src=...   或  音乐: name=..., src=...
    返回 (name, src) 或 None
    """
    line = line.strip()
    # 方括号形式
    m = re.match(r'^\[music:\s*(.+)\]\s*$', line, re.IGNORECASE)
    body = None
    if m:
        body = m.group(1)
    else:
        m2 = re.match(r'^(?:music|音乐)\s*[:：]\s*(.+)$', line, re.IGNORECASE)
        if m2:
            body = m2.group(1)
    if not body:
        return None
    # 提取 name 和 src 键值（简单 k=v, 支持引号）
    name = None
    src = None
    for part in re.split(r'\s*,\s*', body):
        kv = re.match(r'^\s*name\s*=\s*(?:"([^"]+)"|\'([^\']+)\'|(.+))\s*$', part, re.IGNORECASE)
        if kv:
            name = (kv.group(1) or kv.group(2) or kv.group(3)).strip()
            continue
        kv2 = re.match(r'^\s*src\s*=\s*(?:"([^"]+)"|\'([^\']+)\'|(.+))\s*$', part, re.IGNORECASE)
        if kv2:
            src = (kv2.group(1) or kv2.group(2) or kv2.group(3)).strip()
    if name and src:
        return name, src
    return None

def _parse_music_marker(line):
    """
    支持格式：
      [music_start bgm]
      [music_end "轻柔钢琴"]
      <music_start bgm>  或者 <> 形式也支持
    返回 (kind, name) 或 None，kind 为 'start' 或 'end'
    """
    s = line.strip()
    # 方括号或尖括号
    m = re.match(r'^[\[\<]\s*music_(start|end)\s+(?:"([^"]+)"|\'([^\']+)\'|([^\]\>]+))\s*[\]\>]\s*$', s, re.IGNORECASE)
    if not m:
        return None
    kind = m.group(1).lower()
    name = (m.group(2) or m.group(3) or m.group(4)).strip()
    return kind, name

# ========== 分句函数 ==========
def custom_sentence_split(text, max_len=12):
    stripped = text.strip()
    # 如果整行是音乐声明或音乐起止标记，不拆句
    if _parse_music_declaration(stripped) or _parse_music_marker(stripped):
        return [stripped]

    sentence_enders = re.compile(r'(。|！|？|；|…{1,2})(?!(」|”))')
    parts = sentence_enders.split(text)

    grouped = []
    i = 0
    while i < len(parts):
        if parts[i] and re.fullmatch(r'[。！？，；…——]', parts[i].strip()):
            grouped.append(parts[i].strip())
            i += 1
            continue
        if i + 1 < len(parts):
            first = parts[i] or ""
            second = parts[i+1] or ""
            grouped.append(first.strip() + second.strip())
            i += 2
        else:
            if parts[i]:
                grouped.append(parts[i].strip())
            i += 1

    final_sentences = []
    for sent in grouped:
        buffer = ""
        soft_parts = re.split(r'(，|、|——)', sent)
        for part in soft_parts:
            buffer += part
            if len(buffer) >= max_len:
                if not re.fullmatch(r'[。！？，；…——]', buffer.strip()):
                    final_sentences.append(buffer.strip())
                buffer = ""
        if buffer:
            if not re.fullmatch(r'[。！？，；…——]', buffer.strip()):
                final_sentences.append(buffer.strip())
    cleaned_sentences = []
    for sentence in final_sentences:
        cleaned_sentence = re.sub(r'^[^\w“《「（]*|[^\w%”》」）]*$', '', sentence)
        cleaned_sentences.append(cleaned_sentence)

    return cleaned_sentences

# ========== Markdown解析函数 ==========
def parse_markdown_sections(text):
    lines = text.splitlines()
    sections = {
        "h1": None,
        "h2": None,
        "contents": [],
        "appendix": [],
        "music": {}   # name -> src
    }

    # 先从顶部连续行中收集 music 声明（直到遇到第一个非空且非声明行）
    idx = 0
    while idx < len(lines):
        raw = lines[idx]
        if not raw.strip():
            idx += 1
            continue
        parsed = _parse_music_declaration(raw)
        if parsed:
            name, src = parsed
            sections["music"][name] = src
            # 清空该行，避免后续被当成正文
            lines[idx] = ""
            idx += 1
            continue
        break

    current_h3 = None
    current_text_block = []
    is_appendix = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # 音乐起止标记单独作为段保留
        marker = _parse_music_marker(stripped)
        if marker:
            # 将标记作为一段（不作为标题或正文的一部分）
            if is_appendix:
                sections["appendix"].append(stripped)
            else:
                current_text_block.append(stripped)
            continue

        if stripped.startswith("# "):
            sections["h1"] = stripped[2:].strip()
        elif stripped.startswith("## "):
            sections["h2"] = stripped[3:].strip()
        elif stripped.startswith("### "):
            if current_h3:
                # 将当前 h3 和正文存储为字典，正文为分句后的嵌套列表
                sections["contents"].append({
                    "h3": current_h3,
                    "text": [custom_sentence_split(paragraph) for paragraph in current_text_block]
                })
            current_h3 = stripped[4:].strip()
            current_text_block = []
        elif stripped == "---":
            is_appendix = True
            if current_h3:
                sections["contents"].append({
                    "h3": current_h3,
                    "text": [custom_sentence_split(paragraph) for paragraph in current_text_block]
                })
                current_h3 = None
                current_text_block = []
        else:
            if is_appendix:
                if stripped:  # 忽略空行
                    sections["appendix"].append(stripped)
            else:
                if stripped:  # 忽略空行
                    current_text_block.append(stripped)

    if current_h3 and current_text_block:
        sections["contents"].append({
            "h3": current_h3,
            "text": [custom_sentence_split(paragraph) for paragraph in current_text_block]
        })

    return sections

# ========== 读取文件并解析 ==========
def parse_markdown_file(md_path):
    path = Path(md_path)
    if not path.exists():
        print(f"❌ 找不到文件: {md_path}")
        return None
    text = path.read_text(encoding="utf-8")
    sections = parse_markdown_sections(text)

    print(sections)

    return sections

print(parse_markdown_file("example.md"))