# Phase 1.1: 单元测试覆盖

**日期**: 2026-04-01
**状态**: 已完成

## 概述

为 `md2video/` 核心模块编写单元测试，覆盖 Parser、Planner、各 Tool 和 Schema，共 127 个测试全部通过。

## 新增文件

```
tests/
    __init__.py
    conftest.py                      # 共享 fixtures (Manifest 模型、临时文件)
    test_schema.py                   # Pydantic 模型 (16 tests)
    test_segmenter.py                # 中文分句 + 声明/marker 检测 (28 tests)
    test_md_parser.py                # Markdown 解析器全部函数 (34 tests)
    test_rule_planner.py             # 规则规划器 (5 tests)
    test_ffmpeg_extractor.py         # 音乐/图片时间提取 (9 tests)
    test_edge_tts.py                 # TTS 工具，mock asyncio/subprocess (7 tests)
    test_cached_voice.py             # 缓存语音服务 (7 tests)
    test_data/
        full_example.md
        minimal.md
        markers_in_content.md
```

## 测试覆盖

| 模块 | 测试文件 | 测试数 | Mock 策略 |
|------|----------|--------|-----------|
| `manifest/schema.py` | test_schema.py | 16 | 无 (纯 Pydantic) |
| `parser/segmenter.py` | test_segmenter.py | 28 | 无 (纯函数) |
| `parser/md_parser.py` | test_md_parser.py | 34 | 无 (纯函数 + tmp_path) |
| `core/planner/rule_planner.py` | test_rule_planner.py | 5 | 无 (纯逻辑) |
| `assembler/ffmpeg_assembler.py` | test_ffmpeg_extractor.py | 9 | 无 (纯数据变换) |
| `tools/tts/edge_tts.py` | test_edge_tts.py | 7 | mock asyncio.run, subprocess.run |
| `tools/render/cached_voice.py` | test_cached_voice.py | 7 | 无 (tmp_path 真实文件) |

## 运行方式

```bash
python -m pytest tests/ -v
```

## 注意事项

- EdgeTTSTool 测试中有 2 个 RuntimeWarning（coroutine 'Communicate.save' was never awaited），属 mock 预期行为，不影响测试结果
