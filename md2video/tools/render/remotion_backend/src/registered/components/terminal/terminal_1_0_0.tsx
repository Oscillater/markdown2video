import React from 'react';
import {useCurrentFrame} from 'remotion';
import type {ComponentProps} from '../../types';

// terminal@1.0.0 —— A8 首批表现组件：终端黑窗口（技术向）。
// 每个 content 段 = 一行终端内容：以 "$" 开头的段视作命令（绿色提示符 +
// 白色命令文字），其余为输出行（浅灰、缩进）。行在其可见窗口起点渐显，
// 之后全程保持。
// 自带视觉（契约：不消费 pack token）；确定性：一切画面都是 props 与
// 当前帧的纯函数。行数超出画面高度时截断（v1 不做滚动）。

const BACKGROUND = '#0C0C0C';
const BAR = '#1F1F1F';
const BAR_TEXT = '#9A9A9A';
const PROMPT = '#4EC9B0';
const COMMAND = '#F2F2F2';
const OUTPUT = '#B8B8B8';

const Terminal: React.FC<ComponentProps> = ({segments, width, height, fps}) => {
  const frame = useCurrentFrame();
  const now = frame / fps;
  const lines = segments.filter((seg) => seg.segment_type === 'content');
  const barHeight = Math.round(height * 0.05);
  const fontSize = Math.round(width * 0.055);
  const lineHeight = Math.round(fontSize * 1.8);
  const appearSeconds = 0.3;

  return (
    <div style={{position: 'absolute', inset: 0, backgroundColor: BACKGROUND}}>
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: barHeight,
          backgroundColor: BAR,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <div style={{color: BAR_TEXT, fontSize: Math.round(barHeight * 0.5), fontFamily: 'sans-serif'}}>
          terminal
        </div>
      </div>
      {lines.map((line, index) => {
        const appear = now - line.start;
        if (appear < 0) {
          return null;
        }
        const opacity = Math.min(1, appear / appearSeconds);
        const isCommand = line.text.startsWith('$');
        const text = isCommand ? line.text.slice(1).trimStart() : line.text;
        return (
          <div
            key={line.segment_id}
            style={{
              position: 'absolute',
              top: barHeight + 24 + index * lineHeight,
              left: Math.round(width * 0.07),
              right: Math.round(width * 0.07),
              opacity,
              fontFamily: 'Consolas, Menlo, monospace',
              fontSize,
              whiteSpace: 'pre-wrap',
            }}
          >
            {isCommand ? (
              <>
                <span style={{color: PROMPT}}>$ </span>
                <span style={{color: COMMAND}}>{text}</span>
              </>
            ) : (
              <span style={{color: OUTPUT}}>{text}</span>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default Terminal;
