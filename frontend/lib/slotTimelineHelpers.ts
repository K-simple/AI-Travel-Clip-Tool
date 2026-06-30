import type { SubtitleClip, TemplateSlot } from '@/lib/timeline';

/** 上传后默认仅有一个覆盖全片的 base slot。 */
export function isBaseSlot(slot: TemplateSlot): boolean {
  const s = slot as TemplateSlot & { isBaseSlot?: boolean };
  if (s.isBaseSlot) return true;
  if (String(slot.slotSource || '') === 'base') return true;
  if (String(slot.cutReason || '') === 'full_video') return true;
  const id = String(slot.id || '');
  return id.startsWith('slot_base') || id.startsWith('slot-base');
}

export function isBaseOnlyTimeline(slots: TemplateSlot[]): boolean {
  if (!slots.length) return true;
  if (slots.length !== 1) return false;
  return isBaseSlot(slots[0]);
}

export function hasAiCaptionSplitSlots(slots: TemplateSlot[]): boolean {
  return slots.some(
    (s) =>
      String(s.slotSource || '') === 'ai_caption_split' ||
      String(s.cutReason || '') === 'one_sentence_one_shot'
  );
}

export function hasMixedSlotSources(slots: TemplateSlot[]): boolean {
  const hasAi = hasAiCaptionSplitSlots(slots);
  const hasVisual = slots.some(
    (s) =>
      !isBaseSlot(s) &&
      String(s.slotSource || '') !== 'ai_caption_split' &&
      String(s.cutReason || '') !== 'one_sentence_one_shot'
  );
  return hasAi && hasVisual;
}

/** 主画面轨槽位：严格一句一画面，不渲染旧 PySceneDetect 多槽。 */
export function resolveMainTimelineSlots(
  slots: TemplateSlot[],
  subtitleClips: SubtitleClip[] = []
): TemplateSlot[] {
  if (!slots.length) return slots;

  const aiSlots = slots.filter(
    (s) =>
      String(s.slotSource || '') === 'ai_caption_split' ||
      String(s.cutReason || '') === 'one_sentence_one_shot'
  );
  if (aiSlots.length > 0) {
    return aiSlots.length === slots.length ? slots : aiSlots;
  }

  if (isBaseOnlyTimeline(slots)) return slots;

  if (subtitleClips.length > 0) {
    const base = slots.filter(isBaseSlot);
    if (base.length >= 1) return [base[0]];
    const totalDur = slots.reduce((sum, s) => sum + Math.max(0.1, s.duration), 0);
    const first = slots[0];
    return [
      {
        ...first,
        duration: totalDur,
        subtitleText: first?.subtitleText || '',
      },
    ];
  }

  return slots;
}

export type OneCaptionOneShotDebug = {
  captionClipCount: number;
  slotCount: number;
  materialClipCount: number;
  timelineRenderedVideoBlockCount: number;
  slotsEqualCaptions: boolean;
  materialsEqualSlots: boolean;
  timelineBlocksEqualSlots: boolean;
  usingOldVisualSlots: boolean;
  usingFixedIntervalMaterialCuts: boolean;
  secondaryCutsEnabled: boolean;
  renderingMaterialSegmentsAsMainTrack: boolean;
  mixedSlotSources?: boolean;
};

export function buildOneCaptionOneShotDebug(
  slots: TemplateSlot[],
  subtitleClips: SubtitleClip[] = []
): OneCaptionOneShotDebug {
  const mainSlots = resolveMainTimelineSlots(slots, subtitleClips);
  const captionCount = subtitleClips.length;
  const slotCount = mainSlots.length;
  const materialCount = mainSlots.filter(
    (s) => s.matchedAssetId || s.asset_file_path || s.segment_file_path
  ).length;
  const usingOldVisual =
    !hasAiCaptionSplitSlots(slots) &&
    !isBaseOnlyTimeline(slots) &&
    slots.length > 1 &&
    captionCount > 0;

  return {
    captionClipCount: captionCount,
    slotCount,
    materialClipCount: materialCount,
    timelineRenderedVideoBlockCount: slotCount,
    slotsEqualCaptions: captionCount === 0 ? slotCount <= 1 : slotCount === captionCount,
    materialsEqualSlots: materialCount <= slotCount,
    timelineBlocksEqualSlots: slotCount === mainSlots.length,
    usingOldVisualSlots: usingOldVisual,
    usingFixedIntervalMaterialCuts: false,
    secondaryCutsEnabled: false,
    renderingMaterialSegmentsAsMainTrack: false,
    mixedSlotSources: hasMixedSlotSources(slots),
  };
}

export function slotsWillBeOverwrittenByAiSplit(slots: TemplateSlot[]): boolean {
  return !isBaseOnlyTimeline(slots);
}
