import React from 'react';
import {useCurrentFrame} from 'remotion';
import type {ComponentProps} from '../../types';

// step_list@1.0.0 —— A8 首批表现组件：知识口播的步骤列表，逐条浮现。
// 每个 content 段 = 一步，在其可见窗口起点滑入 + 渐显，之后全程保持。
// 自带视觉（契约：不消费 pack token）：深板岩底 + 强调色编号圆点。
// 确定性：一切画面都是 props（segments 窗口）与当前帧的纯函数。

const BACKGROUND = '#101418';
const ACCENT = '#3DDC97';
const TEXT = '#F2F5F7';

const StepList: React.FC<ComponentProps> = ({segments, width, height, fps}) => {
  const frame = useCurrentFrame();
  const now = frame / fps;
  const steps = segments.filter((seg) => seg.segment_type === 'content');
  const left = Math.round(width * 0.12);
  const rowHeight = Math.round(height * 0.09);
  // 首行下移让位章节牌（header 恒画在组件之上，牌占左上带）
  const top = Math.round(height * 0.42);
  const appearSeconds = 0.4;

  return (
    <div style={{position: 'absolute', inset: 0, backgroundColor: BACKGROUND}}>
      {steps.map((step, index) => {
        const appear = now - step.start;
        if (appear < 0) {
          return null;
        }
        const progress = Math.min(1, appear / appearSeconds);
        return (
          <div
            key={step.segment_id}
            style={{
              position: 'absolute',
              left,
              top: top + index * rowHeight,
              opacity: progress,
              transform: `translateX(${(1 - progress) * 24}px)`,
              display: 'flex',
              alignItems: 'center',
              gap: 16,
            }}
          >
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: 22,
                backgroundColor: ACCENT,
                color: BACKGROUND,
                fontSize: 24,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontFamily: 'sans-serif',
              }}
            >
              {index + 1}
            </div>
            <div
              style={{
                color: TEXT,
                fontSize: 30,
                fontFamily: 'sans-serif',
                maxWidth: width - left - 80,
                whiteSpace: 'pre-wrap',
              }}
            >
              {step.text}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default StepList;
