import { apiHeaders, apiUrl } from '@/lib/api';

const cache = new Map<string, number[]>();

export async function fetchTemplateWaveform(templateId: string, bars = 300): Promise<number[]> {
  const key = `${templateId}:${bars}`;
  const cached = cache.get(key);
  if (cached?.length) return cached;

  try {
    const resp = await fetch(apiUrl(`/api/template/${templateId}/waveform?bars=${bars}`), {
      headers: apiHeaders(),
    });
    const data = await resp.json();
    if (!resp.ok || !Array.isArray(data.peaks)) return [];
    cache.set(key, data.peaks);
    return data.peaks as number[];
  } catch {
    return [];
  }
}

/** 从完整波形中截取某时间段对应的峰值条 */
export function sliceWaveformPeaks(
  peaks: number[],
  totalDuration: number,
  start: number,
  end: number,
  minBars = 12
): number[] {
  if (!peaks.length || totalDuration <= 0 || end <= start) return [];
  const startIdx = Math.floor((start / totalDuration) * peaks.length);
  const endIdx = Math.max(startIdx + 1, Math.ceil((end / totalDuration) * peaks.length));
  const slice = peaks.slice(startIdx, endIdx);
  if (slice.length >= minBars) return slice;
  if (!slice.length) return [];
  const step = slice.length / minBars;
  return Array.from({ length: minBars }, (_, i) => slice[Math.min(slice.length - 1, Math.floor(i * step))] ?? 0.2);
}
