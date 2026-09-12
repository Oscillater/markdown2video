import type {SegmentSlot} from '../Md2Video';

// A8 表现组件契约（见 md2video/components/registry.py 与 TODO.md「A8」）：
// 输入 = 文字 + 每段可见窗口 + 画布尺寸；输出 = 自由画面——配色/字体/
// 排版/动效由组件自带，不消费 pack token。
// 两条底线：不改时间事实（窗口是调度器按音频事实裁决的，音频绑定留在
// wrapper）；确定性渲染（禁 random/网络/fs，check-component 双跑逐帧
// 一致验证）。
// 时间语义：start/end 为全片绝对秒；组件内 useCurrentFrame() 也是绝对帧。
export type ComponentProps = {
  component: string; // 本组件 ref（id@version）
  shot_id: string;
  scene_id: string;
  width: number;
  height: number;
  fps: number;
  segments: SegmentSlot[]; // 本 shot 的正文段（标题段与 section_header 不在其中）
  // A8.1 场景画布（mount="scene" 的组件才有）：本场全部 shot 的起止与
  // 正文段（按调度顺序 = 时间顺序；同场 shot 散开也按 scene_id 收拢在此）
  // + 自己排第几。画面状态跨 shot 累积由组件从这份时间线纯函数推导。
  scene_shots?: SceneShotSlot[];
  scene_shot_index?: number;
};

// 场景画布时间线里的一个 shot（本场某次「访问」的窗口与正文段）
export type SceneShotSlot = {
  shot_id: string;
  start: number;
  end: number;
  segments: SegmentSlot[];
};
