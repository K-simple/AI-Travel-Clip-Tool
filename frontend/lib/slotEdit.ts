import type { TemplateSlot } from './timeline';

export type SubtitleSegment = {
  start: number;
  end: number;
  text: string;
};

export function parseSubtitleSegments(raw: unknown[] | undefined): SubtitleSegment[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => {
      const seg = item as Record<string, unknown>;
      const start = Number(seg.start ?? 0);
      const end = Number(seg.end ?? start);
      const text = String(seg.text ?? '').trim();
      if (!text || end <= start) return null;
      return { start, end, text };
    })
    .filter((s): s is SubtitleSegment => s !== null);
}

export function getSlotRange(slot: TemplateSlot, fallbackStart: number): { start: number; end: number } {
  const start = slot.slotStart ?? fallbackStart;
  const end = slot.slotEnd ?? start + slot.duration;
  return { start, end };
}

export function getSlotTimeRange(
  slots: TemplateSlot[],
  slotId: string
): { start: number; end: number } | null {
  let cursor = 0;
  for (const slot of slots) {
    const { start, end } = getSlotRange(slot, cursor);
    cursor = end;
    if (slot.id === slotId) return { start, end };
  }
  return null;
}

/** 在播放头位置将槽位一分为二 */
export function splitSlotAtTime(slots: TemplateSlot[], time: number): TemplateSlot[] | null {
  let cursor = 0;

  for (let i = 0; i < slots.length; i++) {
    const slot = slots[i];
    const { start, end } = getSlotRange(slot, cursor);
    cursor = end;

    if (slot.locked || time <= start + 0.15 || time >= end - 0.15) continue;

    const firstDuration = time - start;
    const secondDuration = end - time;
    const localSplit = time - start;
    const segments = parseSubtitleSegments(slot.subtitle_segments);

    const firstSegments = segments
      .filter((seg) => seg.start < time)
      .map((seg) => ({
        ...seg,
        end: Math.min(seg.end, time),
      }))
      .filter((seg) => seg.end > seg.start);

    const secondSegments = segments
      .filter((seg) => seg.end > time)
      .map((seg) => ({
        ...seg,
        start: Math.max(seg.start, time),
      }))
      .filter((seg) => seg.end > seg.start);

    const first: TemplateSlot = {
      ...slot,
      duration: firstDuration,
      slotStart: start,
      slotEnd: time,
      subtitle_segments: firstSegments,
      subtitleText: firstSegments.map((s) => s.text).join(' ').trim() || slot.subtitleText,
    };

    const second: TemplateSlot = {
      ...slot,
      id: `${slot.id}-b-${Math.round(time * 100)}`,
      duration: secondDuration,
      slotStart: time,
      slotEnd: end,
      clipStart: Number(slot.clipStart || 0) + localSplit,
      subtitle_segments: secondSegments,
      subtitleText: secondSegments.map((s) => s.text).join(' ').trim(),
      match_score: undefined,
      match_reason: undefined,
    };

    return [...slots.slice(0, i), first, second, ...slots.slice(i + 1)];
  }

  return null;
}
