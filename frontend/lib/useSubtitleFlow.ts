import type { Dispatch, SetStateAction } from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { resolvePrimarySubtitleClips } from '@/lib/primarySubtitleClips';
import {
  apiHeaders,
  apiUrl,
  formatApiDetail,
  longRunningApiUrl,
  readApiJson,
  SUBTITLE_BATCH_CHUNK_SIZE,
} from '@/lib/api';
import { enrichSlotsWithDuplicateStatus } from '@/lib/subtitleStatus';
import { getSlotSourceTimeRange } from '@/lib/slotEdit';
import { slotsWillBeOverwrittenByAiSplit } from '@/lib/slotTimelineHelpers';
import type { SubtitleClip, TemplateSlot, TtsSegment } from '@/lib/timeline';
import { timelineToSlots } from '@/lib/timeline';

type SpokenCaptionSegment = {
  id?: string;
  start?: number;
  end?: number;
  text?: string;
  source?: string;
  type?: string;
  confidence?: number;
  effectProfileId?: string;
  renderHints?: Record<string, unknown>;
  debug?: Record<string, unknown>;
};

type BatchResult = {
  slot_id?: string | number;
  slotId?: string | number;
  start?: number;
  end?: number;
  success?: boolean;
  status?: 'matched' | 'no_speech' | 'no_overlap' | 'filtered' | 'error';
  reason?: string;
  linkedSubtitleSegmentIds?: string[];
  subtitle_text?: string;
  subtitle_segments?: unknown[];
  subtitle_visual_context?: string;
  subtitle_scene_match?: number;
  subtitle_scene_match_reason?: string;
  subtitle_effect_label?: string;
  subtitle_style?: import('@/lib/slotEdit').SubtitleStyle;
  ai_effect_understanding?: import('@/lib/timeline').AiEffectUnderstanding;
  applied_effect_presets?: string[];
  ai_description?: string;
  ai_subject?: string;
  scene_tags?: string[];
  error?: string;
  source?: string;
  subtitle_quality?: TemplateSlot['subtitle_quality'];
  subtitle_status_reason?: string;
  subtitle_duplicate?: boolean;
};

type CaptionsResponse = {
  success?: boolean;
  subtitleClips?: SubtitleClip[];
  validatedCaptionClips?: SubtitleClip[];
  asrClips?: SubtitleClip[];
  subtitleClipCount?: number;
  validatedCaptionClipCount?: number;
  rawAsrClipCount?: number;
  needsReviewCount?: number;
  slots?: Record<string, unknown>[];
  slotCount?: number;
  cutStrategy?: string;
  phase?: string;
  captionRecognitionDebug?: Record<string, unknown>;
  captionSlotDebug?: Record<string, unknown>;
  spoken_captions?: SpokenCaptionSegment[];
  spokenCaptionSegments?: SpokenCaptionSegment[];
  segments?: SpokenCaptionSegment[];
  debug?: Record<string, unknown>;
  subtitleClipDebug?: Record<string, unknown>;
  pipelineDebug?: Record<string, unknown>;
  summary?: {
    subtitleClipCount?: number;
    needsReviewCount?: number;
    slotCount?: number;
    cutStrategy?: string;
    rawAsrSegmentCount?: number;
    rawAsrClipCount?: number;
    validatedCaptionClipCount?: number;
    ocrSplitCount?: number;
    ocrMergeCount?: number;
  };
};

type ApplyCaptionSlotsResponse = {
  success?: boolean;
  slotCount?: number;
  subtitleClipCount?: number;
  slots?: Record<string, unknown>[];
  subtitleClips?: SubtitleClip[];
  captionSlotDebug?: Record<string, unknown>;
  aiSplitDebug?: Record<string, unknown>;
  visualSplitDebug?: Record<string, unknown>;
  oneCaptionOneShotDebug?: Record<string, unknown>;
  overwriteWarning?: string;
  reviewWarning?: string;
  ttsWarning?: string;
  pipelineDebug?: Record<string, unknown>;
  summary?: {
    slotCount?: number;
    subtitleClipCount?: number;
    captionClipCount?: number;
    ttsWarning?: string;
    usedTtsAlignedTime?: boolean;
  };
};

