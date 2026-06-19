import { useCallback, useEffect, useRef, useState } from 'react';
import { apiHeaders, apiUrl } from '@/lib/api';
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
        aiVision: (data.ai_vision as TemplateAiVision) || {},
        duration: Number(data.duration ?? 0),
        proxyPaths: (data.proxy_paths as PreviewProxyPaths) || {},
      });
      const done =
        (processingStatus === 'ready' || processingStatus === 'failed') &&
        (enhanceStatus === 'ready' || enhanceStatus === 'failed');
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
    timerRef.current = setInterval(poll, 1500);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [templateId, poll]);

  return state;
}
