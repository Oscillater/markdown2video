import React from 'react';
import {useCurrentFrame} from 'remotion';
import type {ComponentProps} from '../../types';

// math_canvas@1.1.1 —— A8.1 场景画布组件（mount="scene"）。
// 对标 3b1b 的核心语义：**波是点的高度投影**。动点从最右边出发逆时针转，
// 转到哪、正弦画到哪——波头始终在动点的高度上（描线期间画出水平投影
// 虚线）；余弦在第二圈描出（"向左挪四分之一圆"）。
// 角速度由 cue 表推导：动点在**正弦访问结束时恰好完成第一整圈**，于是
// "回到起点，曲线归零"与画面逐帧同步。切走的镜头角度冻结、回场续转
// （累积活跃时间，纯函数，确定性与状态连续兼得）。

const BACKGROUND = '#0B0E14';
const AXIS = '#7C8798';
const LABEL = '#9AA7B8';
const LAYER_COLORS = ['#4FC3F7', '#FFB86C', '#FF7A9E', '#9DE37D', '#C792EA'];
const BASE_DRAW_SECONDS = 1.2;
const CURVE_SAMPLES = 96;
const TAU = Math.PI * 2;

function clamp01(value: number): number {
  if (value < 0) {
    return 0;
  }
  if (value > 1) {
    return 1;
  }
  return value;
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
  width,
  height,
  fps,
}) => {
  const frame = useCurrentFrame();
  const now = frame / fps;
  const visits = scene_shots ?? [];
  const current = scene_shot_index ?? 0;

  const cx = width / 2;
  const cy = height * 0.46;
  const r = Math.min(width, height) * 0.24;
  const span = Math.min(width * 0.86, r * 4.4);
  const amplitude = r; // 波幅 = 半径：波头与动点严格同高（投影对齐的前提）

  // 动点角度：累积活跃时间（此前访问全额 + 当前访问内经过的时间），
  // 以「正弦访问结束时恰好 2π」为基准角速度
  const refIndex = Math.min(1, Math.max(0, visits.length - 1));
  let refActive = 0;
  for (let i = 0; i <= refIndex; i++) {
    const visit = visits[i];
    if (visit) {
      refActive += Math.max(0, visit.end - visit.start);
    }
  }
  let activeSeconds = 0;
  for (let i = 0; i < visits.length; i++) {
    const visit = visits[i];
    if (now <= visit.start) {
      break;
    }
    activeSeconds += Math.min(now, visit.end) - visit.start;
  }
  const theta = refActive > 0 ? (activeSeconds / refActive) * TAU : 0;
  const sweepSine = clamp01(theta / TAU);
  const sweepCos = clamp01((theta - TAU) / TAU);
  const dotX = cx + Math.cos(theta) * r;
  const dotY = cy - Math.sin(theta) * r;

  const layers: React.ReactNode[] = [];
  for (let i = 0; i <= current; i++) {
    const visit = visits[i];
    const start = visit ? visit.start : 0;
    const color = LAYER_COLORS[i % LAYER_COLORS.length];
    if (i === 0) {
      // 单位圆先画出，随后动点与半径线登场
      const progress = clamp01((now - start) / BASE_DRAW_SECONDS);
      layers.push(
        <circle
          key="layer0"
          cx={cx}
          cy={cy}
          r={r}
          pathLength={1}
          strokeDasharray={1}
          strokeDashoffset={1 - progress}
          fill="none"
          stroke={color}
          strokeWidth={3}
        />,
      );
      const dotProgress = clamp01((now - start - BASE_DRAW_SECONDS) / 0.4);
      if (dotProgress > 0) {
        const dotRadius = 8 * dotProgress;
        layers.push(
          <g key="orbit">
            <line
              x1={cx}
              y1={cy}
              x2={dotX}
              y2={dotY}
              stroke={color}
              strokeWidth={2}
              opacity={0.8 * dotProgress}
            />
            <circle cx={dotX} cy={dotY} r={dotRadius} fill={color} opacity={dotProgress} />
          </g>,
        );
      }
      continue;
    }
    if (i === 1 || i === 2) {
      // 波是点的高度投影：描线进度由动点角度驱动（正弦第一圈、余弦第二圈），
      // 描线期间正弦波头与动点严格同高，画出水平投影虚线（3b1b 标志画面）
      const sweep = i === 1 ? sweepSine : sweepCos;
      const phase = i === 1 ? 0 : Math.PI / 2;
      const drawProps = {
        pathLength: 1,
        strokeDasharray: 1,
        strokeDashoffset: 1 - sweep,
        fill: 'none',
        stroke: color,
        strokeWidth: 3,
        strokeLinecap: 'round' as const,
      };
      layers.push(
        <path
          key={`layer${i}`}
          d={curvePath(cx, cy, span, amplitude, phase)}
          {...drawProps}
        />,
      );
      if (sweep > 0 && sweep < 1) {
        const headX = cx - span / 2 + sweep * span;
        const headY =
          cy - Math.sin(phase + sweep * TAU) * amplitude;
        layers.push(
          <circle
            key={`head${i}`}
            cx={headX}
            cy={headY}
            r={6}
            fill={color}
          />,
        );
        if (i === 1) {
          layers.push(
            <line
              key={`guide${i}`}
              x1={dotX}
              y1={dotY}
              x2={headX}
              y2={dotY}
              stroke={color}
              strokeWidth={1.5}
              strokeDasharray="6 6"
              opacity={0.55}
            />,
          );
        }
      }
      continue;
    }
    // 更晚的访问：圆上按 45° 步进补半径线（词汇表扩展位）
    const visitStart = start;
    const progress = clamp01((now - visitStart) / BASE_DRAW_SECONDS);
    const angle = ((i - 2) * Math.PI) / 4;
    const x = cx + Math.cos(angle) * r;
    const y = cy - Math.sin(angle) * r;
    layers.push(
      <g key={`layer${i}`}>
        <line
          x1={cx}
          y1={cy}
          x2={x}
          y2={y}
          pathLength={1}
          strokeDasharray={1}
          strokeDashoffset={1 - progress}
          stroke={color}
          strokeWidth={3}
          strokeLinecap="round"
        />
        <circle cx={x} cy={y} r={6 * progress} fill={color} stroke="none" />
      </g>,
    );
  }

  // 知识区格式：文字归烧录字幕，画布不再渲染解说标签（v1.0.1）
  const watermark = `math_canvas · visit ${current + 1}/${visits.length || 1}`;

  return (
    <div style={{position: 'absolute', inset: 0, backgroundColor: BACKGROUND}}>
      <svg width={width} height={height}>
        {/* 坐标系底座：从第一次访问起就在，不参与累积图层 */}
        <line x1={0} y1={cy} x2={width} y2={cy} stroke={AXIS} strokeWidth={1.5} />
        <line x1={cx} y1={cy - r * 1.5} x2={cx} y2={cy + r * 1.5} stroke={AXIS} strokeWidth={1.5} />
        {layers}
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
