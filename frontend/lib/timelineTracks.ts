import type { TrackKey } from '@/lib/trackControls';
import { resolveTrackHeight, type TrackHeightMap } from '@/lib/trackHeights';

export type TimelineTrackDef = {
  key: TrackKey;
  label: string;
  height: number;
  group?: 'video' | 'effect' | 'meta' | 'text' | 'audio';
  addLabel?: string;
};

/** 全部可选轨道（用户通过「添加轨道」按需启用） */
export const ALL_TRACK_LAYOUT: ReadonlyArray<TimelineTrackDef> = [
  { key: 'video', label: '主视频', height: 88, group: 'video', addLabel: '视频轨' },
  { key: 'overlay', label: '特效', height: 32, group: 'effect', addLabel: '特效轨' },
  { key: 'sticker', label: '贴纸', height: 32, group: 'effect', addLabel: '贴纸轨' },
  { key: 'video2', label: '画中画', height: 32, group: 'effect', addLabel: '画中画轨' },
  { key: 'filter', label: '滤镜', height: 26, group: 'meta', addLabel: '滤镜轨' },
  { key: 'transition', label: '转场', height: 26, group: 'meta', addLabel: '转场轨' },
  { key: 'adjust', label: '调节', height: 26, group: 'meta', addLabel: '调节轨' },
  { key: 'subtitle', label: '文本', height: 32, group: 'text', addLabel: '文本轨' },
  { key: 'audio', label: '音乐', height: 34, group: 'audio', addLabel: '音乐轨' },
  { key: 'audioVoice', label: '原声', height: 34, group: 'audio', addLabel: '原声轨' },
];

/** 默认仅展示主视频轨 */
export const DEFAULT_VISIBLE_TRACK_KEYS: TrackKey[] = ['video'];

const ORDER = ALL_TRACK_LAYOUT.map((t) => t.key);

export function sortTrackKeys(keys: TrackKey[]): TrackKey[] {
  const set = new Set(keys);
  return ORDER.filter((k) => set.has(k));
}

export function buildActiveTrackLayout(keys: TrackKey[], heights?: TrackHeightMap): TimelineTrackDef[] {
  const sorted = sortTrackKeys(keys);
  return ALL_TRACK_LAYOUT.filter((t) => sorted.includes(t.key)).map((t) => ({
    ...t,
    height: resolveTrackHeight(t.key, heights),
  }));
}

export function getAddableTracks(activeKeys: TrackKey[]): TimelineTrackDef[] {
  const set = new Set(activeKeys);
  return ALL_TRACK_LAYOUT.filter((t) => !set.has(t.key));
}

export function getTrackDef(key: TrackKey): TimelineTrackDef | undefined {
  return ALL_TRACK_LAYOUT.find((t) => t.key === key);
}
