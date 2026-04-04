# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a markdown-to-video conversion tool that transforms styled Markdown text into animated videos with text-to-speech, music, and image overlays. The project uses Manim for animation generation and ffmpeg for post-processing media insertion.

## Common Development Commands

### Running the Pipeline
```bash
# Activate venv and run
cd D:\Project\markdown2video
.venv\Scripts\activate
python -m md2video example/example.md -o artifacts/output.mp4
```

### Running Tests
```bash
python -m pytest tests/ -v
```

### Testing Individual Components
```bash
# Test manifest schema
python -c "from md2video.manifest.schema import PlanManifest; print('OK')"

# Test parser
python -c "from md2video.parser.md_parser import parse_to_plan_manifest; print(parse_to_plan_manifest('example/example.md'))"

# Test TTS tool
python -c "from md2video.tools.tts.edge_tts import EdgeTTSTool; t = EdgeTTSTool(); print(t.synthesize('test'))"
```

### Environment Setup
```powershell
# Activate venv
.venv\Scripts\activate

# Ensure ffmpeg is on PATH
$env:PATH += ";D:\ffmpeg\bin"
$env:PATH += ";D:\sox\sox-14-4-2"
```

## Architecture Overview

```
Markdown → Parser → Plan Manifest → Planner → TTS Tool → Result Manifest → Manim Renderer → FFmpeg Assembler → MP4
```

**Key Concepts**:
- **Segment**: Minimum time unit (one sentence). TTS operates per-segment.
- **Shot**: Minimum continuous visual unit. Groups consecutive Segments; each Shot invokes one tool.
- **Scene**: Semantic style group. Planner groups Shots into Scenes that share a visual plan.
- **Manifest is the single data flow**: No direct tool-to-tool communication.

**Key Design**:
- **Two-pass TTS**: TTS audio is pre-computed before Manim rendering via standalone `EdgeTTSTool`
- **CachedVoiceService**: Bridges pre-computed audio into Manim's `VoiceoverScene` without re-generating
- **Scene-based rendering**: Renderer iterates over Scenes, not individual Segments
- **Two-pass LLM Planner**: Global Blueprint (define scene templates) → Chunk Mapping (per-chapter shot mapping) → Reconcile (merge + validate). Scene = visual template, shots sharing the same scene_id merge into one ScenePlan.

### Core Components

1. **Manifest Schema (`manifest/schema.py`)**: Pydantic models defining Plan Manifest and Result Manifest.
   - `SegmentPlan`: single segment's text, type, audio_request, visual_type
   - `ShotPlan`: groups consecutive segment_ids (minimum visual unit)
   - `ScenePlan`: groups shots, visual_type, visual_params, section_context
   - `SegmentResult`: audio path, duration, start/end times
   - `ShotResult`: aggregated start/end from segments, visual result
   - `SceneResult`: aggregated start/end from shots, backward-compatible with segment_ids
   - `PlanManifest`: segments + scenes + media_declarations
   - `ResultManifest`: segments + scenes (scenes built from shot results)

2. **Parser (`parser/`)**: Markdown parsing → Plan Manifest
   - `md_parser.py`: `parse_to_plan_manifest(md_path)` returns `PlanManifest`
   - `segmenter.py`: Chinese text sentence splitting

3. **Planner (`core/planner/`)**: Two implementations with identical `plan(segments) → List[ScenePlan]` interface
   - **Rule Planner (`rule_planner.py`)**: Rule-based scene grouping by segment type and character count
     - Each scene maps 1:1 to a shot (Shot ID globally sequential)
     - `denormalize_scenes_to_segments()`: copies scene visual info back to non-explicit segments
   - **LLM Planner (`llm_planner.py`)**: Two-pass global orchestration
     - **Pass 1 `_global_blueprint()`**: Full Markdown → LLM defines 3~5 Scene templates (Scene Registry)
     - **Pass 2 `_chunk_mapping()`**: Per-chapter chunks → LLM maps shots to scene templates
     - **Pass 3 `_reconcile()`**: Merges chunk results → groups by scene_id → validates → splits explicit
     - `_split_chunks()`: Splits by section_context + MAX_CHUNK_SEGS (30)
     - `_validate_text_integrity()`: Ensures all segments are covered
     - Uses `pydantic-ai` Agent with `tool_plain` for structured output (compatible with API proxies)
     - Auto-falls back to RulePlanner on any failure
   - Config: `.env` with `MD2VIDEO_PLANNER=llm`, `OPENAI_API_KEY`, `MD2VIDEO_LLM_MODEL`, `MD2VIDEO_LLM_BASE_URL`

