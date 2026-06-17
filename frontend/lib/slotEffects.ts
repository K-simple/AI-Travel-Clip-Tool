export type Keyframe = {
  time: number;
  props: { scale?: number; opacity?: number; x?: number; y?: number };
};

export type ColorGrade = {
  brightness?: number;
  contrast?: number;
  saturation?: number;
  gamma?: number;
  hue?: number;
};

export type MaskConfig = {
  enabled?: boolean;
  type?: 'rect' | 'circle';
  x?: number;
  y?: number;
  w?: number;
  h?: number;
  cx?: number;
  cy?: number;
  radius?: number;
  feather?: number;
};

export type TransitionOut = {
  type: string;
  duration: number;
  color?: string;
};

export type SlotEffects = {
  speed?: number;
  opticalFlow?: boolean;
  keyframes?: Keyframe[];
  colorGrade?: ColorGrade;
  mask?: MaskConfig;
  transitionOut?: TransitionOut;
};

export const DEFAULT_SLOT_EFFECTS: SlotEffects = {
  speed: 1,
  opticalFlow: false,
  keyframes: [],
  colorGrade: { brightness: 0, contrast: 1, saturation: 1, gamma: 1 },
  mask: { enabled: false, type: 'rect' },
};

export function hasActiveColorGrade(grade?: ColorGrade): boolean {
  if (!grade) return false;
  const d = DEFAULT_SLOT_EFFECTS.colorGrade!;
  return (
    Math.abs((grade.brightness ?? 0) - (d.brightness ?? 0)) > 0.01 ||
    Math.abs((grade.contrast ?? 1) - (d.contrast ?? 1)) > 0.01 ||
    Math.abs((grade.saturation ?? 1) - (d.saturation ?? 1)) > 0.01 ||
    Math.abs((grade.gamma ?? 1) - (d.gamma ?? 1)) > 0.01 ||
    Math.abs(grade.hue ?? 0) > 0.01
  );
}

export function hasActiveMask(mask?: MaskConfig): boolean {
  return Boolean(mask?.enabled);
}

export function filterLabelForSlot(slot: {
  colorGrade?: ColorGrade;
  mask?: MaskConfig;
}): string {
  if (hasActiveMask(slot.mask)) return '蒙版';
  if (hasActiveColorGrade(slot.colorGrade)) return '调色';
  return '滤镜';
}

export function adjustLabelForSlot(slot: {
  speed?: number;
  opticalFlow?: boolean;
  keyframes?: Keyframe[];
}): string {
  if (slot.keyframes?.length) return '关键帧';
  if (slot.opticalFlow) return '光流';
  if (slot.speed && slot.speed !== 1) return `${slot.speed.toFixed(1)}x`;
  return '调节';
}

export function hasActiveAdjust(slot: {
  speed?: number;
  opticalFlow?: boolean;
  keyframes?: Keyframe[];
}): boolean {
  return (
    Boolean(slot.speed && slot.speed !== 1) ||
    Boolean(slot.opticalFlow) ||
    Boolean(slot.keyframes?.length)
  );
}

/** 预览区 CSS filter，近似 FFmpeg eq 调色 */
export function colorGradeToCssFilter(grade?: ColorGrade): string | undefined {
  if (!grade || !hasActiveColorGrade(grade)) return undefined;
  const brightness = 1 + (grade.brightness ?? 0);
  const contrast = grade.contrast ?? 1;
  const saturation = grade.saturation ?? 1;
  return `brightness(${brightness.toFixed(3)}) contrast(${contrast.toFixed(3)}) saturate(${saturation.toFixed(3)})`;
}
