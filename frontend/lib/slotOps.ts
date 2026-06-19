import type { TemplateSlot } from '@/lib/timeline';

export function deleteSlot(slots: TemplateSlot[], slotId: string): TemplateSlot[] {
  return slots.filter((s) => s.id !== slotId);
}

/** Q：删除播放头右侧槽位内容（波纹删除简化版：清空右侧槽位素材） */
export function rippleClearRight(slots: TemplateSlot[], slotId: string): TemplateSlot[] {
  const idx = slots.findIndex((s) => s.id === slotId);
  if (idx < 0) return slots;
  return slots.map((slot, i) =>
    i > idx
      ? {
          ...slot,
          matchedAssetId: undefined,
          asset_file_path: undefined,
          asset_filename: undefined,
          asset_thumbnail: undefined,
          clipStart: 0,
          match_score: undefined,
          match_reason: undefined,
        }
      : slot
  );
}

/** W：删除当前槽位 */
export function rippleDeleteSlot(slots: TemplateSlot[], slotId: string): TemplateSlot[] {
  return deleteSlot(slots, slotId);
}

export function trimClipStart(slot: TemplateSlot, delta: number, maxAsset?: number): TemplateSlot {
  const max = maxAsset ?? slot.duration * 3;
  const next = Math.min(Math.max(0, slot.clipStart + delta), max);
  return { ...slot, clipStart: next };
}

export function trimClipDuration(slot: TemplateSlot, delta: number): TemplateSlot {
  const next = Math.max(0.3, slot.duration + delta);
  const start = slot.slotStart ?? 0;
  return {
    ...slot,
    duration: next,
    clip_duration: next,
    slotEnd: start + next,
  };
}

/** 按顺序重算 slot_start / slot_end */
export function recalculateSlotTimes(slots: TemplateSlot[]): TemplateSlot[] {
  let cursor = 0;
  return slots.map((slot, index) => {
    const duration = slot.duration;
    const start = cursor;
    const end = start + duration;
    cursor = end;
    return {
      ...slot,
      slotStart: start,
      slotEnd: end,
      originalSlotId: slot.originalSlotId ?? index + 1,
    };
  });
}

export function reorderSlots(slots: TemplateSlot[], fromIndex: number, toIndex: number): TemplateSlot[] {
  if (
    fromIndex === toIndex ||
    fromIndex < 0 ||
    toIndex < 0 ||
    fromIndex >= slots.length ||
    toIndex >= slots.length
  ) {
    return slots;
  }
  const next = [...slots];
  const [moved] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, moved);
  return recalculateSlotTimes(next);
}

export function moveSlotById(slots: TemplateSlot[], slotId: string, direction: -1 | 1): TemplateSlot[] {
  const idx = slots.findIndex((s) => s.id === slotId);
  if (idx < 0) return slots;
  const target = idx + direction;
  if (target < 0 || target >= slots.length) return slots;
  return reorderSlots(slots, idx, target);
}
