"""皮肤包外部文件加载：MD2VIDEO_STYLE_PACK_FILE 惰性加载 + fail fast。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from md2video.style import packs
from md2video.style.packs import (
    DEFAULT_PACK_NAME,
    STYLE_PACK_ENV,
    STYLE_PACK_FILE_ENV,
    active_pack,
    get_pack,
    pack_names,
    reset_pack_registry,
)


def _pack_json(pack_id: str = "sunset_demo") -> dict:
    return {
        "id": pack_id,
        "palette": {
            "background": "#101018",
            "text": "#F5F0E6",
            "secondary": "#C0C0D0",
            "accent": "#FF9E64",
        },
        "typography": {
            "font_family": "FZShuSong-Z01S",
            "size_title_main": 40 / 854,
            "size_title_sub": 30 / 854,
            "size_section_header": 20 / 854,
            "size_section_header_detail": 12 / 854,
            "size_body": 15 / 854,
        },
        "motion": {
            "title_reveal": "write",
            "section_reveal": "write",
            "body_reveal": "appear",
            "body_dismiss": "instant",
            "section_dismiss": "fade",
            "motif_transition_duration": 1.0,
            "silent": {"title_hold": 1.0, "section_header": 0.5, "body": 2.0},
        },
        "motif": {"kind": "orbit_dots"},
    }


@pytest.fixture(autouse=True)
def _fresh_pack_file_state(monkeypatch):
    monkeypatch.delenv(STYLE_PACK_FILE_ENV, raising=False)
    monkeypatch.delenv(STYLE_PACK_ENV, raising=False)
    reset_pack_registry()
    yield
    reset_pack_registry()


class TestLazyFileLoading:
    def test_no_env_is_noop(self):
        assert get_pack() is get_pack(DEFAULT_PACK_NAME)
        assert "sunset_demo" not in pack_names()

    def test_file_pack_loads_once_and_is_idempotent(self, tmp_path, monkeypatch):
        pack_file = tmp_path / "sunset.json"
        pack_file.write_text(json.dumps(_pack_json()), encoding="utf-8")
        monkeypatch.setenv(STYLE_PACK_FILE_ENV, str(pack_file))

        # 惰性：加载发生在第一次取包，之前不在注册表里
        assert "sunset_demo" not in packs._PACKS
        pack = get_pack("sunset_demo")
        assert pack.id == "sunset_demo"
        assert pack.palette.accent == "#FF9E64"
        # 幂等：第二次解析不重复加载（重复注册会 fail fast，能到这就没重复加载）
        assert get_pack("sunset_demo") is pack
        assert pack_names().count("sunset_demo") == 1

    def test_active_pack_triggers_same_load_for_pipeline_side(self, tmp_path, monkeypatch):
        pack_file = tmp_path / "sunset.json"
        pack_file.write_text(json.dumps(_pack_json()), encoding="utf-8")
        monkeypatch.setenv(STYLE_PACK_FILE_ENV, str(pack_file))
        monkeypatch.setenv(STYLE_PACK_ENV, "sunset_demo")

        requested, pack = active_pack()
        assert requested == "sunset_demo"
        assert pack.id == "sunset_demo"

    def test_selection_still_via_style_pack_name(self, tmp_path, monkeypatch):
        """FILE 只管注册，选择仍走名字；未选时用默认包。"""
        pack_file = tmp_path / "sunset.json"
        pack_file.write_text(json.dumps(_pack_json()), encoding="utf-8")
        monkeypatch.setenv(STYLE_PACK_FILE_ENV, str(pack_file))

        _requested, pack = active_pack()
        assert pack.id == DEFAULT_PACK_NAME


class TestFailFast:
    def test_missing_file_fails_fast(self, tmp_path, monkeypatch):
        monkeypatch.setenv(STYLE_PACK_FILE_ENV, str(tmp_path / "nope.json"))
        with pytest.raises(FileNotFoundError, match="MD2VIDEO_STYLE_PACK_FILE"):
            get_pack()

    def test_malformed_json_fails_fast(self, tmp_path, monkeypatch):
        pack_file = tmp_path / "broken.json"
        pack_file.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv(STYLE_PACK_FILE_ENV, str(pack_file))
        with pytest.raises(ValueError, match="not a valid ThemeTokens JSON"):
            get_pack()

    def test_invalid_tokens_fail_fast(self, tmp_path, monkeypatch):
        data = _pack_json()
        data["palette"]["background"] = "not-a-color"
        pack_file = tmp_path / "bad_color.json"
        pack_file.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setenv(STYLE_PACK_FILE_ENV, str(pack_file))
        with pytest.raises(ValueError, match="not a valid ThemeTokens JSON"):
            get_pack()

    def test_duplicate_id_fails_fast(self, tmp_path, monkeypatch):
        data = _pack_json(pack_id=DEFAULT_PACK_NAME)
        pack_file = tmp_path / "shadow_ink_night.json"
        pack_file.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setenv(STYLE_PACK_FILE_ENV, str(pack_file))
        with pytest.raises(ValueError, match="Style pack already registered: ink_night"):
            get_pack()

    def test_unknown_pack_name_still_degrades_with_warning(
        self, tmp_path, monkeypatch, capsys,
    ):
        pack_file = tmp_path / "sunset.json"
        pack_file.write_text(json.dumps(_pack_json()), encoding="utf-8")
        monkeypatch.setenv(STYLE_PACK_FILE_ENV, str(pack_file))

        pack = get_pack("no_such_pack")
        assert pack.id == DEFAULT_PACK_NAME
        assert "unknown style pack" in capsys.readouterr().out

    def test_bad_file_fails_even_when_resolving_unknown_name(self, tmp_path, monkeypatch):
        """加载在解析名字前发生：坏了的显式包不能被降级掩盖。"""
        monkeypatch.setenv(
            STYLE_PACK_FILE_ENV, str(tmp_path / "missing.json"),
        )
        with pytest.raises(FileNotFoundError):
            get_pack("whatever")
