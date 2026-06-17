import { useCallback, useEffect, useRef } from 'react';
import { apiHeaders, apiUrl } from '@/lib/api';
import type { PreviewProxyPaths } from '@/lib/previewSettings';

export type VideoSegment = {
  segment_id: string;
  start: number;
  end: number;
  duration: number;
  thumbnail?: string;
  segment_file_path?: string;
  file_path?: string;
  type?: string;
};

export type AssetProcessingState = {
  status: 'processing' | 'ready' | 'failed';
  progress: number;
  segments?: VideoSegment[];
  segmentCount?: number;
  duration?: number;
  thumbnail?: string;
  proxyPath?: string;
  proxyPaths?: PreviewProxyPaths;
};

export function useAssetProcessingPoll(
  assetIds: string[],
  onUpdate: (assetId: string, state: AssetProcessingState) => void
) {
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;

  const pollOne = useCallback(async (assetId: string) => {
    try {
      const resp = await fetch(apiUrl(`/api/assets/${assetId}/status`), {
        headers: apiHeaders(),
      });
      const data = await resp.json();
      if (!resp.ok) return;
      const status = (data.processing_status || 'ready') as AssetProcessingState['status'];
      const progress = Number(data.processing_progress ?? 100);
      onUpdateRef.current(assetId, {
        status,
        progress,
        segments: (data.segments as VideoSegment[]) || [],
        segmentCount: Number(data.segment_count ?? 0),
        duration: Number(data.duration ?? 0),
        thumbnail: (data.thumbnail as string) || '',
        proxyPath: (data.proxy_path as string) || '',
        proxyPaths: (data.proxy_paths as PreviewProxyPaths) || undefined,
      });
      return status;
    } catch {
      return undefined;
    }
  }, []);

  useEffect(() => {
    const processing = assetIds.filter(Boolean);
    if (!processing.length) return;

    let cancelled = false;
    const tick = async () => {
      for (const id of processing) {
        if (cancelled) break;
        await pollOne(id);
      }
    };

    void tick();
    const timer = setInterval(() => void tick(), 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [assetIds.join(','), pollOne]);
}
