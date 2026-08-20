"""Lightweight manifest loading helpers for render backends."""
from __future__ import annotations

import os
from pathlib import Path

from md2video.manifest.schema import (
    ExecutionAssets,
    PlanManifest,
    ResultManifest,
    result_manifest_from_execution_assets,
)


def required_env_value(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise FileNotFoundError(f"{name} is required")
    return value


def required_existing_env_path(name: str) -> Path:
    path = Path(required_env_value(name))
    if not path.exists():
        raise FileNotFoundError(f"{name} file not found: {path}")
    return path


def load_manifests_from_env() -> tuple[PlanManifest, ResultManifest]:
    """Load renderer inputs from explicit env vars only."""
    plan_path = required_existing_env_path("MD2VIDEO_PLAN_PATH")
    assets_path = required_existing_env_path("MD2VIDEO_EXECUTION_ASSETS_PATH")
    required_env_value("MD2VIDEO_TIMELINE_PATH")

    plan = PlanManifest.model_validate_json(plan_path.read_text(encoding="utf-8"))
    assets = ExecutionAssets.model_validate_json(assets_path.read_text(encoding="utf-8"))
    result = result_manifest_from_execution_assets(plan, assets)
    return plan, result
