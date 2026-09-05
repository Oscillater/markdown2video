"""时长估算器测试：音频事实 + pack 节奏 + 转场开销常数（纯函数）。"""
from __future__ import annotations

from md2video.manifest.schema import (
    AudioAsset,
    ExecutionAssets,
    PlanManifest,
    ScenePlan,
    SegmentPlan,
    ShotPlan,
)
from md2video.style.packs import get_pack
from md2video.timeline.estimate import (
    TRANSITION_OVERHEAD_SECONDS,
    estimate_plan_duration,
)


def _ink_night():
    return get_pack("ink_night")


def _plan(segments, scenes) -> PlanManifest:
    return PlanManifest(segments=segments, scenes=scenes)


class TestEstimatePlanDuration:
    def test_voiced_only_uses_audio_facts(self):
        """有声段 = 音频事实，无转场开销（正文直接出现）。"""
        plan = _plan(
            segments=[
                SegmentPlan(id="s1", text="一", segment_type="content", audio_request={}),
                SegmentPlan(id="s2", text="二", segment_type="content", audio_request={}),
            ],
            scenes=[
                ScenePlan(id="sc1", shots=[ShotPlan(id="sh1", segment_ids=["s1"])]),
                ScenePlan(id="sc2", shots=[ShotPlan(id="sh2", segment_ids=["s2"])]),
            ],
        )
        assets = ExecutionAssets(audio_assets=[
            AudioAsset(segment_id="s1", path="a.wav", duration=3.0),
            AudioAsset(segment_id="s2", path="b.wav", duration=2.5),
        ])

        estimate = estimate_plan_duration(plan, assets, _ink_night())

        assert estimate.voiced_seconds == 5.5
        assert estimate.silent_seconds == 0.0
        assert estimate.overhead_seconds == 0.0
        assert estimate.total_seconds == 5.5
        assert estimate.per_segment == {"s1": 3.0, "s2": 2.5}

    def test_silent_body_uses_pack_pace_without_overhead(self):
        """静默正文直接出现：pack silent.body，不加转场开销。"""
        plan = _plan(
            segments=[SegmentPlan(id="s1", text="一", segment_type="content")],
            scenes=[ScenePlan(id="sc1", shots=[ShotPlan(id="sh1", segment_ids=["s1"])])],
        )

        estimate = estimate_plan_duration(plan, ExecutionAssets(), _ink_night())

        assert estimate.per_segment == {"s1": 2.0}
        assert estimate.silent_seconds == 2.0
        assert estimate.overhead_seconds == 0.0
        assert estimate.total_seconds == 2.0

    def test_silent_section_header_adds_transition_overhead(self):
        """静默 section header 有 Write 动画：pack 节奏 + 转场开销。"""
        plan = _plan(
            segments=[
                SegmentPlan(id="s1", text="节", segment_type="section_header"),
            ],
            scenes=[ScenePlan(id="sc1", shots=[ShotPlan(id="sh1", segment_ids=["s1"])])],
        )

        estimate = estimate_plan_duration(plan, ExecutionAssets(), _ink_night())

        assert estimate.per_segment == {"s1": 0.5 + TRANSITION_OVERHEAD_SECONDS}
        assert estimate.overhead_seconds == TRANSITION_OVERHEAD_SECONDS

    def test_voiced_section_header_adds_transition_overhead(self):
        plan = _plan(
            segments=[
                SegmentPlan(id="s1", text="节", segment_type="section_header",
                            audio_request={}),
            ],
            scenes=[ScenePlan(id="sc1", shots=[ShotPlan(id="sh1", segment_ids=["s1"])])],
        )
        assets = ExecutionAssets(audio_assets=[
            AudioAsset(segment_id="s1", path="a.wav", duration=2.0),
        ])

        estimate = estimate_plan_duration(plan, assets, _ink_night())

        assert estimate.per_segment == {"s1": 2.0 + TRANSITION_OVERHEAD_SECONDS}
        assert estimate.voiced_seconds == 2.0 + TRANSITION_OVERHEAD_SECONDS

    def test_title_card_counted_once(self):
        """标题卡片只计一次：title_hold + 转场开销；其余标题 segment 记 0。"""
        plan = _plan(
            segments=[
                SegmentPlan(id="t1", text="主", segment_type="title_main"),
                SegmentPlan(id="t2", text="副", segment_type="title_sub"),
            ],
            scenes=[ScenePlan(id="sc1", shots=[ShotPlan(id="sh1", segment_ids=["t1", "t2"])])],
        )

        estimate = estimate_plan_duration(plan, ExecutionAssets(), _ink_night())

        assert estimate.per_segment["t1"] == 1.0 + TRANSITION_OVERHEAD_SECONDS
        assert estimate.per_segment["t2"] == 0.0
        assert estimate.total_seconds == 1.0 + TRANSITION_OVERHEAD_SECONDS

    def test_markers_are_zero_duration(self):
        plan = _plan(
            segments=[
                SegmentPlan(id="s1", text="一", segment_type="content"),
                SegmentPlan(id="m1", text="[music_start bgm]", segment_type="marker_music",
                            marker_data={"kind": "start", "name": "bgm"}),
            ],
            scenes=[ScenePlan(id="sc1", shots=[ShotPlan(id="sh1", segment_ids=["s1"])])],
        )

        estimate = estimate_plan_duration(plan, ExecutionAssets(), _ink_night())

        assert "m1" not in estimate.per_segment
        assert estimate.total_seconds == 2.0

    def test_overhead_constant_is_overridable(self):
        plan = _plan(
            segments=[SegmentPlan(id="s1", text="节", segment_type="section_header")],
            scenes=[ScenePlan(id="sc1", shots=[ShotPlan(id="sh1", segment_ids=["s1"])])],
        )

        estimate = estimate_plan_duration(
            plan, ExecutionAssets(), _ink_night(), transition_overhead=0.25,
        )

        assert estimate.per_segment == {"s1": 0.5 + 0.25}

    def test_estimate_is_pure(self):
        """估算不修改输入（纯函数）。"""
        plan = _plan(
            segments=[SegmentPlan(id="s1", text="一", segment_type="content")],
            scenes=[ScenePlan(id="sc1", shots=[ShotPlan(id="sh1", segment_ids=["s1"])])],
        )
        assets = ExecutionAssets()

        estimate_plan_duration(plan, assets, _ink_night())
        estimate_plan_duration(plan, assets, _ink_night())

        assert plan.segments[0].model_dump() == SegmentPlan(
            id="s1", text="一", segment_type="content").model_dump()
        assert assets.audio_assets == []
        assert assets.visual_assets == []
