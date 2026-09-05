"""ThemeTokens schema 与 pack 注册表测试（纯数据层，无 manim 依赖）。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from md2video.style.packs import (
    DEFAULT_PACK_NAME,
    get_pack,
    pack_names,
    register_pack,
)
from md2video.style.schema import (
    MotionTokens,
    MotifTokens,
    PaletteTokens,
    SilentPaceTokens,
    ThemeTokens,
    TypographyTokens,
)


def _tokens(pack_id="test_pack", **overrides) -> ThemeTokens:
    data = {
        "id": pack_id,
        "palette": {"background": "#000000", "text": "#FFFFFF",
                    "secondary": "#EEEEEE", "accent": "#FF0000"},
        "typography": {
            "font_family": "TestFont",
            "size_title_main": 0.05, "size_title_sub": 0.04,
            "size_section_header": 0.03, "size_section_header_detail": 0.02,
            "size_body": 0.02,
        },
        "motion": {
            "title_reveal": "write", "section_reveal": "write",
            "body_reveal": "appear", "body_dismiss": "instant",
            "section_dismiss": "fade", "motif_transition_duration": 0.8,
            "silent": {"title_hold": 1.2, "section_header": 0.6, "body": 2.5},
        },
        "motif": {"kind": "orbit_dots"},
    }
    data.update(overrides)
    return ThemeTokens(**data)


class TestThemeTokensSchema:
    def test_valid_tokens(self):
        tokens = _tokens()
        assert tokens.id == "test_pack"
        assert tokens.motif.kind == "orbit_dots"
        assert tokens.motion.silent.body == 2.5

    def test_motif_default_is_empty_slot(self):
        data = _tokens()
        data.motif = MotifTokens()
        assert data.motif.kind == ""

    def test_rejects_non_hex_color(self):
        with pytest.raises(ValidationError, match="hex"):
            PaletteTokens(background="black", text="#FFFFFF",
                          secondary="#EEEEEE", accent="#FF0000")

    def test_rejects_three_digit_hex_ok(self):
        palette = PaletteTokens(background="#000", text="#FFF",
                                secondary="#EEE", accent="#F00")
        assert palette.text == "#FFF"

    def test_rejects_non_positive_size(self):
        with pytest.raises(ValidationError):
            TypographyTokens(
                font_family="F", size_title_main=0.0, size_title_sub=0.04,
                size_section_header=0.03, size_section_header_detail=0.02,
                size_body=0.02,
            )

    def test_rejects_size_above_frame(self):
        with pytest.raises(ValidationError):
            TypographyTokens(
                font_family="F", size_title_main=1.5, size_title_sub=0.04,
                size_section_header=0.03, size_section_header_detail=0.02,
                size_body=0.02,
            )

    def test_rejects_negative_pace(self):
        with pytest.raises(ValidationError):
            SilentPaceTokens(title_hold=-1.0, section_header=0.5, body=2.0)

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            ThemeTokens(**{**_tokens().model_dump(), "engine": "manim"})

    def test_json_roundtrip_for_external_file_loading(self):
        """pack 纯数据可 JSON 序列化（外部文件加载接口的数据形状）。"""
        tokens = _tokens()
        restored = ThemeTokens.model_validate_json(tokens.model_dump_json())
        assert restored == tokens


class TestPackRegistry:
    def test_default_pack_is_ink_night(self):
        assert DEFAULT_PACK_NAME == "ink_night"
        pack = get_pack(None)
        assert pack.id == "ink_night"

    def test_unknown_pack_falls_back_to_default(self):
        pack = get_pack("no_such_pack")
        assert pack.id == DEFAULT_PACK_NAME

    def test_get_pack_by_name(self):
        assert get_pack("ink_night").id == "ink_night"

    def test_register_pack_roundtrip(self):
        tokens = _tokens("fresh_pack")
        try:
            register_pack(tokens)
            assert get_pack("fresh_pack") is tokens
            assert "fresh_pack" in pack_names()
        finally:
            from md2video.style import packs
            packs._PACKS.pop("fresh_pack", None)

    def test_register_duplicate_pack_fails_fast(self):
        from md2video.style import packs
        with pytest.raises(ValueError, match="already registered"):
            register_pack(_tokens("ink_night"))
        # 原包未被覆盖
        assert packs._PACKS["ink_night"].id == "ink_night"


class TestInkNightReferencePack:
    """B1 验收：现有 house style 抽取为纯数据 pack。"""

    def test_palette_is_house_style(self):
        palette = get_pack("ink_night").palette
        assert palette.background == "#000000"
        assert palette.text == "#FFFFFF"
        assert palette.accent == "#58C4DD"  # manim BLUE（母题副点色）

    def test_typography_is_house_style(self):
        typo = get_pack("ink_night").typography
        assert typo.font_family == "FZShuSong-Z01S"
        # 归一化字号 = 原 manim font_size / 参考画面高 854
        assert typo.size_title_main == pytest.approx(40 / 854)
        assert typo.size_title_sub == pytest.approx(30 / 854)
        assert typo.size_section_header == pytest.approx(20 / 854)
        assert typo.size_section_header_detail == pytest.approx(12 / 854)
        assert typo.size_body == pytest.approx(15 / 854)

    def test_motion_is_house_style(self):
        motion = get_pack("ink_night").motion
        assert motion.title_reveal == "write"
        assert motion.section_reveal == "write"
        assert motion.body_reveal == "appear"
        assert motion.body_dismiss == "instant"
        assert motion.section_dismiss == "fade"
        assert motion.motif_transition_duration == 1.0
        assert motion.silent.title_hold == 1.0
        assert motion.silent.section_header == 0.5
        assert motion.silent.body == 2.0

    def test_motif_is_orbit_dots(self):
        assert get_pack("ink_night").motif.kind == "orbit_dots"
