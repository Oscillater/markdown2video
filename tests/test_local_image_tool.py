"""LocalImageTool 单元测试。"""
from pathlib import Path

import pytest
from PIL import Image

from md2video.tools.protocol import Tool
from md2video.tools.image.local_image_tool import LocalImageTool


def _make_image(tmp_path: Path, name: str = "local_image.jpg") -> Path:
    image_path = tmp_path / name
    Image.new("RGB", (500, 631), color=(32, 96, 160)).save(image_path)
    return image_path


def _make_input(visual_params, base_dir: Path):
    return {
        "scene": {
            "id": "scene_001",
            "visual_type": "stock_image",
            "visual_params": visual_params,
            "section_context": "demo",
        },
        "shot": {"id": "shot_001", "segment_ids": ["seg_001"], "target_duration": 2.0},
        "segments": [],
        "output_dir": str(base_dir),
        "base_dir": str(base_dir),
    }


class TestLocalImageToolProtocol:
    def test_satisfies_tool_protocol(self):
        assert isinstance(LocalImageTool(), Tool)

    def test_tool_type(self):
        assert LocalImageTool().tool_type == "image"

    def test_provider_name(self):
        assert LocalImageTool().provider_name == "local"


class TestLocalImageToolExecute:
    def test_execute_relative_path(self, tmp_path):
        image_path = _make_image(tmp_path)
        tool = LocalImageTool()
        output = tool.execute(_make_input({"path": image_path.name}, tmp_path))

        visual = output["visuals"][0]
        assert visual["shot_id"] == "shot_001"
        assert visual["path"] == str(image_path.resolve())
        assert visual["width"] == 500
        assert visual["height"] == 631
        assert visual["source"] == "local"

    def test_execute_src_alias(self, tmp_path):
        image_path = _make_image(tmp_path)
        tool = LocalImageTool()
        output = tool.execute(_make_input({"src": image_path.name}, tmp_path))

        visual = output["visuals"][0]
        assert visual["path"] == str(image_path.resolve())

    def test_execute_absolute_path(self, tmp_path):
        image_path = _make_image(tmp_path)
        tool = LocalImageTool()
        output = tool.execute(_make_input({"path": str(image_path.resolve())}, tmp_path))

        visual = output["visuals"][0]
        assert visual["path"] == str(image_path.resolve())

    def test_missing_path_raises(self, tmp_path):
        tool = LocalImageTool()
        with pytest.raises(ValueError, match="visual_params.path"):
            tool.execute(_make_input({}, tmp_path))

    def test_missing_file_raises(self, tmp_path):
        tool = LocalImageTool()
        with pytest.raises(FileNotFoundError, match="Local image not found"):
            tool.execute(_make_input({"path": "missing.jpg"}, tmp_path))
