import { apiHeaders, apiUrl } from '@/lib/api';
import type { SlotEffects } from '@/lib/slotEffects';
import type { TemplateSlot } from '@/lib/timeline';

export type EffectPresetApply = {
  animation_in?: string;
  animation_out?: string;
  animation_loop?: string;
  text_color?: string;
  outline_color?: string;
  font_size?: number;
  position?: string;
  color_grade?: SlotEffects['colorGrade'];
  transition_out?: SlotEffects['transitionOut'];
  keyframes?: SlotEffects['keyframes'];
  speed?: number;
};

export type EffectPreset = {
  id: string;
  name: string;
  icon?: string;
  apply: EffectPresetApply;
  category_id?: string;
  category_label?: string;
};

export type EffectCategory = {
  id: string;
  label: string;
  description?: string;
  presets: EffectPreset[];
};

export type EffectsLibraryResponse = {
  version: number;
  category_count: number;
  preset_count: number;
  categories: EffectCategory[];
};

export async function fetchEffectsLibrary(): Promise<EffectsLibraryResponse | null> {
  try {
    const resp = await fetch(apiUrl('/api/effects/library'), { headers: apiHeaders(), cache: 'no-store' });
    if (!resp.ok) return null;
    return (await resp.json()) as EffectsLibraryResponse;
  } catch {
    return null;
  }
}

function mergeSubtitleStyle(
  existing: Record<string, unknown> | undefined,
  patch: EffectPresetApply
): Record<string, unknown> {
  const style = { ...(existing || {}) };
  for (const key of ['animation_in', 'animation_out', 'animation_loop', 'text_color', 'outline_color', 'font_size', 'position'] as const) {
    if (patch[key] !== undefined) style[key] = patch[key];
  }
  return style;
}

/** 客户端将预设应用到 TemplateSlot（与后端 apply_preset_to_slot 对齐） */
export function applyEffectPresetToSlot(slot: TemplateSlot, preset: EffectPreset): TemplateSlot {
  const apply = preset.apply || {};
  const next: TemplateSlot = { ...slot };

  if (apply.color_grade) {
    next.colorGrade = { ...(slot.colorGrade || {}), ...apply.color_grade };
  }
  if (apply.transition_out) {
    next.transitionOut = { ...(slot.transitionOut || { type: 'fade', duration: 0.3 }), ...apply.transition_out };
  }
  if (apply.keyframes) {
    next.keyframes = apply.keyframes.map((k) => ({ ...k, props: { ...k.props } }));
  }
  if (apply.speed !== undefined) {
    next.speed = apply.speed;
  }

  const subtitlePatch = {
    animation_in: apply.animation_in,
    animation_out: apply.animation_out,
    animation_loop: apply.animation_loop,
    text_color: apply.text_color,
    outline_color: apply.outline_color,
    font_size: apply.font_size,
    position: apply.position,
  };
  const hasSubtitlePatch = Object.values(subtitlePatch).some((v) => v !== undefined);

  if (hasSubtitlePatch) {
    const segs = Array.isArray(slot.subtitle_segments) ? [...slot.subtitle_segments] : [];
    if (segs.length) {
      next.subtitle_segments = segs.map((raw) => {
        const seg = raw as Record<string, unknown>;
        const style = mergeSubtitleStyle(seg.style as Record<string, unknown> | undefined, subtitlePatch);
        return { ...seg, style };
      });
    }
  }

  return next;
}

export function applyEffectPresetToSlots(
  slots: TemplateSlot[],
  preset: EffectPreset,
  target: 'selected' | 'all',
  selectedSlotId?: string
): TemplateSlot[] {
  if (target === 'all') {
    return slots.map((slot) => applyEffectPresetToSlot(slot, preset));
  }
  if (!selectedSlotId) return slots;
  return slots.map((slot) =>
    slot.id === selectedSlotId ? applyEffectPresetToSlot(slot, preset) : slot
  );
}

export const EFFECT_CATEGORY_ORDER = [
  'subtitle_in',
  'subtitle_out',
  'subtitle_loop',
  'video_motion',
  'color_grade',
  'transition',
] as const;
