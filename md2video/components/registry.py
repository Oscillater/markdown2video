"""表现组件注册表（A8）。

表现组件 = 接管一个 scene 正文画面的 Remotion 组件。契约：输入 =
文字 + 每段可见窗口 + 画布尺寸；输出 = 自由画面——配色/字体/排版/
动效由组件自带，不消费 pack token。两条底线：组件不改时间事实
（可见窗口由调度器按音频事实裁决，音频绑定留在 Node wrapper）；
确定性渲染（禁 random/网络/fs，由 `python -m md2video.check_component`
双跑逐帧一致 + 黄金帧验证，全过才安装）。

代码分发沿用 A5 模式：组件代码只经显式模块加载——注册模块通过 env
`MD2VIDEO_COMPONENTS`（逗号分隔 Python 模块路径）导入并调用
`register_component`，导入/注册失败 fail fast；pack JSON 永不执行。

plan 引用 `id@version` 完整形式，不搞浮动最新版；未知 id 在渲染层
降级默认渲染 + warning（与 pack 未知名同通道）；同 (id, version)
重复注册且内容一致时幂等，内容不同 fail fast。
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

COMPONENTS_ENV = "MD2VIDEO_COMPONENTS"

# v1 只开放 body 表现；标题卡与 section 堆叠字幕仍归引擎
COMPONENT_KINDS = ("body",)

# A8.1 挂载方式：shot = 逐 shot 窗口独立实例（默认，一镜一段完整演示）；
# scene = 场景画布——组件拿整场镜头时间线 + 自己排第几，画面状态跨 shot
# 累积（时间不连续、状态连续；同场 shot 散开是合法用法）。挂载方式记在
# 组件注册表里，plan 格式不动：ScenePlan.component 仍只写 id@version。
COMPONENT_MOUNT_MODES = ("shot", "scene")

# 目前只有 Remotion 后端能消费表现组件；manim scene 声明组件 fail fast
COMPONENT_CAPABLE_BACKENDS = ("remotion",)

_COMPONENT_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_COMPONENT_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_COMPONENT_REF_RE = re.compile(r"^[a-z][a-z0-9_-]*@\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class RegisteredComponent:
    """一个已注册的表现组件：身份、版本与内容哈希（供应链审计用）。

    `displayed_texts` 是 P0 字幕去重的契约声明（纯函数：payload → 组件画
    在画面上的文本列表）；它住在注册模块（Python）里、不可序列化，
    installed.json 只记 `register_module`，消费方按需显式 import 补全
    （A5 模式：代码只经显式 import，JSON 永不执行）。
    """

    id: str
    version: str
    kind: str
    mount: str  # "shot"（逐镜独立）或 "scene"（场景画布，状态跨 shot 累积）
    component_file: str  # 解析后的绝对路径（.tsx 源码）
    content_hash: str  # sha256(component_file bytes)
    displayed_texts: Callable[[list[dict[str, Any]]], list[str]] | None = None
    register_module: str = ""  # 提供 displayed_texts 的注册模块（惰性 import 用）

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"


_REGISTRY: dict[str, RegisteredComponent] = {}


def register_component(
    component_id: str,
    version: str,
    kind: str,
    component_file: str | Path,
    mount: str = "shot",
    *,
    displayed_texts: Callable[[list[dict[str, Any]]], list[str]] | None = None,
    register_module: str = "",
) -> RegisteredComponent:
    """注册一个表现组件；相对路径按调用方模块所在目录解析（组件文件随
    注册模块走，与 cwd 无关）。重名同内容幂等，重名异内容 fail fast。"""
    if not _COMPONENT_ID_RE.match(component_id):
        raise ValueError(
            f"Invalid component id {component_id!r}: "
            "expected lowercase identifier [a-z][a-z0-9_-]*"
        )
    if not _COMPONENT_VERSION_RE.match(version):
        raise ValueError(
            f"Invalid component version {version!r}: "
            "expected semver 'MAJOR.MINOR.PATCH'"
        )
    if kind not in COMPONENT_KINDS:
        raise ValueError(
            f"Unsupported component kind {kind!r}; v1 supports {COMPONENT_KINDS}"
        )
    if mount not in COMPONENT_MOUNT_MODES:
        raise ValueError(
            f"Unsupported component mount {mount!r}; "
            f"supported modes are {COMPONENT_MOUNT_MODES}"
        )
    if displayed_texts is not None and not callable(displayed_texts):
        raise ValueError("displayed_texts must be a callable (pure function)")
    if not isinstance(register_module, str):
        raise ValueError("register_module must be a module path string")

    path = Path(component_file)
    if not path.is_absolute():
        caller = inspect.stack()[1]
        path = Path(caller.filename).parent / path
    path = path.resolve()
    if path.suffix != ".tsx":
        raise ValueError(f"Component file must be a .tsx module: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Component file not found: {path}")
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    ref = f"{component_id}@{version}"
    existing = _REGISTRY.get(ref)
    if existing is not None:
        if (
            existing.content_hash == content_hash
            and existing.kind == kind
            and existing.mount == mount
        ):
            # 同内容幂等 + 契约补全：清单路径先注册（无 callable），注册
            # 模块随后被 import 时把 displayed_texts/register_module 补上
            if displayed_texts is not None and existing.displayed_texts is None:
                enriched = replace(
                    existing,
                    displayed_texts=displayed_texts,
                    register_module=register_module or existing.register_module,
                )
                _REGISTRY[ref] = enriched
                return enriched
            return existing
        raise ValueError(
            f"Component {ref} already registered with different content "
            f"({existing.component_file}); bump the version or fix the conflict"
        )

    component = RegisteredComponent(
        id=component_id,
        version=version,
        kind=kind,
        mount=mount,
        component_file=str(path),
        content_hash=content_hash,
        displayed_texts=displayed_texts,
        register_module=register_module,
    )
    _REGISTRY[ref] = component
    return component


def get_component(ref: str) -> RegisteredComponent | None:
    """按完整 `id@version` 查找；不认识返回 None（调用方降级 + warning）。"""
    return _REGISTRY.get(ref)


def displayed_texts_for(
    ref: str, payload: list[dict[str, Any]]
) -> list[str] | None:
    """P0 字幕去重：组件声明画面上呈现的文本（纯函数调用）。

    返回 None = 无法回答（组件未注册 / 未声明 / 声明模块不可加载）
    ——调用方必须回退到「保留字幕」（宁可重复，不可丢字）。注册表条目
    来自 installed.json 时没有 callable：按 `register_module` 显式 import
    补全（A5 模式）；模块已缓存但注册表被 reset 过时 reload 一次再取。
    声明函数抛错按字幕侧降级约定处理：打印警告、返回 None，不阻断成片。
    """
    component = get_component(ref)
    if component is None:
        return None
    fn = component.displayed_texts
    if fn is None and component.register_module:
        try:
            importlib.import_module(component.register_module)
            component = get_component(ref) or component
            fn = component.displayed_texts
            if fn is None:
                # 模块在本次进程早前已被 import（缓存不重跑）而注册表被
                # reset 过 → reload 一次让 register 调用重新执行
                import sys

                module = sys.modules.get(component.register_module)
                if module is not None:
                    importlib.reload(module)
                    component = get_component(ref) or component
                    fn = component.displayed_texts
        except Exception as exc:  # noqa: BLE001 - 字幕问题只降级不阻断
            print(f"  Component warning ({ref}): displayed_texts unavailable: {exc}")
            return None
    if fn is None:
        return None
    try:
        return [str(text) for text in fn(payload)]
    except Exception as exc:  # noqa: BLE001 - 声明违约回退到保留字幕
        print(f"  Component warning ({ref}): displayed_texts raised: {exc}")
        return None


def registered_components() -> list[RegisteredComponent]:
    return list(_REGISTRY.values())


def is_installed(ref: str) -> bool:
    """该 ref 是否已安装进 Remotion 工程（安装才真正可渲染）。"""
    from md2video.components.install import is_installed as _is_installed

    return _is_installed(ref)


def reset_components() -> None:
    """恢复为已安装组件（测试与进程级重载用）。"""
    _REGISTRY.clear()
    _register_installed_components()


def _register_installed_components() -> None:
    """installed = registered：安装进 Remotion 工程的组件默认可用（零特权）。

    安装文件的 content_hash 与 manifest 对不上 = 安装后被人手改 → fail fast
    （供应链完整性：内容哈希是审计依据，漂移必须重经验收）。
    """
    import hashlib

    from md2video.components.install import REGISTERED_DIR, read_installed_manifest

    for entry in read_installed_manifest():
        path = REGISTERED_DIR / entry["file"]
        if not path.is_file():
            raise FileNotFoundError(
                f"Installed component file missing: {path} "
                "(manifest drifted? reinstall via `python -m md2video.check_component`)"
            )
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if content_hash != entry.get("content_hash"):
            raise ValueError(
                f"Installed component {entry['ref']} content hash mismatch "
                "(file edited after install); reinstall via "
                "`python -m md2video.check_component`"
            )
        component_id, _, version = entry["ref"].partition("@")
        register_component(
            component_id,
            version,
            entry["kind"],
            path,
            mount=entry.get("mount", "shot"),
            register_module=entry.get("register_module", ""),
        )


_register_installed_components()


def is_valid_component_ref(ref: str) -> bool:
    return bool(_COMPONENT_REF_RE.match(ref))


def component_module_spec(spec: str | None = None) -> list[str]:
    """取要加载的组件注册模块名列表（参数优先，否则读 env）。"""
    raw = spec if spec is not None else os.environ.get(COMPONENTS_ENV, "")
    return [name.strip() for name in raw.split(",") if name.strip()]


def load_component_modules(spec: str | None = None) -> list[str]:
    """显式导入组件注册模块并执行其 register_component；导入/注册失败
    直接抛错（fail fast）。只接受 Python 模块路径；组件的 .tsx 本体在
    这里不被执行（Node 渲染时才消费）。"""
    loaded: list[str] = []
    for module_name in component_module_spec(spec):
        importlib.import_module(module_name)
        loaded.append(module_name)
    return loaded
