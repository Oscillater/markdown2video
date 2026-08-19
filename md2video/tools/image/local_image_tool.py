"""Local image tool for keyless stock_image validation."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PIL import Image


class LocalImageTool:
    """Use a local image file as a visual tool output."""

    @property
    def tool_type(self) -> str:
        return "image"

    @property
    def provider_name(self) -> str:
        return "local"

    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        shot_id = input_data["shot"]["id"]
        visual_params = input_data["scene"].get("visual_params", {})
        raw_path = (
            visual_params.get("path")
            or visual_params.get("src")
            or visual_params.get("image_path")
        )
        if not raw_path:
            raise ValueError("LocalImageTool requires visual_params.path or visual_params.src")

        path = self._resolve_path(raw_path, input_data)
        with Image.open(path) as image:
            width, height = image.size

        return {
            "visuals": [{
                "shot_id": shot_id,
                "path": str(path),
                "width": width,
                "height": height,
                "source": "local",
            }]
        }

    def _resolve_path(self, raw_path: str, input_data: Dict[str, Any]) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_absolute() and path.exists():
            return path.resolve()

        candidates = []
        base_dir = input_data.get("base_dir")
        if base_dir:
            candidates.append(Path(base_dir) / path)
        candidates.append(Path.cwd() / path)

        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()

        searched = ", ".join(str(p) for p in candidates)
        raise FileNotFoundError(f"Local image not found: {raw_path} (searched: {searched})")
