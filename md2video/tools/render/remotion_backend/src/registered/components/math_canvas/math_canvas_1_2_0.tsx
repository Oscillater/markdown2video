import React from 'react';
import {useCurrentFrame} from 'remotion';
import type {ComponentProps} from '../../types';

// math_canvas@1.2.0 —— A8.1 场景画布组件（mount="scene"）。
// 对标 3b1b 的核心语义：**波是点的高度投影**。动点从最右边出发逆时针转，
// 转到哪、正弦画到哪——波头始终在动点的高度上（描线期间画出水平投影
// 虚线）；余弦画的是点的**水平位置**：圆心到垂足的横线段就是它的长度，
// 波头与纵轴上对应点等高，虚线相连（半径三角构造）。
//
// 图层编排是 plan 作者的数据（visual_params.layers），组件不猜：
//   "layers": [{"shot": "shot_005", "kind": "sine"},
//              {"shot": "shot_007", "kind": "cosine"}]
// 每层从锚点 shot 的窗口起点可见（把 header shot 写成锚点 = 动画从上一
// 个 shot 起笔）；描线进度由动点角度 θ 驱动。θ 的基准：在正弦锚点窗口
// 结束时恰好完成第一整圈（"回到起点，曲线归零"与画面逐帧同步）。切走
// 的镜头角度冻结、回场续转（累积活跃时间，纯函数，确定性不变）。
// 未声明 layers 时只画底座（坐标系 + 圆 + 动点），确定性降级。

const BACKGROUND = '#0B0E14';
const AXIS = '#7C8798';
const LABEL = '#9AA7B8';
const LAYER_COLORS = ['#4FC3F7', '#FFB86C', '#FF7A9E', '#9DE37D', '#C792EA'];
const BASE_DRAW_SECONDS = 1.2;
const CURVE_SAMPLES = 96;
const TAU = Math.PI * 2;

type LayerPlan = {shot: string; kind: string};

function clamp01(value: number): number {
  if (value < 0) {
    return 0;
  }
  if (value > 1) {
    return 1;
  }
  return value;
}

function parseLayers(visual_params: Record<string, unknown> | undefined): LayerPlan[] {
  const raw = visual_params?.['layers'];
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw
    .filter(
      (item): item is {shot: string; kind: string} =>
        !!item && typeof item === 'object' &&
        typeof (item as {shot?: unknown}).shot === 'string' &&
        typeof (item as {kind?: unknown}).kind === 'string',
    )
    .map((item) => ({shot: item.shot, kind: item.kind}));
}

function curvePath(
  cx: number,
  cy: number,
  span: number,
  amplitude: number,
  phase: number,
): string {
  const points: string[] = [];
  for (let i = 0; i <= CURVE_SAMPLES; i++) {
    const t = i / CURVE_SAMPLES;
    const x = cx - span / 2 + t * span;
    const y = cy - Math.sin(phase + t * Math.PI * 2) * amplitude;
    points.push(`${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`);
  }
  return points.join(' ');
}

