import {Config} from '@remotion/cli/config';

// md2video Remotion 后端渲染配置：画布/时长由 schedule props 经
// calculateMetadata 动态决定；这里只固定输出行为。
Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
