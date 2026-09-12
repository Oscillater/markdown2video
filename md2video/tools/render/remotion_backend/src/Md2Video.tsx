import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

// md2video Remotion 后端 composition（A6 后半）。
// 输入：Python 调度器（remotion_schedule.py）产出的确定性 schedule props。
// 职责边界：这里只按 schedule 逐帧执行可见窗口、动效原语与音频绑定；
// 不做时间决策（时间是调度器从音频事实 + pack 节奏推导出的事实）。

export type SegmentSlot = {
  segment_id: string;
  segment_type: string;
  text: string;
  start: number;
  end: number;
  audio_path: string;
  shot_id: string;
  scene_id: string;
};

export type ShotSlot = {
  shot_id: string;
  scene_id: string;
  segment_ids: string[];
  layout_type: string;
  start: number;
  end: number;
  regions: Record<string, [number, number, number, number]>;
  has_image_region: boolean;
  segments: SegmentSlot[];
};

export type StylePayload = {
  id: string;
  palette: {background: string; text: string; secondary: string; accent: string};
  typography: {
    font_family: string;
    sizes_px: {
      title_main: number;
      title_sub: number;
      section_header: number;
      section_header_detail: number;
      body: number;
    };
  };
  motion: {
    title_reveal: string;
    section_reveal: string;
    body_reveal: string;
    body_dismiss: string;
    section_dismiss: string;
    motif_transition_duration: number;
  };
  motif: {kind: string};
};

// 组件的 props 就是调度器产出的 schedule dict 本体（CLI --props 直传）。
export type Schedule = {
  version: string;
  fps: number;
  width: number;
  height: number;
  duration: number;
  style: StylePayload;
  shots: ShotSlot[];
  title: {
    layout_type: string;
    regions: Record<string, [number, number, number, number]>;
    segments: SegmentSlot[];
  } | null;
  timeline: unknown;
};

const TITLE_REGION_PREFERENCE = ['title', 'body', 'text', 'caption'];
const BODY_REGION_PREFERENCE = ['body', 'text', 'caption'];
const STACK_REGION_NAME = 'section_stack';

// 动效在可见窗口内完成（与调度器的“动效不消耗时间窗口”语义一致）。
const REVEAL_SECONDS = 0.4;
const DISMISS_SECONDS = 0.4;
const TYPEWRITER_MAX_SECONDS = 1.2;

function regionRect(
  regions: Record<string, [number, number, number, number]>,
  preference: string[],
): [number, number, number, number] | null {
  for (const name of preference) {
    if (regions[name]) {
      return regions[name];
    }
  }
  return null;
}

