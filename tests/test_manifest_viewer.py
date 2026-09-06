"""A4 manifest_viewer.html 生成器：结构化断言 + 黄金快照。

黄金快照的输入全部使用确定性合成数据（固定 run_id / 固定路径 / 固定
文本），生成器是纯函数，因此快照可以逐字节比对。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from md2video.inspect.viewer import (
    VIEWER_FILENAME,
    build_run_view,
    render_viewer_html,
    write_manifest_viewer,
)
from md2video.manifest.schema import (
    AudioAsset,
    AudioRequest,
    ExecutionAssets,
    FinalResultManifest,
    PlanManifest,
    ScenePlan,
    SegmentPlan,
    ShotPlan,
    VisualAsset,
)
from md2video.style.packs import get_pack


RUN_DIR = "X:/runs/20260906-120000-abc123"

GOLDEN_PATH = Path(__file__).parent / "golden" / "manifest_viewer.html"


def _sample_plan() -> PlanManifest:
    return PlanManifest(
        version="2",
        segments=[
            SegmentPlan(id="title_main_001", text="检查页示例", segment_type="title_main"),
            SegmentPlan(
                id="content_001", text="第一段正文", segment_type="content",
                audio_request=AudioRequest(),
                section_context="第一节",
            ),
            SegmentPlan(
                id="header_001", text="第二节标题", segment_type="section_header",
                section_context="第二节",
            ),
        ],
        scenes=[
            ScenePlan(
                id="scene_001",
                visual_type="text_only",
                layout_type="center_title_body",
                shots=[ShotPlan(id="shot_001", segment_ids=["title_main_001"])],
            ),
            ScenePlan(
                id="scene_002",
                visual_type="stock_image",
                visual_params={"preferred_provider": "local", "path": "img.png"},
                layout_type="image_top_text_bottom",
                layout_params={"split": "balanced"},
                shots=[
                    ShotPlan(
                        id="shot_002",
                        segment_ids=["content_001", "header_001"],
                        cues=[{
                            "id": "img_logo", "cue_type": "marker_image",
                            "kind": "start", "name": "logo", "position": "start",
                            "anchor_segment_id": "content_001",
                        }],
                    ),
                ],
            ),
        ],
    )


def _sample_assets() -> ExecutionAssets:
    return ExecutionAssets(
        audio_assets=[
            AudioAsset(
                segment_id="content_001", path=f"{RUN_DIR}/tts/a.wav",
                duration=2.4, provider="edge-tts", cache_key="key-audio-1",
            ),
        ],
        visual_assets=[
            VisualAsset(
                shot_id="shot_002", path=f"{RUN_DIR}/visuals/scene_002/img.png",
                width=300, height=300, provider="local", cache_key="key-visual-1",
            ),
        ],
    )


def _sample_timeline() -> dict:
    return {
        "text": [
            {
                "segment_id": "content_001", "segment_type": "content",
                "text": "第一段正文", "start": 1.0, "end": 3.4,
                "scene_id": "scene_002", "shot_id": "shot_002",
            },
        ],
        "markers": [
            {
                "id": "img_logo", "cue_type": "marker_image", "kind": "start",
                "name": "logo", "time": 1.0, "scene_id": "scene_002",
                "shot_id": "shot_002",
            },
        ],
        "shots": [
            {
                "shot_id": "shot_001", "scene_id": "scene_001",
                "layout_type": "center_title_body",
                "start": 0.0, "end": 1.0, "segment_ids": ["title_main_001"],
            },
            {
                "shot_id": "shot_002", "scene_id": "scene_002",
                "layout_type": "image_top_text_bottom",
                "start": 1.0, "end": 5.0, "segment_ids": ["content_001", "header_001"],
            },
        ],
    }


def _sample_final_result(warnings: list[str] | None = None) -> FinalResultManifest:
    return FinalResultManifest(
        run_id="20260906-120000-abc123",
        status="completed",
        output_mp4=f"{RUN_DIR}/output.mp4",
        used_assets={"audio": [{"segment_id": "content_001"}],
                     "visual": [{"shot_id": "shot_002"}]},
        warnings=warnings or [],
        artifact_index={
            "plan": f"{RUN_DIR}/plan.json",
            "execution_assets": f"{RUN_DIR}/execution-assets.json",
            "timeline": f"{RUN_DIR}/timeline.json",
            "result": f"{RUN_DIR}/result.json",
            "manifest_viewer": f"{RUN_DIR}/manifest_viewer.html",
            "base_video": f"{RUN_DIR}/base.mp4",
            "render_dir": f"{RUN_DIR}/manim_render_x",
            "render_provider": "manim",
        },
    )


def _build_view(**overrides) -> dict:
    kwargs = dict(
        run_id="20260906-120000-abc123",
        plan=_sample_plan(),
        assets=_sample_assets(),
        timeline_data=_sample_timeline(),
        final_result=_sample_final_result(
            warnings=["Tool pexels failed for scene scene_002: no key"],
        ),
        style_pack=get_pack("ink_night"),
        style_requested="ink_night",
    )
    kwargs.update(overrides)
    return build_run_view(**kwargs)


class TestBuildRunView:
    def test_duration_estimate_vs_actual(self):
        view = _build_view()
        duration = view["duration"]
        # 估算：标题卡 title_hold 1.0 + 转场 1.0；content_001 有声 2.4；
        # header_001 静默 0.5 + 转场 1.0
        assert duration["estimated_total"] == pytest.approx(1.0 + 1.0 + 2.4 + 0.5 + 1.0)
        assert duration["voiced_seconds"] == pytest.approx(2.4)
        # 实际 = timeline 末 shot end
        assert duration["actual_total"] == pytest.approx(5.0)
        assert duration["delta"] == pytest.approx(5.0 - duration["estimated_total"])

    def test_view_sections_carry_the_four_ledgers(self):
        view = _build_view()
        assert view["run_id"] == "20260906-120000-abc123"
        assert view["status"] == "completed"
        assert view["style_pack"] == {
            "requested": "ink_night", "resolved": "ink_night", "motif_kind": "orbit_dots",
        }
        # plan：segments 角色 + scenes visual/layout intent + shots with cues
        segment_types = {s["id"]: s["segment_type"] for s in view["plan"]["segments"]}
        assert segment_types == {
            "title_main_001": "title_main",
            "content_001": "content",
            "header_001": "section_header",
        }
        scene_002 = view["plan"]["scenes"][1]
        assert scene_002["visual_type"] == "stock_image"
        assert scene_002["layout_type"] == "image_top_text_bottom"
        assert scene_002["shots"][0]["cues"][0]["id"] == "img_logo"
        # assets：provider / cache key / 尺寸 / duration / 路径
        assert view["assets"]["audio"][0]["cache_key"] == "key-audio-1"
        assert view["assets"]["visual"][0]["provider"] == "local"
        assert view["assets"]["visual"][0]["width"] == 300
        # timeline：shot 主时间轴（含实际时长）、text/marker cue
        shots = view["timeline"]["shots"]
        assert [s["shot_id"] for s in shots] == ["shot_001", "shot_002"]
        assert shots[1]["duration"] == pytest.approx(4.0)
        assert view["timeline"]["text_cues"][0]["text"] == "第一段正文"
        assert view["timeline"]["markers"][0]["id"] == "img_logo"
        # result + warnings
        assert view["result"]["artifact_index"]["render_provider"] == "manim"
        assert "Tool pexels failed" in view["warnings"][0]

    def test_missing_timeline_is_tolerated(self):
        view = _build_view(timeline_data=None)
        assert view["timeline"] == {"shots": [], "text_cues": [], "markers": []}
        assert view["duration"]["actual_total"] == 0.0


def _json_payload(html: str) -> str:
    marker = '<script id="md2video-view" type="application/json">'
    start = html.index(marker) + len(marker)
    # 内嵌 JSON 中的 "</" 已转义为 "<\/"，因此首个 "</script>" 就是数据块结尾
    end = html.index("</script>", start)
    return html[start:end]


class TestRenderViewerHtml:
    def test_html_is_self_contained_and_shows_key_facts(self):
        html = render_viewer_html(_build_view())
        # 单文件自包含：无外部引用
        assert "http://" not in html
        assert "https://" not in html
        assert "<script src=" not in html
        assert "<link" not in html
        # 关键事实出现在页面数据里
        assert "20260906-120000-abc123" in html
        assert "检查页示例" in html
        assert "第一段正文" in html
        assert "image_top_text_bottom" in html
        assert "orbit_dots" in html
        assert "key-audio-1" in html
        assert "img_logo" in html
        assert "Tool pexels failed" in html

    def test_script_close_tag_in_text_is_escaped(self):
        plan = _sample_plan()
        plan.segments[1].text = "</script><script>alert(1)</script>"
        html = render_viewer_html(_build_view(plan=plan))
        payload = _json_payload(html)
        assert "</script><script>alert(1)</script>" not in payload
        # "<\\/" 是合法 JSON 转义，解析回来仍是原文
        parsed = json.loads(payload)
        assert parsed["plan"]["segments"][1]["text"] == "</script><script>alert(1)</script>"


class TestGoldenSnapshot:
    def test_matches_golden_snapshot(self):
        html = render_viewer_html(_build_view())
        if not GOLDEN_PATH.exists():
            pytest.fail(
                f"golden snapshot missing: {GOLDEN_PATH}; "
                "regenerate it deliberately (render_viewer_html is deterministic) "
                "and commit the new snapshot"
            )
        assert html == GOLDEN_PATH.read_text(encoding="utf-8")

    def test_write_manifest_viewer_writes_run_dir(self, tmp_path):
        path = write_manifest_viewer(tmp_path, view=_build_view())
        assert path == tmp_path / VIEWER_FILENAME
        assert path.read_text(encoding="utf-8") == render_viewer_html(_build_view())
