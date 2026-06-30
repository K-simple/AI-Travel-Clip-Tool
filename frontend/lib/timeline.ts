import { recalculateSlotTimes } from './slotOps';
import { enrichSlotsWithDuplicateStatus } from './subtitleStatus';

export type { TimelineThumbnail } from './timelineThumbnails';

/** 编辑器时间轴状态（filmstrip 预览数据，不参与切槽/导出） */
export type TimelineEditorFilmstripState = {
  timelineThumbnails: import('./timelineThumbnails').TimelineThumbnail[];
};

export type AiEffectUnderstanding = {
  catalog_preset_ids?: string[];
  preset_labels?: string[];
  summary?: string;
  subtitle_match?: number;
  subtitle_match_reason?: string;
  visual_context?: string;
  source?: string;
};

export type TemplateSlot = {
  id: string;
  name: string;
  duration: number;
  matchedAssetId?: string;
  useOriginalAudio: boolean;
  clipStart: number;
  /** 模板源视频上的起始秒（匹配素材后不随 asset clipStart 变化） */
  templateSourceStart?: number;
  subtitleText: string;
  originalSlotId?: string | number;
  slotStart?: number;
  slotEnd?: number;
  asset_file_path?: string;
  segment_file_path?: string;
  asset_filename?: string;
  asset_thumbnail?: string;
  template_thumbnail?: string;
  filmstrip?: string;
  filmstripFrames?: number;
  filmstripTileWidth?: number;
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
  template_effect_label?: string;
  auto_effects?: Record<string, unknown>;
  subtitle_style?: import('@/lib/slotEdit').SubtitleStyle;
  subtitle_visual_context?: string;
  subtitle_scene_match?: number;
  subtitle_scene_match_reason?: string;
  subtitle_effect_label?: string;
  applied_effect_presets?: string[];
  ai_effect_understanding?: AiEffectUnderstanding;
  subtitle_source?: string;
  subtitle_quality?: 'ok' | 'low' | 'empty';
  subtitle_status_reason?: string;
  subtitle_duplicate?: boolean;
  /** caption_slot：关联 sentenceClip */
  linkedSubtitleClipId?: string;
  slotSource?: string;
  cutReason?: string;
  confidence?: number;
  linkedTtsSegmentId?: string;
  linkedCaptionClipId?: string;
};

/** 剪映式独立字幕片段（源视频绝对时间，不依赖画面 slot） */
export type SubtitleClip = {
  id?: string;
  start?: number;
  end?: number;
  duration?: number;
  text?: string;
  displayText?: string;
  source?: string;
  type?: string;
  clipType?: string;
  confidence?: number;
  linkedSegmentIds?: string[];
  linkedWordIds?: string[];
  words?: Array<{ word?: string; start?: number; end?: number; confidence?: number }>;
  lineBreaks?: number[];
  effectProfileId?: string;
  renderHints?: Record<string, unknown>;
  splitReason?: string;
  quality?: {
    textConfidence?: number;
    timeConfidence?: number;
    source?: string;
    needsReview?: boolean;
    reasons?: string[];
  };
  fusionDebug?: Record<string, unknown>;
  originalStart?: number;
  originalEnd?: number;
  index?: number;
  /** ASR 主 + OCR 校验状态 */
  validated?: boolean;
  validationStatus?: 'validated' | 'needs_review' | 'invalid';
  validationDebug?: {
    validationAction?: string;
    asrText?: string;
    ocrText?: string;
    similarity?: number;
    textSource?: string;
    textCorrectedByOcr?: boolean;
    ocrMatched?: boolean;
    needsLocalReAsr?: boolean;
  };
  tts?: {
    status?: 'pending' | 'generated' | 'failed';
    voiceId?: string;
    voiceName?: string;
    audioPath?: string;
    duration?: number;
    provider?: string;
  };
};

export type TtsSegment = {
  id?: string;
  captionClipId?: string;
  index?: number;
  text?: string;
  voiceId?: string;
  voiceName?: string;
  audioPath?: string;
  duration?: number;
  start?: number;
  end?: number;
  status?: 'pending' | 'generated' | 'failed';
  error?: string | null;
  provider?: string;
};

