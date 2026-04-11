"""统一工具缓存 — 按 tool_type + input_hash 缓存产物。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional


class ToolCache:
    """统一缓存层。key = sha256("{tool_type}:{canonical_json(params)}")。"""

    def __init__(self, cache_root: str | Path = "artifacts/cache"):
        self.cache_root = Path(cache_root)

    def make_key(self, tool_type: str, params: Dict[str, Any]) -> str:
        """生成确定性缓存 key。"""
        canonical = json.dumps(params, sort_keys=True, ensure_ascii=False)
        raw = f"{tool_type}:{canonical}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def cache_path(self, tool_type: str, cache_key: str, ext: str = "bin") -> Path:
        dir_path = self.cache_root / tool_type
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path / f"{cache_key}.{ext}"

    def has(self, tool_type: str, cache_key: str, ext: str = "bin") -> bool:
        return self.cache_path(tool_type, cache_key, ext).exists()

    def read(self, tool_type: str, cache_key: str, ext: str = "bin") -> Optional[bytes]:
        path = self.cache_path(tool_type, cache_key, ext)
        return path.read_bytes() if path.exists() else None

    def write(self, tool_type: str, cache_key: str, data: bytes, ext: str = "bin") -> Path:
        path = self.cache_path(tool_type, cache_key, ext)
        path.write_bytes(data)
        return path

    def read_json(self, tool_type: str, cache_key: str) -> Optional[Dict]:
        data = self.read(tool_type, cache_key, ext="json")
        if data is not None:
            return json.loads(data)
        return None

    def write_json(self, tool_type: str, cache_key: str, result: Dict) -> Path:
        return self.write(
            tool_type, cache_key,
            json.dumps(result, ensure_ascii=False).encode(),
            ext="json",
        )
