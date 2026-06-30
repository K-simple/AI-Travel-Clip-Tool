import { useCallback, useEffect, useRef, useState } from 'react';
import { apiHeaders, apiUrl } from '@/lib/api';
import { templateStatusPollMs } from '@/lib/deviceProfile';
import type { PreviewProxyPaths } from '@/lib/previewSettings';

export type TemplateAiVision = {
  summary?: string;
  style?: string;
  pacing?: string;
  mood?: string;
  narrative?: string;
  replace_guide?: string;
};

export type TemplateProcessingState = {
  status: string;
  progress: number;
  enhanceStatus: string;
  enhanceProgress: number;
  editable: boolean;
  audioReady: boolean;
  subtitleReady: boolean;
  beatMarkers: number[];
  sfxMarkers: import('@/lib/slotEdit').SfxMarker[];
  slotCount: number;
  slotsAiReadyCount: number;
  slotsSubtitleReadyCount: number;
  subtitleBatchRunning: boolean;
  subtitleRecognitionMode: string;
  subtitleEmptyCount: number;
  subtitleLowCount: number;
  subtitleDuplicateCount: number;
  subtitleProgressLabel: string;
  aiUnderstandingReady: boolean;
  aiVision: TemplateAiVision;
  duration: number;
  proxyPaths: PreviewProxyPaths;
};

export function useTemplateProcessing(templateId: string | null) {
  const [state, setState] = useState<TemplateProcessingState>({
    status: 'ready',
    progress: 100,
    enhanceStatus: 'ready',
    enhanceProgress: 100,
    editable: false,
    audioReady: false,
    subtitleReady: false,
    beatMarkers: [],
    sfxMarkers: [],
    slotCount: 0,
    slotsAiReadyCount: 0,
    slotsSubtitleReadyCount: 0,
    subtitleBatchRunning: false,
    subtitleRecognitionMode: 'fast',
    subtitleEmptyCount: 0,
    subtitleLowCount: 0,
    subtitleDuplicateCount: 0,
    subtitleProgressLabel: '',
    aiUnderstandingReady: true,
    aiVision: {},
    duration: 0,
    proxyPaths: {},
  });
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    if (!templateId) return;
    try {
      const resp = await fetch(apiUrl(`/api/template/${templateId}/status`), {
        headers: apiHeaders(),
      });
      const data = await resp.json();
      if (!resp.ok) return;
      const enhanceStatus = data.enhance_status || 'ready';
      const processingStatus = data.processing_status || 'ready';
      const subtitleBatchRunning = !!data.subtitle_batch_running;
      setState({
        status: processingStatus,
        progress: Number(data.processing_progress ?? 100),
        enhanceStatus,
        enhanceProgress: Number(data.enhance_progress ?? 100),
        editable: !!data.editable,
        audioReady: !!data.audio_ready,
        subtitleReady: !!data.subtitle_ready,
        beatMarkers: Array.isArray(data.beat_markers) ? data.beat_markers : [],
        sfxMarkers: Array.isArray(data.sfx_markers) ? data.sfx_markers : [],
        slotCount: Number(data.slot_count ?? 0),
        slotsAiReadyCount: Number(data.slots_ai_ready_count ?? 0),
        slotsSubtitleReadyCount: Number(data.slots_subtitle_ready_count ?? 0),
        subtitleBatchRunning,
        subtitleRecognitionMode: String(data.subtitle_recognition_mode || 'fast'),
        subtitleEmptyCount: Number(data.subtitle_empty_count ?? 0),
        subtitleLowCount: Number(data.subtitle_low_count ?? 0),
        subtitleDuplicateCount: Number(data.subtitle_duplicate_count ?? 0),
        subtitleProgressLabel: String(data.subtitle_progress_label || ''),
        aiUnderstandingReady: data.ai_understanding_ready !== false,
        aiVision: (data.ai_vision as TemplateAiVision) || {},
        duration: Number(data.duration ?? 0),
        proxyPaths: (data.proxy_paths as PreviewProxyPaths) || {},
      });
      const processingDone =
        (processingStatus === 'ready' || processingStatus === 'failed') &&
        (enhanceStatus === 'ready' || enhanceStatus === 'failed');
      const done = processingDone && !subtitleBatchRunning;
      if (done) {
        if (timerRef.current) clearInterval(timerRef.current);
        timerRef.current = null;
      }
    } catch {
      /* ignore */
    }
  }, [templateId]);

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (!templateId) {
      setState({
        status: 'ready',
        progress: 100,
        enhanceStatus: 'ready',
        enhanceProgress: 100,
        editable: false,
        audioReady: false,
        subtitleReady: false,
        beatMarkers: [],
        sfxMarkers: [],
        slotCount: 0,
        slotsAiReadyCount: 0,
        slotsSubtitleReadyCount: 0,
        subtitleBatchRunning: false,
        subtitleRecognitionMode: 'fast',
        subtitleEmptyCount: 0,
        subtitleLowCount: 0,
        subtitleDuplicateCount: 0,
        subtitleProgressLabel: '',
        aiUnderstandingReady: true,
        aiVision: {},
        duration: 0,
        proxyPaths: {},
      });
      return;
    }
    setState((prev) => ({
      ...prev,
      status: 'processing',
      progress: Math.min(prev.progress, 5),
      enhanceStatus: 'processing',
    }));
    void poll();
    const pollMs = templateStatusPollMs();
    timerRef.current = setInterval(poll, pollMs);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [templateId, poll]);

  return state;
}
