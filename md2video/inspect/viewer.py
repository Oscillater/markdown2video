"""manifest_viewer.html 生成器 — 一次 run 的紧凑静态查看页。

单文件自包含：数据以 JSON 内嵌，样式与渲染逻辑内联，不依赖任何外部
网络资源。生成器是纯函数（视图模型 dict -> HTML str），管线负责取材与
写盘。验收标准：人不读原始 JSON 能看懂一次运行——plan 意图、素材事实、
时间事实、交付摘要、warnings、预计 vs 实际时长一页看完。
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from md2video.manifest.schema import ExecutionAssets, FinalResultManifest, PlanManifest
from md2video.style.schema import ThemeTokens
from md2video.timeline.estimate import DurationEstimate, estimate_plan_duration

VIEWER_FILENAME = "manifest_viewer.html"


def _round(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def _finite_or_zero(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def build_run_view(
    *,
    run_id: str,
    plan: PlanManifest,
    assets: ExecutionAssets,
    timeline_data: dict | None,
    final_result: FinalResultManifest,
    style_pack: ThemeTokens,
    style_requested: str,
) -> dict:
    """把一次 run 的四本账汇总成检查页视图模型（纯函数，输出确定）。"""
    estimate = estimate_plan_duration(plan, assets, style_pack)
    timeline_shots = list(timeline_data.get("shots", [])) if timeline_data else []
    actual_total = max(
        (_finite_or_zero(shot.get("end")) for shot in timeline_shots),
        default=0.0,
    )

    return {
        "run_id": run_id,
        "status": final_result.status,
        "style_pack": {
            "requested": style_requested,
            "resolved": style_pack.id,
            "motif_kind": style_pack.motif.kind,
        },
        "duration": _duration_view(estimate, actual_total),
        "plan": _plan_view(plan),
        "assets": _assets_view(assets),
        "timeline": _timeline_view(timeline_data),
        "result": _result_view(final_result),
        "warnings": list(final_result.warnings),
    }


def _duration_view(estimate: DurationEstimate, actual_total: float) -> dict:
    estimated_total = estimate.total_seconds
    return {
        "estimated_total": _round(estimated_total),
        "voiced_seconds": _round(estimate.voiced_seconds),
        "silent_seconds": _round(estimate.silent_seconds),
        "overhead_seconds": _round(estimate.overhead_seconds),
        "actual_total": _round(actual_total),
        "delta": _round(actual_total - estimated_total),
        "per_segment": {
            segment_id: _round(seconds)
            for segment_id, seconds in estimate.per_segment.items()
        },
    }


def _plan_view(plan: PlanManifest) -> dict:
    return {
        "version": plan.version,
        "segments": [
            {
                "id": segment.id,
                "segment_type": segment.segment_type,
                "text": segment.text,
                "explicit": segment.explicit,
                "voiced": segment.audio_request is not None,
                "voice": segment.audio_request.voice if segment.audio_request else "",
                "section_context": segment.section_context,
            }
            for segment in plan.segments
        ],
        "scenes": [
            {
                "id": scene.id,
                "visual_type": scene.visual_type,
                "visual_params": dict(scene.visual_params),
                "layout_type": scene.layout_type,
                "layout_params": dict(scene.layout_params),
                "layout_regions": (
                    dict(scene.layout_regions) if scene.layout_regions else {}
                ),
                "render_backend": scene.render_backend,
                "section_context": scene.section_context,
                "shots": [
                    {
                        "id": shot.id,
                        "segment_ids": list(shot.segment_ids),
                        "cues": [dict(cue) for cue in shot.cues],
                    }
                    for shot in scene.shots
                ],
            }
            for scene in plan.scenes
        ],
    }


def _assets_view(assets: ExecutionAssets) -> dict:
    return {
        "audio": [
            {
                "segment_id": asset.segment_id,
                "provider": asset.provider,
                "duration": _round(asset.duration),
                "path": asset.path,
                "cache_key": asset.cache_key,
            }
            for asset in assets.audio_assets
        ],
        "visual": [
            {
                "shot_id": asset.shot_id,
                "provider": asset.provider,
                "width": asset.width,
                "height": asset.height,
                "duration": _round(asset.duration),
                "path": asset.path,
                "cache_key": asset.cache_key,
            }
            for asset in assets.visual_assets
        ],
    }


def _timeline_view(timeline_data: dict | None) -> dict:
    if not timeline_data:
        return {"shots": [], "text_cues": [], "markers": []}
    return {
        "shots": [
            {
                "shot_id": shot.get("shot_id", ""),
                "scene_id": shot.get("scene_id", ""),
                "layout_type": shot.get("layout_type", ""),
                "start": _round(_finite_or_zero(shot.get("start"))),
                "end": _round(_finite_or_zero(shot.get("end"))),
                "duration": _round(
                    _finite_or_zero(shot.get("end")) - _finite_or_zero(shot.get("start"))
                ),
                "segment_ids": [
                    sid for sid in shot.get("segment_ids", []) if isinstance(sid, str)
                ],
            }
            for shot in timeline_data.get("shots", [])
            if isinstance(shot, dict)
        ],
        "text_cues": [
            {
                "segment_id": entry.get("segment_id", ""),
                "segment_type": entry.get("segment_type", ""),
                "text": entry.get("text", ""),
                "start": _round(_finite_or_zero(entry.get("start"))),
                "end": _round(_finite_or_zero(entry.get("end"))),
                "shot_id": entry.get("shot_id", ""),
            }
            for entry in timeline_data.get("text", [])
            if isinstance(entry, dict)
        ],
        "markers": [
            {
                "id": entry.get("id", ""),
                "cue_type": entry.get("cue_type", ""),
                "kind": entry.get("kind", ""),
                "name": entry.get("name", ""),
                "time": _round(_finite_or_zero(entry.get("time"))),
                "shot_id": entry.get("shot_id", ""),
            }
            for entry in timeline_data.get("markers", [])
            if isinstance(entry, dict)
        ],
    }


def _result_view(final_result: FinalResultManifest) -> dict:
    return {
        "output_mp4": final_result.output_mp4,
        "used_assets": {
            kind: len(entries) for kind, entries in final_result.used_assets.items()
        },
        "artifact_index": dict(final_result.artifact_index),
    }


_HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>md2video run inspect</title>
<style>
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px 16px 64px; background: #f5f6f8; color: #1c2330;
       font: 14px/1.55 "Segoe UI", system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; }
main { max-width: 1080px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
h1 { font-size: 18px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 0 0 10px; color: #24304d; }
section { background: #fff; border: 1px solid #dfe3ea; border-radius: 10px; padding: 14px 16px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border: 1px solid #e3e7ee; padding: 4px 8px; text-align: left; vertical-align: top; }
th { background: #f0f3f8; font-weight: 600; white-space: nowrap; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
code, .path { font-family: Consolas, "Courier New", monospace; font-size: 12px; word-break: break-all; }
.muted { color: #67718a; }
.chip { display: inline-block; background: #eef2f9; border: 1px solid #d8e0ee; border-radius: 4px;
        padding: 0 6px; margin: 1px 2px 1px 0; font-size: 12px; }
.chip.warn { background: #fdf3e2; border-color: #eed9ac; color: #7a5410; }
.badge { display: inline-block; border-radius: 999px; padding: 1px 10px; font-size: 12px; font-weight: 600; }
.badge.completed { background: #e2f5e9; color: #14683a; }
.badge.failed { background: #fbe4e4; color: #8f1f1f; }
.delta-ok { color: #14683a; font-weight: 600; }
.delta-off { color: #9a6a08; font-weight: 600; }
.scene { margin: 10px 0 0; border-top: 1px dashed #e3e7ee; padding-top: 8px; }
.scene:first-of-type { border-top: none; padding-top: 0; }
.shots { margin: 6px 0 0 18px; }
.shot { margin: 4px 0; }
ul.plain { margin: 4px 0; padding-left: 20px; }
.kv { margin: 2px 0; }
.kv b { color: #24304d; }
</style>
</head>
<body>
<main id="app"></main>
<script id="md2video-view" type="application/json">"""

