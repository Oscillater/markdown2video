import React from 'react';
import {useCurrentFrame} from 'remotion';
import type {ComponentProps} from '../../types';

// math_canvas@1.3.0 —— A8.1 场景画布组件（mount="scene"）。
// 对标 3b1b 的核心语义：**波是点的高度投影**，且**动画跨 shot 连续**。
//
// 章节化角度（1.3.0 的核心）：动点"一章转一圈"——
//   章节 0：场起点 → 第一个波层锚点（底座章，只有圆和动点）
//   章节 k：第 k 波层锚点 → 下一锚点（或场尾），该波的整条曲线只在
//   自己的章节内随动点描出（描满永久保持）
// 章边界恰好是切镜点，动点在边界上恰好回到最右（cos 2π = cos 0）→
// 跨 shot 无跳变；章内多 shot 之间 θ 连续。描线与解说天然同步：
// 波只在用它解说的章节里生长。
//
// 图层编排是 plan 作者的数据（visual_params.layers），组件不猜：
//   "layers": [{"shot": "shot_005", "kind": "sine"},
//              {"shot": "shot_007", "kind": "cosine"}]
// 投影构造：正弦——波头与动点严格同高（水平投影虚线）；余弦——半径
// 三角（圆心→垂足横线段 = 点的水平位置，纵轴对应点到波头投影虚线）。
// 角度由累积活跃时间驱动（切走冻结/回场续转，纯函数，确定性不变）。
// 未声明 layers 时只画底座，确定性降级。

const BACKGROUND = '#0B0E14';
const AXIS = '#7C8798';
const LABEL = '#9AA7B8';
const LAYER_COLORS = ['#4FC3F7', '#FFB86C', '#FF7A9E', '#9DE37D', '#C792EA'];
const BASE_DRAW_SECONDS = 1.2;
const CURVE_SAMPLES = 96;
const TAU = Math.PI * 2;

type LayerPlan = {shot: string; kind: string};
type Window = {shot_id: string; start: number; end: number; segments: unknown[]};

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

// 竖排余弦：从 (cx, topY) 垂直向下，横向摆动 = cos(s·2π)·amplitude。
// 余弦是点的横坐标，只有竖排波头的横偏移才与动点的横偏移严格相等——
// 连接两者的引导线是垂直的，构造无需观众做任何心理旋转。
function verticalCosPath(
  cx: number,
  topY: number,
  length: number,
  amplitude: number,
): string {
  const points: string[] = [];
  for (let i = 0; i <= CURVE_SAMPLES; i++) {
    const t = i / CURVE_SAMPLES;
    const x = cx + Math.cos(t * Math.PI * 2) * amplitude;
    const y = topY + t * length;
    points.push(`${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`);
  }
  return points.join(' ');
}

