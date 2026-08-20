"""Timeline helpers shared by render backends and tests."""
from __future__ import annotations

from typing import Any


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


def build_shot_timeline(text_timeline: list[dict], marker_timeline: list[dict]) -> list[dict]:
    """Build per-shot timing from subtitle/text entries and zero-duration markers."""
    shots_by_id: dict[str, dict[str, Any]] = {}

    def add_entry(item: dict, start: float, end: float) -> None:
        shot_id = item.get("shot_id")
        if not shot_id:
            return
        entry = shots_by_id.setdefault(shot_id, {
            "shot_id": shot_id,
            "scene_id": item.get("scene_id", ""),
            "segment_ids": [],
            "start": start,
            "end": end,
        })
        entry["start"] = min(entry["start"], start)
        entry["end"] = max(entry["end"], end)
        segment_id = item.get("segment_id")
        if segment_id and segment_id not in entry["segment_ids"]:
            entry["segment_ids"].append(segment_id)

    for item in text_timeline:
        if item.get("end") is None:
            continue
        add_entry(item, item["start"], item["end"])

    for item in marker_timeline:
        if item.get("time") is None:
            continue
        add_entry(item, item["time"], item["time"])

    return list(shots_by_id.values())