const MathCanvas: React.FC<ComponentProps> = ({
  scene_shots,
  scene_shot_index,
  visual_params,
  width,
  height,
  fps,
}) => {
  const frame = useCurrentFrame();
  const now = frame / fps;
  const visits = scene_shots ?? [];
  const current = scene_shot_index ?? 0;
  const layers = parseLayers(visual_params);

  const cx = width / 2;
  const cy = height * 0.46;
  const r = Math.min(width, height) * 0.24;
  const span = Math.min(width * 0.86, r * 4.4);
  const amplitude = r; // 波幅 = 半径：波头与动点/纵轴点严格同高（投影前提）

  const windowById = new Map(visits.map((v) => [v.shot_id, v]));

  // θ 基准：正弦锚点窗口结束时 θ = 2π；锚点缺失时退化为最后一个窗口
  const sineAnchor = layers.find((l) => l.kind === 'sine');
  const refShot = sineAnchor
    ? windowById.get(sineAnchor.shot)
    : visits[visits.length - 1];
  const origin = visits.length > 0 ? visits[0].start : 0;
  const refActive = refShot ? Math.max(0.001, refShot.end - origin) : 1;

  // 累积活跃时间：起点到当前帧之间，落在各窗口内的部分求和
  // （切走的镜头不在窗口内 → 角度冻结；回场续转）
  let activeSeconds = 0;
  for (const visit of visits) {
    if (now <= visit.start) {
      break;
    }
    activeSeconds += Math.min(now, visit.end) - visit.start;
  }
  const theta = (activeSeconds / refActive) * TAU;
  const sweepSine = clamp01(theta / TAU);
  const sweepCos = clamp01((theta - TAU) / TAU);
  const dotX = cx + Math.cos(theta) * r;
  const dotY = cy - Math.sin(theta) * r;

  // 底座：坐标系 + 圆 + 动点 + 半径线（从第一个窗口起，始终在场）
  const baseDraw = visits.length > 0 ? clamp01((now - origin) / BASE_DRAW_SECONDS) : 1;
  const dotIn = clamp01((now - origin - BASE_DRAW_SECONDS) / 0.4);
  const base: React.ReactNode[] = [
    <line x1={0} y1={cy} x2={width} y2={cy} stroke={AXIS} strokeWidth={1.5} key="axH" />,
    <line x1={cx} y1={cy - r * 1.5} x2={cx} y2={cy + r * 1.5} stroke={AXIS} strokeWidth={1.5} key="axV" />,
    <circle
      key="circle"
      cx={cx}
      cy={cy}
      r={r}
      pathLength={1}
      strokeDasharray={1}
      strokeDashoffset={1 - baseDraw}
      fill="none"
      stroke={LAYER_COLORS[0]}
      strokeWidth={3}
    />,
  ];
  if (dotIn > 0) {
    base.push(
      <g key="orbit">
        <line
          x1={cx}
          y1={cy}
          x2={dotX}
          y2={dotY}
          stroke={LAYER_COLORS[0]}
          strokeWidth={2}
          opacity={0.8 * dotIn}
        />
        <circle
          cx={dotX}
          cy={dotY}
          r={8 * dotIn}
          fill={LAYER_COLORS[0]}
          opacity={dotIn}
        />
      </g>,
    );
  }

  // 图层：按声明锚点可见，描线进度由 θ 驱动
  const layerNodes: React.ReactNode[] = [];
  layers.forEach((layer, layerIndex) => {
    const anchor = windowById.get(layer.shot);
    if (!anchor || now < anchor.start) {
      return; // 锚点窗口未到（未知 shot 的锚点确定性跳过）
    }
    const color = LAYER_COLORS[(layerIndex + 1) % LAYER_COLORS.length];
    if (layer.kind === 'sine') {
      const sweep = sweepSine;
      layerNodes.push(
        <path
          key={`sine${layerIndex}`}
          d={curvePath(cx, cy, span, amplitude, 0)}
          pathLength={1}
          strokeDasharray={1}
          strokeDashoffset={1 - sweep}
          fill="none"
          stroke={color}
          strokeWidth={3}
          strokeLinecap="round"
        />,
      );
      if (sweep > 0 && sweep < 1) {
        const headX = cx - span / 2 + sweep * span;
        const headY = cy - Math.sin(sweep * TAU) * amplitude;
        layerNodes.push(
          <g key={`sineHead${layerIndex}`}>
            {/* 投影虚线：波头与动点严格同高 */}
            <line
              x1={dotX}
              y1={dotY}
              x2={headX}
              y2={dotY}
              stroke={color}
              strokeWidth={1.5}
              strokeDasharray="6 6"
              opacity={0.55}
            />
            <circle cx={headX} cy={headY} r={6} fill={color} />
          </g>,
        );
      }
    } else if (layer.kind === 'cosine') {
      const sweep = sweepCos;
      layerNodes.push(
        <path
          key={`cos${layerIndex}`}
          d={curvePath(cx, cy, span, amplitude, Math.PI / 2)}
          pathLength={1}
          strokeDasharray={1}
          strokeDashoffset={1 - sweep}
          fill="none"
          stroke={color}
          strokeWidth={3}
          strokeLinecap="round"
        />,
      );
      if (sweep > 0 && sweep < 1) {
        const headX = cx - span / 2 + sweep * span;
        const headY = cy - Math.sin(Math.PI / 2 + sweep * TAU) * amplitude;
        // 半径三角：圆心→垂足的横线段 = 点的水平位置（cos θ），
        // 其长度即波头高度；纵轴对应点到波头画投影虚线
        layerNodes.push(
          <g key={`cosProj${layerIndex}`}>
            <line
              x1={cx}
              y1={cy}
              x2={dotX}
              y2={cy}
              stroke={color}
              strokeWidth={2.5}
              opacity={0.7}
            />
            <circle cx={dotX} cy={cy} r={3.5} fill={color} opacity={0.9} />
            <line
              x1={cx}
              y1={headY}
              x2={headX}
              y2={headY}
              stroke={color}
              strokeWidth={1.5}
              strokeDasharray="6 6"
              opacity={0.55}
            />
            <circle cx={headX} cy={headY} r={6} fill={color} />
          </g>,
        );
      }
    }
    // 未知 kind：确定性跳过（组件词汇表外不猜）
  });
  void current; // 图层可见性由锚点决定；current 保留在 props 契约里

  const watermark = `math_canvas · visit ${current + 1}/${visits.length || 1}`;

  return (
    <div style={{position: 'absolute', inset: 0, backgroundColor: BACKGROUND}}>
      <svg width={width} height={height}>
        {base}
        {layerNodes}
      </svg>
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: height * 0.03,
          textAlign: 'center',
          color: LABEL,
          fontSize: 14,
          fontFamily: 'sans-serif',
        }}
      >
        {watermark}
      </div>
    </div>
  );
};

export default MathCanvas;
