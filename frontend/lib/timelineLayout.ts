import type { SubtitleClip, TemplateSlot, TtsSegment } from './timeline';
import { parseSubtitleSegments, type SubtitleSegment } from './slotEdit';
import {
  hasAiCaptionSplitSlots,
  resolveMainTimelineSlots,
} from './slotTimelineHelpers';

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

export type TtsSegmentLayout = {
  segment: TtsSegment;
  start: number;
  end: number;
  left: number;
  width: number;
};

function isTtsTimelineClip(clip: SubtitleClip): boolean {
  const tts = clip.tts;
  if (tts && (tts.status === 'generated' || tts.status === 'failed')) return true;
  if (clip.originalStart != null && clip.start != null) {
    return Math.abs(Number(clip.originalStart) - Number(clip.start)) > 0.05;
  }
  return false;
}

export function buildTtsSegmentLayouts(
  segments: TtsSegment[],
  pxPerSec: number,
): TtsSegmentLayout[] {
  const layouts: TtsSegmentLayout[] = [];
  for (const segment of segments) {
    const tStart = Number(segment.start ?? 0);
    const tEnd = Number(segment.end ?? tStart);
    if (tEnd <= tStart) continue;
    layouts.push({
      segment,
      start: tStart,
      end: tEnd,
      left: tStart * pxPerSec,
      width: Math.max((tEnd - tStart) * pxPerSec, 22),
    });
  }
  return layouts;
}

export type SubtitleClipLayout = {
  clip: SubtitleClip;
  start: number;
  end: number;
  left: number;
  width: number;
};

/** 模板源视频秒 → 编辑时间轴秒 */
export function mapSourceTimeToTimeline(sourceTime: number, slots: TemplateSlot[]): number {
  if (!slots.length) return sourceTime;
  let cursor = 0;
  for (const slot of slots) {
    const srcStart = slot.templateSourceStart ?? slot.clipStart ?? 0;
    const dur = Math.max(0.1, slot.duration);
    const srcEnd = srcStart + dur;
    if (sourceTime >= srcStart - 0.05 && sourceTime <= srcEnd + 0.05) {
      return cursor + Math.max(0, sourceTime - srcStart);
    }
    cursor += dur;
  }
  const last = slots[slots.length - 1];
  const lastStart = last.templateSourceStart ?? last.clipStart ?? 0;
  let cursorBefore = 0;
  for (let i = 0; i < slots.length - 1; i += 1) {
    cursorBefore += Math.max(0.1, slots[i].duration);
  }
  return cursorBefore + Math.max(0, sourceTime - lastStart);
}

/** 源视频时间段 → 时间轴区间（按槽位重叠映射，避免起止点落不同槽时丢片段） */
export function mapSourceRangeToTimeline(
  sourceStart: number,
  sourceEnd: number,
  slots: TemplateSlot[],
): { start: number; end: number } {
  if (sourceEnd <= sourceStart) {
    return { start: sourceStart, end: sourceStart + 0.05 };
  }
  if (!slots.length) {
    return { start: sourceStart, end: sourceEnd };
  }

  let cursor = 0;
  let tStart: number | null = null;
  let tEnd: number | null = null;

  for (const slot of slots) {
    const srcStart = Number(slot.templateSourceStart ?? slot.clipStart ?? 0);
    const srcDur = Math.max(0.1, Number(slot.clip_duration ?? slot.duration));
    const slotDur = Math.max(0.1, slot.duration);
    const srcEnd = srcStart + srcDur;

    const overlapStart = Math.max(sourceStart, srcStart);
    const overlapEnd = Math.min(sourceEnd, srcEnd);
    if (overlapEnd > overlapStart + 0.001) {
      const mappedStart = cursor + (overlapStart - srcStart);
      const mappedEnd = cursor + (overlapEnd - srcStart);
      tStart = tStart == null ? mappedStart : Math.min(tStart, mappedStart);
      tEnd = tEnd == null ? mappedEnd : Math.max(tEnd, mappedEnd);
    }
    cursor += slotDur;
  }

  if (tStart != null && tEnd != null && tEnd > tStart) {
    return { start: tStart, end: tEnd };
  }

  const totalTimeline = slots.reduce((sum, slot) => sum + Math.max(0.1, slot.duration), 0);
  const firstSrc = Number(slots[0].templateSourceStart ?? slots[0].clipStart ?? 0);
  if (Math.abs(firstSrc) < 0.1 && sourceStart >= 0 && sourceEnd <= totalTimeline + 1) {
    return {
      start: Math.max(0, sourceStart),
      end: Math.min(totalTimeline, Math.max(sourceStart + 0.05, sourceEnd)),
    };
  }

  const pointStart = mapSourceTimeToTimeline(sourceStart, slots);
  const pointEnd = mapSourceTimeToTimeline(sourceEnd, slots);
  return {
    start: pointStart,
    end: Math.max(pointStart + 0.05, pointEnd),
  };
}

