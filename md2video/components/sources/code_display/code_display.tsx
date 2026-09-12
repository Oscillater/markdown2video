import React from 'react';
import {useCurrentFrame} from 'remotion';
import type {ComponentProps} from '../../types';

// code_display@1.0.0 —— A8 首批表现组件：代码展示（技术向核心卖点）。
// 每个 content 段 = 一行代码，在其可见窗口起点渐显，之后全程保持。
// 自带视觉（契约：不消费 pack token）：GitHub-dark 风格编辑器面板 +
// 红绿灯窗口条 + 行号 + 极简语法着色。
// 确定性：着色是纯词法扫描（无高亮库、无随机），一切画面都是 props
// 与当前帧的纯函数。行数超出画面高度时截断（v1 不做滚动，行数由
// plan 作者控制）。

const BACKGROUND = '#0D1117';
const BAR = '#161B22';
const PLAIN = '#C9D1D9';
const KEYWORD = '#FF7B72';
const STRING = '#A5D6FF';
const NUMBER = '#79C0FF';
const COMMENT = '#8B949E';
const GUTTER = '#6E7681';
const DOT_COLORS = ['#FF5F57', '#FEBC2E', '#28C840'];

const KEYWORDS = new Set([
  'def', 'return', 'import', 'from', 'class', 'if', 'elif', 'else',
  'for', 'while', 'with', 'as', 'pass', 'lambda', 'yield', 'try',
  'except', 'finally', 'raise', 'not', 'in', 'is', 'and', 'or', 'None', 'True', 'False',
]);

type Token = {text: string; color: string};

function tokenizeLine(line: string): Token[] {
  const tokens: Token[] = [];
  const push = (text: string, color: string) => {
    if (text) {
      tokens.push({text, color});
    }
  };
  let i = 0;
  while (i < line.length) {
    const ch = line[i];
    if (ch === '#') {
      push(line.slice(i), COMMENT);
      break;
    }
    if (ch === '"' || ch === "'") {
      let j = i + 1;
      while (j < line.length && line[j] !== ch) {
        j++;
      }
      j = Math.min(j + 1, line.length);
      push(line.slice(i, j), STRING);
      i = j;
      continue;
    }
    if (/[0-9]/.test(ch)) {
      let j = i;
      while (j < line.length && /[0-9._]/.test(line[j])) {
        j++;
      }
      push(line.slice(i, j), NUMBER);
      i = j;
      continue;
    }
    if (/[A-Za-z_]/.test(ch)) {
      let j = i;
      while (j < line.length && /[A-Za-z0-9_]/.test(line[j])) {
        j++;
      }
      const word = line.slice(i, j);
      push(word, KEYWORDS.has(word) ? KEYWORD : PLAIN);
      i = j;
      continue;
    }
    let j = i;
    while (j < line.length && !/[A-Za-z0-9_"'#]/.test(line[j])) {
      j++;
    }
    push(line.slice(i, j), PLAIN);
    i = j;
  }
  return tokens;
}

const CodeDisplay: React.FC<ComponentProps> = ({segments, width, height, fps}) => {
  const frame = useCurrentFrame();
  const now = frame / fps;
  const lines = segments.filter((seg) => seg.segment_type === 'content');
  const barHeight = Math.round(height * 0.06);
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
          paddingLeft: 16,
          gap: 8,
        }}
      >
        {DOT_COLORS.map((color) => (
          <div
            key={color}
            style={{width: 12, height: 12, borderRadius: 6, backgroundColor: color}}
          />
        ))}
      </div>
      {lines.map((line, index) => {
        const appear = now - line.start;
        if (appear < 0) {
          return null;
        }
        const opacity = Math.min(1, appear / appearSeconds);
        return (
          <div
            key={line.segment_id}
            style={{
              position: 'absolute',
              top: barHeight + 24 + index * lineHeight,
              left: 0,
              right: 0,
              display: 'flex',
              opacity,
              fontFamily: 'Consolas, Menlo, monospace',
              fontSize,
            }}
          >
            <div
              style={{
                width: Math.round(width * 0.1),
                textAlign: 'right',
                paddingRight: 14,
                color: GUTTER,
              }}
            >
              {index + 1}
            </div>
            <div style={{color: PLAIN, whiteSpace: 'pre-wrap'}}>
              {tokenizeLine(line.text).map((token, tokenIndex) => (
                <span key={tokenIndex} style={{color: token.color}}>
                  {token.text}
                </span>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default CodeDisplay;
