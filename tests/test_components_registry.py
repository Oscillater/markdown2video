"""A8 表现组件注册表测试：注册/查找约定 + 显式模块加载（A5 模式）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from md2video.components.registry import (
    COMPONENTS_ENV,
    component_module_spec,
    get_component,
    is_valid_component_ref,
    load_component_modules,
    register_component,
    registered_components,
    reset_components,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_components()
    yield
    reset_components()


def _write_tsx(tmp_path: Path, name: str = "demo.tsx", body: str = "export default 1;\n") -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_register_and_get_roundtrip(tmp_path):
    tsx = _write_tsx(tmp_path)
    component = register_component("demo_display", "1.0.0", "body", tsx)

    assert component.ref == "demo_display@1.0.0"
    assert component.content_hash
    assert Path(component.component_file).is_absolute()
    assert get_component("demo_display@1.0.0") is component
    assert component in registered_components()


def test_register_requires_lowercase_id_and_semver(tmp_path):
    tsx = _write_tsx(tmp_path)
    with pytest.raises(ValueError, match="Invalid component id"):
        register_component("Code-Display", "1.0.0", "body", tsx)
    with pytest.raises(ValueError, match="Invalid component version"):
        register_component("code_display", "1.0", "body", tsx)
    with pytest.raises(ValueError, match="Unsupported component kind"):
        register_component("code_display", "1.0.0", "title", tsx)


def test_register_rejects_missing_or_non_tsx_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        register_component("code_display", "1.0.0", "body", tmp_path / "missing.tsx")

    plain = tmp_path / "not_react.py"
    plain.write_text("x = 1", encoding="utf-8")
    with pytest.raises(ValueError, match=r"\.tsx"):
        register_component("code_display", "1.0.0", "body", plain)


def test_duplicate_same_content_is_idempotent(tmp_path):
    tsx = _write_tsx(tmp_path)
    first = register_component("demo", "1.0.0", "body", tsx)
    second = register_component("demo", "1.0.0", "body", tsx)
    assert first is second


def test_duplicate_different_content_fails_fast(tmp_path):
    tsx = _write_tsx(tmp_path, body="export default 1;\n")
    register_component("demo", "1.0.0", "body", tsx)
    changed = _write_tsx(tmp_path, body="export default 2;\n")
    with pytest.raises(ValueError, match="different content"):
        register_component("demo", "1.0.0", "body", changed)


def test_multiple_versions_of_same_id_coexist(tmp_path):
    v1 = _write_tsx(tmp_path, name="v1.tsx", body="export default 1;\n")
    v2 = _write_tsx(tmp_path, name="v2.tsx", body="export default 2;\n")
    register_component("demo", "1.0.0", "body", v1)
    register_component("demo", "1.1.0", "body", v2)

    assert get_component("demo@1.0.0") is not None
    assert get_component("demo@1.1.0") is not None
    assert len([c for c in registered_components() if c.id == "demo"]) == 2


# ==================== A8.1 挂载方式（shot / scene） ====================


def test_mount_defaults_to_shot_and_validates(tmp_path):
    tsx = _write_tsx(tmp_path)
    component = register_component("demo", "1.0.0", "body", tsx)
    assert component.mount == "shot"

    with pytest.raises(ValueError, match="Unsupported component mount"):
        register_component("demo2", "1.0.0", "body", tsx, mount="timeline")


def test_scene_mount_roundtrip(tmp_path):
    tsx = _write_tsx(tmp_path)
    component = register_component("canvas_demo", "1.0.0", "body", tsx, mount="scene")
    assert component.mount == "scene"
    assert get_component("canvas_demo@1.0.0").mount == "scene"


def test_same_content_different_mount_fails_fast(tmp_path):
    tsx = _write_tsx(tmp_path)
    register_component("demo", "1.0.0", "body", tsx)
    with pytest.raises(ValueError, match="different content"):
        register_component("demo", "1.0.0", "body", tsx, mount="scene")


def test_install_roundtrip_preserves_mount(tmp_path, monkeypatch):
    """安装 manifest 携带 mount；installed = registered 恢复后不丢。"""
    import json

    from md2video.components import install as install_mod

    monkeypatch.setattr(install_mod, "REGISTERED_DIR", tmp_path)
    tsx = _write_tsx(tmp_path / "src", name="canvas.tsx", body="export default 1;\n")
    component = register_component("tmp_canvas", "1.0.0", "body", tsx, mount="scene")
    install_mod.install_component(component)

    manifest = json.loads((tmp_path / "installed.json").read_text(encoding="utf-8"))
    assert manifest["components"][0]["mount"] == "scene"

    reset_components()
    assert get_component("tmp_canvas@1.0.0").mount == "scene"


def test_legacy_manifest_entry_without_mount_defaults_to_shot(tmp_path, monkeypatch):
    """旧 installed.json 没有 mount 字段（A8 首批三组件）→ 按 shot 挂载恢复。"""
    import json

    from md2video.components import install as install_mod

    monkeypatch.setattr(install_mod, "REGISTERED_DIR", tmp_path)
    tsx = _write_tsx(tmp_path / "src", name="legacy.tsx", body="export default 1;\n")
    component = register_component("legacy_comp", "1.0.0", "body", tsx)
    install_mod.install_component(component)

    manifest_path = tmp_path / "installed.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["components"][0]["mount"]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    reset_components()
    assert get_component("legacy_comp@1.0.0").mount == "shot"


def test_unknown_ref_returns_none():
    assert get_component("nope@9.9.9") is None


def test_ref_format_validation():
    assert is_valid_component_ref("code_display@1.0.0")
    assert not is_valid_component_ref("code_display")
    assert not is_valid_component_ref("code_display@1.0")
    assert not is_valid_component_ref("Code@1.0.0")


def test_component_module_spec_parses_env(monkeypatch):
    monkeypatch.setenv(COMPONENTS_ENV, " a , b , ")
    assert component_module_spec() == ["a", "b"]
    assert component_module_spec("") == []
    assert component_module_spec("x") == ["x"]


def test_load_component_modules_fails_fast_on_missing_module(monkeypatch):
    monkeypatch.setenv(COMPONENTS_ENV, "definitely_not_a_component_module_xyz")
    with pytest.raises(ModuleNotFoundError):
        load_component_modules()


def test_load_component_modules_resolves_relative_tsx_against_caller(
    tmp_path, monkeypatch,
):
    """组件 .tsx 随注册模块走：相对路径按调用方模块目录解析，与 cwd 无关。"""
    module_dir = tmp_path / "my_components"
    module_dir.mkdir()
    (module_dir / "demo.tsx").write_text("export default 1;\n", encoding="utf-8")
    (module_dir / "cmp_reg_demo.py").write_text(
        "from md2video.components.registry import register_component\n"
        "register_component('demo', '1.0.0', 'body', 'demo.tsx')\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(module_dir))
    monkeypatch.setenv(COMPONENTS_ENV, "cmp_reg_demo")
    monkeypatch.chdir(tmp_path)  # cwd 下没有 demo.tsx，证明不是按 cwd 解析

    assert load_component_modules() == ["cmp_reg_demo"]
    component = get_component("demo@1.0.0")
    assert component is not None
    assert Path(component.component_file) == module_dir / "demo.tsx"


# ==================== 安装器（A8 staged install） ====================


def test_barrel_rendering_is_deterministic_and_sorted():
    from md2video.components.install import render_barrel

    empty = render_barrel([])
    assert "Record<string, ComponentType<ComponentProps>> = {};" in empty

    entries = [
        {"ref": "step_list@1.0.0", "file": "components/step_list/step_list_1_0_0.tsx"},
        {"ref": "code_display@2.1.3", "file": "components/code_display/code_display_2_1_3.tsx"},
    ]
    first = render_barrel(entries)
    second = render_barrel(list(reversed([dict(e) for e in entries])))
    assert first == second  # 与输入顺序无关
    assert first.index("'code_display@2.1.3'") < first.index("'step_list@1.0.0'")  # 按 ref 排序
    assert "import code_display_2_1_3 from './components/code_display/code_display_2_1_3.tsx';" in first
    assert "'step_list@1.0.0': step_list_1_0_0," in first


def test_install_and_uninstall_roundtrip(tmp_path, monkeypatch):
    import json

    from md2video.components import install as install_mod

    monkeypatch.setattr(install_mod, "REGISTERED_DIR", tmp_path)
    tsx = _write_tsx(tmp_path / "src", name="tmp_step.tsx", body="export default 1;\n")
    component = register_component("tmp_step", "1.0.0", "body", tsx)

    installed_path = install_mod.install_component(component)

    assert installed_path == tmp_path / "components" / "tmp_step" / "tmp_step_1_0_0.tsx"
    assert installed_path.is_file()
    assert install_mod.is_installed("tmp_step@1.0.0")
    manifest = json.loads((tmp_path / "installed.json").read_text(encoding="utf-8"))
    assert manifest["components"] == [{
        "ref": "tmp_step@1.0.0",
        "kind": "body",
        "mount": "shot",
        "file": "components/tmp_step/tmp_step_1_0_0.tsx",
        "content_hash": component.content_hash,
        # P0 字幕去重：未声明 displayed_texts 的组件清单带空模块名
        "register_module": "",
    }]
    assert (tmp_path / "index.ts").read_text(encoding="utf-8") == install_mod.render_barrel(
        manifest["components"]
    )

    install_mod.uninstall_component("tmp_step@1.0.0")
    assert not install_mod.is_installed("tmp_step@1.0.0")
    assert not installed_path.exists()
    assert json.loads((tmp_path / "installed.json").read_text(encoding="utf-8")) == {
        "components": []
    }
    assert "{};" in (tmp_path / "index.ts").read_text(encoding="utf-8")


def test_installed_components_auto_register(tmp_path, monkeypatch):
    """installed = registered：安装过的组件经 reset 恢复后默认可用。"""
    from md2video.components import install as install_mod
    from md2video.components import registry as registry_mod

    monkeypatch.setattr(install_mod, "REGISTERED_DIR", tmp_path)
    tsx = _write_tsx(tmp_path / "src", name="demo.tsx", body="export default 1;\n")
    component = register_component("demo", "1.2.3", "body", tsx)
    install_mod.install_component(component)

    registry_mod.reset_components()
    assert get_component("demo@1.2.3") is not None
    assert registry_mod.is_installed("demo@1.2.3")


def test_installed_component_drift_fails_fast(tmp_path, monkeypatch):
    """安装后手改 .tsx → 内容哈希对不上 manifest → 导入即 fail fast。"""
    from md2video.components import install as install_mod
    from md2video.components import registry as registry_mod

    monkeypatch.setattr(install_mod, "REGISTERED_DIR", tmp_path)
    tsx = _write_tsx(tmp_path / "src", name="demo.tsx", body="export default 1;\n")
    component = register_component("demo", "1.0.0", "body", tsx)
    install_mod.install_component(component)

    installed = tmp_path / "components" / "demo" / "demo_1_0_0.tsx"
    installed.write_text("export default 999;\n", encoding="utf-8")  # 手改

    with pytest.raises(ValueError, match="content hash mismatch"):
        registry_mod.reset_components()


# ========== P0 字幕去重契约：displayed_texts / register_module ==========


def test_register_displayed_texts_roundtrip(tmp_path):
    tsx = _write_tsx(tmp_path, name="dedup.tsx", body="export default 1;\n")

    def displayed(payload):
        return [s["text"] for s in payload if s.get("segment_type") == "content"]

    component = register_component(
        "dedup_demo", "1.0.0", "body", tsx,
        displayed_texts=displayed, register_module=__name__,
    )
    assert component.displayed_texts is displayed
    assert component.register_module == __name__
    assert get_component("dedup_demo@1.0.0") is component


def test_register_rejects_non_callable_displayed_texts(tmp_path):
    tsx = _write_tsx(tmp_path, name="bad.tsx", body="export default 1;\n")
    with pytest.raises(ValueError, match="callable"):
        register_component(
            "bad_display", "1.0.0", "body", tsx, displayed_texts=["not", "callable"],
        )


def test_idempotent_registration_enriches_displayed_texts(tmp_path):
    """清单路径先注册（无 callable），注册模块随后 import → 契约补全。"""
    tsx = _write_tsx(tmp_path, name="enrich.tsx", body="export default 1;\n")
    first = register_component("enrich_demo", "1.0.0", "body", tsx)

    def displayed(payload):
        return []

    second = register_component(
        "enrich_demo", "1.0.0", "body", tsx,
        displayed_texts=displayed, register_module="some.register",
    )
    assert second is not first  # 条目被替换为补全后的版本
    assert second.content_hash == first.content_hash
    assert second.displayed_texts is displayed
    assert second.register_module == "some.register"
    # 幂等：再注册（带同一 callable）不再替换
    third = register_component(
        "enrich_demo", "1.0.0", "body", tsx,
        displayed_texts=displayed, register_module="some.register",
    )
    assert third is second


def test_displayed_texts_for_answers_from_register_module(tmp_path, monkeypatch):
    """注册表条目缺 callable → 按 register_module 显式 import 补全后作答。"""
    from md2video.components import registry as reg

    tsx = _write_tsx(tmp_path, name="lazy.tsx", body="export default 1;\n")
    reg.register_component(
        "lazy_demo", "1.0.0", "body", tsx, register_module="",
    )
    # 无模块可 import → 无法回答（None，调用方保留字幕）
    assert reg.displayed_texts_for("lazy_demo@1.0.0", []) is None
    # 未注册 ref → None
    assert reg.displayed_texts_for("ghost@9.9.9", []) is None


def test_manifest_roundtrip_preserves_register_module(tmp_path, monkeypatch):
    """installed.json 记住 register_module，清单重注册后可追溯声明来源。"""
    import json

    from md2video.components import install as install_mod

    monkeypatch.setattr(install_mod, "REGISTERED_DIR", tmp_path)
    tsx = _write_tsx(tmp_path / "src", name="mod.tsx", body="export default 1;\n")
    component = register_component(
        "mod_demo", "1.0.0", "body", tsx,
        displayed_texts=lambda payload: [], register_module="pkg.mod.register",
    )
    install_mod.install_component(component)
    manifest = json.loads((tmp_path / "installed.json").read_text(encoding="utf-8"))
    assert manifest["components"][0]["register_module"] == "pkg.mod.register"
