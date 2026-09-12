import React from 'react';
import {Composition} from 'remotion';
import {Md2Video, type Schedule} from './Md2Video';

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="Md2VideoMain"
      component={Md2Video}
      durationInFrames={1}
      fps={30}
      width={480}
      height={854}
      defaultProps={{
        version: 'remotion.v1',
        fps: 30,
        width: 480,
        height: 854,
        duration: 0,
        style: {
          id: '',
          palette: {background: '#000000', text: '#FFFFFF', secondary: '#FFFFFF', accent: '#FFFFFF'},
          typography: {
            font_family: 'sans-serif',
            sizes_px: {
              title_main: 40,
              title_sub: 30,
              section_header: 20,
              section_header_detail: 12,
              body: 15,
            },
          },
          motion: {
            title_reveal: 'appear',
            section_reveal: 'appear',
            body_reveal: 'appear',
            body_dismiss: 'instant',
            section_dismiss: 'instant',
            motif_transition_duration: 1.0,
          },
          motif: {kind: ''},
        },
        shots: [],
        title: null,
        timeline: {text: [], markers: [], shots: []},
      } as Schedule}
      calculateMetadata={({props}) => ({
        durationInFrames: Math.max(1, Math.round(props.duration * props.fps)),
        fps: props.fps,
        width: props.width,
        height: props.height,
      })}
    />
  );
};
