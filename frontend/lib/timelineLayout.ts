import type { TemplateSlot } from './timeline';
import { getSlotRange, parseSubtitleSegments, type SubtitleSegment } from './slotEdit';

export type ClipLayout = {
  slot: TemplateSlot;
  start: number;
  end: number;
  left: number;
  width: number;
};

export type SegmentLayout = {
  segment: SubtitleSegment;
  slot: TemplateSlot;
  start: number;
  end: number;
  left: number;
  width: number;
};

export function buildClipLayouts(slots: TemplateSlot[], pxPerSec: number): ClipLayout[] {
  let cursor = 0;
  return slots.map((slot) => {
    const { start, end } = getSlotRange(slot, cursor);
    cursor = end;
    const left = start * pxPerSec;
    const width = Math.max(slot.duration * pxPerSec, 28);
    return { slot, start, end, left, width };
  });
}

export function buildSubtitleSegmentLayouts(slots: TemplateSlot[], pxPerSec: number): SegmentLayout[] {
  const layouts: SegmentLayout[] = [];
  let cursor = 0;

  for (const slot of slots) {
    const { start: slotStart, end: slotEnd } = getSlotRange(slot, cursor);
    cursor = slotEnd;

    const segments = parseSubtitleSegments(slot.subtitle_segments);
    if (segments.length) {
      for (const segment of segments) {
        const segStart = Math.max(segment.start, slotStart);
        const segEnd = Math.min(segment.end, slotEnd);
        if (segEnd <= segStart) continue;
        layouts.push({
          segment: { ...segment, start: segStart, end: segEnd },
          slot,
          start: segStart,
          end: segEnd,
          left: segStart * pxPerSec,
          width: Math.max((segEnd - segStart) * pxPerSec, 18),
        });
      }
    } else if (slot.subtitleText) {
      layouts.push({
        segment: { start: slotStart, end: slotEnd, text: slot.subtitleText },
        slot,
        start: slotStart,
        end: slotEnd,
        left: slotStart * pxPerSec,
        width: Math.max(slot.duration * pxPerSec, 28),
      });
    }
  }

  return layouts;
}

export function getTotalDuration(slots: TemplateSlot[]): number {
  const layouts = buildClipLayouts(slots, 1);
  const last = layouts[layouts.length - 1];
  return Math.max(last?.end ?? 0, 1);
}

/** 时间轴 / 预览统一帧率 */
export const TIMELINE_FPS = 30;
export const FRAME_STEP = 1 / TIMELINE_FPS;

export function snapToFrame(time: number, fps = TIMELINE_FPS): number {
  return Math.round(Math.max(0, time) * fps) / fps;
}

export function isNearPlayheadX(
  clientX: number,
  scrollEl: HTMLElement,
  playheadTime: number,
  pxPerSec: number,
  thresholdPx = 18
): boolean {
  const rect = scrollEl.getBoundingClientRect();
  const x = clientX - rect.left + scrollEl.scrollLeft;
  const playheadX = playheadTime * pxPerSec;
  return Math.abs(x - playheadX) <= thresholdPx;
}

export function findClipAtTime(layouts: ClipLayout[], time: number): ClipLayout | null {
  const hit = layouts.find((l) => time >= l.start && time < l.end);
  if (hit) return hit;
  return layouts[layouts.length - 1] ?? null;
}

export function snapTime(
  time: number,
  layouts: ClipLayout[],
  magnet: boolean,
  segmentLayouts: SegmentLayout[] = [],
  step = FRAME_STEP
): number {
  const raw = Math.max(0, time);
  if (!magnet) return snapToFrame(raw);

  const candidates = [
    0,
    ...layouts.flatMap((l) => [l.start, l.end]),
    ...segmentLayouts.flatMap((s) => [s.start, s.end]),
  ];

  let best = raw;
  let minDist = Infinity;
  for (const c of candidates) {
    const d = Math.abs(c - time);
    if (d < minDist && d <= step * 2) {
      minDist = d;
      best = c;
    }
  }

  if (minDist === Infinity) {
    return snapToFrame(raw);
  }
  return snapToFrame(best);
}

export function formatTimecode(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

/** 根据 slot id 生成稳定的伪波形条 */
export function pseudoWaveform(seed: string, bars = 24): number[] {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash << 5) - hash + seed.charCodeAt(i);
    hash |= 0;
  }
  return Array.from({ length: bars }, (_, i) => {
    const v = Math.abs(Math.sin((hash + i) * 12.9898) * 43758.5453) % 1;
    return 0.2 + v * 0.8;
  });
}
