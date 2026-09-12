import React from 'react';
import {useCurrentFrame} from 'remotion';
import type {ComponentProps} from '../../types';

// math_canvas@1.0.0 —— A8.1 场景画布试点组件（mount="scene"）。
// 对标 3b1b 的画面累积感：坐标系是底座，第一次访问画单位圆，第二次访问
// 叠加正弦曲线，第三次叠加余弦曲线，再往后每次访问在圆上补一条半径线。
// 关键语义：画面状态跨 shot 累积由组件从 scene_shots 时间线纯函数推导——
// 第 N 次访问的实例画出图层 0..N（每个图层在自己的访问窗口内画完并永久
// 保持），时间不连续、状态连续。
// 自带视觉（契约：不消费 pack token）；确定性：一切画面都是 props 与当前
// 帧的纯函数。

const BACKGROUND = '#0B0E14';
const AXIS = '#7C8798';
const TEXT = '#E8EDF4';
const LABEL = '#9AA7B8';
const LAYER_COLORS = ['#4FC3F7', '#FFB86C', '#FF7A9E', '#9DE37D', '#C792EA'];
const DRAW_SECONDS = 1.2;
// 曲线采样点数（确定性数值积分的近似，纯几何）
const CURVE_SAMPLES = 96;

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
  const amplitude = r * 0.92;

  const layers: React.ReactNode[] = [];
  for (let i = 0; i <= current; i++) {
    const visit = visits[i];
    const start = visit ? visit.start : 0;
    const progress = clamp01((now - start) / DRAW_SECONDS);
    const color = LAYER_COLORS[i % LAYER_COLORS.length];
    const drawProps = {
      pathLength: 1,
      strokeDasharray: 1,
      strokeDashoffset: 1 - progress,
      fill: 'none',
      stroke: color,
      strokeWidth: 3,
      strokeLinecap: 'round' as const,
    };
    if (i === 0) {
      layers.push(<circle key="layer0" cx={cx} cy={cy} r={r} {...drawProps} />);
    } else if (i === 1) {
      layers.push(
        <path
          key="layer1"
          d={curvePath(cx, cy, span, amplitude, 0)}
          {...drawProps}
        />,
      );
    } else if (i === 2) {
      layers.push(
        <path
          key="layer2"
          d={curvePath(cx, cy, span, amplitude, Math.PI / 2)}
          {...drawProps}
        />,
      );
    } else {
      const angle = ((i - 2) * Math.PI) / 4;
      const x = cx + Math.cos(angle) * r;
      const y = cy - Math.sin(angle) * r;
      layers.push(
        <g key={`layer${i}`}>
          <line x1={cx} y1={cy} x2={x} y2={y} {...drawProps} />
          <circle
            cx={x}
            cy={y}
            r={6 * progress}
            fill={color}
            stroke="none"
          />
        </g>,
      );
    }
  }

  // 当前访问的解说首句作为画布标签（跟着本次访问的窗口淡入）
  const visit = visits[current];
  const label = visit && visit.segments.length > 0 ? visit.segments[0].text : '';
  const labelStart = visit ? visit.start : 0;
  const labelOpacity = clamp01((now - labelStart) / 0.4);

  return (
    <div style={{position: 'absolute', inset: 0, backgroundColor: BACKGROUND}}>
      <svg width={width} height={height}>
        {/* 坐标系底座：从第一次访问起就在，不参与累积图层 */}
        <line x1={0} y1={cy} x2={width} y2={cy} stroke={AXIS} strokeWidth={1.5} />
        <line x1={cx} y1={cy - r * 1.5} x2={cx} y2={cy + r * 1.5} stroke={AXIS} strokeWidth={1.5} />
        {layers}
      </svg>
      {label ? (
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            bottom: height * 0.08,
            textAlign: 'center',
            color: TEXT,
            fontSize: 22,
            fontFamily: 'sans-serif',
            opacity: labelOpacity,
          }}
        >
          {label}
        </div>
      ) : null}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: height * 0.03,
          textAlign: 'center',
          color: LABEL,
          fontSize: 14,
          fontFamily: 'sans-serif',
        }}
      >
        {`math_canvas · visit ${current + 1}/${visits.length || 1}`}
      </div>
    </div>
  );
};

export default MathCanvas;
