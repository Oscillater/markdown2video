"""PexelsImageTool 单元测试。"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from md2video.tools.protocol import Tool
from md2video.tools.image.pexels_image_tool import PexelsImageTool


def _make_api_response(photos=None, status_code=200):
    """构建 mock Pexels API 搜索响应。"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.reason = "OK" if status_code == 200 else "Unauthorized"
    default_photos = [
        {
            "id": 12345,
            "width": 1080,
            "height": 1920,
            "url": "https://www.pexels.com/photo/test-12345/",
            "src": {
                "original": "https://images.pexels.com/photos/12345/original.jpg",
                "large2x": "https://images.pexels.com/photos/12345/large2x.jpg",
            },
        }
    ]
    resp.json.return_value = {"photos": default_photos if photos is None else photos}
    return resp


def _make_download_response(content=b"fake-jpeg-bytes"):
    """构建 mock 图片下载响应。"""
    resp = MagicMock()
    resp.status_code = 200
    resp.content = content
    return resp


@pytest.fixture
def pexels_tool(tmp_path):
    return PexelsImageTool(api_key="test-key", cache_dir=tmp_path / "images")


class TestPexelsImageToolProtocol:
    def test_satisfies_tool_protocol(self, pexels_tool):
        assert isinstance(pexels_tool, Tool)

    def test_tool_type(self, pexels_tool):
        assert pexels_tool.tool_type == "image"

    def test_provider_name(self, pexels_tool):
        assert pexels_tool.provider_name == "pexels"


class TestPexelsImageToolInit:
    def test_creates_cache_dir(self, tmp_path):
        tool = PexelsImageTool(api_key="k", cache_dir=tmp_path / "new_dir")
        assert tool.cache_dir.exists()

    def test_no_api_key_is_allowed_on_init(self, tmp_path):
        """构造时不要求 API key，execute 时才检查。"""
        tool = PexelsImageTool(api_key="", cache_dir=tmp_path)
        assert tool.api_key == ""


