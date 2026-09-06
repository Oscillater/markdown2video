"""A5 layout 约束注册表：结构化 LayoutIssue、零特权注册、外部模块加载。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from md2video.layout.constraints import (
    LAYOUT_CONSTRAINTS_ENV,
    LayoutGeometry,
    LayoutIssue,
    LayoutValidationError,
    constraint_module_spec,
    judge_geometry,
    load_constraint_modules,
    register_constraint,
    registered_constraints,
    reset_constraints,
)
from md2video.layout.resolve import evaluate_layout_proposal, resolve_scene_layout
from md2video.layout.templates import SAFE_AREA, BUILTIN_TEMPLATES
from md2video.layout.registry import LayoutRegistry


def _geometry(regions: dict, safe_names: tuple = (), content_names: tuple = ()) -> LayoutGeometry:
    from md2video.layout.schema import LayoutBox

    return LayoutGeometry(
        frame_width=480,
        frame_height=854,
        safe_area=SAFE_AREA,
        regions=regions,
        safe_region_names=safe_names,
        content_region_names=content_names,
    )


def _box(x, y, w, h):
    from md2video.layout.schema import LayoutBox

    return LayoutBox(x=x, y=y, width=w, height=h)


@pytest.fixture(autouse=True)
def _clean_constraint_registry():
    reset_constraints()
    yield
    reset_constraints()


class TestBuiltinConstraints:
    def test_judge_reports_all_issues_at_once(self):
        geo = _geometry(
            regions={
                "a": _box(0.0, 0.0, 0.30, 0.04),   # 出安全区 + 与 b 重叠 + 太小
                "b": _box(0.10, 0.02, 0.60, 0.30),
            },
            safe_names=("a", "b"),
            content_names=("a", "b"),
        )
        issues = judge_geometry(geo)
        codes = {issue.code for issue in issues}
        assert {"outside_safe_area", "regions_overlap", "region_too_small"} <= codes
        # 数值可执行：重叠面积 > 0、最小尺寸带期望/实际
        overlap = next(i for i in issues if i.code == "regions_overlap")
        assert overlap.region == "a+b"
        assert overlap.expected == 0.0
        assert overlap.actual > 0.0
        too_small = next(i for i in issues if i.code == "region_too_small")
        assert too_small.expected == pytest.approx(0.05)
        assert too_small.actual == pytest.approx(0.04)

    def test_valid_geometry_has_no_issues(self):
        geo = _geometry(
            regions={
                "title": _box(0.08, 0.06, 0.84, 0.20),
                "body": _box(0.08, 0.30, 0.84, 0.64),
            },
            safe_names=("title", "body"),
            content_names=("title", "body"),
        )
        assert judge_geometry(geo) == []

    def test_issue_str_carries_code_region_numbers_and_suggestion(self):
        issue = LayoutIssue(
            code="region_too_small", region="body", message="too thin",
            expected=0.05, actual=0.01, suggestion="raise height",
        )
        text = str(issue)
        assert "[region_too_small]" in text
        assert "body" in text
        assert "expected=0.05" in text and "actual=0.01" in text
        assert "raise height" in text


class TestConstraintRegistry:
    def test_builtin_constraints_registered(self):
        names = {fn.__name__ for fn in registered_constraints()}
        assert {
            "_regions_within_safe_area",
            "_content_regions_disjoint",
            "_regions_meet_min_size",
        } <= names

    def test_register_duplicate_fails_fast(self):
        def my_constraint(geo):
            return []

        register_constraint(my_constraint)
        with pytest.raises(ValueError, match="already registered: my_constraint"):
            register_constraint(my_constraint)

    def test_register_as_decorator_and_custom_rule_participates(self):
        @register_constraint
        def title_must_be_top(geo):
            title = geo.regions.get("title")
            if title and title.y > 0.5:
                return [LayoutIssue(
                    code="title_not_top", region="title",
                    message="title should live in the upper half",
                    expected=0.5, actual=title.y,
                    suggestion="move title above y=0.5",
                )]
            return []

        geo = _geometry(
            regions={"title": _box(0.1, 0.8, 0.8, 0.1)},
            safe_names=("title",), content_names=("title",),
        )
        codes = {issue.code for issue in judge_geometry(geo)}
        assert "title_not_top" in codes

    def test_reset_constraints_drops_external_rules(self):
        register_constraint(lambda geo: [])
        assert len(registered_constraints()) == 4
        reset_constraints()
        assert len(registered_constraints()) == 3


class TestLoadConstraintModules:
    def test_spec_from_env_comma_separated(self, monkeypatch):
        monkeypatch.delenv(LAYOUT_CONSTRAINTS_ENV, raising=False)
        assert constraint_module_spec() == []
        monkeypatch.setenv(LAYOUT_CONSTRAINTS_ENV, " mod_a , mod_b ,, ")
        assert constraint_module_spec() == ["mod_a", "mod_b"]

    def test_loads_modules_and_runs_registrations(self, tmp_path, monkeypatch):
        module = tmp_path / "my_pack_constraints.py"
        module.write_text(
            "from md2video.layout.constraints import register_constraint, LayoutIssue\n"
            "@register_constraint\n"
            "def pack_rule(geo):\n"
            "    return []\n",
            encoding="utf-8",
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        loaded = load_constraint_modules("my_pack_constraints")
        assert loaded == ["my_pack_constraints"]
        assert "pack_rule" in {fn.__name__ for fn in registered_constraints()}

    def test_missing_module_fails_fast(self):
        with pytest.raises(ModuleNotFoundError):
            load_constraint_modules("definitely_not_a_module_xyz")

    def test_module_raising_at_import_fails_fast(self, tmp_path, monkeypatch):
        module = tmp_path / "broken_constraints.py"
        module.write_text("raise RuntimeError('bad constraint module')\n", encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
        with pytest.raises(RuntimeError, match="bad constraint module"):
            load_constraint_modules("broken_constraints")

    def test_pipeline_loads_env_constraints_at_startup(self, tmp_path, monkeypatch):
        """pipeline 启动即导入并注册外部约束；导入失败开不了工。"""
        from unittest.mock import patch

        from md2video.core.pipeline import Pipeline

        module = tmp_path / "pipeline_pack_constraints.py"
        module.write_text(
            "from md2video.layout.constraints import register_constraint\n"
            "@register_constraint\n"
            "def pipeline_pack_rule(geo):\n"
            "    return []\n",
            encoding="utf-8",
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setenv(LAYOUT_CONSTRAINTS_ENV, "pipeline_pack_constraints")
        reset_constraints()

        with patch.object(Pipeline, "_create_planner"), \
                patch.object(Pipeline, "_register_default_tools"):
            pipeline = Pipeline(artifacts_dir=tmp_path / "artifacts")
        assert "pipeline_pack_rule" in {
            fn.__name__ for fn in registered_constraints()
        }
        reset_constraints()

    def test_pipeline_fails_fast_on_broken_constraint_module(self, tmp_path, monkeypatch):
        from unittest.mock import patch

        from md2video.core.pipeline import Pipeline

        monkeypatch.setenv(LAYOUT_CONSTRAINTS_ENV, "no_such_constraint_module")
        reset_constraints()
        with patch.object(Pipeline, "_create_planner"), \
                patch.object(Pipeline, "_register_default_tools"):
            with pytest.raises(ModuleNotFoundError):
                Pipeline(artifacts_dir=tmp_path / "artifacts")
        reset_constraints()
