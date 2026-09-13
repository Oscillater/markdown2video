"""Ken Burns 动效单元测试。"""
from md2video.assembler.ffmpeg_assembler import (
    _build_ken_burns_filter,
    _kb_supersample_size,
)
from md2video.config import KenBurnsConfig


class TestBuildKenBurnsFilter:
    def test_zoom_in_expr(self):
        result = _build_ken_burns_filter("[in]", "[out]", 5.0, 480, 854,
                                         zoom_direction="in")
        assert "min(zoom+0.001" in result

    def test_zoom_out_expr(self):
        result = _build_ken_burns_filter("[in]", "[out]", 5.0, 480, 854,
                                         zoom_direction="out")
        assert "max(zoom-0.001" in result

    def test_total_frames(self):
        result = _build_ken_burns_filter("[in]", "[out]", 5.0, 480, 854,
                                         fps=30)
        assert "d=150" in result  # 5.0 * 30

    def test_output_size(self):
        result = _build_ken_burns_filter("[in]", "[out]", 5.0, 480, 854)
        assert "s=480x854" in result

    def test_custom_speed(self):
        result = _build_ken_burns_filter("[in]", "[out]", 5.0, 480, 854,
                                         zoom_speed=0.002)
        assert "min(zoom+0.002" in result

    def test_disabled_config(self):
        """KenBurnsConfig(enabled=False) 时不应生成 zoompan。"""
        cfg = KenBurnsConfig(enabled=False)
        assert not cfg.enabled


class TestKenBurnsSupersample:
    """zoompan 亚像素取整抖动的超采样治理。"""

    def test_supersample_is_four_times(self):
        assert _kb_supersample_size(480, 854) == (1920, 3416)

    def test_supersample_capped(self):
        width, height = _kb_supersample_size(2000, 3000)
        assert width == 3840
        assert height == 6144
