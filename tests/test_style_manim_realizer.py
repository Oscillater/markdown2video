"""ManimRealizer 测试：token → manim 参数的唯一换算点。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from manim import FadeIn, FadeOut, Square, Write

from md2video.style.manim_realizer import ManimRealizer
from md2video.style.packs import get_pack


def _realizer(frame_height_px: int = 854) -> ManimRealizer:
    return ManimRealizer(get_pack("ink_night"), frame_height_px=frame_height_px)


class TestFontSizeRoundTrip:
    """归一化字号 × 参考画面高 = 原 manim font_size（像素不变的关键换算）。"""

    @pytest.mark.parametrize(
        ("role", "expected"),
        [
            ("title_main", 40),
            ("title_sub", 30),
            ("section_header", 20),
            ("section_header_detail", 12),
            ("body", 15),
        ],
    )
    def test_house_style_sizes_at_reference_height(self, role, expected):
        assert _realizer(854).font_size(role) == expected

    def test_font_size_scales_with_frame_height(self):
        # 同一 token 在更高分辨率下按比例放大
        assert _realizer(1708).font_size("title_main") == 80

    def test_unknown_role_fails_fast(self):
        with pytest.raises(ValueError, match="Unknown typography role"):
            _realizer().font_size("no_such_role")

    def test_rejects_non_positive_frame_height(self):
        with pytest.raises(ValueError, match="frame_height_px"):
            ManimRealizer(get_pack("ink_night"), frame_height_px=0)


class TestTextConstruction:
    def test_text_uses_pack_tokens(self):
        realizer = _realizer()
        with patch("md2video.style.manim_realizer.Text") as text_cls:
            realizer.text("你好", role="body", line_spacing=0.5)

        text_cls.assert_called_once_with(
            "你好",
            font="FZShuSong-Z01S",
            color="#FFFFFF",
            font_size=15,
            line_spacing=0.5,
        )


class TestMotionIntentMapping:
    def test_write_reveal(self):
        animation = _realizer().reveal("write", Square())
        assert isinstance(animation, Write)

    def test_fade_reveal(self):
        assert isinstance(_realizer().reveal("fade", Square()), FadeIn)

    def test_appear_reveal_is_silent_add(self):
        assert _realizer().reveal("appear", Square()) is None

    def test_instant_dismiss_is_silent_remove(self):
        assert _realizer().dismiss("instant", Square()) is None

    def test_fade_dismiss(self):
        assert isinstance(_realizer().dismiss("fade", Square()), FadeOut)

    def test_unknown_intent_degrades_with_warning(self, capsys):
        realizer = _realizer()
        assert realizer.reveal("explode", Square()) is None
        assert realizer.dismiss("explode", Square()) is None

        assert len(realizer.warnings) == 2
        assert any("reveal" in w and "explode" in w for w in realizer.warnings)
        assert any("dismiss" in w and "explode" in w for w in realizer.warnings)
        captured = capsys.readouterr().out
        assert captured.count("Style warning") == 2

    def test_unknown_intent_warning_deduplicated(self):
        realizer = _realizer()
        realizer.reveal("explode", Square())
        realizer.reveal("explode", Square())
        assert len(realizer.warnings) == 1


class TestPaceAndColors:
    def test_silent_pace_slots(self):
        realizer = _realizer()
        assert realizer.silent_pace("title_hold") == 1.0
        assert realizer.silent_pace("section_header") == 0.5
        assert realizer.silent_pace("body") == 2.0

    def test_unknown_pace_slot_fails_fast(self):
        with pytest.raises(ValueError, match="Unknown silent pace slot"):
            _realizer().silent_pace("nope")

    def test_transition_duration_from_token(self):
        assert _realizer().transition_duration() == 1.0

    def test_background_color_from_palette(self):
        assert _realizer().background_color() == "#000000"

    def test_motif_colors_from_palette(self):
        # 主点=文字色（原 WHITE 圆点），副点=强调色（原 manim BLUE 圆点）
        assert _realizer().motif_colors() == ("#FFFFFF", "#58C4DD")
