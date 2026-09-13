"""GenImageTool 测试：程序化插画（代码生图）的确定性、契约与注册。"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from md2video.config import ToolConfig
from md2video.core.pipeline import Pipeline
from md2video.tools.cache import ToolCache
from md2video.tools.image.gen_image_tool import PALETTES, STYLES, GenImageTool
from md2video.tools.registry import ToolRegistry


def _tool(tmp_path: Path) -> GenImageTool:
    return GenImageTool(cache_dir=tmp_path / "cache" / "images")


def _input(
    prompt: str = "单位圆与正弦余弦的概念插画",
    style: str = "",
    palette: str = "",
    shot_id: str = "shot_001",
) -> dict:
    visual_params = {"prompt": prompt}
    if style:
        visual_params["style"] = style
    if palette:
        visual_params["palette"] = palette
    return {
        "scene": {
            "id": "scene_001",
            "visual_type": "gen_image",
            "visual_params": visual_params,
            "layout_type": "center_title_body",
            "layout_params": {},
            "section_context": "test",
        },
        "shot": {"id": shot_id, "segment_ids": ["s1"], "cues": []},
        "segments": [{"id": "s1", "text": "一段解说", "segment_type": "content", "audio": None}],
        "output_dir": "",
        "base_dir": None,
    }


def test_tool_protocol_fields(tmp_path):
    tool = _tool(tmp_path)
    assert tool.tool_type == "image"
    assert tool.provider_name == "procedural"


def test_generate_is_deterministic_bytes(tmp_path):
    """同 prompt+参数两次生成（各自独立缓存目录）→ 逐字节一致。"""
    first = _tool(tmp_path / "a").generate("单位圆", style="orbit", palette="ink")
    second = _tool(tmp_path / "b").generate("单位圆", style="orbit", palette="ink")

    assert first["cache_key"] == second["cache_key"]
    assert Path(first["path"]).read_bytes() == Path(second["path"]).read_bytes()


def test_generate_reuses_cache_on_second_call(tmp_path):
    """同工具同参数第二次调用命中缓存：同路径同字节，不重画。"""
    tool = _tool(tmp_path)
    first = tool.generate("分层架构", style="layers")
    stamp = Path(first["path"]).stat().st_mtime_ns
    second = tool.generate("分层架构", style="layers")

    assert second["path"] == first["path"]
    assert Path(second["path"]).stat().st_mtime_ns == stamp


def test_different_prompts_produce_different_images(tmp_path):
    first = _tool(tmp_path).generate("概念 A 的插画", style="orbit")
    second = _tool(tmp_path).generate("概念 B 的插画", style="orbit")

    assert first["cache_key"] != second["cache_key"]
    assert Path(first["path"]).read_bytes() != Path(second["path"]).read_bytes()


def test_visual_output_contract(tmp_path):
    tool = _tool(tmp_path)
    output = tool.execute(_input(prompt="结构块", style="blocks", shot_id="shot_009"))

    assert list(output.keys()) == ["visuals"]
    visual = output["visuals"][0]
    assert visual["shot_id"] == "shot_009"
    assert visual["source"] == "procedural"
    assert visual["duration"] == 0.0
    assert visual["cache_key"]
    assert Path(visual["path"]).is_file()
    # 绝对路径：装配器在 --plan 场景用 plan 目录解析相对路径，工具产物必须自带完整定位
    assert Path(visual["path"]).is_absolute()
    with Image.open(visual["path"]) as image:
        assert image.size == (visual["width"], visual["height"])
        # 默认 9:16 双倍分辨率
        assert image.size == (960, 1704)


def test_empty_prompt_fails_fast(tmp_path):
    with pytest.raises(ValueError, match="requires visual_params.prompt"):
        _tool(tmp_path).execute(_input(prompt="  "))


def test_unknown_style_and_palette_fail_fast(tmp_path):
    with pytest.raises(ValueError, match="Unknown gen_image style"):
        _tool(tmp_path).execute(_input(style="photo"))
    with pytest.raises(ValueError, match="Unknown gen_image palette"):
        _tool(tmp_path).execute(_input(palette="sunset"))


def test_style_omitted_is_picked_deterministically(tmp_path):
    """style 缺省 → 按 prompt 种子确定选母题；同 prompt 两次一致。"""
    first = _tool(tmp_path / "a").generate("某种概念的插画")
    second = _tool(tmp_path / "b").generate("某种概念的插画")

    assert first["style"] in STYLES
    assert first["style"] == second["style"]


@pytest.mark.parametrize("style", STYLES)
def test_all_styles_render(tmp_path, style):
    result = _tool(tmp_path).generate(f"测试 {style}", style=style, width=480, height=854)
    assert Path(result["path"]).is_file()


def test_registry_lookup(tmp_path):
    registry = ToolRegistry()
    tool = _tool(tmp_path)
    registry.register("gen_image", tool)

    assert registry.get_tool("gen_image", "procedural") is tool
    assert registry.get_providers("gen_image") == ["procedural"]


def test_pipeline_registry_contains_gen_image(tmp_path):
    """管线默认注册 gen_image/procedural，且优先级表收录。"""
    from unittest.mock import patch

    with patch.object(Pipeline, "_create_planner"):
        pipeline = Pipeline(artifacts_dir=tmp_path, tool_config=ToolConfig())

    assert pipeline.registry.get_tool("gen_image", "procedural") is not None
    assert pipeline.tool_config.get_priority("gen_image") == ["procedural"]
    # 缓存目录落在 run artifacts 下
    assert (Path(pipeline.artifacts_dir) / "images").is_dir()