type TtsResponse = {
  success?: boolean;
  ttsSegments?: TtsSegment[];
  subtitleClips?: SubtitleClip[];
  summary?: { generatedCount?: number; failedCount?: number; captionClipCount?: number; voiceId?: string };
  pipelineDebug?: Record<string, unknown>;
};

type AlignTimelineResponse = {
  success?: boolean;
  alignedCaptionClips?: SubtitleClip[];
  subtitleClips?: SubtitleClip[];
  ttsSegments?: TtsSegment[];
  totalDuration?: number;
  pipelineDebug?: Record<string, unknown>;
};

type VoiceProfile = {
  voiceId?: string;
  displayName?: string;
  language?: string;
  gender?: string;
  style?: string;
  provider?: string;
};

type BatchResponse = {
  results?: BatchResult[];
  spoken_captions?: SpokenCaptionSegment[];
  segments?: SpokenCaptionSegment[];
  subtitleClips?: SubtitleClip[];
  debug?: Record<string, unknown>;
  subtitleSplitDebug?: Record<string, unknown>;
  subtitleClipDebug?: Record<string, unknown>;
  summary?: {
    mode?: string;
    slotCount?: number;
    matchedSlotCount?: number;
    emptySlotCount?: number;
    errorSlotCount?: number;
    subtitleClipCount?: number;
    rawAsrSegmentCount?: number;
    finalAsrSegmentCount?: number;
    droppedSegmentCount?: number;
  };
};

type UseSubtitleFlowOptions = {
  templateId: string | null;
  slots: TemplateSlot[];
  setSlots: Dispatch<SetStateAction<TemplateSlot[]>>;
  onAfterAiSplit?: () => void | Promise<void>;
};

function applyBatchResults(setSlots: UseSubtitleFlowOptions['setSlots'], results: BatchResult[]) {
  const resultMap = new Map<string, BatchResult>();
  for (const r of results) {
    if (r.slot_id != null) resultMap.set(String(r.slot_id), r);
    if (r.slotId != null) resultMap.set(String(r.slotId), r);
  }
  setSlots((prev) => {
    const merged = prev.map((slot) => {
      const hit =
        resultMap.get(String(slot.id)) || resultMap.get(String(slot.originalSlotId ?? ''));
      if (!hit) return slot;
      const status = hit.status;
      const text = String(hit.subtitle_text || '').trim();
      let nextText = slot.subtitleText;
      if (status === 'matched') {
        nextText = hit.subtitle_text || '';
      } else if (status === 'no_speech' || status === 'no_overlap' || status === 'filtered') {
        nextText = '';
      } else if (text && status !== 'error') {
        nextText = hit.subtitle_text || slot.subtitleText;
      }
      return {
        ...slot,
        subtitleText: nextText,
        subtitle_segments:
          status === 'no_speech' || status === 'no_overlap' || status === 'filtered'
            ? hit.subtitle_segments || []
            : status === 'matched'
              ? hit.subtitle_segments || slot.subtitle_segments
              : slot.subtitle_segments,
        subtitle_source: hit.source ?? slot.subtitle_source,
        subtitle_quality: hit.subtitle_quality ?? slot.subtitle_quality,
        subtitle_status_reason: hit.reason ?? hit.subtitle_status_reason ?? hit.error ?? slot.subtitle_status_reason,
        subtitle_duplicate: hit.subtitle_duplicate ?? slot.subtitle_duplicate,
        subtitle_visual_context: hit.subtitle_visual_context ?? slot.subtitle_visual_context,
        subtitle_scene_match: hit.subtitle_scene_match ?? slot.subtitle_scene_match,
        subtitle_scene_match_reason:
          hit.subtitle_scene_match_reason ?? slot.subtitle_scene_match_reason,
        subtitle_effect_label: hit.subtitle_effect_label ?? slot.subtitle_effect_label,
        subtitle_style: hit.subtitle_style ?? slot.subtitle_style,
        ai_effect_understanding: hit.ai_effect_understanding ?? slot.ai_effect_understanding,
        applied_effect_presets: hit.applied_effect_presets ?? slot.applied_effect_presets,
        ai_description: hit.ai_description ?? slot.ai_description,
        ai_subject: hit.ai_subject ?? slot.ai_subject,
        scene_tags: hit.scene_tags?.length ? hit.scene_tags : slot.scene_tags,
      };
    });
    return enrichSlotsWithDuplicateStatus(merged);
  });
}

