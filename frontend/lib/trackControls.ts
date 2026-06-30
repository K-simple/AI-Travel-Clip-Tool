export type TrackKey =
  | 'video'
  | 'overlay'
  | 'sticker'
  | 'video2'
  | 'filter'
  | 'transition'
  | 'adjust'
  | 'subtitle'
  | 'ttsVoice'
  | 'audio'
  | 'audioVoice';

export type TrackControls = {
  locked: boolean;
  visible: boolean;
  muted: boolean;
  solo: boolean;
};

export const TRACK_KEYS: TrackKey[] = [
  'video',
  'overlay',
  'sticker',
  'video2',
  'filter',
  'transition',
  'adjust',
  'subtitle',
  'ttsVoice',
  'audio',
  'audioVoice',
];

export const TRACK_LABELS: Record<TrackKey, string> = {
  video: '主视频',
  overlay: '特效',
  sticker: '贴纸',
  video2: '画中画',
  filter: '滤镜',
  transition: '转场',
  adjust: '调节',
  subtitle: '字幕',
  ttsVoice: 'AI人声',
  audio: '音乐',
  audioVoice: '原声',
};

const defaultCtrl = (): TrackControls => ({
  locked: false,
  visible: true,
  muted: false,
  solo: false,
});

export const DEFAULT_TRACK_CONTROLS: Record<TrackKey, TrackControls> = Object.fromEntries(
  TRACK_KEYS.map((key) => [key, defaultCtrl()])
) as Record<TrackKey, TrackControls>;

export function hasActiveSolo(controls: Record<TrackKey, TrackControls>): boolean {
  return TRACK_KEYS.some((key) => controls[key].solo);
}

export function isTrackContentVisible(
  controls: Record<TrackKey, TrackControls>,
  key: TrackKey
): boolean {
  const ctrl = controls[key];
  if (!ctrl.visible) return false;
  if (hasActiveSolo(controls)) return ctrl.solo;
  return true;
}

export function isTrackLocked(controls: Record<TrackKey, TrackControls>, key: TrackKey): boolean {
  return controls[key].locked;
}

export function isTrackMuted(controls: Record<TrackKey, TrackControls>, key: TrackKey): boolean {
  return controls[key].muted;
}

export type PreviewMix = {
  showVideo: boolean;
  showSubtitle: boolean;
  showOverlay: boolean;
  showVideo2: boolean;
  showSticker: boolean;
  showFilter: boolean;
  showTransition: boolean;
  showAdjust: boolean;
  videoAudible: boolean;
  audioAudible: boolean;
  mutePreviewAudio: boolean;
};

export function resolvePreviewMix(controls: Record<TrackKey, TrackControls>): PreviewMix {
  const solo = hasActiveSolo(controls);

  const active = (key: TrackKey) => {
    const ctrl = controls[key];
    if (!ctrl.visible) return false;
    if (solo) return ctrl.solo;
    return true;
  };

  const videoAudible =
    active('video') && !controls.video.muted && active('audioVoice') && !controls.audioVoice.muted;
  const audioAudible = active('audio') && !controls.audio.muted;

  return {
    showVideo: active('video'),
    showSubtitle: active('subtitle') && !controls.subtitle.muted,
    showOverlay: active('overlay') && !controls.overlay.muted,
    showVideo2: active('video2') && !controls.video2.muted,
    showSticker: active('sticker') && !controls.sticker.muted,
    showFilter: active('filter') && !controls.filter.muted,
    showTransition: active('transition') && !controls.transition.muted,
    showAdjust: active('adjust') && !controls.adjust.muted,
    videoAudible,
    audioAudible,
    mutePreviewAudio: !videoAudible && !audioAudible,
  };
}

export function toggleTrackControl(
  controls: Record<TrackKey, TrackControls>,
  key: TrackKey,
  field: keyof TrackControls
): Record<TrackKey, TrackControls> {
  if (field === 'solo') {
    const nextSolo = !controls[key].solo;
    const next = { ...controls };
    for (const trackKey of TRACK_KEYS) {
      next[trackKey] = { ...next[trackKey], solo: trackKey === key ? nextSolo : false };
    }
    return next;
  }
  return {
    ...controls,
    [key]: { ...controls[key], [field]: !controls[key][field] },
  };
}

export function describeTrackToggle(
  key: TrackKey,
  field: keyof TrackControls,
  next: TrackControls
): string {
  const label = TRACK_LABELS[key];
  if (field === 'locked') return next.locked ? `${label}轨已锁定` : `${label}轨已解锁`;
  if (field === 'visible') return next.visible ? `${label}轨已显示` : `${label}轨已隐藏`;
  if (field === 'muted') return next.muted ? `${label}轨已静音` : `${label}轨已取消静音`;
  if (field === 'solo') return next.solo ? `${label}轨独奏` : `${label}轨取消独奏`;
  return '';
}

/** 合并旧项目保存的轨道控制，补齐新增轨道字段 */
export function mergeTrackControls(
  saved: Partial<Record<TrackKey, TrackControls>> | null | undefined
): Record<TrackKey, TrackControls> {
  const merged = { ...DEFAULT_TRACK_CONTROLS };
  if (!saved || typeof saved !== 'object') return merged;
  for (const key of TRACK_KEYS) {
    const ctrl = saved[key];
    if (ctrl && typeof ctrl === 'object') {
      merged[key] = { ...merged[key], ...ctrl };
    }
  }
  return merged;
}
