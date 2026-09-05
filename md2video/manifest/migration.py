"""Plan schema 迁移：v1 → v2（一次切换）。

v2 移除的内容（plan 不含时间、visual/layout 决策收拢到 scene 级）：

- `SegmentPlan.target_duration`（时长是事实，plan 不含时间）。
- `SegmentPlan.visual_type/visual_params/layout_type/layout_params`
  （scene 级决策的 segment 副本，去 denormalize）。

迁移只做无损剥离：v1 数据里这些字段的值本就是 scene 值的副本或
回写缓存，剥离不改变 scene 级语义。未知字段不迁移，交给 schema
校验拒绝（SegmentPlan extra=forbid）。
"""
from __future__ import annotations

from typing import Any

from md2video.manifest.schema import PlanManifest

PLAN_VERSION = "2"

_REMOVED_SEGMENT_FIELDS = (
    "target_duration",
    "visual_type",
    "visual_params",
    "layout_type",
    "layout_params",
)


def migrate_plan_manifest_data(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """把 v1 plan dict 迁移到 v2，返回 (迁移后数据, warnings)。幂等。"""
    if not isinstance(data, dict):
        raise ValueError("Plan manifest must be a JSON object")

    warnings: list[str] = []
    version = str(data.get("version", "1"))
    if version == PLAN_VERSION:
        return data, warnings
    if version != "1":
        raise ValueError(
            f"Unsupported plan manifest version: {version} "
            f"(supported: 1 -> migrate to {PLAN_VERSION})"
        )

    migrated = dict(data)
    segments = migrated.get("segments")
    if isinstance(segments, list):
        stripped: dict[str, int] = {}
        migrated_segments = []
        for segment in segments:
            if not isinstance(segment, dict):
                migrated_segments.append(segment)
                continue
            cleaned = dict(segment)
            for field in _REMOVED_SEGMENT_FIELDS:
                if field in cleaned:
                    stripped[field] = stripped.get(field, 0) + 1
                    del cleaned[field]
            migrated_segments.append(cleaned)
        migrated["segments"] = migrated_segments
        if stripped:
            details = ", ".join(
                f"{field} x{n}" for field, n in sorted(stripped.items())
            )
            warnings.append(
                "Migrated plan manifest v1 -> v2: removed segment-level "
                f"fields (plan no longer carries time or visual/layout "
                f"copies): {details}"
            )

    migrated["version"] = PLAN_VERSION
    return migrated, warnings


def load_plan_manifest_json(text: str) -> tuple[PlanManifest, list[str]]:
    """读取 plan JSON 文本，必要时迁移到 v2，返回 (PlanManifest, warnings)。"""
    import json

    data = json.loads(text)
    migrated, warnings = migrate_plan_manifest_data(data)
    return PlanManifest.model_validate(migrated), warnings