function hydrateFromTemplatePayload(data: Record<string, unknown>): {
  spoken: SpokenCaptionSegment[];
  clips: SubtitleClip[];
  tts: TtsSegment[];
} {
  const spokenRaw =
    (data.spokenCaptionSegments as SpokenCaptionSegment[] | undefined) ||
    (data.segments_json as SpokenCaptionSegment[] | undefined) ||
    (data.segments as SpokenCaptionSegment[] | undefined) ||
    [];
  const spoken = spokenRaw.filter((seg) => {
    const t = String(seg.type || 'spoken_caption');
    return t !== 'screen_text' && t !== 'burned_subtitle_candidate' && t !== 'uncertain';
  });
  const clips =
    (data.validatedCaptionClips as SubtitleClip[] | undefined) ||
    (data.subtitleClips as SubtitleClip[] | undefined) ||
    (data.subtitle_clips_json as SubtitleClip[] | undefined) ||
    [];
  const tts =
    (data.ttsSegments as TtsSegment[] | undefined) ||
    (data.tts_segments_json as TtsSegment[] | undefined) ||
    [];
  return { spoken, clips, tts };
}

async function ensureSubtitleBackendReady(): Promise<void> {
  const resp = await fetch(apiUrl('/api/export/capcut-status'), {
    headers: apiHeaders(),
    cache: 'no-store',
  });
  if (!resp.ok) {
    throw new Error('backend 未就绪，请执行 scripts/restart-all.ps1 重启服务后重试');
  }
  try {
    await resp.json();
  } catch {
    throw new Error('服务器响应无效，请执行 scripts/restart-all.ps1 重启 backend 与 frontend');
  }
}