class TestPexelsImageToolExecute:
    def test_no_api_key_raises_on_execute(self, tmp_path):
        tool = PexelsImageTool(api_key="", cache_dir=tmp_path)
        with pytest.raises(ValueError, match="API key"):
            tool.execute({
                "scene": {"id": "s1", "visual_type": "stock_image",
                          "visual_params": {"query": "nature"}, "section_context": ""},
                "shot": {"id": "sh1", "segment_ids": [], "target_duration": 5.0},
                "segments": [],
                "output_dir": str(tmp_path),
            })

    @patch("md2video.tools.image.pexels_image_tool.requests.get")
    def test_execute_success(self, mock_get, pexels_tool):
        mock_get.side_effect = [_make_api_response(), _make_download_response()]
        output = pexels_tool.execute({
            "scene": {"id": "s1", "visual_type": "stock_image",
                      "visual_params": {"query": "mountain"}, "section_context": "intro"},
            "shot": {"id": "sh1", "segment_ids": ["seg_1"], "target_duration": 5.0},
            "segments": [{"id": "seg_1", "text": "A mountain", "segment_type": "content", "audio": None}],
            "output_dir": str(pexels_tool.cache_dir),
        })
        assert "visuals" in output
        assert len(output["visuals"]) == 1
        vis = output["visuals"][0]
        assert vis["shot_id"] == "sh1"
        assert vis["source"] == "pexels"
        assert vis["width"] == 1080
        assert vis["height"] == 1920
        assert vis["path"].endswith(".jpg")
        assert vis["cache_key"] == pexels_tool._cache.make_key(
            "image", {"query": "mountain", "orientation": "portrait"}
        )

    @patch("md2video.tools.image.pexels_image_tool.requests.get")
    def test_cache_hit_no_http_call(self, mock_get, pexels_tool):
        """缓存命中时不发起 HTTP 请求。"""
        # 第一次调用：正常搜索+下载
        mock_get.side_effect = [_make_api_response(), _make_download_response()]
        input_data = {
            "scene": {"id": "s1", "visual_type": "stock_image",
                      "visual_params": {"query": "ocean", "orientation": "portrait"},
                      "section_context": ""},
            "shot": {"id": "sh1", "segment_ids": [], "target_duration": 3.0},
            "segments": [],
            "output_dir": str(pexels_tool.cache_dir),
        }
        pexels_tool.execute(input_data)
        call_count_after_first = mock_get.call_count

        # 第二次调用：应从缓存读取
        output = pexels_tool.execute(input_data)
        assert mock_get.call_count == call_count_after_first
        assert output["visuals"][0]["cache_key"] == pexels_tool._cache.make_key(
            "image", {"query": "ocean", "orientation": "portrait"}
        )

    @patch("md2video.tools.image.pexels_image_tool.requests.get")
    def test_api_error_401(self, mock_get, pexels_tool):
        mock_get.return_value = _make_api_response(status_code=401)
        mock_get.return_value.reason = "Unauthorized"
        with pytest.raises(RuntimeError, match="401"):
            pexels_tool.search_and_download("test")

    @patch("md2video.tools.image.pexels_image_tool.requests.get")
    def test_no_photos_found(self, mock_get, pexels_tool):
        """API 返回空结果列表时 raise RuntimeError。"""
        mock_get.side_effect = [_make_api_response(photos=[])]
        with pytest.raises(RuntimeError, match="No photos found"):
            pexels_tool.search_and_download("nonexistent-query-xyz")

    @patch("md2video.tools.image.pexels_image_tool.requests.get")
    def test_download_failure(self, mock_get, pexels_tool):
        api_resp = _make_api_response()
        dl_resp = MagicMock()
        dl_resp.status_code = 500
        mock_get.side_effect = [api_resp, dl_resp]
        with pytest.raises(RuntimeError, match="Failed to download"):
            pexels_tool.search_and_download("nature")

    @patch("md2video.tools.image.pexels_image_tool.requests.get")
    def test_query_from_visual_params(self, mock_get, pexels_tool):
        """query 从 visual_params 中提取。"""
        mock_get.side_effect = [_make_api_response(), _make_download_response()]
        pexels_tool.execute({
            "scene": {"id": "s1", "visual_type": "stock_image",
                      "visual_params": {"query": "city night"}, "section_context": ""},
            "shot": {"id": "sh1", "segment_ids": [], "target_duration": 3.0},
            "segments": [],
            "output_dir": str(pexels_tool.cache_dir),
        })
        # Verify the search query in the API call
        search_call = mock_get.call_args_list[0]
        assert search_call.kwargs["params"]["query"] == "city night"

    @patch("md2video.tools.image.pexels_image_tool.requests.get")
    def test_orientation_default_portrait(self, mock_get, pexels_tool):
        """未指定 orientation 时默认 portrait。"""
        mock_get.side_effect = [_make_api_response(), _make_download_response()]
        pexels_tool.execute({
            "scene": {"id": "s1", "visual_type": "stock_image",
                      "visual_params": {"query": "forest"}, "section_context": ""},
            "shot": {"id": "sh1", "segment_ids": [], "target_duration": 3.0},
            "segments": [],
            "output_dir": str(pexels_tool.cache_dir),
        })
        search_call = mock_get.call_args_list[0]
        assert search_call.kwargs["params"]["orientation"] == "portrait"

    @patch("md2video.tools.image.pexels_image_tool.requests.get")
    def test_orientation_from_params(self, mock_get, pexels_tool):
        """visual_params 中指定 orientation 时使用该值。"""
        mock_get.side_effect = [_make_api_response(), _make_download_response()]
        pexels_tool.execute({
            "scene": {"id": "s1", "visual_type": "stock_image",
                      "visual_params": {"query": "sunset", "orientation": "landscape"},
                      "section_context": ""},
            "shot": {"id": "sh1", "segment_ids": [], "target_duration": 3.0},
            "segments": [],
            "output_dir": str(pexels_tool.cache_dir),
        })
        search_call = mock_get.call_args_list[0]
        assert search_call.kwargs["params"]["orientation"] == "landscape"


class TestPexelsImageToolCache:
    def test_cache_key_deterministic(self, pexels_tool):
        """相同参数生成相同 cache key。"""
        k1 = pexels_tool._cache.make_key("image", {"query": "test", "orientation": "portrait"})
        k2 = pexels_tool._cache.make_key("image", {"orientation": "portrait", "query": "test"})
        assert k1 == k2

    @patch("md2video.tools.image.pexels_image_tool.requests.get")
    def test_cache_stores_jpg_and_meta(self, mock_get, pexels_tool):
        """execute 后 cache 中应存在 .jpg 和 _meta.json。"""
        mock_get.side_effect = [_make_api_response(), _make_download_response()]
        pexels_tool.execute({
            "scene": {"id": "s1", "visual_type": "stock_image",
                      "visual_params": {"query": "cat"}, "section_context": ""},
            "shot": {"id": "sh1", "segment_ids": [], "target_duration": 3.0},
            "segments": [],
            "output_dir": str(pexels_tool.cache_dir),
        })
        # 找到 cache_key
        cache_key = pexels_tool._cache.make_key("image", {"query": "cat", "orientation": "portrait"})
        img_path = pexels_tool._cache.cache_path("image", cache_key, ext="jpg")
        meta_path = pexels_tool._cache.cache_path("image", cache_key + "_meta", ext="json")
        assert img_path.exists()
        assert meta_path.exists()