const MathCanvas: React.FC<ComponentProps> = ({
  scene_shots,
  visual_params,
  width,
  height,
  fps,
}) => {
  const frame = useCurrentFrame();
  const now = frame / fps;
  const visits = scene_shots ?? [];
  const layers = parseLayers(visual_params).filter(
    (l) => l.kind === 'sine' || l.kind === 'cosine',
  );

  const cx = width / 2;
  const cy = height * 0.46;
  const r = Math.min(width, height) * 0.24;
  const span = Math.min(width * 0.86, r * 4.4);
  const amplitude = r; // 波幅 = 半径：波头与投影点严格同高（投影前提）

  const windowById = new Map(visits.map((v) => [v.shot_id, v]));
  const lastEnd = visits.length > 0 ? visits[visits.length - 1].end : 0;
  const origin = visits.length > 0 ? visits[0].start : 0;

  // 活跃时间：起点到 wall 之间落在各窗口内的部分（切走冻结的语义）
  const activeAt = (wall: number): number => {
    let acc = 0;
    for (const visit of visits) {
      if (wall <= visit.start) {
        break;
      }
      acc += Math.min(wall, visit.end) - visit.start;
    }
    return acc;
  };

  // 章节：[origin→锚点1][锚点1→锚点2]…[锚点n→场尾]，一章一圈
  const waveAnchors = layers
    .map((l) => ({...l, win: windowById.get(l.shot)}))
    .filter((l): l is LayerPlan & {win: Window} => !!l.win)
    .sort((a, b) => a.win.start - b.win.start);
  const boundsWall = [origin, ...waveAnchors.map((l) => l.win.start), lastEnd];
  const boundsActive = boundsWall.map(activeAt);

  const tActive = activeAt(now);
  let chapterIndex = 0;
  for (let i = 0; i < boundsActive.length - 1; i++) {
    if (tActive >= boundsActive[i]) {
      chapterIndex = i;
    }
  }
  const chapterStart = boundsActive[chapterIndex];
  const chapterEnd = boundsActive[chapterIndex + 1] ?? chapterStart + 1;
  const chapterProgress = clamp01(
    (tActive - chapterStart) / Math.max(0.001, chapterEnd - chapterStart),
  );
  const theta = TAU * (chapterIndex + chapterProgress);
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
        <circle cx={dotX} cy={dotY} r={8 * dotIn} fill={LAYER_COLORS[0]} opacity={dotIn} />
      </g>,
    );
  }

  // 波层：第 j 个波层占据章节 j+1，描线进度 = 该章节进度；章末描满保持
  const layerNodes: React.ReactNode[] = [];
  waveAnchors.forEach((wave, j) => {
    const lapStart = boundsActive[j + 1];
    const lapEnd = boundsActive[j + 2] ?? lapStart + 1;
    if (tActive < lapStart) {
      return; // 章节未到
    }
    const sweep = clamp01((tActive - lapStart) / Math.max(0.001, lapEnd - lapStart));
    const color = LAYER_COLORS[(j + 1) % LAYER_COLORS.length];
    // 聚焦降杂：已描满的历史波层降到低亮度，当前正在描的波层满亮度
    const dimmed = sweep >= 1;

    if (wave.kind === 'sine') {
      // 正弦 = 点的高度 → 横排波，波头与动点严格同高（水平投影虚线）
      layerNodes.push(
        <path
          key={`wave${j}`}
          d={curvePath(cx, cy, span, amplitude, 0)}
          pathLength={1}
          strokeDasharray={1}
          strokeDashoffset={1 - sweep}
          fill="none"
          stroke={color}
          strokeWidth={3}
          strokeLinecap="round"
          opacity={dimmed ? 0.3 : 1}
        />,
      );
      if (sweep > 0 && sweep < 1) {
        const headX = cx - span / 2 + sweep * span;
        const headY = cy - Math.sin(sweep * TAU) * amplitude;
        layerNodes.push(
          <g key={`head${j}`}>
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
      return;
    }

    if (wave.kind === 'cosine') {
      // 余弦 = 点的水平位置 → 波竖排：从圆心高度垂直向下，横向摆动与
      // 动点同步（headX ≡ dotX），垂直投影虚线连接两者——点的横偏移
      // 直接就是下方波的左右摆动，零心理旋转（3b1b 原始构造）
      const waveLength = r * 2.3;
      const topY = cy;
      const headX = cx + Math.cos(sweep * TAU) * amplitude;
      const headY = topY + sweep * waveLength;
      layerNodes.push(
        <path
          key={`vcos${j}`}
          d={verticalCosPath(cx, topY, waveLength, amplitude)}
          pathLength={1}
          strokeDasharray={1}
          strokeDashoffset={1 - sweep}
          fill="none"
          stroke={color}
          strokeWidth={3}
          strokeLinecap="round"
          opacity={dimmed ? 0.3 : 1}
        />,
      );
      if (sweep > 0 && sweep < 1) {
        layerNodes.push(
          <g key={`cosGuide${j}`}>
            <line
              x1={dotX}
              y1={dotY}
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
      return;
    }
  });

  const chapterCount = Math.max(1, boundsWall.length - 1);
  // P0 水印退场：组件 id 不进成片（调试信息感）；章节指示改纯数字牌
  const chapterBadge = `${chapterIndex + 1} / ${chapterCount}`;

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
          letterSpacing: 2,
        }}
      >
        {chapterBadge}
      </div>
    </div>
  );
};

export default MathCanvas;
