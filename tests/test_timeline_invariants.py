"""Timeline invariants 纯函数检查器测试 + manim_tool 闸门接入测试。"""
from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from md2video.manifest.schema import AudioAsset, ExecutionAssets, PlanManifest
from md2video.timeline.invariants import (
    TIME_EPSILON,
    check_timeline,
)


def _plan(segments=None, scenes=None) -> PlanManifest:
    return PlanManifest(
        segments=segments or [],
        scenes=scenes if scenes is not None else [],
    )


def _two_shot_plan() -> PlanManifest:
    return _plan(
        segments=[
            {
                "id": "seg_001",
                "text": "first",
                "segment_type": "content",
            },
            {
                "id": "seg_002",
                "text": "second",
                "segment_type": "content",
            },
        ],
        scenes=[
            {
                "id": "scene_001",
                "shots": [{
                    "id": "shot_001",
                    "segment_ids": ["seg_001"],
                }],
            },
            {
                "id": "scene_002",
                "shots": [{
                    "id": "shot_002",
                    "segment_ids": ["seg_002"],
                }],
            },
        ],
    )


def _text_entry(segment_id, shot_id, start, end, segment_type="content"):
    return {
        "segment_id": segment_id,
        "segment_type": segment_type,
        "shot_id": shot_id,
        "start": start,
        "end": end,
    }


def _shot_entry(shot_id, segment_ids, start, end, scene_id=""):
    return {
        "shot_id": shot_id,
        "scene_id": scene_id,
        "segment_ids": segment_ids,
        "start": start,
        "end": end,
    }


def _timeline(text=None, markers=None, shots=None) -> dict:
    return {
        "text": text or [],
        "markers": markers or [],
        "shots": shots or [],
    }


def _empty_assets() -> ExecutionAssets:
    return ExecutionAssets()


class TestStructureChecks:
    def test_missing_required_keys(self):
        check = check_timeline(_plan(), _empty_assets(), {"text": []})
        assert not check.ok
        assert any("Timeline missing required keys" in e for e in check.errors)

    def test_non_dict_payload(self):
        check = check_timeline(_plan(), _empty_assets(), ["text"])
        assert not check.ok
        assert any("Timeline missing required keys" in e for e in check.errors)

    @pytest.mark.parametrize("key", ["text", "markers", "shots"])
    def test_field_must_be_list(self, key):
        data = _timeline()
        data[key] = {}
        check = check_timeline(_plan(), _empty_assets(), data)
        assert not check.ok
        assert f"Timeline field must be a list: {key}" in check.errors


class TestShotCoverageAndTiming:
    def test_missing_plan_shot(self):
        plan = _two_shot_plan()
        data = _timeline(shots=[
            _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
        ])
        check = check_timeline(plan, _empty_assets(), data)
        assert not check.ok
        assert any("Timeline missing plan shots: ['shot_002']" in e for e in check.errors)

    def test_missing_plan_segment(self):
        plan = _two_shot_plan()
        data = _timeline(shots=[
            _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
            _shot_entry("shot_002", [], 2.0, 4.0),
        ])
        check = check_timeline(plan, _empty_assets(), data)
        assert not check.ok
        assert any(
            "Timeline missing plan segments" in e and "shot_002" in e
            for e in check.errors
        )

    def test_shot_missing_start_end(self):
        plan = _two_shot_plan()
        data = _timeline(shots=[
            _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
            {"shot_id": "shot_002", "segment_ids": ["seg_002"]},
        ])
        check = check_timeline(plan, _empty_assets(), data)
        assert not check.ok
        assert any("Timeline shot missing start/end: shot_002" in e for e in check.errors)

    def test_shot_non_numeric_timing(self):
        plan = _two_shot_plan()
        data = _timeline(shots=[
            _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
            _shot_entry("shot_002", ["seg_002"], "x", 4.0),
        ])
        check = check_timeline(plan, _empty_assets(), data)
        assert not check.ok
        assert any("Timeline shot start/end must be numeric: shot_002" in e for e in check.errors)

    def test_shot_infinite_timing(self):
        plan = _two_shot_plan()
        data = _timeline(shots=[
            _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
            _shot_entry("shot_002", ["seg_002"], 2.0, math.inf),
        ])
        check = check_timeline(plan, _empty_assets(), data)
        assert not check.ok
        assert any("Timeline shot start/end must be finite: shot_002" in e for e in check.errors)

    def test_shot_end_before_start(self):
        plan = _two_shot_plan()
        data = _timeline(shots=[
            _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
            _shot_entry("shot_002", ["seg_002"], 4.0, 3.0),
        ])
        check = check_timeline(plan, _empty_assets(), data)
        assert not check.ok
        assert any("Timeline shot end before start: shot_002" in e for e in check.errors)

    def test_zero_duration_shot_allowed(self):
        plan = _two_shot_plan()
        data = _timeline(shots=[
            _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
            _shot_entry("shot_002", ["seg_002"], 2.0, 2.0),
        ])
        check = check_timeline(plan, _empty_assets(), data)
        assert check.ok


