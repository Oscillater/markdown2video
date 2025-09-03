# edge_tts_voice.py
import asyncio
from pathlib import Path
from manim_voiceover.services import VoiceService
from edge_tts import Communicate

class EdgeTTSVoice(VoiceService):
    """
    Edge TTS 语音服务，兼容最新 manim-voiceover
    """
    def __init__(self, voice: str = "zh-CN-YunxiaNeural", rate: str = "+0%", volume: str = "+50%"):
        super().__init__()
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.cache_dir = Path("voice_cache")
        self.cache_dir.mkdir(exist_ok=True)

    async def _save_audio_async(self, text: str, output_file: Path):
        comm = Communicate(text=text, voice=self.voice, rate=self.rate, volume=self.volume)
        await comm.save(str(output_file))

    def _wrap_generate_from_text(self, text: str, **kwargs):
        """
        manim-voiceover 调用这个接口生成语音
        返回 dict，必须包含 final_audio
        """
        audio_file = self.cache_dir / f"{hash(text)}.wav"

        # 异步生成音频
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._save_audio_async(text, audio_file))
        loop.close()

        return {
            "final_audio": audio_file.name,  # 文件名即可
            "text": text,
        }
