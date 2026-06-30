/** 剪映 PC 风格时间轴配色 */
export const TIMELINE_THEME = {
  bg: '#101012',
  headerBg: '#18181a',
  rulerBg: '#141416',
  laneBg: '#121214',
  laneSelected: '#1a1a1e',
  border: '#242428',
  borderLight: '#303034',
  textMuted: '#6e6e72',
  textPrimary: '#ececef',
  accent: '#face15',
  accentDim: 'rgba(250,206,21,0.12)',
  playhead: '#ffffff',
  toolbarBg: '#1a1a1c',
  trackIcon: {
    video: { bg: '#1a4a40', fg: '#6ee7c7' },
    overlay: { bg: '#1e4d2e', fg: '#86efac' },
    sticker: { bg: '#3b1f5c', fg: '#c4b5fd' },
    video2: { bg: '#2d1f4a', fg: '#a78bfa' },
    filter: { bg: '#4a2040', fg: '#f9a8d4' },
    transition: { bg: '#3d3520', fg: '#fde047' },
    adjust: { bg: '#1a3050', fg: '#93c5fd' },
    subtitle: { bg: '#6b3410', fg: '#fdba74' },
    audio: { bg: '#1a3050', fg: '#60a5fa' },
    audioVoice: { bg: '#1a3a55', fg: '#7dd3fc' },
    ttsVoice: { bg: '#3d1f55', fg: '#e879f9' },
  },
  video: {
    header: '#163d34',
    headerText: '#a7f3d0',
    body: '#0a1a16',
    border: '#1e3a32',
    borderSelected: '#face15',
    frameGap: 'transparent',
    labelShadow: 'rgba(0,0,0,0.65)',
  },
  subtitle: {
    bg: '#e85d04',
    bgHover: '#f97316',
    bgSelected: '#fb923c',
    border: '#c2410c',
    text: '#ffffff',
  },
  sticker: {
    bg: '#14532d',
    border: '#22c55e',
    icon: '#86efac',
    text: '#bbf7d0',
  },
  audio: {
    bg: '#0c1828',
    border: '#1e3a5f',
    wave: '#4fc3f7',
    waveDim: '#1a4a6e',
    label: '#90caf9',
  },
  meta: {
    filter: { bg: '#4a2040', border: '#be185d', text: '#fbcfe8' },
    transition: { bg: '#3d3520', border: '#ca8a04', text: '#fef08a' },
    adjust: { bg: '#1a3050', border: '#2563eb', text: '#bfdbfe' },
  },
} as const;

export const CLIP_INSET = 1;
export const CLIP_GAP = 0;
export const RULER_H = 28;
export const HEADER_W = 148;
export const TOOLBAR_H = 34;