class TestShotOrderAndOverlap:
    def test_out_of_order_shots_rejected(self):
        plan = _two_shot_plan()
        data = _timeline(shots=[
            _shot_entry("shot_002", ["seg_002"], 2.0, 4.0),
            _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
        ])
        check = check_timeline(plan, _empty_assets(), data)
        assert not check.ok
        assert any("Timeline shots out of plan order" in e for e in check.errors)
        # 报错可定位：包含乱序的 shot id
        assert any("shot_002" in e and "shot_001" in e for e in check.errors)

    def test_overlapping_shots_rejected(self):
        plan = _two_shot_plan()
        data = _timeline(shots=[
            _shot_entry("shot_001", ["seg_001"], 0.0, 2.5),
            _shot_entry("shot_002", ["seg_002"], 2.0, 4.0),
        ])
        check = check_timeline(plan, _empty_assets(), data)
        assert not check.ok
        assert any("Timeline shots overlap" in e for e in check.errors)
        assert any("shot_002" in e and "shot_001" in e for e in check.errors)

    def test_contiguous_shots_accepted(self):
        plan = _two_shot_plan()
        data = _timeline(shots=[
            _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
            _shot_entry("shot_002", ["seg_002"], 2.0, 4.0),
        ])
        check = check_timeline(plan, _empty_assets(), data)
        assert check.ok

    def test_gap_between_shots_allowed(self):
        plan = _two_shot_plan()
        data = _timeline(shots=[
            _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
            _shot_entry("shot_002", ["seg_002"], 2.5, 4.0),
        ])
        check = check_timeline(plan, _empty_assets(), data)
        assert check.ok

    def test_float_noise_within_epsilon_accepted(self):
        plan = _two_shot_plan()
        data = _timeline(shots=[
            _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
            _shot_entry("shot_002", ["seg_002"], 2.0 - TIME_EPSILON / 2, 4.0),
        ])
        check = check_timeline(plan, _empty_assets(), data)
        assert check.ok