function revealStyle(
  intent: string,
  localSeconds: number,
  textLength: number,
): {opacity: number; visibleChars: number | null} {
  if (intent === 'appear' || localSeconds <= 0) {
    return {opacity: 1, visibleChars: null};
  }
  if (intent === 'fade') {
    const opacity = interpolate(localSeconds, [0, REVEAL_SECONDS], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    return {opacity, visibleChars: null};
  }
  // write → typewriter（逐字显现，manim Write 意图的 web 对应物）
  const duration = Math.min(
    TYPEWRITER_MAX_SECONDS,
    Math.max(REVEAL_SECONDS, textLength * 0.05),
  );
  const progress = interpolate(localSeconds, [0, duration], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return {opacity: 1, visibleChars: Math.ceil(progress * textLength)};
}

function dismissStyle(
  intent: string,
  secondsLeft: number,
): {opacity: number} {
  if (intent !== 'fade' || secondsLeft > DISMISS_SECONDS) {
    return {opacity: 1};
  }
  const opacity = interpolate(secondsLeft, [0, DISMISS_SECONDS], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return {opacity};
}

const OrbitDots: React.FC<{style: StylePayload}> = ({style}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  if (!style.motif.kind) {
    return null;
  }
  const period = Math.max(1, style.motion.motif_transition_duration) * fps;
  const angle = ((frame % period) / period) * Math.PI * 2;
  const radius = 42;
  const cx = style.palette.accent;
  const dots = [0, Math.PI].map((offset, index) => {
    const a = angle + offset;
    return {
      key: index,
      left: 60 + Math.cos(a) * radius,
      top: style.typography.sizes_px.body * 4 + Math.sin(a) * (radius / 3),
      color: index === 0 ? style.palette.text : style.palette.accent,
      size: index === 0 ? 10 : 7,
    };
  });
  return (
    <div style={{position: 'absolute', left: 0, top: 0, width: '100%', height: '100%'}}>
      {dots.map((dot) => (
        <div
          key={dot.key}
          style={{
            position: 'absolute',
            left: dot.left,
            top: dot.top,
            width: dot.size,
            height: dot.size,
            borderRadius: dot.size / 2,
            backgroundColor: dot.color,
            opacity: 0.85,
          }}
        />
      ))}
    </div>
  );
};

const SegmentedText: React.FC<{
  text: string;
  intent: string;
  dismissIntent: string;
  windowStart: number;
  windowEnd: number;
  fontFamily: string;
  fontSize: number;
  color: string;
  maxWidth: number | null;
  align: 'left' | 'center';
}> = ({
  text,
  intent,
  dismissIntent,
  windowStart,
  windowEnd,
  fontFamily,
  fontSize,
  color,
  maxWidth,
  align,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const now = frame / fps;
  const reveal = revealStyle(intent, now - windowStart, text.length);
  const dismiss = dismissStyle(dismissIntent, windowEnd - now);
  const visible =
    reveal.visibleChars === null ? text : text.slice(0, reveal.visibleChars);
  const boxStyle: React.CSSProperties = {
    fontFamily,
    fontSize,
    color,
    lineHeight: 1.5,
    whiteSpace: 'pre-wrap',
    opacity: reveal.opacity * dismiss.opacity,
    textAlign: align,
  };
  if (maxWidth !== null) {
    boxStyle.maxWidth = maxWidth;
  }
  return <div style={boxStyle}>{visible}</div>;
};

export const Md2Video: React.FC<Schedule> = (schedule) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const now = frame / fps;
  const style = schedule.style;
  const titlePayload = schedule.title;

  // 标题卡片：标题 pass 的文本全程可见（与 manim 语义一致）
  const titleMain = titlePayload?.segments.find(
    (s) => s.segment_type === 'title_main',
  );
  const titleSub = titlePayload?.segments.find(
    (s) => s.segment_type === 'title_sub',
  );
  const titleRegions = titlePayload?.regions ?? {};
  const titleRect = regionRect(titleRegions, TITLE_REGION_PREFERENCE);

  // section headers：按窗口起点排序，堆叠在 section_stack（回退 body）区域
  const headers: {seg: SegmentSlot; slotIndex: number}[] = [];
  for (const shot of schedule.shots) {
    for (const seg of shot.segments) {
      if (seg.segment_type === 'section_header') {
        headers.push({seg, slotIndex: headers.length});
      }
    }
  }
  headers.sort((a, b) => a.seg.start - b.seg.start);

  const visibleHeaders = headers.filter(
    ({seg}) => now >= seg.start && now <= seg.end,
  );

  return (
    <AbsoluteFill style={{backgroundColor: style.palette.background}}>
      <OrbitDots style={style} />

      {titleMain || titleSub ? (
        <div
          style={{
            position: 'absolute',
            left: titleRect ? titleRect[0] : 0,
            top: titleRect ? titleRect[1] : 0,
            width: titleRect ? titleRect[2] : '100%',
            height: titleRect ? titleRect[3] : '100%',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 12,
          }}
        >
          {titleMain ? (
            <SegmentedText
              text={titleMain.text}
              intent={style.motion.title_reveal}
              dismissIntent="instant"
              windowStart={titleMain.start}
              windowEnd={schedule.duration}
              fontFamily={style.typography.font_family}
              fontSize={style.typography.sizes_px.title_main}
              color={style.palette.text}
              maxWidth={titleRect ? titleRect[2] : null}
              align="center"
            />
          ) : null}
          {titleSub ? (
            <SegmentedText
              text={titleSub.text}
              intent={style.motion.title_reveal}
              dismissIntent="instant"
              windowStart={titleSub.start}
              windowEnd={schedule.duration}
              fontFamily={style.typography.font_family}
              fontSize={style.typography.sizes_px.title_sub}
              color={style.palette.text}
              maxWidth={titleRect ? titleRect[2] : null}
              align="center"
            />
          ) : null}
        </div>
      ) : null}

      {/* 正文：content/appendix 逐段按可见窗口渲染 */}
      {schedule.shots.map((shot) =>
        shot.segments
          .filter((seg) => seg.segment_type !== 'section_header')
          .map((seg) => {
            if (now < seg.start || now > seg.end) {
              return null;
            }
            const rect = regionRect(shot.regions, BODY_REGION_PREFERENCE);
            const left = rect ? rect[0] : 0;
            const top = rect ? rect[1] : 0;
            const width = rect ? rect[2] : schedule.width;
            const height = rect ? rect[3] : schedule.height;
            return (
              <div
                key={`${shot.shot_id}:${seg.segment_id}`}
                style={{
                  position: 'absolute',
                  left,
                  top,
                  width,
                  height,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <SegmentedText
                  text={seg.text}
                  intent={style.motion.body_reveal}
                  dismissIntent={style.motion.body_dismiss}
                  windowStart={seg.start}
                  windowEnd={seg.end}
                  fontFamily={style.typography.font_family}
                  fontSize={style.typography.sizes_px.body}
                  color={style.palette.text}
                  maxWidth={width}
                  align="center"
                />
              </div>
            );
          }),
      )}

      {/* section header 堆叠字幕 */}
      {(() => {
        if (visibleHeaders.length === 0) {
          return null;
        }
        const first = visibleHeaders[0].seg;
        const ownerShot =
          schedule.shots.find((shot) => shot.shot_id === first.shot_id) ?? null;
        const regions = ownerShot?.regions ?? {};
        const stackRect =
          regions[STACK_REGION_NAME] ?? regionRect(regions, BODY_REGION_PREFERENCE);
        const left = stackRect ? stackRect[0] : 24;
        const top = stackRect ? stackRect[1] : 24;
        const width = stackRect ? stackRect[2] : schedule.width - 48;
        return (
          <div
            style={{
              position: 'absolute',
              left,
              top,
              width,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'flex-start',
              gap: 8,
            }}
          >
            {visibleHeaders.map(({seg}) => (
              <div key={seg.segment_id} style={{maxWidth: '100%'}}>
                <SegmentedText
                  text={seg.text}
                  intent={style.motion.section_reveal}
                  dismissIntent={style.motion.section_dismiss}
                  windowStart={seg.start}
                  windowEnd={seg.end}
                  fontFamily={style.typography.font_family}
                  fontSize={style.typography.sizes_px.section_header}
                  color={style.palette.text}
                  maxWidth={width}
                  align="left"
                />
              </div>
            ))}
          </div>
        );
      })()}

      {/* 音频绑定：每段一个 Audio 序列，起点 = 调度窗口起点 */}
      {schedule.shots.map((shot) =>
        shot.segments
          .filter((seg) => seg.audio_path)
          .map((seg) => (
            <Sequence
              key={`audio:${seg.segment_id}`}
              from={Math.round(seg.start * fps)}
              durationInFrames={Math.max(
                1,
                Math.round((seg.end - seg.start) * fps),
              )}
            >
              <Audio src={staticFile(seg.audio_path)} />
            </Sequence>
          )),
      )}
    </AbsoluteFill>
  );
};
