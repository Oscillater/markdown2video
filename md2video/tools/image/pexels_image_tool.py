"""Pexels Image Tool — 通过 Pexels API 搜索并下载图片。

实现 Tool Protocol（tool_type="image", provider_name="pexels"），
使用 ToolCache 缓存下载结果。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import requests

from md2video.tools.cache import ToolCache


class PexelsImageTool:
    """Pexels 图片搜索工具。搜索 → 下载 → 缓存。"""

    def __init__(self, api_key: str, cache_dir: str | Path = "artifacts/cache/images"):
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = ToolCache(self.cache_dir)

    # --- Tool Protocol conformance ---

    @property
    def tool_type(self) -> str:
        return "image"

    @property
    def provider_name(self) -> str:
        return "pexels"

    def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Tool Protocol: visual tool 输入 → 输出契约。"""
        shot_id = input_data["shot"]["id"]
        visual_params = input_data["scene"]["visual_params"]
        query = visual_params.get("query", "")
        orientation = visual_params.get("orientation", "portrait")
        output_dir = input_data.get("output_dir", str(self.cache_dir))

        result = self.search_and_download(query, orientation, output_dir)
        result["shot_id"] = shot_id
        return {"visuals": [result]}

    # --- Core logic ---

    def search_and_download(
        self, query: str, orientation: str = "portrait", output_dir: str = "",
    ) -> Dict[str, Any]:
        """搜索图片并下载，返回 visual result dict。

        Returns: {"shot_id": str, "path": str, "width": int, "height": int, "source": str}
        Raises: ValueError (no API key), RuntimeError (API error, no results, download failure)
        """
        if not self.api_key:
            raise ValueError("PexelsImageTool requires an API key (set PEXELS_API_KEY)")

        cache_params = {"query": query, "orientation": orientation}
        cache_key = self._cache.make_key("image", cache_params)

        # Cache hit
        meta = self._cache.read_json("image", cache_key + "_meta")
        img_path = self._cache.cache_path("image", cache_key, ext="jpg")
        if meta and img_path.exists():
            return {
                "path": str(img_path),
                "width": meta["width"],
                "height": meta["height"],
                "source": "pexels",
                "source_url": meta.get("source_url", ""),
                "cache_key": cache_key,
                "duration": 0.0,
            }

        # API search
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "orientation": orientation, "per_page": 1, "size": "large"},
            headers={"Authorization": self.api_key},
            timeout=10,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Pexels API error: {resp.status_code} {resp.reason}")
        photos = resp.json().get("photos", [])
        if not photos:
            raise RuntimeError(f"No photos found for query: {query}")

        photo = photos[0]
        photo_url = photo["src"]["large2x"]
        width = photo["width"]
        height = photo["height"]
        source_url = photo.get("url", "")

        # Download
        dl_resp = requests.get(photo_url, timeout=30, stream=True)
        if dl_resp.status_code != 200:
            raise RuntimeError(f"Failed to download image: {dl_resp.status_code}")
        self._cache.write("image", cache_key, dl_resp.content, ext="jpg")

        # Write metadata
        self._cache.write_json("image", cache_key + "_meta", {
            "width": width,
            "height": height,
            "source_url": source_url,
        })

        return {
            "path": str(img_path),
            "width": width,
            "height": height,
            "source": "pexels",
            "source_url": source_url,
            "cache_key": cache_key,
            "duration": 0.0,
        }
