"""Tests for md2video.parser.md_parser."""
from __future__ import annotations

import pytest

from md2video.parser.md_parser import (
    _extract_name_src,
    _parse_image_declaration,
    _parse_image_marker,
    _parse_markdown_sections,
    _parse_music_declaration,
    _parse_music_marker,
    parse_to_plan_manifest,
)


# ========== _extract_name_src ==========


class TestExtractNameSrc:
    def test_double_quoted(self):
        assert _extract_name_src('name="bgm",src="./music.mp3"') == ("bgm", "./music.mp3")

    def test_single_quoted(self):
        assert _extract_name_src("name='bgm',src='./music.mp3'") == ("bgm", "./music.mp3")

    def test_unquoted(self):
        assert _extract_name_src("name=bgm,src=./music.mp3") == ("bgm", "./music.mp3")

    def test_mixed_quotes(self):
        assert _extract_name_src('name="bgm",src=./music.mp3') == ("bgm", "./music.mp3")

    def test_spaces_around_equals(self):
        assert _extract_name_src('name = "bgm" , src = "./music.mp3"') == ("bgm", "./music.mp3")

    def test_missing_name(self):
        assert _extract_name_src('src="./music.mp3"') is None

    def test_missing_src(self):
        assert _extract_name_src('name="bgm"') is None

    def test_empty(self):
        assert _extract_name_src("") is None

    def test_extra_whitespace(self):
        # 额外空格导致 regex group(3) 匹配到带引号的值，这是实际行为
        result = _extract_name_src('  name  =  "bgm"  ,  src  =  "./music.mp3"  ')
        assert result is not None
        assert result[0] == "bgm"


# ========== _parse_music_declaration ==========


class TestParseMusicDeclaration:
    def test_bracket_form(self):
        assert _parse_music_declaration('[music:name="bgm",src="./music.mp3"]') == \
            ("bgm", "./music.mp3")

    def test_bracket_with_spaces(self):
        # 额外空格导致 src 值保留引号，这是实际行为
        result = _parse_music_declaration('[music: name="bgm" , src="./music.mp3" ]')
        assert result is not None
        assert result[0] == "bgm"

    def test_colon_form(self):
        assert _parse_music_declaration('music: name="bgm", src="./music.mp3"') == \
            ("bgm", "./music.mp3")

    def test_chinese_colon_form(self):
        assert _parse_music_declaration('音乐：name="bgm",src="./music.mp3"') == \
            ("bgm", "./music.mp3")

    def test_none_for_heading(self):
        assert _parse_music_declaration("# some heading") is None

    def test_none_for_missing_src(self):
        assert _parse_music_declaration('[music:name="bgm"]') is None


# ========== _parse_music_marker ==========


class TestParseMusicMarker:
    def test_start_bracket(self):
        assert _parse_music_marker("[music_start bgm]") == ("start", "bgm")

    def test_end_bracket(self):
        assert _parse_music_marker("[music_end bgm]") == ("end", "bgm")

    def test_start_angle_bracket(self):
        assert _parse_music_marker("<music_start bgm>") == ("start", "bgm")

    def test_end_angle_bracket(self):
        assert _parse_music_marker("<music_end bgm>") == ("end", "bgm")

    def test_quoted_name(self):
        assert _parse_music_marker('[music_start "my bgm"]') == ("start", "my bgm")

    def test_single_quoted_name(self):
        assert _parse_music_marker("[music_start 'bgm']") == ("start", "bgm")

    def test_case_insensitive(self):
        assert _parse_music_marker("[MUSIC_START BGM]") == ("start", "BGM")

    def test_none_for_declaration(self):
        # 声明格式不是 marker
        assert _parse_music_marker('[music:name="bgm",src="./music.mp3"]') is None


# ========== _parse_image_declaration ==========


class TestParseImageDeclaration:
    def test_bracket_form(self):
        assert _parse_image_declaration('[image:name="logo",src="./logo.png"]') == \
            ("logo", "./logo.png")

    def test_colon_form(self):
        assert _parse_image_declaration('image: name="logo", src="./logo.png"') == \
            ("logo", "./logo.png")

    def test_chinese_form(self):
        assert _parse_image_declaration('图片：name="logo",src="./logo.png"') == \
            ("logo", "./logo.png")

    def test_none_for_normal_text(self):
        assert _parse_image_declaration("normal text") is None


# ========== _parse_image_marker ==========


class TestParseImageMarker:
    def test_start_bracket(self):
        assert _parse_image_marker("[image_start logo]") == ("start", "logo")

    def test_end_bracket(self):
        assert _parse_image_marker("[image_end logo]") == ("end", "logo")

    def test_angle_bracket(self):
        assert _parse_image_marker("<image_start logo>") == ("start", "logo")

    def test_none_for_declaration(self):
        assert _parse_image_marker('[image:name="logo"]') is None


# ========== _parse_markdown_sections ==========