_HTML_TAIL = """</script>
<script>
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("md2video-view").textContent);

  function el(tag, attrs) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        if (key === "text") { node.textContent = attrs[key]; }
        else if (key === "cls") { node.className = attrs[key]; }
        else { node.setAttribute(key, attrs[key]); }
      });
    }
    for (var i = 2; i < arguments.length; i++) {
      var child = arguments[i];
      if (child === null || child === undefined) { continue; }
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return node;
  }

  function sec(title) {
    var h = el("h2", { text: title });
    var s = el("section");
    s.appendChild(h);
    return s;
  }

  function table(headers, rows) {
    var t = el("table");
    var thead = el("thead");
    var trh = el("tr");
    headers.forEach(function (h) {
      var attrs = { text: h.label };
      if (h.num) { attrs.cls = "num"; }
      trh.appendChild(el("th", attrs));
    });
    thead.appendChild(trh);
    t.appendChild(thead);
    var tbody = el("tbody");
    rows.forEach(function (row) {
      var tr = el("tr");
      row.forEach(function (cell, i) {
        var attrs = {};
        if (headers[i] && headers[i].num) { attrs.cls = "num"; }
        if (cell && cell.path) { attrs.cls = "path"; }
        var td = el("td", attrs);
        td.textContent = (cell === null || cell === undefined) ? "" : String(cell);
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    t.appendChild(tbody);
    return t;
  }

  function kvLine(label, value, cls) {
    return el("div", { cls: cls || "kv" }, el("b", { text: label + ": " }), value === "" ? "(空)" : String(value));
  }

  function paramsText(params) {
    var keys = Object.keys(params || {});
    if (!keys.length) { return ""; }
    return keys.map(function (k) { return k + "=" + JSON.stringify(params[k]); }).join(", ");
  }

  function emptyNote(text) {
    return el("p", { cls: "muted", text: text });
  }

  // ---- header ----
  var app = document.getElementById("app");
  var head = el("section");
  head.appendChild(el("h1", { text: "md2video run " + data.run_id }));
  head.appendChild(el("span", { cls: "badge " + data.status, text: data.status }));
  head.appendChild(el("span", { cls: "muted", text: "  style pack: " +
    (data.style_pack.requested === data.style_pack.resolved
      ? data.style_pack.resolved
      : data.style_pack.requested + " → " + data.style_pack.resolved + " (降级)")
    + "，motif: " + (data.style_pack.motif_kind || "(无)") }));
  head.appendChild(kvLine("输出 MP4", data.result.output_mp4, "kv path"));
  app.appendChild(head);

  // ---- duration ----
  var dur = data.duration;
  var durSec = sec("时长：预计 vs 实际");
  var deltaOk = Math.abs(dur.delta) <= Math.max(1.5, 0.1 * dur.estimated_total);
  durSec.appendChild(table(
    [{ label: "预计（估算）", num: true }, { label: "实际（timeline 末 shot end）", num: true },
     { label: "差值", num: true }, { label: "有声 / 静默 / 转场开销", num: true }],
    [[dur.estimated_total.toFixed(2) + "s", dur.actual_total.toFixed(2) + "s", dur.delta.toFixed(2) + "s",
      dur.voiced_seconds.toFixed(2) + "s / " + dur.silent_seconds.toFixed(2) + "s / " +
      dur.overhead_seconds.toFixed(2) + "s"]]
  ));
  var deltaNote = el("p", null,
    el("span", { cls: deltaOk ? "delta-ok" : "delta-off",
                 text: deltaOk ? "差值在容错范围内" : "差值偏大：检查 warnings 与静默段节奏" }));
  durSec.appendChild(deltaNote);
  app.appendChild(durSec);

  // ---- warnings ----
  var warnSec = sec("Warnings（降级 / 缺失 / 时长差异）");
  if (data.warnings.length) {
    var ul = el("ul", { cls: "plain" });
    data.warnings.forEach(function (w) { ul.appendChild(el("li", { text: w })); });
    warnSec.appendChild(ul);
  } else {
    warnSec.appendChild(emptyNote("无"));
  }
  app.appendChild(warnSec);

  // ---- plan ----
  var planSec = sec("Plan（意图：" + data.plan.version + "，不含时间与风格取值）");

  var segTable = table(
    [{ label: "id" }, { label: "类型" }, { label: "文本" }, { label: "角色" }, { label: "section" }],
    data.plan.segments.map(function (s) {
      var role = [s.segment_type, s.explicit ? "explicit" : null, s.voiced ? "voice(" + s.voice + ")" : "silent"]
        .filter(Boolean).join(" · ");
      return [s.id, s.segment_type, s.text, role, s.section_context];
    })
  );
  planSec.appendChild(segTable);

  data.plan.scenes.forEach(function (scene) {
    var box = el("div", { cls: "scene" });
    var sceneLine = el("b", { text: scene.id });
    var lineText = " · visual=" + scene.visual_type +
      (paramsText(scene.visual_params) ? " (" + paramsText(scene.visual_params) + ")" : "") +
      " · layout=" + (scene.layout_regions && Object.keys(scene.layout_regions).length
        ? "proposal(" + Object.keys(scene.layout_regions).join("+") + ")"
        : scene.layout_type) +
      (scene.layout_type && !(scene.layout_regions && Object.keys(scene.layout_regions).length)
        ? (paramsText(scene.layout_params) ? " (" + paramsText(scene.layout_params) + ")" : "")
        : "") +
      " · backend=" + (scene.render_backend || "(默认)") +
      (scene.section_context ? " · " + scene.section_context : "");
    box.appendChild(el("div", null, sceneLine, lineText));
    var shots = el("div", { cls: "shots" });
    scene.shots.forEach(function (shot) {
      var line = el("div", { cls: "shot" }, el("b", { text: shot.id }), " ← ");
      shot.segment_ids.forEach(function (sid, i) {
        if (i) { line.appendChild(document.createTextNode(" + ")); }
        line.appendChild(el("code", { text: sid }));
      });
      shot.cues.forEach(function (cue) {
        var label = (cue.cue_type || "cue") + (cue.kind ? ":" + cue.kind : "") +
          (cue.name ? ":" + cue.name : "") + " @" + (cue.position || "start");
        line.appendChild(document.createTextNode(" "));
        line.appendChild(el("span", { cls: "chip warn", text: label }));
      });
      if (!shot.segment_ids.length && !shot.cues.length) {
        line.appendChild(el("span", { cls: "muted", text: "(空 shot)" }));
      }
      shots.appendChild(line);
    });
    box.appendChild(shots);
    planSec.appendChild(box);
  });
  app.appendChild(planSec);

  // ---- execution assets ----
  var assetSec = sec("Execution Assets（素材事实）");
  assetSec.appendChild(el("h2", { text: "音频（TTS）" }));
  if (data.assets.audio.length) {
    assetSec.appendChild(table(
      [{ label: "segment" }, { label: "provider" }, { label: "duration(s)", num: true },
       { label: "path" }, { label: "cache key" }],
      data.assets.audio.map(function (a) {
        return [a.segment_id, a.provider, a.duration.toFixed(2), a.path, a.cache_key];
      })
    ));
  } else {
    assetSec.appendChild(emptyNote("无音频素材（静默 run）"));
  }
  assetSec.appendChild(el("h2", { text: "图片 / 视觉素材" }));
  if (data.assets.visual.length) {
    assetSec.appendChild(table(
      [{ label: "shot" }, { label: "provider" }, { label: "尺寸" }, { label: "duration(s)", num: true },
       { label: "path" }, { label: "cache key" }],
      data.assets.visual.map(function (v) {
        return [v.shot_id, v.provider, v.width + "x" + v.height, v.duration.toFixed(2), v.path, v.cache_key];
      })
    ));
  } else {
    assetSec.appendChild(emptyNote("无"));
  }
  app.appendChild(assetSec);

  // ---- timeline ----
  var tlSec = sec("Timeline（时间事实，shots 为主时间轴）");
  if (data.timeline.shots.length) {
    tlSec.appendChild(table(
      [{ label: "shot" }, { label: "scene" }, { label: "layout" }, { label: "start(s)", num: true },
       { label: "end(s)", num: true }, { label: "时长(s)", num: true }, { label: "segments" }],
      data.timeline.shots.map(function (s) {
        return [s.shot_id, s.scene_id, s.layout_type, s.start.toFixed(2), s.end.toFixed(2),
                s.duration.toFixed(2), s.segment_ids.join(" + ")];
      })
    ));
    tlSec.appendChild(el("h2", { text: "文本 cue" }));
    if (data.timeline.text_cues.length) {
      tlSec.appendChild(table(
        [{ label: "segment" }, { label: "类型" }, { label: "文本" }, { label: "start(s)", num: true },
         { label: "end(s)", num: true }, { label: "shot" }],
        data.timeline.text_cues.map(function (t) {
          return [t.segment_id, t.segment_type, t.text, t.start.toFixed(2), t.end.toFixed(2), t.shot_id];
        })
      ));
    } else {
      tlSec.appendChild(emptyNote("无"));
    }
    tlSec.appendChild(el("h2", { text: "marker cue" }));
    if (data.timeline.markers.length) {
      tlSec.appendChild(table(
        [{ label: "id" }, { label: "类型" }, { label: "kind" }, { label: "name" },
         { label: "time(s)", num: true }, { label: "shot" }],
        data.timeline.markers.map(function (m) {
          return [m.id, m.cue_type, m.kind, m.name, m.time.toFixed(2), m.shot_id];
        })
      ));
    } else {
      tlSec.appendChild(emptyNote("无"));
    }
  } else {
    tlSec.appendChild(emptyNote("本次 run 没有 timeline（可能失败于渲染之前）"));
  }
  app.appendChild(tlSec);

  // ---- result ----
  var resSec = sec("Result（交付摘要）");
  resSec.appendChild(kvLine("输出 MP4", data.result.output_mp4, "kv path"));
  var used = data.result.used_assets;
  resSec.appendChild(kvLine("used assets", "audio=" + (used.audio || 0) + ", visual=" + (used.visual || 0)));
  resSec.appendChild(el("h2", { text: "artifact index" }));
  resSec.appendChild(table(
    [{ label: "artifact" }, { label: "路径" }],
    Object.keys(data.result.artifact_index).map(function (key) {
      return [key, data.result.artifact_index[key]];
    })
  ));
  app.appendChild(resSec);
})();
</script>
</body>
</html>
"""


def render_viewer_html(view: dict) -> str:
    """视图模型 -> 单文件自包含 HTML。

    JSON 内嵌进 <script type="application/json">，转义 "</" 防止提前闭合
    标签（"<\\/" 是合法 JSON 转义）；页面脚本用 DOM API 渲染，文本节点
    不经 HTML 拼接。
    """
    payload = json.dumps(view, ensure_ascii=False, indent=1).replace("</", "<\\/")
    return _HTML_HEAD + payload + _HTML_TAIL


def write_manifest_viewer(
    run_dir: Path,
    *,
    view: dict,
) -> Path:
    """把检查页写进 run 目录并返回路径（管线负责登记 artifact_index）。"""
    path = Path(run_dir) / VIEWER_FILENAME
    path.write_text(render_viewer_html(view), encoding="utf-8")
    return path