export function buildSubtitleClipLayouts(
  clips: SubtitleClip[],
  slots: TemplateSlot[],
  pxPerSec: number,
): SubtitleClipLayout[] {
  const mainSlots = resolveMainTimelineSlots(slots, clips);
  const clipLayouts = buildClipLayouts(mainSlots, pxPerSec);

  if (hasAiCaptionSplitSlots(mainSlots) && mainSlots.length === clips.length && clips.length > 0) {
    const slotIndexByCaptionId = new Map<string, number>();
    mainSlots.forEach((slot, index) => {
      const cid = String(slot.linkedCaptionClipId || slot.linkedSubtitleClipId || '');
      if (cid) slotIndexByCaptionId.set(cid, index);
    });

    const layouts: SubtitleClipLayout[] = [];
    clips.forEach((clip, index) => {
      const cid = String(clip.id || '');
      const layoutIndex = slotIndexByCaptionId.get(cid) ?? index;
      const block = clipLayouts[layoutIndex];
      if (!block) return;
      layouts.push({
        clip,
        start: block.start,
        end: block.end,
        left: block.left,
        width: block.width,
      });
    });
    if (layouts.length > 0) return layouts;
  }

  const layouts: SubtitleClipLayout[] = [];
  for (const clip of clips) {
    const srcStart = Number(clip.start ?? 0);
    const srcEnd = Number(clip.end ?? srcStart);
    if (srcEnd <= srcStart) continue;
    let tStart: number;
    let tEnd: number;
    if (isTtsTimelineClip(clip)) {
      tStart = srcStart;
      tEnd = srcEnd;
    } else {
      const mapped = mapSourceRangeToTimeline(srcStart, srcEnd, mainSlots);
      tStart = mapped.start;
      tEnd = mapped.end;
    }
    if (tEnd <= tStart) continue;
    layouts.push({
      clip,
      start: tStart,
      end: tEnd,
      left: tStart * pxPerSec,
      width: Math.max((tEnd - tStart) * pxPerSec, 22),
    });
  }

  if (layouts.length > 0 || !clips.length) return layouts;

  const totalTimeline = mainSlots.reduce((sum, slot) => sum + Math.max(0.1, slot.duration), 0);
  for (const clip of clips) {
    const srcStart = Number(clip.start ?? 0);
    const srcEnd = Number(clip.end ?? srcStart);
    if (srcEnd <= srcStart) continue;
    const tStart = Math.max(0, srcStart);
    const tEnd = totalTimeline > 0 ? Math.min(totalTimeline, srcEnd) : srcEnd;
    if (tEnd <= tStart) continue;
    layouts.push({
      clip,
      start: tStart,
      end: tEnd,
      left: tStart * pxPerSec,
      width: Math.max((tEnd - tStart) * pxPerSec, 22),
    });
  }
  return layouts;
}

/** 将槽位字幕片段时间统一映射到时间轴绝对坐标（支持源视频绝对 / 槽内相对 / 已是时间轴坐标） */
export function resolveSegmentTimelineRange(
  slot: TemplateSlot,
  segment: SubtitleSegment,
  timelineSlotStart: number
): { start: number; end: number } | null {
  const duration = Math.max(0.1, slot.duration);
  const clipStart = slot.templateSourceStart ?? slot.clipStart ?? 0;
  const segStart = segment.start;
  const segEnd = segment.end;
  if (segEnd <= segStart) return null;

  const inSourceRange =
    segStart >= clipStart - 0.05 && segEnd <= clipStart + duration + 0.05;
  const inTimelineRange =
    segStart >= timelineSlotStart - 0.05 && segEnd <= timelineSlotStart + duration + 0.05;
  const inSlotRelativeRange = segStart >= 0 && segEnd <= duration + 0.05;

  if (inSourceRange && segStart >= clipStart - 0.01) {
    return {
      start: timelineSlotStart + (segStart - clipStart),
      end: timelineSlotStart + (segEnd - clipStart),
    };
  }

  if (inTimelineRange) {
    return { start: segStart, end: segEnd };
  }

  if (inSlotRelativeRange) {
    return {
      start: timelineSlotStart + segStart,
      end: timelineSlotStart + segEnd,
    };
  }

  return { start: timelineSlotStart, end: timelineSlotStart + duration };
}