class TestMarkerChecks:
    def _marker_plan(self) -> PlanManifest:
        return _plan(
            scenes=[
                {
                    "id": "scene_001",
                    "shots": [{
                        "id": "shot_001",
                        "segment_ids": [],
                        "cues": [{
                            "id": "marker_001",
                            "cue_type": "marker_music",
                            "kind": "start",
                            "name": "bgm",
                        }],
                    }],
                },
            ],
        )

    def test_missing_marker_entry(self):
        data = _timeline(shots=[_shot_entry("shot_001", [], 1.0, 3.0)])
        check = check_timeline(self._marker_plan(), _empty_assets(), data)
        assert not check.ok
        assert any("Timeline missing marker entries: ['marker_001']" in e for e in check.errors)

    @pytest.mark.parametrize(
        "time_value",
        ["not-a-number", math.inf, None],
    )
    def test_marker_invalid_time(self, time_value):
        data = _timeline(
            markers=[{"id": "marker_001", "time": time_value}],
            shots=[_shot_entry("shot_001", [], 1.0, 3.0)],
        )
        check = check_timeline(self._marker_plan(), _empty_assets(), data)
        assert not check.ok
        assert any(
            "Timeline marker time must be numeric and finite" in e
            for e in check.errors
        )

    def test_marker_inside_shot_accepted(self):
        data = _timeline(
            markers=[{"id": "marker_001", "time": 1.5}],
            shots=[_shot_entry("shot_001", [], 1.0, 3.0)],
        )
        check = check_timeline(self._marker_plan(), _empty_assets(), data)
        assert check.ok

    def test_marker_at_shot_boundary_accepted(self):
        data = _timeline(
            markers=[{"id": "marker_001", "time": 3.0}],
            shots=[_shot_entry("shot_001", [], 1.0, 3.0)],
        )
        check = check_timeline(self._marker_plan(), _empty_assets(), data)
        assert check.ok

    def test_marker_outside_shot_rejected(self):
        data = _timeline(
            markers=[{"id": "marker_001", "time": 5.0}],
            shots=[_shot_entry("shot_001", [], 1.0, 3.0)],
        )
        check = check_timeline(self._marker_plan(), _empty_assets(), data)
        assert not check.ok
        assert any("Timeline marker outside its shot interval" in e for e in check.errors)
        assert any("marker_001" in e and "shot_001" in e for e in check.errors)

    def test_marker_matched_by_segment_id(self):
        data = _timeline(
            markers=[{"segment_id": "marker_001", "time": 2.0}],
            shots=[_shot_entry("shot_001", [], 1.0, 3.0)],
        )
        check = check_timeline(self._marker_plan(), _empty_assets(), data)
        assert check.ok


class TestTextCueChecks:
    def test_text_cue_inside_shot_accepted(self):
        plan = _two_shot_plan()
        data = _timeline(
            text=[
                _text_entry("seg_001", "shot_001", 0.5, 1.5),
                _text_entry("seg_002", "shot_002", 2.5, 3.5),
            ],
            shots=[
                _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
                _shot_entry("shot_002", ["seg_002"], 2.0, 4.0),
            ],
        )
        check = check_timeline(plan, _empty_assets(), data)
        assert check.ok

    def test_text_cue_crossing_shot_end_accepted(self):
        """堆叠字幕在起点 shot 之后才关闭，与所属 shot 相交即合法。"""
        plan = _two_shot_plan()
        data = _timeline(
            text=[_text_entry("seg_001", "shot_001", 0.5, 10.0)],
            shots=[
                _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
                _shot_entry("shot_002", ["seg_002"], 2.0, 4.0),
            ],
        )
        check = check_timeline(plan, _empty_assets(), data)
        assert check.ok

    def test_text_cue_outside_shot_rejected(self):
        plan = _two_shot_plan()
        data = _timeline(
            text=[_text_entry("seg_002", "shot_002", 6.0, 8.0)],
            shots=[
                _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
                _shot_entry("shot_002", ["seg_002"], 2.0, 4.0),
            ],
        )
        check = check_timeline(plan, _empty_assets(), data)
        assert not check.ok
        assert any("Timeline text cue outside its shot interval" in e for e in check.errors)
        assert any("seg_002" in e and "shot_002" in e for e in check.errors)

    def test_text_cue_before_shot_rejected(self):
        plan = _two_shot_plan()
        data = _timeline(
            text=[_text_entry("seg_002", "shot_002", 0.0, 1.0)],
            shots=[
                _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
                _shot_entry("shot_002", ["seg_002"], 2.0, 4.0),
            ],
        )
        check = check_timeline(plan, _empty_assets(), data)
        assert not check.ok

    def test_text_cue_unresolvable_shot_ignored(self):
        """无 layout 契约的条目（如 legacy marker 文本）不强制归属检查。"""
        plan = _two_shot_plan()
        data = _timeline(
            text=[_text_entry("seg_x", "unknown_shot", 0.0, 1.0)],
            shots=[
                _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
                _shot_entry("shot_002", ["seg_002"], 2.0, 4.0),
            ],
        )
        check = check_timeline(plan, _empty_assets(), data)
        assert check.ok

    def test_text_cue_unclosed_warns_not_rejects(self):
        plan = _two_shot_plan()
        data = _timeline(
            text=[_text_entry("seg_001", "shot_001", 0.5, None)],
            shots=[
                _shot_entry("shot_001", ["seg_001"], 0.0, 2.0),
                _shot_entry("shot_002", ["seg_002"], 2.0, 4.0),
            ],
        )
        check = check_timeline(plan, _empty_assets(), data)
        assert check.ok
        assert any("missing or non-finite timing" in w for w in check.warnings)


