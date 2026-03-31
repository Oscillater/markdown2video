"""Tests for md2video.parser.segmenter: custom_sentence_split and _is_declaration_or_marker."""
from __future__ import annotations

from md2video.parser.segmenter import _is_declaration_or_marker, custom_sentence_split


# ========== _is_declaration_or_marker ==========


class TestIsDeclarationOrMarker:
    # music 声明
    def test_music_declaration_bracket(self):
        assert _is_declaration_or_marker('[music:name="bgm",src="./music.mp3"]') is True

    def test_music_declaration_lowercase(self):
        assert _is_declaration_or_marker('[music:name="x",src="y"]') is True

    def test_music_declaration_uppercase(self):
        assert _is_declaration_or_marker('[MUSIC:name="x",src="y"]') is True

    def test_music_declaration_with_spaces(self):
        assert _is_declaration_or_marker('[music: name="x", src="y"]') is True

    def test_music_declaration_not_missing_bracket(self):
        assert _is_declaration_or_marker('music:name="x",src="y"') is False

    # music marker
    def test_music_start_bracket(self):
        assert _is_declaration_or_marker("[music_start bgm]") is True

    def test_music_start_angle_bracket(self):
        assert _is_declaration_or_marker("<music_start bgm>") is True

    def test_music_end_bracket(self):
        assert _is_declaration_or_marker("[music_end bgm]") is True

    def test_music_end_angle_bracket(self):
        assert _is_declaration_or_marker("<music_end bgm>") is True

    def test_music_start_quoted(self):
        assert _is_declaration_or_marker('[music_start "my bgm"]') is True

    # image 声明
    def test_image_declaration_bracket(self):
        assert _is_declaration_or_marker('[image:name="logo",src="./logo.png"]') is True

    # image marker
    def test_image_start_bracket(self):
        assert _is_declaration_or_marker("[image_start logo]") is True

    def test_image_end_bracket(self):
        assert _is_declaration_or_marker("[image_end logo]") is True

    # 无关文本
    def test_plain_text(self):
        assert _is_declaration_or_marker("这是一段普通文本") is False

    def test_heading(self):
        assert _is_declaration_or_marker("# 大标题") is False

    def test_empty_string(self):
        assert _is_declaration_or_marker("") is False


# ========== custom_sentence_split ==========


class TestCustomSentenceSplit:
    # 声明和 marker 直接透传
    def test_declaration_passthrough(self):
        assert custom_sentence_split('[music:name="bgm",src="./music.mp3"]') == \
            ['[music:name="bgm",src="./music.mp3"]']

    def test_marker_passthrough(self):
        assert custom_sentence_split("[music_start bgm]") == ["[music_start bgm]"]

    # 基本分句
    def test_single_sentence(self):
        result = custom_sentence_split("这是一个测试。")
        assert result == ["这是一个测试"]

    def test_comma_grouping(self):
        # 逗号分组，未超 max_len，整体作为一段（结尾标点被去除）
        result = custom_sentence_split("短句一，短句二，短句三。")
        assert result == ["短句一，短句二，短句三"]

    def test_comma_split_exceeds_max_len(self):
        result = custom_sentence_split("第一句很长很长的话，第二句也很长，第三句结束。")
        assert result == ["第一句很长很长的话，第二句也很长", "第三句结束"]

    def test_question_and_period_split(self):
        result = custom_sentence_split("问君能有几多愁？恰似一江春水向东流。")
        assert result == ["问君能有几多愁", "恰似一江春水向东流"]

    def test_semicolon_split(self):
        result = custom_sentence_split("第一部分；第二部分。")
        assert result == ["第一部分", "第二部分"]

    def test_ellipsis_split(self):
        result = custom_sentence_split("他在想什么……然后走开了。")
        assert result == ["他在想什么", "然后走开了"]

    def test_ideographic_comma(self):
        result = custom_sentence_split("苹果、香蕉、橘子、葡萄。")
        assert result == ["苹果、香蕉、橘子、葡萄"]

    def test_em_dash(self):
        result = custom_sentence_split("前面——后面。")
        assert result == ["前面——后面"]

    # 边界情况
    def test_empty_string(self):
        assert custom_sentence_split("") == []

    def test_whitespace_only(self):
        assert custom_sentence_split("   ") == []

    def test_no_punctuation(self):
        assert custom_sentence_split("这是一段没有标点的连续文本") == \
            ["这是一段没有标点的连续文本"]

    def test_only_commas_no_period(self):
        # 仅逗号无句号，结尾时 buffer 刷出
        result = custom_sentence_split("一，二，三，四")
        assert result == ["一，二，三，四"]

    def test_mixed_comma_and_period(self):
        result = custom_sentence_split("第一句，还有内容。第二句，也是内容。")
        assert result == ["第一句，还有内容", "第二句，也是内容"]

    # max_len 参数
    def test_custom_max_len_short(self):
        result = custom_sentence_split("一二三四五六七八九十。十一十二十三十四十五十六。", max_len=6)
        assert result == ["一二三四五六七八九十", "十一十二十三十四十五十六"]

    def test_custom_max_len_long(self):
        result = custom_sentence_split("一二三四五六七八九十。十一十二十三十四十五十六。", max_len=100)
        assert result == ["一二三四五六七八九十", "十一十二十三十四十五十六"]