export function buildClipLayouts(slots: TemplateSlot[], pxPerSec: number): ClipLayout[] {
  let cursor = 0;
  return slots.map((slot) => {
    const duration = Math.max(0.1, slot.duration);
    const start = cursor;
    const end = start + duration;
    cursor = end;
    const span = end - start;
    return {
      slot,
      start,
      end,
      left: start * pxPerSec,
      width: Math.max(span * pxPerSec, 28),
    };
  });
}

/** 主画面轨：仅渲染 resolveMainTimelineSlots 后的槽位。 */
export function buildMainVideoClipLayouts(
  slots: TemplateSlot[],
  subtitleClips: SubtitleClip[],
  pxPerSec: number,
): ClipLayout[] {
  return buildClipLayouts(resolveMainTimelineSlots(slots, subtitleClips), pxPerSec);
}

export function buildSubtitleSegmentLayouts(slots: TemplateSlot[], pxPerSec: number): SegmentLayout[] {
  const layouts: SegmentLayout[] = [];
  let cursor = 0;

  for (const slot of slots) {
    const duration = Math.max(0.1, slot.duration);
    const slotStart = cursor;
    const slotEnd = slotStart + duration;
    cursor = slotEnd;

    const segments = parseSubtitleSegments(slot.subtitle_segments);
    if (segments.length) {
      for (const segment of segments) {
        const mapped = resolveSegmentTimelineRange(slot, segment, slotStart);
        if (!mapped) continue;
        const segStart = Math.max(mapped.start, slotStart);
        const segEnd = Math.min(mapped.end, slotEnd);
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
        width: Math.max(duration * pxPerSec, 28),
      });
    }
  }

  return layouts;
}

/** 预览区：按时间轴 playhead 取当前应显示的字幕（优先 subtitleClips） */
export function subtitleTextAtPlayheadGlobal(
  slots: TemplateSlot[],
  playheadTime: number,
  subtitleClips?: SubtitleClip[],
): string {
  if (subtitleClips?.length) {
    const clipLayouts = buildSubtitleClipLayouts(subtitleClips, slots, 1);
    for (const layout of clipLayouts) {
      if (playheadTime >= layout.start && playheadTime < layout.end) {
        return String(layout.clip.displayText || layout.clip.text || '');
      }
    }
  }

  const segmentLayouts = buildSubtitleSegmentLayouts(slots, 1);
  for (const layout of segmentLayouts) {
    if (playheadTime >= layout.start && playheadTime < layout.end) {
      return layout.segment.text;
    }
  }

  const clipLayouts = buildClipLayouts(slots, 1);
  const active = findClipAtTime(clipLayouts, playheadTime);
  if (!active) return '';
  return subtitleTextAtPlayhead(active.slot, playheadTime, active.start);
}

/** 预览区：按时间轴 playhead 取当前槽位应显示的字幕 */
export function subtitleTextAtPlayhead(
  slot: TemplateSlot,
  playheadTime: number,
  timelineSlotStart: number
): string {
  const segments = parseSubtitleSegments(slot.subtitle_segments);
  if (segments.length) {
    for (const segment of segments) {
      const mapped = resolveSegmentTimelineRange(slot, segment, timelineSlotStart);
      if (!mapped) continue;
      if (playheadTime >= mapped.start && playheadTime < mapped.end) {
        return segment.text;
      }
    }
    return '';
  }
  const duration = Math.max(0.1, slot.duration);
  if (playheadTime >= timelineSlotStart && playheadTime < timelineSlotStart + duration) {
    return slot.subtitleText || '';
  }
  return '';
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