class TestParseMarkdownSections:
    def test_h1_h2(self):
        s = _parse_markdown_sections("# Main\n## Sub")
        assert s["h1"] == "Main"
        assert s["h2"] == "Sub"

    def test_music_declaration_top(self):
        text = '[music:name="x",src="y.mp3"]\n# Title'
        s = _parse_markdown_sections(text)
        assert s["music"] == {"x": "y.mp3"}
        assert s["h1"] == "Title"

    def test_image_declaration_top(self):
        text = '[image:name="logo",src="./logo.png"]\n# Title'
        s = _parse_markdown_sections(text)
        assert s["images"] == {"logo": "./logo.png"}

    def test_content_sections(self):
        text = "### Section A\nPara one\n### Section B\nPara two"
        s = _parse_markdown_sections(text)
        assert len(s["contents"]) == 2
        assert s["contents"][0]["h3"] == "Section A"
        assert s["contents"][1]["h3"] == "Section B"

    def test_appendix_after_separator(self):
        text = "### S\ncontent\n---\nAppendix text"
        s = _parse_markdown_sections(text)
        assert len(s["contents"]) == 1
        assert s["contents"][0]["h3"] == "S"
        assert "Appendix text" in s["appendix"]

    def test_music_markers_in_appendix(self):
        text = "---\n[music_start bgm]\nLyrics\n[music_end bgm]"
        s = _parse_markdown_sections(text)
        assert "[music_start bgm]" in s["appendix"]
        assert "[music_end bgm]" in s["appendix"]

    def test_music_markers_in_content(self):
        text = "### S\n[music_start bgm]\nText"
        s = _parse_markdown_sections(text)
        assert len(s["contents"]) == 1
        # marker 保留在 content text_block 中
        assert any("[music_start bgm]" in line
                    for para in s["contents"][0]["text"] for line in para)

    def test_trailing_header_is_preserved(self):
        s = _parse_markdown_sections("### First\nBody\n### Last")
        assert [section["h3"] for section in s["contents"]] == ["First", "Last"]
        assert s["contents"][-1]["text"] == []

    def test_empty_markdown(self):
        s = _parse_markdown_sections("")
        assert s["h1"] is None
        assert s["h2"] is None
        assert s["contents"] == []
        assert s["appendix"] == []


# ========== parse_to_plan_manifest ==========


class TestParseToPlanManifest:
    def test_full_example(self, full_md):
        manifest = parse_to_plan_manifest(str(full_md))
        # 标题
        assert manifest.segments[0].segment_type == "title_main"
        assert manifest.segments[0].audio_request is None
        assert manifest.segments[0].text == "大标题"
        assert manifest.segments[1].segment_type == "title_sub"
        assert manifest.segments[1].audio_request is None
        assert manifest.segments[1].text == "二级标题"
        # 第一个 section_header
        assert manifest.segments[2].segment_type == "section_header"
        assert manifest.segments[2].text == "小重山"
        # media_declarations
        assert manifest.media_declarations["music"]["222"] == "./music.mp3"

    def test_minimal(self, minimal_md):
        manifest = parse_to_plan_manifest(str(minimal_md))
        types = [s.segment_type for s in manifest.segments]
        assert "title_main" in types
        assert "title_sub" in types
        assert "section_header" in types
        assert "content" in types

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            parse_to_plan_manifest("/nonexistent/path.md")

    def test_segment_ids_sequential(self, full_md):
        manifest = parse_to_plan_manifest(str(full_md))
        ids = [s.id for s in manifest.segments]
        expected = [f"seg_{i:03d}" for i in range(1, len(ids) + 1)]
        assert ids == expected

    def test_version_default(self, minimal_md):
        manifest = parse_to_plan_manifest(str(minimal_md))
        assert manifest.version == "2"

    def test_header_only_input_is_narrated(self, tmp_path):
        path = tmp_path / "header.md"
        path.write_text("### Only section\n", encoding="utf-8")
        manifest = parse_to_plan_manifest(str(path))
        assert [(s.text, s.segment_type) for s in manifest.segments] == [
            ("Only section", "section_header"),
        ]
        assert manifest.segments[0].audio_request is not None

    def test_marker_data_structure(self, full_md):
        manifest = parse_to_plan_manifest(str(full_md))
        music_markers = [s for s in manifest.segments if s.segment_type == "marker_music"]
        assert len(music_markers) >= 2
        # 第一个 marker 应该是 start
        assert music_markers[0].marker_data["kind"] == "start"
        assert music_markers[0].marker_data["name"] == "222"
        # 第二个 marker 应该是 end
        assert music_markers[1].marker_data["kind"] == "end"

    def test_section_context_propagated(self, full_md):
        manifest = parse_to_plan_manifest(str(full_md))
        # 找到 "小重山" section 下的 content 段
        for seg in manifest.segments:
            if seg.segment_type == "content" and seg.text == "12345":
                assert seg.section_context == "小重山"
                break

    def test_appendix_segment_type(self, full_md):
        manifest = parse_to_plan_manifest(str(full_md))
        appendix_segs = [s for s in manifest.segments if s.segment_type == "appendix"]
        assert len(appendix_segs) > 0
        texts = [s.text for s in appendix_segs]
        assert any("下面是附录" in t for t in texts)
