from __future__ import annotations

from typing import List, Protocol, runtime_checkable

from md2video.manifest.schema import ScenePlan, SegmentPlan


@runtime_checkable
class Planner(Protocol):
    def plan(self, segments: List[SegmentPlan]) -> List[ScenePlan]: ...


from md2video.core.planner.rule_planner import RulePlanner, denormalize_scenes_to_segments

# lazy import for LlmPlanner (requires pydantic-ai)
def __getattr__(name):
    if name in ("LlmPlanner", "SceneTemplate", "BlueprintOutput", "ChunkMappingOutput"):
        from md2video.core.planner.llm_planner import (
            LlmPlanner, SceneTemplate, BlueprintOutput, ChunkMappingOutput,
        )
        globals()["LlmPlanner"] = LlmPlanner
        globals()["SceneTemplate"] = SceneTemplate
        globals()["BlueprintOutput"] = BlueprintOutput
        globals()["ChunkMappingOutput"] = ChunkMappingOutput
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "Planner", "RulePlanner", "denormalize_scenes_to_segments",
    "LlmPlanner", "SceneTemplate", "BlueprintOutput", "ChunkMappingOutput",
]
