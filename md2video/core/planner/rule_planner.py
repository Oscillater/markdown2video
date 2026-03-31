from __future__ import annotations

from typing import List
from md2video.manifest.schema import SegmentPlan


class RulePlanner:
    """Phase 1 规则规划器: 所有 segment 设为 text_only。"""

    def plan(self, segments: List[SegmentPlan]) -> List[SegmentPlan]:
        for seg in segments:
            if not seg.explicit:
                seg.visual_type = "text_only"
                seg.visual_params = {}
        return segments