export function useSubtitleFlow({ templateId, slots, setSlots, onAfterAiSplit }: UseSubtitleFlowOptions) {
  const [recognizingAllSubtitles, setRecognizingAllSubtitles] = useState(false);
  const [recognizeProgress, setRecognizeProgress] = useState<string>('');
  const [subtitleMode, setSubtitleMode] = useState<'speech' | 'burned'>('speech');
  const [spokenCaptions, setSpokenCaptions] = useState<SpokenCaptionSegment[]>([]);
  const [subtitleClips, setSubtitleClips] = useState<SubtitleClip[]>([]);
  const [cutStrategy, setCutStrategy] = useState<string>('caption_slot');
  const [applyingCaptionSlots, setApplyingCaptionSlots] = useState(false);
  const [recognitionDebug, setRecognitionDebug] = useState<Record<string, unknown> | null>(null);
  const [ttsSegments, setTtsSegments] = useState<TtsSegment[]>([]);
  const [voiceProfiles, setVoiceProfiles] = useState<VoiceProfile[]>([]);
  const [selectedVoiceId, setSelectedVoiceId] = useState<string>('real_blog_female');
  const [generatingTts, setGeneratingTts] = useState(false);
  const [aligningTimeline, setAligningTimeline] = useState(false);
  const [pipelineDebug, setPipelineDebug] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const resp = await fetch(apiUrl('/api/template/voices/list'), {
          headers: apiHeaders(),
          cache: 'no-store',
        });
        const data = await resp.json();
        if (resp.ok) {
          const profiles = (data.voiceProfiles || data.voices || []) as VoiceProfile[];
          setVoiceProfiles(profiles);
          if (profiles[0]?.voiceId) setSelectedVoiceId(String(profiles[0].voiceId));
        }
      } catch {
        setVoiceProfiles([{ voiceId: 'real_blog_female', displayName: '真人博客女', provider: 'mock' }]);
      }
    })();
  }, []);

  useEffect(() => {
    if (!templateId) {
      setSpokenCaptions([]);
      setSubtitleClips([]);
      setTtsSegments([]);
      setRecognitionDebug(null);
      setPipelineDebug(null);
      return;
    }
    void (async () => {
      try {
        const resp = await fetch(apiUrl(`/api/template/${templateId}`), {
          headers: apiHeaders(),
          cache: 'no-store',
        });
        const data = await resp.json();
        if (!resp.ok) return;
        const { spoken, clips, tts } = hydrateFromTemplatePayload(data as Record<string, unknown>);
        setSpokenCaptions(spoken);
        setSubtitleClips(clips);
        setTtsSegments(tts);
        if (data.pipelineDebug) setPipelineDebug(data.pipelineDebug as Record<string, unknown>);
        if (data.voiceId) setSelectedVoiceId(String(data.voiceId));
        const strategy = String(data.cutStrategy || data.cut_strategy || 'caption_slot');
        setCutStrategy(strategy);
      } catch {
        /* ignore */
      }
    })();
  }, [templateId]);

  const runRecognizeSpeechCaptions = useCallback(async () => {
    if (!templateId) {
      alert('请先上传模板');
      return { recognized: 0, total: 0, failed: 0 };
    }

    setRecognizingAllSubtitles(true);
    setRecognizeProgress('ASR 切句 → OCR 校验边界与文本…');

    try {
      await ensureSubtitleBackendReady();

      const resp = await fetch(longRunningApiUrl('/api/subtitle/recognize-captions'), {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({
          template_id: templateId,
          mode: 'speech',
          force: true,
          quality: false,
        }),
      });
      const data = (await readApiJson(resp)) as CaptionsResponse;
      if (!resp.ok) {
        throw new Error(formatApiDetail((data as { detail?: unknown }).detail, '字幕识别失败'));
      }

      setRecognizeProgress('生成 validatedCaptionClips…');

      const clips =
        data.validatedCaptionClips ||
        data.subtitleClips ||
        [];
      const spoken =
        data.spokenCaptionSegments || data.spoken_captions || data.segments || spokenCaptions;
      setSubtitleClips(clips);
      if (spoken.length) setSpokenCaptions(spoken);
      if (data.cutStrategy) setCutStrategy(data.cutStrategy);
      if (data.debug || data.subtitleClipDebug || data.captionRecognitionDebug) {
        setRecognitionDebug({
          ...(data.debug || {}),
          subtitleClipDebug: data.subtitleClipDebug,
          captionRecognitionDebug: data.captionRecognitionDebug,
          rawAsrClipCount: data.rawAsrClipCount ?? data.summary?.rawAsrClipCount,
          validatedCaptionClipCount:
            data.validatedCaptionClipCount ?? data.summary?.validatedCaptionClipCount,
          ocrSplitCount: data.summary?.ocrSplitCount,
          ocrMergeCount: data.summary?.ocrMergeCount,
        });
      }
      if (data.pipelineDebug) setPipelineDebug(data.pipelineDebug as Record<string, unknown>);

      const clipCount =
        data.validatedCaptionClipCount ??
        data.subtitleClipCount ??
        data.summary?.validatedCaptionClipCount ??
        data.summary?.subtitleClipCount ??
        clips.length;
      const rawAsrCount = data.rawAsrClipCount ?? data.summary?.rawAsrClipCount;
      const needsReview =
        data.needsReviewCount ?? data.summary?.needsReviewCount ?? 0;
      const ocrSplit = data.summary?.ocrSplitCount ?? 0;
      const ocrMerge = data.summary?.ocrMergeCount ?? 0;

      if (clipCount === 0) {
        alert('识别完成，但未检测到清晰口播字幕。');
      } else {
        const parts = [`识别完成：生成 ${clipCount} 句校验字幕。`];
        if (rawAsrCount != null && rawAsrCount !== clipCount) {
          parts.push(`（ASR 初切 ${rawAsrCount} 句 → OCR 校验后 ${clipCount} 句）`);
        }
        if (ocrSplit > 0 || ocrMerge > 0) {
          parts.push(`OCR 校验：拆分 ${ocrSplit} 处，合并 ${ocrMerge} 处。`);
        }
        if (needsReview > 0) {
          parts.push(`其中 ${needsReview} 句建议检查（ASR/OCR 不一致或无 OCR 校验）。`);
        }
        alert(parts.join('\n'));
      }
      setRecognizeProgress('完成');

      return {
        recognized: clipCount,
        total: clipCount,
        failed: 0,
        empty: 0,
      };
    } catch (err) {
      alert(err instanceof Error ? err.message : '字幕识别失败');
      setRecognizeProgress('');
      return { recognized: 0, total: 0, failed: 0 };
    } finally {
      setRecognizingAllSubtitles(false);
    }
  }, [templateId, spokenCaptions]);

  const saveSubtitleClips = useCallback(
    async (clips: SubtitleClip[]) => {
      if (!templateId) return false;
      try {
        const resp = await fetch(apiUrl('/api/subtitle/subtitle-clips'), {
          method: 'POST',
          headers: apiHeaders(),
          body: JSON.stringify({ template_id: templateId, subtitle_clips: clips }),
        });
        const data = await readApiJson(resp);
        if (!resp.ok) {
          throw new Error(formatApiDetail((data as { detail?: unknown }).detail, '保存字幕失败'));
        }
        setSubtitleClips(clips);
        return true;
      } catch (err) {
        alert(err instanceof Error ? err.message : '保存字幕失败');
        return false;
      }
    },
    [templateId]
  );

  const applyCaptionSlots = useCallback(async () => {
    if (!templateId) {
      alert('请先上传模板');
      return;
    }
    if (!subtitleClips.length) {
      alert('请先识别字幕');
      return;
    }

    if (slotsWillBeOverwrittenByAiSplit(slots)) {
      const ok = window.confirm('AI 一键分割画面会覆盖当前画面槽，是否继续？');
      if (!ok) return;
    }

    setApplyingCaptionSlots(true);
    try {
      await ensureSubtitleBackendReady();
      const resp = await fetch(
        longRunningApiUrl(`/api/template/${templateId}/ai-split-by-captions`),
        {
          method: 'POST',
          headers: apiHeaders(),
          body: JSON.stringify({
            source: 'caption_clips',
            overwriteSlots: true,
            useTtsAlignedTime: true,
            mergeShortFragments: true,
            subtitleClips: subtitleClips,
          }),
        }
      );
      const data = (await readApiJson(resp)) as ApplyCaptionSlotsResponse;
      if (!resp.ok) {
        throw new Error(formatApiDetail((data as { detail?: unknown }).detail, 'AI 分割画面失败'));
      }
      if (Array.isArray(data.slots) && data.slots.length > 0) {
        setSlots(timelineToSlots(data.slots));
      }
      if (data.subtitleClips?.length) {
        setSubtitleClips(data.subtitleClips);
      }
      if (data.pipelineDebug) setPipelineDebug(data.pipelineDebug as Record<string, unknown>);
      if (data.oneCaptionOneShotDebug) {
        setPipelineDebug((prev) => ({
          ...(prev || {}),
          oneCaptionOneShotDebug: data.oneCaptionOneShotDebug,
        }));
      }
      const slotCount =
        data.slotCount ??
        data.summary?.slotCount ??
        data.aiSplitDebug?.slotCount ??
        data.slots?.length ??
        0;
      const clipCount =
        data.subtitleClipCount ??
        data.summary?.captionClipCount ??
        data.aiSplitDebug?.normalizedCaptionClipCount ??
        subtitleClips.length;
      const parts = [`已根据 ${clipCount} 句字幕生成 ${slotCount} 个画面槽。`];
      if (data.reviewWarning) parts.push(data.reviewWarning);
      if (data.overwriteWarning) parts.push(data.overwriteWarning);
      if (data.ttsWarning) parts.push(data.ttsWarning);
      alert(parts.join('\n\n'));
      await onAfterAiSplit?.();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'AI 分割画面失败');
    } finally {
      setApplyingCaptionSlots(false);
    }
  }, [templateId, subtitleClips, slots, setSlots, onAfterAiSplit]);

  const applyVisualSceneSlots = useCallback(async () => {
    if (!templateId) {
      alert('请先上传模板');
      return;
    }

    if (slotsWillBeOverwrittenByAiSplit(slots)) {
      const ok = window.confirm('按原视频画面切分会覆盖当前画面槽，是否继续？');
      if (!ok) return;
    }

    setApplyingCaptionSlots(true);
    try {
      await ensureSubtitleBackendReady();
      const resp = await fetch(
        longRunningApiUrl(`/api/template/${templateId}/ai-split-by-visual`),
        {
          method: 'POST',
          headers: apiHeaders(),
          body: JSON.stringify({
            overwriteSlots: true,
            skipAiRefine: false,
            subtitleClips: subtitleClips.length ? subtitleClips : undefined,
          }),
        }
      );
      const data = (await readApiJson(resp)) as ApplyCaptionSlotsResponse;
      if (!resp.ok) {
        throw new Error(formatApiDetail((data as { detail?: unknown }).detail, '画面镜头切分失败'));
      }
      if (Array.isArray(data.slots) && data.slots.length > 0) {
        setSlots(timelineToSlots(data.slots));
      }
      if (data.subtitleClips?.length) {
        setSubtitleClips(data.subtitleClips);
      }
      if (data.pipelineDebug) setPipelineDebug(data.pipelineDebug as Record<string, unknown>);
      const slotCount = data.slotCount ?? data.slots?.length ?? 0;
      const shotCount =
        (data.visualSplitDebug as { visualShotCount?: number } | undefined)?.visualShotCount ??
        (data.aiSplitDebug as { visualShotCount?: number } | undefined)?.visualShotCount ??
        slotCount;
      const parts = [`已按原视频画面切分为 ${shotCount} 个镜头槽（共 ${slotCount} 段）。`];
      if (data.overwriteWarning) parts.push(data.overwriteWarning);
      alert(parts.join('\n\n'));
      await onAfterAiSplit?.();
    } catch (err) {
      alert(err instanceof Error ? err.message : '画面镜头切分失败');
    } finally {
      setApplyingCaptionSlots(false);
    }
  }, [templateId, subtitleClips, slots, setSlots, onAfterAiSplit]);

  const generateTts = useCallback(async () => {
    if (!templateId) {
      alert('请先上传模板');
      return;
    }
    if (!subtitleClips.length) {
      alert('请先识别字幕');
      return;
    }
    setGeneratingTts(true);
    try {
      await ensureSubtitleBackendReady();
      const resp = await fetch(longRunningApiUrl(`/api/template/${templateId}/generate-tts`), {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({ voiceId: selectedVoiceId, clipIds: [], overwrite: false }),
      });
      const data = (await readApiJson(resp)) as TtsResponse;
      if (!resp.ok) {
        throw new Error(formatApiDetail((data as { detail?: unknown }).detail, 'AI 人声生成失败'));
      }
      if (data.ttsSegments?.length) setTtsSegments(data.ttsSegments);
      if (data.subtitleClips?.length) setSubtitleClips(data.subtitleClips);
      if (data.pipelineDebug) setPipelineDebug(data.pipelineDebug);
      const count = data.summary?.generatedCount ?? data.ttsSegments?.length ?? 0;
      alert(`已生成 ${count} 段人声音频。`);
    } catch (err) {
      alert(err instanceof Error ? err.message : 'AI 人声生成失败');
    } finally {
      setGeneratingTts(false);
    }
  }, [templateId, subtitleClips.length, selectedVoiceId]);

  const alignTimelineToTts = useCallback(async () => {
    if (!templateId) {
      alert('请先上传模板');
      return;
    }
    if (!ttsSegments.length) {
      alert('请先生成 AI 人声');
      return;
    }
    setAligningTimeline(true);
    try {
      await ensureSubtitleBackendReady();
      const resp = await fetch(longRunningApiUrl(`/api/template/${templateId}/align-timeline-to-tts`), {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({}),
      });
      const data = (await readApiJson(resp)) as AlignTimelineResponse;
      if (!resp.ok) {
        throw new Error(formatApiDetail((data as { detail?: unknown }).detail, '时间线对齐失败'));
      }
      const clips = data.alignedCaptionClips || data.subtitleClips;
      if (clips?.length) setSubtitleClips(clips);
      if (data.ttsSegments?.length) setTtsSegments(data.ttsSegments);
      if (data.pipelineDebug) setPipelineDebug(data.pipelineDebug);
      alert('字幕轨和 AI 人声轨已按音频时长对齐。');
    } catch (err) {
      alert(err instanceof Error ? err.message : '时间线对齐失败');
    } finally {
      setAligningTimeline(false);
    }
  }, [templateId, ttsSegments.length]);

  const updateSubtitleClipAt = useCallback(
    (index: number, patch: Partial<SubtitleClip>) => {
      setSubtitleClips((prev) => {
        const next = prev.map((c, i) => (i === index ? { ...c, ...patch } : c));
        void saveSubtitleClips(next);
        return next;
      });
    },
    [saveSubtitleClips]
  );

  const runRecognizeBurnedBatch = useCallback(async () => {
    if (!templateId || !slots.length) {
      alert('请先上传模板');
      return { recognized: 0, total: 0, failed: 0 };
    }

    setRecognizingAllSubtitles(true);
    setRecognizeProgress('画面 OCR 识别…');

    try {
      await ensureSubtitleBackendReady();

      const payload = slots
        .map((slot) => {
          const range = getSlotSourceTimeRange(slot);
          if (!range || range.end <= range.start) return null;
          return {
            slot_id: String(slot.originalSlotId ?? slot.id),
            slot_start: range.start,
            slot_end: range.end,
          };
        })
        .filter(Boolean) as Array<{ slot_id: string; slot_start: number; slot_end: number }>;

      if (!payload.length) {
        alert('没有可识别的槽位');
        return { recognized: 0, total: 0, failed: 0 };
      }

      const allResults: BatchResult[] = [];
      for (let i = 0; i < payload.length; i += SUBTITLE_BATCH_CHUNK_SIZE) {
        const chunk = payload.slice(i, i + SUBTITLE_BATCH_CHUNK_SIZE);
        const resp = await fetch(longRunningApiUrl('/api/subtitle/recognize-slot-batch'), {
          method: 'POST',
          headers: apiHeaders(),
          body: JSON.stringify({
            template_id: templateId,
            slots: chunk,
            mode: 'burned',
            force: true,
            quality: false,
          }),
        });
        const data = (await readApiJson(resp)) as BatchResponse;
        if (!resp.ok) {
          throw new Error(formatApiDetail((data as { detail?: unknown }).detail, '字幕识别失败'));
        }
        allResults.push(...(data.results || []));
        applyBatchResults(setSlots, data.results || []);
      }

      const matched = allResults.filter((r) => r.status === 'matched').length;
      alert(`识别完成：${matched} 个槽位匹配到画面字幕`);
      setRecognizeProgress('完成');
      return { recognized: matched, total: payload.length, failed: 0 };
    } catch (err) {
      alert(err instanceof Error ? err.message : '字幕识别失败');
      setRecognizeProgress('');
      return { recognized: 0, total: 0, failed: 0 };
    } finally {
      setRecognizingAllSubtitles(false);
    }
  }, [templateId, slots, setSlots]);

  const runRecognizeAll = useCallback(async () => {
    if (subtitleMode === 'burned') {
      return runRecognizeBurnedBatch();
    }
    return runRecognizeSpeechCaptions();
  }, [subtitleMode, runRecognizeBurnedBatch, runRecognizeSpeechCaptions]);

  const resolvedSubtitleClips = useMemo(
    () => resolvePrimarySubtitleClips(subtitleClips, spokenCaptions, subtitleMode),
    [subtitleClips, spokenCaptions, subtitleMode]
  );

  return {
    recognizingAllSubtitles,
    recognizeProgress,
    subtitleMode,
    setSubtitleMode,
    spokenCaptions,
    subtitleClips: resolvedSubtitleClips,
    cutStrategy,
    applyingCaptionSlots,
    recognitionDebug,
    ttsSegments,
    voiceProfiles,
    selectedVoiceId,
    setSelectedVoiceId,
    generatingTts,
    aligningTimeline,
    pipelineDebug,
    runRecognizeAll,
    applyCaptionSlots,
    applyVisualSceneSlots,
    generateTts,
    alignTimelineToTts,
    saveSubtitleClips,
    updateSubtitleClipAt,
  };
}
