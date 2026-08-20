"""Tests for md2video.tools.render.cached_voice."""
from __future__ import annotations

import pytest

from md2video.manifest.schema import AudioResult, ResultManifest, SegmentResult
from md2video.tools.render.cached_voice import CachedVoiceService


class TestResolvePath:
    def test_absolute_path(self, audio_file):
        svc = CachedVoiceService(
            result_manifest=ResultManifest(),
            project_root=None,
        )
        result = svc._resolve_path(str(audio_file))
        assert result == str(audio_file)

    def test_existing_relative_with_project_root(self, audio_file, tmp_path):
        # 在 project_root 下创建音频文件
        rel_audio = tmp_path / "audio.wav"
        rel_audio.write_bytes(audio_file.read_bytes())
        svc = CachedVoiceService(
            result_manifest=ResultManifest(),
            project_root=tmp_path,
        )
        result = svc._resolve_path("audio.wav")
        assert result == str(rel_audio)

    def test_nonexistent_returns_as_is(self):
        svc = CachedVoiceService(
            result_manifest=ResultManifest(),
            project_root="/some/nonexistent",
        )
        assert svc._resolve_path("nonexistent_file.wav") == "nonexistent_file.wav"


class TestWrapGenerateFromText:
    def test_sequential_calls(self, audio_file, tmp_path):
        # 创建 3 个音频文件
        audios = []
        for i in range(3):
            p = tmp_path / f"seg_{i+1}.wav"
            p.write_bytes(audio_file.read_bytes())
            audios.append(str(p))

        manifest = ResultManifest(segments=[
            SegmentResult(id=f"seg_{i+1:03d}", start=float(i * 2), end=float(i * 2 + 2),
                          audio=AudioResult(path=audios[i], duration=2.0))
            for i in range(3)
        ])
        svc = CachedVoiceService(result_manifest=manifest)

        for i in range(3):
            result = svc._wrap_generate_from_text("text")
            assert result["final_audio"] == audios[i]
            assert result["text"] == "text"

    def test_skips_non_voiced(self, audio_file, tmp_path):
        # 3 个段，只有第二个有音频
        audios = []
        for i in range(3):
            p = tmp_path / f"seg_{i+1}.wav"
            p.write_bytes(audio_file.read_bytes())
            audios.append(str(p))

        manifest = ResultManifest(segments=[
            SegmentResult(id="seg_001", start=0.0, end=2.0,
                          audio=AudioResult(path=audios[0], duration=2.0)),
            SegmentResult(id="seg_002", start=2.0, end=4.0,
                          audio=AudioResult(path=audios[1], duration=2.0)),
            SegmentResult(id="seg_003", start=4.0, end=6.0,
                          audio=AudioResult(path=audios[2], duration=2.0)),
        ])
        svc = CachedVoiceService(
            result_manifest=manifest,
            voiced_segment_ids={"seg_002"},
        )
        result = svc._wrap_generate_from_text("text")
        assert result["final_audio"] == audios[1]

    def test_exhausted_raises(self, audio_file, tmp_path):
        p = tmp_path / "seg_001.wav"
        p.write_bytes(audio_file.read_bytes())

        manifest = ResultManifest(segments=[
            SegmentResult(id="seg_001", start=0.0, end=2.0,
                          audio=AudioResult(path=str(p), duration=2.0)),
        ])
        svc = CachedVoiceService(result_manifest=manifest)

        # 第一次成功
        svc._wrap_generate_from_text("text")
        # 第二次应抛错
        with pytest.raises(RuntimeError, match="没有更多预生成音频可用"):
            svc._wrap_generate_from_text("text")

    def test_missing_audio_skipped(self, audio_file, tmp_path):
        # 第一个段无音频，第二个段有音频
        p = tmp_path / "seg_002.wav"
        p.write_bytes(audio_file.read_bytes())

        manifest = ResultManifest(segments=[
            SegmentResult(id="seg_001", start=0.0, end=0.0, audio=None),
            SegmentResult(id="seg_002", start=0.0, end=2.0,
                          audio=AudioResult(path=str(p), duration=2.0)),
        ])
        svc = CachedVoiceService(result_manifest=manifest)

        result = svc._wrap_generate_from_text("text")
        assert result["final_audio"] == str(p)

    def test_use_segment_returns_matching_audio_when_order_differs(self, audio_file, tmp_path):
        audio_a = tmp_path / "seg_a.wav"
        audio_b = tmp_path / "seg_b.wav"
        audio_a.write_bytes(audio_file.read_bytes())
        audio_b.write_bytes(audio_file.read_bytes())

        manifest = ResultManifest(segments=[
            SegmentResult(id="seg_b", start=0.0, end=2.0,
                          audio=AudioResult(path=str(audio_b), duration=2.0)),
            SegmentResult(id="seg_a", start=2.0, end=4.0,
                          audio=AudioResult(path=str(audio_a), duration=2.0)),
        ])
        svc = CachedVoiceService(result_manifest=manifest)

        with svc.use_segment("seg_a"):
            result_a = svc._wrap_generate_from_text("text a")
        with svc.use_segment("seg_b"):
            result_b = svc._wrap_generate_from_text("text b")

        assert result_a["final_audio"] == str(audio_a)
        assert result_a["text"] == "text a"
        assert result_b["final_audio"] == str(audio_b)
        assert result_b["text"] == "text b"

    def test_use_segment_missing_segment_hard_fails(self):
        svc = CachedVoiceService(result_manifest=ResultManifest())

        with svc.use_segment("seg_missing"):
            with pytest.raises(RuntimeError, match="seg_missing"):
                svc._wrap_generate_from_text("text")

    def test_use_segment_without_audio_hard_fails(self):
        manifest = ResultManifest(segments=[
            SegmentResult(id="seg_001", start=0.0, end=0.0, audio=None),
        ])
        svc = CachedVoiceService(result_manifest=manifest)

        with svc.use_segment("seg_001"):
            with pytest.raises(RuntimeError, match="seg_001"):
                svc._wrap_generate_from_text("text")

    def test_use_segment_excluded_from_voiced_ids_hard_fails(self, audio_file, tmp_path):
        p = tmp_path / "seg_001.wav"
        p.write_bytes(audio_file.read_bytes())
        manifest = ResultManifest(segments=[
            SegmentResult(id="seg_001", start=0.0, end=1.0,
                          audio=AudioResult(path=str(p), duration=1.0)),
        ])
        svc = CachedVoiceService(
            result_manifest=manifest,
            voiced_segment_ids={"seg_other"},
        )

        with svc.use_segment("seg_001"):
            with pytest.raises(RuntimeError, match="seg_001"):
                svc._wrap_generate_from_text("text")

    def test_use_segment_missing_file_hard_fails(self, tmp_path):
        missing = tmp_path / "missing.wav"
        manifest = ResultManifest(segments=[
            SegmentResult(id="seg_001", start=0.0, end=1.0,
                          audio=AudioResult(path=str(missing), duration=1.0)),
        ])
        svc = CachedVoiceService(result_manifest=manifest)

        with svc.use_segment("seg_001"):
            with pytest.raises(FileNotFoundError, match="seg_001"):
                svc._wrap_generate_from_text("text")
