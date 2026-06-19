import type { TemplateSlot } from './timeline';

export type SubtitleStyle = {
  text_color?: string;
  outline_color?: string;
  font_size?: number;
  position?: string;
  animation_in?: string;
  animation_out?: string;
  style_label?: string;
  confidence?: number;
};

export type SubtitleSegment = {
  start: number;
  end: number;
  text: string;
  style?: SubtitleStyle;
};

export type SfxMarker = {
  time: number;
  duration?: number;
  type?: string;
  confidence?: number;
  energy?: number;
};

const ANIMATION_LABELS: Record<string, string> = {
  fade: '淡入',
  fade_up: '上滑',
  fade_down: '下滑',
  bounce: '弹跳',
  scale: '缩放',
  none: '无',
};

const SFX_LABELS: Record<string, string> = {
  whoosh: '嗖',
  swoosh: '嗖',
  ding: '叮',
  click: '点击',
  impact: '撞击',
  thump: '咚',
  sfx: '音效',
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
      const styleRaw = seg.style;
      const style =
        styleRaw && typeof styleRaw === 'object'
          ? (styleRaw as SubtitleStyle)
          : undefined;
      return { start, end, text, style };
    })
    .filter((s): s is SubtitleSegment => s !== null);
}

export function describeSubtitleStyle(style?: SubtitleStyle): string {
  if (!style) return '未识别样式（默认白字）';
  const parts: string[] = [];
  if (style.text_color) parts.push(`字色 ${style.text_color}`);
  if (style.outline_color) parts.push(`描边 ${style.outline_color}`);
  if (style.animation_in) {
    parts.push(`入场 ${ANIMATION_LABELS[style.animation_in] || style.animation_in}`);
  }
  if (style.style_label) parts.push(style.style_label);
  return parts.join(' · ') || '已识别样式';
}

export function describeSfxMarker(marker: SfxMarker): string {
  const label = SFX_LABELS[marker.type || 'sfx'] || marker.type || '音效';
  return `${label} @ ${marker.time.toFixed(2)}s`;
}

export function getSlotRange(slot: TemplateSlot, fallbackStart: number): { start: number; end: number } {
  const start = slot.slotStart ?? fallbackStart;
  const duration = Math.max(0.1, slot.duration);
  const end = start + duration;
  if (slot.slotEnd != null && Math.abs(slot.slotEnd - end) <= 0.05) {
    return { start, end: slot.slotEnd };
  }
  return { start, end };
}

/** 槽位在模板源视频/人声上的起止时间（用于 Whisper 识别） */
export function getSlotSourceTimeRange(slot: TemplateSlot): { start: number; end: number } {
  const start = Math.max(0, Number(slot.clipStart ?? slot.slotStart ?? 0));
  const duration = Math.max(0.1, Number(slot.clip_duration ?? slot.duration ?? 0.1));
  return { start, end: start + duration };
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

export function getSlotSourceTimeRangeById(
  slots: TemplateSlot[],
  slotId: string
): { start: number; end: number } | null {
  const slot = slots.find((s) => s.id === slotId);
  if (!slot) return null;
  const range = getSlotSourceTimeRange(slot);
  if (range.end <= range.start) return null;
  return range;
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
