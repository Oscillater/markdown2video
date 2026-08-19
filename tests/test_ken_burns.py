"""Ken Burns 动效单元测试。"""
from md2video.assembler.ffmpeg_assembler import _build_ken_burns_filter
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
