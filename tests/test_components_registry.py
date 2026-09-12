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
        "file": "components/tmp_step/tmp_step_1_0_0.tsx",
        "content_hash": component.content_hash,
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
