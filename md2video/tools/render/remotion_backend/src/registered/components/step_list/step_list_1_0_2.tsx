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
  // 首行下移让位章节牌（header 恒画在组件之上，牌占左上带）
  const top = Math.round(height * 0.42);
  const appearSeconds = 0.4;

  // 行距按换行行数动态累计：固定行距会让两行文本与下一步重叠
  const textWidth = width - left - 80;
  const fontSize = 30;
  const charsPerLine = Math.max(4, Math.floor(textWidth / fontSize));
  const lineHeight = Math.round(fontSize * 1.5);
  const stepGap = Math.round(height * 0.035);
  let cursor = top;
  const rows = steps.map((step) => {
    const lines = Math.max(1, Math.ceil(step.text.length / charsPerLine));
    const y = cursor;
    cursor += lines * lineHeight + stepGap;
    return {step, y};
  });

  return (
    <div style={{position: 'absolute', inset: 0, backgroundColor: BACKGROUND}}>
      {rows.map(({step, y}, index) => {
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
              top: y,
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
