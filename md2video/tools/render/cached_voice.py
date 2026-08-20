from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Dict

from md2video.manifest.schema import ResultManifest


class CachedVoiceService:
    """
    模拟 manim-voiceover SpeechService 接口。
    不生成音频，直接返回预生成的音频文件路径。

    注意: 由于 manim 当前环境有 typing_extensions 冲突无法直接 import VoiceService，
    我们实现相同的接口约定。Demo class 的 voiceover() 调用 _wrap_generate_from_text(text)，
    只需要返回 {"final_audio": path, "original_audio": path, "text": text} 即可。
    """

    def __init__(self, result_manifest: ResultManifest, project_root: str | Path = None,
                 voiced_segment_ids: set | None = None):
        self.result_manifest = result_manifest
        self.project_root = Path(project_root) if project_root else None
        # 只对 voiced_segment_ids 中的 segment 返回音频，其他跳过
        self._voiced_ids = voiced_segment_ids  # None 表示全部可用
        self._segment_by_id = {seg.id: seg for seg in result_manifest.segments}
        self._current_segment_id: str | None = None
        # 构建 segment_id -> audio_path 查找表
        self._audio_map: Dict[str, str] = {}
        for seg in result_manifest.segments:
            if seg.audio and seg.audio.path:
                self._audio_map[seg.id] = seg.audio.path
        # 用于按顺序查找
        self._seg_id_by_index: Dict[int, str] = {
            i: seg.id for i, seg in enumerate(result_manifest.segments)
        }
        self._call_index = 0
        self.cache_dir = Path("voice_cache")
        self.cache_dir.mkdir(exist_ok=True)
        self.global_speed = 1.0
        self._whisper_model = None

    @contextmanager
    def use_segment(self, segment_id: str):
        previous_segment_id = self._current_segment_id
        self._current_segment_id = segment_id
        try:
            yield
        finally:
            self._current_segment_id = previous_segment_id

    def _resolve_path(self, audio_path: str) -> str:
        """将相对路径解析为绝对路径（manim 从 anim/ 运行，但音频在项目根目录下）。"""
        p = Path(audio_path)
        if p.is_absolute() or p.exists():
            return str(p)
        # 尝试相对于项目根目录
        if self.project_root:
            resolved = self.project_root / audio_path
            if resolved.exists():
                return str(resolved)
        # 尝试相对于 cwd 的上级（anim/ -> project/）
        parent = Path.cwd().parent
        resolved = parent / audio_path
        if resolved.exists():
            return str(resolved)
        return audio_path

    def _wrap_generate_from_text(self, text: str, path: str = None, **kwargs) -> dict:
        """Return pregenerated audio, preferring the active segment id."""
        if self._current_segment_id is not None:
            return self._audio_for_segment(self._current_segment_id, text)

        return self._audio_by_sequence(text)

    def _audio_for_segment(self, segment_id: str, text: str) -> dict:
        if self._voiced_ids is not None and segment_id not in self._voiced_ids:
            raise RuntimeError(
                f"CachedVoiceService: segment_id is not voiced: {segment_id}"
            )

        seg = self._segment_by_id.get(segment_id)
        if seg is None:
            raise RuntimeError(
                f"CachedVoiceService: segment_id not found: {segment_id}"
            )
        if not seg.audio or not seg.audio.path:
            raise RuntimeError(
                f"CachedVoiceService: no audio for segment_id: {segment_id}"
            )

        audio_path = self._resolve_path(seg.audio.path)
        if not Path(audio_path).exists():
            raise FileNotFoundError(
                f"预生成音频不存在 for segment_id {segment_id}: {audio_path}"
            )
        return {
            "final_audio": audio_path,
            "original_audio": audio_path,
            "text": text,
        }

    def _audio_by_sequence(self, text: str) -> dict:
        """按调用顺序返回预生成的音频文件。"""
        # voiceover 每次只调用一个 segment，按调用顺序匹配
        # 找到下一个有音频的 segment
        while self._call_index < len(self.result_manifest.segments):
            seg = self.result_manifest.segments[self._call_index]
            self._call_index += 1
            # 跳过不在 voiced_segment_ids 中的 segment
            if self._voiced_ids is not None and seg.id not in self._voiced_ids:
                continue
            if seg.audio and seg.audio.path:
                audio_path = seg.audio.path
                audio_path = self._resolve_path(seg.audio.path)
                if not Path(audio_path).exists():
                    raise FileNotFoundError(f"预生成音频不存在: {audio_path}")
                return {
                    "final_audio": audio_path,
                    "original_audio": audio_path,
                    "text": text,
                }
        # fallback: 如果没有预生成的音频，抛错
        raise RuntimeError(f"CachedVoiceService: 没有更多预生成音频可用 (text={text[:20]})")