/** 保留模板源视频偏移：clip_start 由后端写入，勿把 slotStart（时间轴位置）误当成源时间 */
function ensureTemplateSourceOffset(slots: TemplateSlot[]): TemplateSlot[] {
  return slots.map((slot) => ({
    ...slot,
    templateSourceStart:
      slot.templateSourceStart ??
      Number(slot.clipStart ?? 0),
  }));
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
    templateSourceStart:
      entry.template_source_start != null
        ? Number(entry.template_source_start)
        : Number(entry.clip_start ?? entry.start ?? 0),
    subtitleText: (entry.subtitle_text as string) || '',
    originalSlotId: (entry.slot_id as string | number) ?? index + 1,
    slotStart: entry.slot_start != null ? Number(entry.slot_start) : undefined,
    slotEnd: entry.slot_end != null ? Number(entry.slot_end) : undefined,
    asset_file_path: entry.asset_file_path as string | undefined,
    segment_file_path: entry.segment_file_path as string | undefined,
    asset_filename: entry.asset_filename as string | undefined,
    asset_thumbnail: entry.asset_thumbnail as string | undefined,
    template_thumbnail: entry.template_thumbnail as string | undefined,
    filmstrip: (entry.filmstrip as string) || undefined,
    filmstripFrames:
      entry.filmstrip_frames != null ? Number(entry.filmstrip_frames) : undefined,
    filmstripTileWidth:
      entry.filmstrip_tile_width != null ? Number(entry.filmstrip_tile_width) : undefined,
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
    template_effect_label: entry.template_effect_label as string | undefined,
    auto_effects: entry.auto_effects as TemplateSlot['auto_effects'],
    subtitle_style: entry.subtitle_style as TemplateSlot['subtitle_style'],
    subtitle_visual_context: entry.subtitle_visual_context as string | undefined,
    subtitle_scene_match:
      entry.subtitle_scene_match != null ? Number(entry.subtitle_scene_match) : undefined,
    subtitle_scene_match_reason: entry.subtitle_scene_match_reason as string | undefined,
    subtitle_effect_label: (entry.subtitle_effect_label as string) || undefined,
    applied_effect_presets: (entry.applied_effect_presets as string[]) || [],
    ai_effect_understanding: entry.ai_effect_understanding as TemplateSlot['ai_effect_understanding'],
    subtitle_source: entry.subtitle_source as string | undefined,
    subtitle_quality: entry.subtitle_quality as TemplateSlot['subtitle_quality'],
    subtitle_status_reason: entry.subtitle_status_reason as string | undefined,
    subtitle_duplicate: Boolean(entry.subtitle_duplicate ?? false),
    linkedSubtitleClipId:
      (entry.linked_subtitle_clip_id as string) ||
      (entry.linkedSubtitleClipId as string) ||
      (entry.linkedCaptionClipId as string) ||
      undefined,
    linkedTtsSegmentId:
      (entry.linked_tts_segment_id as string) ||
      (entry.linkedTtsSegmentId as string) ||
      undefined,
    linkedCaptionClipId:
      (entry.linkedCaptionClipId as string) ||
      (entry.linked_subtitle_clip_id as string) ||
      undefined,
    slotSource: (entry.source as string) || undefined,
    cutReason: (entry.cut_reason as string) || undefined,
    confidence: entry.confidence != null ? Number(entry.confidence) : undefined,
  }));
  return enrichSlotsWithDuplicateStatus(recalculateSlotTimes(ensureTemplateSourceOffset(slots)));
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
    filmstrip: slot.filmstrip,
    filmstrip_frames: slot.filmstripFrames,
    filmstrip_tile_width: slot.filmstripTileWidth,
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
    template_source_start: slot.templateSourceStart ?? slot.clipStart,
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
    template_effect_label: slot.template_effect_label,
    auto_effects: slot.auto_effects,
    subtitle_style: slot.subtitle_style,
    subtitle_visual_context: slot.subtitle_visual_context,
    subtitle_scene_match: slot.subtitle_scene_match,
    subtitle_scene_match_reason: slot.subtitle_scene_match_reason,
    subtitle_effect_label: slot.subtitle_effect_label ?? slot.template_effect_label,
    applied_effect_presets: slot.applied_effect_presets,
    ai_effect_understanding: slot.ai_effect_understanding,
    subtitle_source: slot.subtitle_source,
    subtitle_quality: slot.subtitle_quality,
    subtitle_status_reason: slot.subtitle_status_reason,
    subtitle_duplicate: slot.subtitle_duplicate,
    linked_subtitle_clip_id: slot.linkedSubtitleClipId ?? slot.linkedCaptionClipId,
    linkedSubtitleClipId: slot.linkedSubtitleClipId ?? slot.linkedCaptionClipId,
    linkedCaptionClipId: slot.linkedCaptionClipId ?? slot.linkedSubtitleClipId,
    linked_tts_segment_id: slot.linkedTtsSegmentId,
    linkedTtsSegmentId: slot.linkedTtsSegmentId,
    source: slot.slotSource,
    cut_reason: slot.cutReason,
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
    useOriginalAudio: false,
    templateSourceStart: slot.templateSourceStart ?? slot.clipStart,
    clipStart: useSegmentFile ? 0 : Number(asset.clipStart ?? 0),
    segment_file_path: useSegmentFile ? asset.segmentFilePath : undefined,
    asset_file_path: useSegmentFile ? asset.segmentFilePath : asset.filePath,
    asset_filename: asset.title,
    asset_thumbnail: asset.thumbnail,
    match_score: undefined,
    match_reason: undefined,
  };
}
