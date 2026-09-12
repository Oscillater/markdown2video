"""表现组件安装器（A8）：把通过验收的组件装进 Remotion 工程。

安装 = .tsx 拷进 `src/registered/components/<id>/<ident>.tsx` + 重写生成
barrel `src/registered/index.ts` + 更新 `installed.json`。安装是确定性的：
文件内容只由 ref 与源内容决定，无时间戳。已安装组件在 registry 导入时
自动注册（installed = registered，零特权）；`md2video.check_component` 用
staged 安装——验收失败即回滚，不留痕。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from md2video.components.registry import RegisteredComponent

# Remotion 工程 src/registered/（组件 .tsx、生成 barrel、installed.json 都在这）
REGISTERED_DIR = (
    Path(__file__).resolve().parents[1]
    / "tools" / "render" / "remotion_backend" / "src" / "registered"
)
BARREL_FILENAME = "index.ts"
MANIFEST_FILENAME = "installed.json"

_BARREL_HEADER = (
    "// 本文件由 md2video 组件安装器生成"
    "（`python -m md2video.check_component` 安装时重写）。\n"
    "// 手工改动会在下一次安装时被覆盖。\n"
    "import type {ComponentType} from 'react';\n"
    "import type {ComponentProps} from './types';\n"
    "\n"
)


def _ident(ref: str) -> str:
    """`step_list@1.0.0` -> `step_list_1_0_0`（合法 JS 标识符 + 安全文件名）。"""
    component_id, _, version = ref.partition("@")
    return f"{component_id}_{version.replace('.', '_')}"


def _installed_relpath(ref: str) -> str:
    component_id, _, _ = ref.partition("@")
    return f"components/{component_id}/{_ident(ref)}.tsx"


def render_barrel(entries: list[dict[str, str]]) -> str:
    """已安装组件条目（{ref, file, ...}）→ barrel 文件内容（逐字节确定，
    与输入顺序无关，按 ref 排序）。"""
    sorted_entries = sorted(entries, key=lambda e: e["ref"])
    lines = [_BARREL_HEADER]
    for entry in sorted_entries:
        lines.append(
            f"import {_ident(entry['ref'])} from './{entry['file'].replace(chr(92), '/')}';\n"
        )
    if sorted_entries:
        lines.append("\n")
        lines.append(
            "export const REGISTERED_COMPONENTS: "
            "Record<string, ComponentType<ComponentProps>> = {\n"
        )
        for entry in sorted_entries:
            lines.append(f"  '{entry['ref']}': {_ident(entry['ref'])},\n")
        lines.append("};\n")
    else:
        lines.append(
            "export const REGISTERED_COMPONENTS: "
            "Record<string, ComponentType<ComponentProps>> = {};\n"
        )
    return "".join(lines)


def read_installed_manifest(base_dir: Path | None = None) -> list[dict[str, str]]:
    root = base_dir if base_dir is not None else REGISTERED_DIR
    manifest = root / MANIFEST_FILENAME
    if not manifest.is_file():
        return []
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return sorted(data.get("components", []), key=lambda e: e["ref"])


def is_installed(ref: str, base_dir: Path | None = None) -> bool:
    return any(e["ref"] == ref for e in read_installed_manifest(base_dir))


def install_component(
    component: "RegisteredComponent", base_dir: Path | None = None
) -> Path:
    """装一个组件（staged 调用方负责验收与回滚）；同 ref 重装 = 覆盖。"""
    root = base_dir if base_dir is not None else REGISTERED_DIR
    relative = _installed_relpath(component.ref)
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    # 复核已安装组件时源即安装副本（幂等注册返回既有条目），跳过自拷贝
    if Path(component.component_file).resolve() != target.resolve():
        shutil.copyfile(component.component_file, target)

    entries = [e for e in read_installed_manifest(root) if e["ref"] != component.ref]
    entries.append({
        "ref": component.ref,
        "kind": component.kind,
        "file": relative,
        "content_hash": component.content_hash,
    })
    _write_manifest(root, entries)
    _write_barrel(root, entries)
    return target


def uninstall_component(ref: str, base_dir: Path | None = None) -> None:
    """回滚用：移除安装文件与 manifest 条目并重写 barrel；不存在则无操作。"""
    root = base_dir if base_dir is not None else REGISTERED_DIR
    entries = read_installed_manifest(root)
    remaining = [e for e in entries if e["ref"] != ref]
    if len(remaining) == len(entries):
        return
    for entry in entries:
        if entry["ref"] == ref:
            file_path = root / entry["file"]
            if file_path.is_file():
                file_path.unlink()
            parent = file_path.parent
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
    _write_manifest(root, remaining)
    _write_barrel(root, remaining)


def _write_manifest(root: Path, entries: list[dict[str, str]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {"components": sorted(entries, key=lambda e: e["ref"])}
    (root / MANIFEST_FILENAME).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def _write_barrel(root: Path, entries: list[dict[str, str]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / BARREL_FILENAME).write_text(render_barrel(entries), encoding="utf-8")
