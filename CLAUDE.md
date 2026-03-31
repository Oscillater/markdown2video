# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a markdown-to-video conversion tool that transforms styled Markdown text into animated videos with text-to-speech, music, and image overlays. The project uses Manim for animation generation and ffmpeg for post-processing media insertion.

## Common Development Commands

### Running the New Pipeline (Phase 1)
```bash
# Activate venv and run
cd D:\Project\markdown2video
.venv\Scripts\activate
python -m md2video anim/example.md -o artifacts/output.mp4
```

### Running the Legacy Pipeline (anim/)
```bash
cd anim
manim -pql main.py Demo
```

### Testing Individual Components
```bash
# Test manifest schema
python -c "from md2video.manifest.schema import PlanManifest; print('OK')"

# Test parser
python -c "from md2video.parser.md_parser import parse_to_plan_manifest; print(parse_to_plan_manifest('anim/example.md'))"

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

### Two Codebases

1. **`md2video/`** (New, Phase 1): Manifest-driven pipeline with clean module separation
2. **`anim/`** (Legacy): Original monolithic implementation, kept as reference

### New Architecture (md2video/)

```
Markdown → Parser → Plan Manifest → Planner → TTS Tool → Result Manifest → Manim Renderer → FFmpeg Assembler → MP4
```

**Key Design**:
- **Two-pass TTS**: TTS audio is pre-computed before Manim rendering via standalone `EdgeTTSTool`
- **CachedVoiceService**: Bridges pre-computed audio into Manim's `VoiceoverScene` without re-generating
- **Manifest is the single data flow**: No direct tool-to-tool communication

### Core Components (md2video/)

1. **Manifest Schema (`manifest/schema.py`)**: Pydantic models defining Plan Manifest and Result Manifest.
   - `PlanManifest`: segments list with text, type, audio_request, visual_type
   - `ResultManifest`: segments list with audio path, duration, start/end times

2. **Parser (`parser/`)**: Markdown parsing → Plan Manifest
   - `md_parser.py`: `parse_to_plan_manifest(md_path)` returns `PlanManifest`
   - `segmenter.py`: Chinese text sentence splitting

3. **TTS Tool (`tools/tts/edge_tts.py`)**: Standalone edge-tts, no manim dependency
   - `EdgeTTSTool.synthesize(text, voice, speed)` → `{path, duration, provider, cache_key}`
   - Caches to `artifacts/tts/`

4. **CachedVoiceService (`tools/render/cached_voice.py`)**: Bridge for Manim
   - Returns pre-computed audio paths during `VoiceoverScene.voiceover()` calls

5. **Manim Renderer (`tools/render/manim_renderer.py`)**: `ManifestDrivenScene`
   - Consumes PlanManifest + ResultManifest (reads from `artifacts/`)
   - Rendering logic ported from legacy `Demo.construct()`

6. **FFmpeg Assembler (`assembler/ffmpeg_assembler.py`)**: Consumes Result Manifest
   - Extracts music/image timing from manifest (no markdown re-parsing)
   - Uses ffmpeg for audio mixing and image overlays

7. **Pipeline (`core/pipeline.py`)**: Orchestrates Parser → Planner → TTS → Render → Assemble

8. **Planner (`core/planner/rule_planner.py`)**: Phase 1 stub, all segments set to `text_only`

9. **CLI (`cli.py`)**: Entry point `python -m md2video <input.md>`

### Legacy Components (anim/)

Kept as reference. See original code for details.

### File Structure

- `md2video/`: New modular pipeline (Phase 1)
  - `manifest/schema.py`: Pydantic models (Plan + Result Manifest)
  - `parser/`: Markdown → Plan Manifest
  - `tools/tts/edge_tts.py`: Standalone TTS tool
  - `tools/render/`: CachedVoiceService + Manim renderer
  - `assembler/ffmpeg_assembler.py`: FFmpeg post-processing
  - `core/pipeline.py`: Framework orchestrator
  - `core/planner/`: Rule planner (Phase 1: all text_only)
  - `cli.py`: Entry point `python -m md2video`
  - `config.py`: Layout constants and defaults
- `anim/`: Legacy implementation
- `artifacts/`: Generated intermediate files (gitignored)

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

The project requires several external tools and libraries:
- **Manim**: Animation engine
- **ffmpeg**: Video processing and media insertion
- **edge-tts**: Microsoft Edge text-to-speech
- **manim-voiceover**: Voiceover integration for Manim
- **sox**: Audio processing (optional, for advanced audio features)

### Important Implementation Details

1. **Text Layout**: Uses a dual-column approach with section titles on the left (positioned at `LEFT_X = -1.75`) and content on the right (positioned at `RIGHT_X = 0.2`).

2. **Animation Timing**: The system tracks timing using `self.time` and generates a timeline.json file that maps text segments to their start/end times.

3. **Media Synchronization**: The media insertion script uses the timeline to synchronize music and image overlays with the animated content.

4. **Voice Caching**: Generated voice files are cached in `voice_cache/` directory to avoid repeated API calls.

5. **Chinese Support**: The system is optimized for Chinese text with proper font handling (`FZShuSong-Z01S`) and TTS voice (`zh-CN-YunxiNeural`).

### Troubleshooting

- **SSL Issues**: The `EdgeTTSVoice` class includes custom SSL context configuration to handle TLS connection problems.
- **Media Not Found**: The media insertion script automatically falls back if media files are missing.
- **Timing Issues**: Timeline generation accounts for voiceover duration and animation timing.
- **Video Resolution**: The system automatically detects video resolution for proper overlay positioning.