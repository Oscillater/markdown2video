"""Plan schema v1 → v2 迁移 validator 测试。"""
from __future__ import annotations

import json

import pytest

from md2video.manifest.migration import (
    PLAN_VERSION,
    load_plan_manifest_json,
    migrate_plan_manifest_data,
)
from md2video.manifest.schema import PlanManifest


def _v1_plan_dict() -> dict:
    return {
        "version": "1",
        "segments": [
            {
                "id": "seg_001",
                "text": "hello",
                "segment_type": "content",
                "target_duration": 2.0,
                "visual_type": "stock_image",
                "visual_params": {"query": "logo"},
                "layout_type": "image_top_text_bottom",
                "layout_params": {"split": "balanced"},
            },
            {
                "id": "seg_002",
                "text": "干净段",
                "segment_type": "content",
            },
        ],
        "scenes": [
            {
                "id": "scene_001",
                "visual_type": "stock_image",
                "visual_params": {"query": "logo"},
                "layout_type": "image_top_text_bottom",
                "shots": [{"id": "shot_001", "segment_ids": ["seg_001"]}],
            },
        ],
    }


class TestMigratePlanManifestData:
    def test_v1_segments_are_stripped_and_version_bumped(self):
        migrated, warnings = migrate_plan_manifest_data(_v1_plan_dict())

        assert migrated["version"] == PLAN_VERSION
        assert migrated["segments"][0] == {
            "id": "seg_001",
            "text": "hello",
            "segment_type": "content",
        }
        assert migrated["segments"][1] == {
            "id": "seg_002",
            "text": "干净段",
            "segment_type": "content",
        }
        # scene 级字段不动（scene 级决策已在）
        assert migrated["scenes"][0]["visual_type"] == "stock_image"
        assert migrated["scenes"][0]["layout_type"] == "image_top_text_bottom"
        assert len(warnings) == 1
        assert "target_duration" in warnings[0]

    def test_migration_is_idempotent(self):
        once, _ = migrate_plan_manifest_data(_v1_plan_dict())
        twice, warnings = migrate_plan_manifest_data(once)
        assert twice == once
        assert warnings == []

    def test_v2_data_passes_through(self):
        data = json.loads(PlanManifest().model_dump_json())
        migrated, warnings = migrate_plan_manifest_data(data)
        assert migrated is data
        assert warnings == []

    def test_unsupported_version_rejected(self):
        with pytest.raises(ValueError, match="Unsupported plan manifest version"):
            migrate_plan_manifest_data({"version": "3", "segments": []})

    def test_non_dict_rejected(self):
        with pytest.raises(ValueError, match="JSON object"):
            migrate_plan_manifest_data(["not", "a", "dict"])

    def test_unknown_segment_fields_are_not_stripped(self):
        """迁移只剥离 v1 已知副本字段；未知字段留给 schema 校验拒绝。"""
        data = {
            "version": "1",
            "segments": [{"id": "s1", "text": "x", "segment_type": "content",
                          "unknown_field": 1}],
        }
        migrated, _ = migrate_plan_manifest_data(data)
        assert migrated["segments"][0]["unknown_field"] == 1
        with pytest.raises(Exception):
            PlanManifest.model_validate(migrated)


class TestLoadPlanManifestJson:
    def test_v1_json_loads_migrated(self):
        text = json.dumps(_v1_plan_dict(), ensure_ascii=False)
        plan, warnings = load_plan_manifest_json(text)

        assert isinstance(plan, PlanManifest)
        assert plan.version == PLAN_VERSION
        assert [seg.id for seg in plan.segments] == ["seg_001", "seg_002"]
        # plan 不含时间/visual 副本
        assert not hasattr(plan.segments[0], "target_duration")
        assert not hasattr(plan.segments[0], "visual_type")
        assert len(warnings) == 1

    def test_v2_json_loads_directly(self):
        plan_data = PlanManifest(
            segments=[
                {"id": "s1", "text": "x", "segment_type": "content"},
            ],
        )
        plan, warnings = load_plan_manifest_json(plan_data.model_dump_json())
        assert plan.version == PLAN_VERSION
        assert warnings == []

    def test_v1_json_with_extra_unknown_field_still_rejected(self):
        data = _v1_plan_dict()
        data["segments"][0]["bogus"] = True
        with pytest.raises(Exception):
            load_plan_manifest_json(json.dumps(data))
