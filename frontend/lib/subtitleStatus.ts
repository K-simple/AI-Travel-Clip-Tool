import type { TemplateSlot } from '@/lib/timeline';

export type SubtitleQualityLevel = 'ok' | 'low' | 'empty';

/** 与后端 SUBTITLE_DUPLICATE_* 对齐 */
export const SUBTITLE_DUPLICATE_MIN_CHARS = 8;
export const SUBTITLE_DUPLICATE_SIMILARITY = 0.88;

const SOURCE_LABELS: Record<string, string> = {
  none: '无',
  whisper: '人声',
  whisper_low_quality: '人声（低质量）',
  visual: '画面',
  visual_primary: '画面（主）',
  visual_audio_fallback: '画面（人声不可用）',
  visual_fallback: '画面（回退）',
  visual_timeline: '画面（时间轴）',
  hybrid_visual: '融合（偏画面）',
  hybrid_whisper: '融合（偏人声）',
};

export function labelSubtitleSource(source?: string | null): string {
  const key = String(source || 'none').trim() || 'none';
  return SOURCE_LABELS[key] || key;
}

export function labelSubtitleQuality(quality?: string | null): string {
  switch (quality) {
    case 'ok':
      return '正常';
    case 'low':
      return '质量偏低';
    case 'empty':
      return '未识别';
    default:
      return quality ? String(quality) : '未知';
  }
}

export function subtitleQualityTone(quality?: string | null): 'ok' | 'warn' | 'bad' {
  if (quality === 'ok') return 'ok';
  if (quality === 'low') return 'warn';
  return 'bad';
}

export function summarizeSubtitleSlots(slots: TemplateSlot[]) {
  let ok = 0;
  let low = 0;
  let empty = 0;
  for (const slot of slots) {
    const q = slot.subtitle_quality;
    const hasText = Boolean(String(slot.subtitleText || '').trim());
    if (q === 'ok' || (!q && hasText)) ok += 1;
    else if (q === 'low') low += 1;
    else if (q === 'empty' || !hasText) empty += 1;
    else if (hasText) ok += 1;
    else empty += 1;
  }
  return { ok, low, empty, total: slots.length };
}

export function slotSubtitleAttentionLevel(
  slot: TemplateSlot | null | undefined
): 'none' | 'warn' | 'bad' {
  if (!slot) return 'none';
  if (slot.subtitle_duplicate) return 'bad';
  if (slot.subtitle_quality === 'empty') return 'bad';
  const reason = String(slot.subtitle_status_reason || '');
  if (reason.includes('重复')) return 'bad';
  if (slot.subtitle_quality === 'low') return 'warn';
  return 'none';
}

export function slotSubtitleWarning(slot: TemplateSlot | null | undefined): string {
  if (!slot) return '';
  if (slot.subtitle_status_reason) return slot.subtitle_status_reason;
  if (!String(slot.subtitleText || '').trim()) return '本槽位暂无字幕，可重识别或手填';
  return '';
}

const MIN_DUP_CHARS = SUBTITLE_DUPLICATE_MIN_CHARS;
const DUP_SIMILARITY = SUBTITLE_DUPLICATE_SIMILARITY;

function charCount(text: string): number {
  return text.replace(/\s+/g, '').length;
}

/** 与 Python difflib SequenceMatcher.ratio 一致：2*LCS/(len(a)+len(b)) */
export function textSimilarity(a: string, b: string): number {
  const ta = String(a || '').trim().replace(/\s+/g, '');
  const tb = String(b || '').trim().replace(/\s+/g, '');
  if (!ta || !tb) return 0;
  if (ta === tb) return 1;
  const rows = ta.length + 1;
  const cols = tb.length + 1;
  let prev = new Array<number>(cols).fill(0);
  let curr = new Array<number>(cols).fill(0);
  for (let i = 1; i < rows; i += 1) {
    curr[0] = 0;
    for (let j = 1; j < cols; j += 1) {
      if (ta[i - 1] === tb[j - 1]) {
        curr[j] = prev[j - 1] + 1;
      } else {
        curr[j] = Math.max(prev[j], curr[j - 1]);
      }
    }
    [prev, curr] = [curr, prev];
  }
  const lcs = prev[tb.length];
  return (2 * lcs) / (ta.length + tb.length);
}

/** 与后端 count_near_duplicate_peers 对齐：≥8 字 + 精确或 fuzzy≥0.88 */
export function countDuplicatePeers(text: string, peerTexts: string[]): number {
  const target = String(text || '').trim();
  if (!target || charCount(target) < MIN_DUP_CHARS) return 0;
  let count = 0;
  for (const peer of peerTexts) {
    const peerText = String(peer || '').trim();
    if (!peerText) continue;
    if (peerText === target) {
      count += 1;
    } else if (textSimilarity(target, peerText) >= DUP_SIMILARITY) {
      count += 1;
    }
  }
  return count;
}

/** 批量刷新后在前端重算跨槽重复（不依赖后端逐条返回 subtitle_duplicate） */
export function enrichSlotsWithDuplicateStatus(slots: TemplateSlot[]): TemplateSlot[] {
  const peerTexts: string[] = [];
  return slots.map((slot) => {
    const text = String(slot.subtitleText || '').trim();
    const dup = text ? countDuplicatePeers(text, peerTexts) >= 1 : false;
    if (text) peerTexts.push(text);

    if (!dup) return slot;

    const reason =
      slot.subtitle_status_reason?.includes('重复')
        ? slot.subtitle_status_reason
        : '与其他槽位字幕重复，请核对切分或手改';

    return {
      ...slot,
      subtitle_duplicate: true,
      subtitle_quality: slot.subtitle_quality === 'empty' ? 'empty' : 'low',
      subtitle_status_reason: reason,
    };
  });
}
