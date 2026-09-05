"""Timeline state helpers for renderers."""
from __future__ import annotations

from md2video.tools.render.timeline_builder import ShotTimelineWriter, TimelineWriter


def test_timeline_writer_closes_duplicate_text_by_handle():
    writer = TimelineWriter()
    first = writer.append({
        "segment_id": "seg_001",
        "shot_id": "shot_001",
        "text": "same",
        "start": 0.0,
        "end": None,
    })
    second = writer.append({
        "segment_id": "seg_002",
        "shot_id": "shot_002",
        "text": "same",
        "start": 1.0,
        "end": None,
    })

    writer.close(second, 2.0)

    assert writer.entry(first)["end"] is None
    assert writer.entry(second)["end"] == 2.0


def test_timeline_writer_keeps_header_and_content_with_same_text_separate():
    writer = TimelineWriter()
    header = writer.append({
        "segment_id": "header_001",
        "segment_type": "section_header",
        "shot_id": "shot_header",
        "text": "same",
        "start": 0.0,
        "end": None,
    })
    content = writer.append({
        "segment_id": "content_001",
        "segment_type": "content",
        "shot_id": "shot_content",
        "text": "same",
        "start": 1.0,
        "end": None,
    })

    writer.close(header, 0.8)

    assert writer.entry(header)["end"] == 0.8
    assert writer.entry(content)["end"] is None


def test_shot_timeline_writer_merges_split_rendering_for_same_shot():
    entries = []
    writer = ShotTimelineWriter(entries)

    writer.upsert({
        "shot_id": "shot_001",
        "scene_id": "scene_001",
        "segment_ids": ["title"],
        "start": 0.0,
        "end": 2.0,
    })
    writer.upsert({
        "shot_id": "shot_001",
        "scene_id": "scene_001",
        "segment_ids": ["title", "body"],
        "start": 2.0,
        "end": 5.0,
    })

    assert entries == [{
        "shot_id": "shot_001",
        "scene_id": "scene_001",
        "segment_ids": ["title", "body"],
        "start": 0.0,
        "end": 5.0,
    }]
