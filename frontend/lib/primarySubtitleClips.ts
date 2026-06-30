import type { SubtitleClip } from '@/lib/timeline';

export type SpokenCaptionSegment = {
  id?: string;
  start?: number;
  end?: number;
  text?: string;
  source?: string;
  type?: string;
  confidence?: number;
};

export function visibleSpokenCaptions(segments: SpokenCaptionSegment[]): SpokenCaptionSegment[] {
  return segments.filter((seg) => {
    const t = String(seg.type || 'spoken_caption');
    return t !== 'screen_text' && t !== 'burned_subtitle_candidate' && t !== 'uncertain';
  });
}

/** 面板与时间轴共用：优先剪映式 subtitleClips，否则回退 ASR 主轨 */
export function resolvePrimarySubtitleClips(
  subtitleClips: SubtitleClip[],
  spokenCaptions: SpokenCaptionSegment[],
  subtitleMode: 'speech' | 'burned' = 'speech',
): SubtitleClip[] {
  if (subtitleClips.length > 0) return subtitleClips;
  if (subtitleMode !== 'speech') return [];
  return visibleSpokenCaptions(spokenCaptions).map((seg, i) => ({
    id: seg.id || `spoken-${i}`,
    start: seg.start,
    end: seg.end,
    duration:
      seg.end != null && seg.start != null ? Number(seg.end) - Number(seg.start) : undefined,
    text: seg.text,
    displayText: seg.text,
    confidence: seg.confidence,
    splitReason: 'asr_segment',
  }));
}
