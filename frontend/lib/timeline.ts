import { recalculateSlotTimes } from './slotOps';

export type TemplateSlot = {
  id: string;
  name: string;
  duration: number;
  matchedAssetId?: string;
  useOriginalAudio: boolean;
  clipStart: number;
  subtitleText: string;
  originalSlotId?: string | number;
  slotStart?: number;
  slotEnd?: number;
  asset_file_path?: string;
  segment_file_path?: string;
  asset_filename?: string;
  asset_thumbnail?: string;
  template_thumbnail?: string;
  shot_type?: string;
  scene_tags?: string[];
  ai_description?: string;
  ai_tags?: string[];
  ai_replace_hint?: string;
  ai_subject?: string;
  subtitle_segments?: unknown[];
  clip_duration?: number;
  asset_audio_volume?: number;
  match_score?: number;
  match_reason?: string;
  locked?: boolean;
  speed?: number;
  opticalFlow?: boolean;
  keyframes?: import('@/lib/slotEffects').Keyframe[];
  colorGrade?: import('@/lib/slotEffects').ColorGrade;
  mask?: import('@/lib/slotEffects').MaskConfig;
  transitionOut?: import('@/lib/slotEffects').TransitionOut;
};

/** 旧时间线可能把模板源时间写在 slot_start；在重排时间轴前保留到 clipStart */
function ensureTemplateSourceOffset(slots: TemplateSlot[]): TemplateSlot[] {
  return slots.map((slot) => {
    const hasAsset = Boolean(slot.matchedAssetId || slot.asset_file_path?.trim());
    if (hasAsset || slot.clipStart > 0) return slot;
    const legacySource = slot.slotStart ?? 0;
    if (legacySource > 0) {
      return { ...slot, clipStart: legacySource };
    }
    return slot;
  });
}

export function timelineToSlots(timeline: Record<string, unknown>[]): TemplateSlot[] {
  const slots = timeline.map((entry, index) => ({
    id: `slot-${entry.slot_id ?? index + 1}`,
    name:
      (entry.ai_description as string) ||
      (entry.slot_name as string) ||
      (entry.shot_type as string) ||
      `槽位 ${entry.slot_id ?? index + 1}`,
    duration: Number(entry.slot_duration ?? entry.duration ?? 3),
    matchedAssetId: entry.asset_id as string | undefined,
    useOriginalAudio: Boolean(entry.use_original_audio ?? false),
    clipStart: Number(entry.clip_start ?? 0),
    subtitleText: (entry.subtitle_text as string) || '',
    originalSlotId: (entry.slot_id as string | number) ?? index + 1,
    slotStart: entry.slot_start != null ? Number(entry.slot_start) : undefined,
    slotEnd: entry.slot_end != null ? Number(entry.slot_end) : undefined,
    asset_file_path: entry.asset_file_path as string | undefined,
    segment_file_path: entry.segment_file_path as string | undefined,
    asset_filename: entry.asset_filename as string | undefined,
    asset_thumbnail: entry.asset_thumbnail as string | undefined,
    template_thumbnail: entry.template_thumbnail as string | undefined,
    shot_type: entry.shot_type as string | undefined,
    scene_tags: (entry.scene_tags as string[]) || [],
    ai_description: (entry.ai_description as string) || undefined,
    ai_tags: (entry.ai_tags as string[]) || [],
    ai_replace_hint: (entry.ai_replace_hint as string) || undefined,
    ai_subject: (entry.ai_subject as string) || undefined,
    subtitle_segments: (entry.subtitle_segments as unknown[]) || [],
    clip_duration: entry.clip_duration != null ? Number(entry.clip_duration) : undefined,
    asset_audio_volume:
      entry.asset_audio_volume != null ? Number(entry.asset_audio_volume) : undefined,
    match_score: entry.match_score != null ? Number(entry.match_score) : undefined,
    match_reason: entry.match_reason as string | undefined,
    locked: Boolean(entry.locked ?? false),
    speed: entry.speed != null ? Number(entry.speed) : undefined,
    opticalFlow: Boolean(entry.optical_flow ?? false),
    keyframes: (entry.keyframes as TemplateSlot['keyframes']) || [],
    colorGrade: entry.color_grade as TemplateSlot['colorGrade'],
    mask: entry.mask as TemplateSlot['mask'],
    transitionOut: entry.transition_out as TemplateSlot['transitionOut'],
  }));
  return recalculateSlotTimes(ensureTemplateSourceOffset(slots));
}

export function slotToTimelineEntry(
  slot: TemplateSlot,
  index: number,
  assetMap: Record<string, { filePath?: string; title?: string }>
): Record<string, unknown> {
  const clipDuration = slot.clip_duration ?? slot.duration;
  return {
    slot_id: slot.originalSlotId ?? index + 1,
    slot_name: slot.name,
    slot_start: slot.slotStart,
    slot_end: slot.slotEnd,
    slot_duration: slot.duration,
    template_thumbnail: slot.template_thumbnail,
    shot_type: slot.shot_type,
    scene_tags: slot.scene_tags,
    ai_description: slot.ai_description,
    ai_tags: slot.ai_tags,
    ai_replace_hint: slot.ai_replace_hint,
    ai_subject: slot.ai_subject,
    subtitle_segments: slot.subtitle_segments,
    asset_id: slot.matchedAssetId ?? null,
    segment_file_path: slot.segment_file_path,
    asset_file_path:
      slot.segment_file_path ||
      slot.asset_file_path ||
      (slot.matchedAssetId ? assetMap[slot.matchedAssetId]?.filePath : undefined),
    asset_filename:
      slot.asset_filename ??
      (slot.matchedAssetId ? assetMap[slot.matchedAssetId]?.title : undefined),
    asset_thumbnail: slot.asset_thumbnail,
    locked: slot.locked ?? false,
    clip_start: slot.clipStart,
    clip_duration: clipDuration,
    use_original_audio: slot.useOriginalAudio,
    asset_audio_volume: slot.asset_audio_volume ?? 0.3,
    subtitle_text: slot.subtitleText,
    match_score: slot.match_score,
    match_reason: slot.match_reason,
    speed: slot.speed ?? 1,
    optical_flow: slot.opticalFlow ?? false,
    keyframes: slot.keyframes ?? [],
    color_grade: slot.colorGrade,
    mask: slot.mask,
    transition_out: slot.transitionOut,
  };
}

export function slotsToTimeline(
  slots: TemplateSlot[],
  assetMap: Record<string, { filePath?: string; title?: string }>
): Record<string, unknown>[] {
  return slots.map((slot, index) => slotToTimelineEntry(slot, index, assetMap));
}

export type SlotAssetBinding = {
  id: string;
  filePath?: string;
  title?: string;
  thumbnail?: string;
  segmentId?: string;
  segmentFilePath?: string;
  clipStart?: number;
};

export function applyAssetToSlot(slot: TemplateSlot, asset: SlotAssetBinding): TemplateSlot {
  const useSegmentFile = Boolean(asset.segmentFilePath?.trim());
  return {
    ...slot,
    matchedAssetId: asset.id,
    clipStart: useSegmentFile ? 0 : Number(asset.clipStart ?? 0),
    segment_file_path: useSegmentFile ? asset.segmentFilePath : undefined,
    asset_file_path: useSegmentFile ? asset.segmentFilePath : asset.filePath,
    asset_filename: asset.title,
    asset_thumbnail: asset.thumbnail,
    match_score: undefined,
    match_reason: undefined,
  };
}
