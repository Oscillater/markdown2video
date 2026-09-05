"""母题 kind 注册表与 OrbitDotsMotif 测试。"""
from __future__ import annotations

from unittest.mock import MagicMock

from manim import Square

import pytest

from md2video.style.motifs import (
    OrbitDotsMotif,
    create_motif,
    motif_kinds,
    register_motif,
)


class TestMotifRegistry:
    def test_orbit_dots_registered(self):
        assert "orbit_dots" in motif_kinds()

    def test_create_motif_by_kind(self):
        motif = create_motif(
            "orbit_dots", primary_color="#FFFFFF",
            secondary_color="#58C4DD", transition_duration=1.0,
        )
        assert isinstance(motif, OrbitDotsMotif)

    def test_unknown_kind_degrades_to_none_with_warning(self):
        sink: list[str] = []
        motif = create_motif(
            "fireworks", primary_color="#FFFFFF",
            secondary_color="#58C4DD", transition_duration=1.0,
            warnings_sink=sink,
        )
        assert motif is None
        assert len(sink) == 1
        assert "fireworks" in sink[0]

    def test_duplicate_kind_fails_fast(self):
        with pytest.raises(ValueError, match="already registered"):
            @register_motif("orbit_dots")
            class _Duplicate:
                pass


class TestOrbitDotsMotif:
    def _motif(self) -> OrbitDotsMotif:
        return OrbitDotsMotif(
            primary_color="#FFFFFF",
            secondary_color="#58C4DD",
            transition_duration=1.0,
        )

    def test_setup_adds_trackers_but_not_dots(self):
        motif = self._motif()
        scene = MagicMock()

        motif.setup(scene)

        # t_tracker + 隐形锚点加入场景；圆点不加入（标题交接后才 add）
        assert scene.add.call_count == 2
        assert len(motif.dots) == 2

    def test_title_handoff_transforms_and_adds_dots(self):
        motif = self._motif()
        scene = MagicMock()
        motif.setup(scene)
        title_mobject = Square()

        motif.play_title_handoff(scene, [(title_mobject, 0)])

        transform, = scene.play.call_args.args
        assert scene.play.call_args.kwargs["run_time"] == 2.0
        assert transform.mobject is title_mobject
        assert transform.target_mobject is motif.dots[0]
        scene.remove.assert_called_once_with(title_mobject)
        scene.add.assert_called_with(*motif.dots)

    def test_dodge_plays_with_pack_transition_duration(self):
        motif = self._motif()
        scene = MagicMock()
        motif.setup(scene)

        motif.dodge(scene, "image")
        assert scene.play.call_count == 1
        assert scene.play.call_args.kwargs["run_time"] == 1.0
        (image_move,) = scene.play.call_args.args

        scene.play.reset_mock()
        motif.dodge(scene, "default")
        assert scene.play.call_count == 1
        assert scene.play.call_args.kwargs["run_time"] == 1.0
        (default_move,) = scene.play.call_args.args
        # 两个方向的让位目标不同（引擎空间常量）
        assert image_move is not default_move

    def test_dodge_rejects_unknown_target(self):
        motif = self._motif()
        with pytest.raises(ValueError, match="Unknown dodge target"):
            motif.dodge(MagicMock(), "sideways")

    def test_teardown_fades_dots_and_stops_clock(self):
        motif = self._motif()
        scene = MagicMock()
        motif.setup(scene)
        t_tracker = scene.add.call_args_list[0].args[0]
        assert len(t_tracker.get_updaters()) == 1

        motif.teardown(scene)

        fade_outs = scene.play.call_args.args
        assert len(fade_outs) == 2
        assert len(t_tracker.get_updaters()) == 0