class TestVoiceoverDurationWarnings:
    def _voiced_plan(self, segment_type: str = "content") -> PlanManifest:
        return _plan(
            segments=[{
                "id": "seg_001",
                "text": "hello",
                "segment_type": segment_type,
                "audio_request": {},
            }],
            scenes=[
                {
                    "id": "scene_001",
                    "shots": [{"id": "shot_001", "segment_ids": ["seg_001"]}],
                },
            ],
        )

    def _voiced_assets(self, duration: float) -> ExecutionAssets:
        return ExecutionAssets(audio_assets=[
            AudioAsset(segment_id="seg_001", path="/x.wav", duration=duration),
        ])

    def test_matching_duration_no_warning(self):
        plan = self._voiced_plan()
        data = _timeline(
            text=[_text_entry("seg_001", "shot_001", 0.0, 3.0)],
            shots=[_shot_entry("shot_001", ["seg_001"], 0.0, 3.0)],
        )
        check = check_timeline(plan, self._voiced_assets(3.0), data)
        assert check.ok
        assert check.warnings == []

    def test_small_deviation_within_slack_no_warning(self):
        plan = self._voiced_plan()
        data = _timeline(
            text=[_text_entry("seg_001", "shot_001", 0.0, 3.9)],
            shots=[_shot_entry("shot_001", ["seg_001"], 0.0, 3.9)],
        )
        check = check_timeline(plan, self._voiced_assets(3.0), data)
        assert check.ok
        assert check.warnings == []

    def test_large_deviation_warns(self):
        plan = self._voiced_plan()
        data = _timeline(
            text=[_text_entry("seg_001", "shot_001", 0.0, 10.0)],
            shots=[_shot_entry("shot_001", ["seg_001"], 0.0, 10.0)],
        )
        check = check_timeline(plan, self._voiced_assets(3.0), data)
        assert check.ok  # 告警不拒绝
        assert any(
            "Voiceover duration mismatch" in w and "seg_001" in w
            for w in check.warnings
        )

    def test_truncated_cue_warns(self):
        plan = self._voiced_plan()
        data = _timeline(
            text=[_text_entry("seg_001", "shot_001", 0.0, 1.0)],
            shots=[_shot_entry("shot_001", ["seg_001"], 0.0, 1.0)],
        )
        check = check_timeline(plan, self._voiced_assets(3.0), data)
        assert check.ok
        assert any("Voiceover duration mismatch" in w for w in check.warnings)

    def test_missing_text_cue_for_voiced_segment_warns(self):
        plan = self._voiced_plan()
        data = _timeline(shots=[_shot_entry("shot_001", ["seg_001"], 0.0, 3.0)])
        check = check_timeline(plan, self._voiced_assets(3.0), data)
        assert check.ok
        assert any("no text cue for voiced segment" in w for w in check.warnings)

    def test_section_header_overlong_no_warning(self):
        """堆叠字幕持续显示到收尾是设计行为，超长不告警。"""
        plan = self._voiced_plan("section_header")
        data = _timeline(
            text=[_text_entry("seg_001", "shot_001", 0.0, 75.77,
                              segment_type="section_header")],
            shots=[_shot_entry("shot_001", ["seg_001"], 0.0, 75.77)],
        )
        check = check_timeline(plan, self._voiced_assets(1.92), data)
        assert check.ok
        assert check.warnings == []

    def test_section_header_truncated_still_warns(self):
        plan = self._voiced_plan("section_header")
        data = _timeline(
            text=[_text_entry("seg_001", "shot_001", 0.0, 1.0,
                              segment_type="section_header")],
            shots=[_shot_entry("shot_001", ["seg_001"], 0.0, 1.0)],
        )
        check = check_timeline(plan, self._voiced_assets(3.0), data)
        assert check.ok
        assert any("Voiceover duration mismatch" in w for w in check.warnings)