4. **TTS Tool (`tools/tts/edge_tts.py`)**: Standalone edge-tts, no manim dependency
   - `EdgeTTSTool.synthesize(text, voice, speed)` → `{path, duration, provider, cache_key}`
   - Caches to `artifacts/tts/`

5. **CachedVoiceService (`tools/render/cached_voice.py`)**: Bridge for Manim
   - Returns pre-computed audio paths during `VoiceoverScene.voiceover()` calls

6. **Manim Renderer (`tools/render/manim_renderer.py`)**: `ManifestDrivenScene`
   - `_construct_by_scenes()`: iterates over scenes, renders segments within each
   - Uses `scene.all_segment_ids` (property that expands shots' segment_ids)
   - `_construct_flat()`: Phase 1 compat fallback when `plan.scenes` is empty
   - Helper methods: `_render_segment()`, `_render_section_header()`, `_render_title()`, `_setup_dot_animation()`, `_finish()`

7. **FFmpeg Assembler (`assembler/ffmpeg_assembler.py`)**: Consumes Result Manifest
   - Extracts music/image timing from manifest (no markdown re-parsing)
   - Scene-based visual loop placeholder (Phase 2B: image overlays)

8. **Pipeline (`core/pipeline.py`)**: Orchestrates Parser → Planner → TTS → Render → Assemble
   - `_build_scene_results()`: builds ShotResult from segment times, then aggregates into SceneResult

9. **CLI (`cli.py`)**: Entry point `python -m md2video <input.md>`

### File Structure

- `md2video/`: Core pipeline
  - `manifest/schema.py`: Pydantic models (Segment + Shot + Scene, Plan + Result Manifest)
  - `parser/`: Markdown → Plan Manifest
  - `tools/tts/edge_tts.py`: Standalone TTS tool
  - `tools/render/`: CachedVoiceService + Manim renderer
  - `assembler/ffmpeg_assembler.py`: FFmpeg post-processing
  - `core/pipeline.py`: Pipeline orchestrator
  - `core/planner/rule_planner.py`: Rule-based scene grouping (Scene → Shot 1:1 mapping)
  - `core/planner/llm_planner.py`: Two-pass LLM planner (Blueprint → Chunk Mapping → Reconcile)
  - `cli.py`: Entry point `python -m md2video`
  - `config.py`: Layout constants and defaults
- `example/`: Example Markdown
- `tests/`: Unit tests
- `artifacts/`: Generated intermediate files (gitignored)
- `changelog/`: Change logs

**Markdown Syntax**:
- `# Title`: Main title (appears at beginning)
- `## Subtitle`: Subtitle (appears at beginning)
- `### Section`: Section headers (displayed on left side)
- `---`: Separator between main content and appendix
- `[music:name="name",src="path"]`: Music file declaration
- `[image:name="name",src="path"]`: Image file declaration
- `[music_start name]`, `[music_end name]`: Music playback markers
- `[image_start name]`, `[image_end name]`: Image display markers

### Dependencies

- **Manim**: Animation engine
- **ffmpeg**: Video processing and media insertion
- **edge-tts**: Microsoft Edge text-to-speech
- **manim-voiceover**: Voiceover integration for Manim
- **sox**: Audio processing (optional, for advanced audio features)

### Important Implementation Details

1. **Text Layout**: Uses a dual-column approach with section titles on the left (positioned at `LEFT_X = -1.75`) and content on the right (positioned at `RIGHT_X = 0.2`).

2. **Animation Timing**: The system tracks timing using `self.time` and generates a timeline.json file that maps text segments to their start/end times.

3. **Media Synchronization**: The media insertion script uses the timeline to synchronize music and image overlays with the animated content.

4. **Voice Caching**: Generated voice files are cached in `artifacts/tts/` directory to avoid repeated API calls.

5. **Chinese Support**: The system is optimized for Chinese text with proper font handling (`FZShuSong-Z01S`) and TTS voice (`zh-CN-YunxiNeural`).

### Troubleshooting

- **SSL Issues**: The `EdgeTTSVoice` class includes custom SSL context configuration to handle TLS connection problems.
- **Media Not Found**: The media insertion script automatically falls back if media files are missing.
- **Timing Issues**: Timeline generation accounts for voiceover duration and animation timing.
- **Video Resolution**: The system automatically detects video resolution for proper overlay positioning.
