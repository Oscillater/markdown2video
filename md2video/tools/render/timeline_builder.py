"""Timeline helpers shared by render backends and tests."""
from __future__ import annotations


class TimelineWriter:
    """Append timeline entries and close them by handle, never by display text."""

    def __init__(self, entries: list[dict] | None = None):
        self.entries = entries if entries is not None else []

    def append(self, entry: dict) -> int:
        self.entries.append(entry)
        return len(self.entries) - 1

    def close(self, handle: int, end: float) -> None:
        self.entries[handle]["end"] = end

    def entry(self, handle: int) -> dict:
        return self.entries[handle]


class ShotTimelineWriter:
    """Write one logical shot timeline entry even if rendering is split internally."""

    def __init__(self, entries: list[dict] | None = None):
        self.entries = entries if entries is not None else []
        self._index_by_shot_id: dict[str, int] = {}
        for index, entry in enumerate(self.entries):
            shot_id = entry.get("shot_id")
            if isinstance(shot_id, str) and shot_id:
                self._index_by_shot_id.setdefault(shot_id, index)

    def upsert(self, entry: dict) -> int:
        shot_id = entry.get("shot_id")
        if not isinstance(shot_id, str) or not shot_id:
            self.entries.append(entry)
            return len(self.entries) - 1

        existing_index = self._index_by_shot_id.get(shot_id)
        if existing_index is None:
            self.entries.append(entry)
            self._index_by_shot_id[shot_id] = len(self.entries) - 1
            return len(self.entries) - 1

        existing = self.entries[existing_index]
        existing["start"] = min(float(existing["start"]), float(entry["start"]))
        existing["end"] = max(float(existing["end"]), float(entry["end"]))
        if not existing.get("scene_id") and entry.get("scene_id"):
            existing["scene_id"] = entry["scene_id"]

        segment_ids = entry.get("segment_ids")
        if isinstance(segment_ids, list) and segment_ids:
            existing["segment_ids"] = segment_ids

        return existing_index
