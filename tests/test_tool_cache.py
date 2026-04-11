"""ToolCache 单元测试。"""
import json

import pytest

from md2video.tools.cache import ToolCache


class TestMakeKey:
    def test_deterministic(self, tmp_path):
        cache = ToolCache(tmp_path)
        k1 = cache.make_key("tts", {"text": "hello", "voice": "a"})
        k2 = cache.make_key("tts", {"text": "hello", "voice": "a"})
        assert k1 == k2

    def test_order_insensitive(self, tmp_path):
        cache = ToolCache(tmp_path)
        k1 = cache.make_key("tts", {"a": 1, "b": 2})
        k2 = cache.make_key("tts", {"b": 2, "a": 1})
        assert k1 == k2

    def test_different_params(self, tmp_path):
        cache = ToolCache(tmp_path)
        k1 = cache.make_key("tts", {"text": "a"})
        k2 = cache.make_key("tts", {"text": "b"})
        assert k1 != k2

    def test_tool_type_prefix(self, tmp_path):
        cache = ToolCache(tmp_path)
        k1 = cache.make_key("tts", {"x": 1})
        k2 = cache.make_key("image", {"x": 1})
        assert k1 != k2


class TestReadWrite:
    def test_write_read_roundtrip(self, tmp_path):
        cache = ToolCache(tmp_path)
        key = "abc123"
        path = cache.write("tts", key, b"hello world")
        assert path.exists()
        assert cache.read("tts", key) == b"hello world"

    def test_has_miss(self, tmp_path):
        cache = ToolCache(tmp_path)
        assert not cache.has("tts", "nonexistent")

    def test_has_hit(self, tmp_path):
        cache = ToolCache(tmp_path)
        cache.write("tts", "k", b"data")
        assert cache.has("tts", "k")


class TestJsonRoundtrip:
    def test_write_read_json(self, tmp_path):
        cache = ToolCache(tmp_path)
        result = {"path": "/a/b.mp3", "duration": 3.5}
        cache.write_json("tts", "k1", result)
        assert cache.read_json("tts", "k1") == result

    def test_read_json_miss(self, tmp_path):
        cache = ToolCache(tmp_path)
        assert cache.read_json("tts", "nope") is None

    def test_json_ext(self, tmp_path):
        cache = ToolCache(tmp_path)
        cache.write_json("tts", "k", {"a": 1})
        assert (tmp_path / "tts" / "k.json").exists()