class TestManimToolGate:
    """闸门接入：manim_tool 渲染后必须跑 invariants，坏 timeline 被拒。"""

    def _write_render_inputs(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        plan_path = tmp_path / "plan.json"
        assets_path = tmp_path / "execution-assets.json"
        timeline_path = tmp_path / "timeline.json"
        plan = _two_shot_plan()
        plan_path.write_text(plan.model_dump_json(), encoding="utf-8")
        assets_path.write_text(
            _empty_assets().model_dump_json(), encoding="utf-8",
        )
        return plan_path, assets_path, timeline_path

    def _execute_with_timeline(self, tmp_path: Path, timeline_data: dict) -> dict:
        from md2video.tools.render.manim_tool import ManimRenderTool

        plan_path, assets_path, timeline_path = self._write_render_inputs(tmp_path)
        tool = ManimRenderTool()
        completed = MagicMock(returncode=0, stderr="")

        def run_success(*args, **kwargs):
            Path(kwargs["env"]["MD2VIDEO_TIMELINE_PATH"]).write_text(
                json.dumps(timeline_data), encoding="utf-8",
            )
            return completed

        with patch(
            "md2video.tools.render.manim_tool.subprocess.run",
            side_effect=run_success,
        ):
            with patch.object(
                tool,
                "_find_rendered_video",
                return_value=tmp_path / "rendered.mp4",
            ):
                return tool.execute({
                    "plan_path": str(plan_path),
                    "execution_assets_path": str(assets_path),
                    "timeline_path": str(timeline_path),
                    "output_dir": str(tmp_path),
                })

    def test_valid_timeline_passes_and_reports_no_warnings(self, tmp_path):
        output = self._execute_with_timeline(tmp_path, _timeline(
            text=[
                _text_entry("seg_001", "shot_001", 0.0, 2.0),
                _text_entry("seg_002", "shot_002", 2.0, 4.0),
            ],
            shots=[
                _shot_entry("shot_001", ["seg_001"], 0.0, 2.0, "scene_001"),
                _shot_entry("shot_002", ["seg_002"], 2.0, 4.0, "scene_002"),
            ],
        ))
        assert output["warnings"] == []

    def test_overlapping_timeline_rejected(self, tmp_path):
        with pytest.raises(RuntimeError, match="Timeline shots overlap"):
            self._execute_with_timeline(tmp_path, _timeline(shots=[
                _shot_entry("shot_001", ["seg_001"], 0.0, 3.0, "scene_001"),
                _shot_entry("shot_002", ["seg_002"], 2.0, 4.0, "scene_002"),
            ]))

    def test_out_of_order_timeline_rejected(self, tmp_path):
        with pytest.raises(RuntimeError, match="Timeline shots out of plan order"):
            self._execute_with_timeline(tmp_path, _timeline(shots=[
                _shot_entry("shot_002", ["seg_002"], 2.0, 4.0, "scene_002"),
                _shot_entry("shot_001", ["seg_001"], 0.0, 2.0, "scene_001"),
            ]))

    def test_error_message_includes_timeline_path(self, tmp_path):
        with pytest.raises(RuntimeError, match="timeline.json"):
            self._execute_with_timeline(tmp_path, _timeline(shots=[
                _shot_entry("shot_001", ["seg_001"], 0.0, 3.0, "scene_001"),
                _shot_entry("shot_002", ["seg_002"], 2.0, 4.0, "scene_002"),
            ]))
