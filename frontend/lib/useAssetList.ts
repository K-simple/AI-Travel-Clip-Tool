import { useCallback, useEffect, useState } from 'react';
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

export type Asset = {
  id: string;
  title: string;
  filename?: string;
  duration: string;
  durationSeconds: number;
  tags: string[];
  filePath: string;
  proxyPath?: string;
  proxyPaths?: PreviewProxyPaths;
  thumbnail?: string;
  segments?: VideoSegment[];
  segmentCount?: number;
  processingStatus?: 'processing' | 'ready' | 'failed';
  processingProgress?: number;
};

export function formatAssetDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

type UseAssetListOptions = {
  autoLoad?: boolean;
};

export function useAssetList({ autoLoad = true }: UseAssetListOptions = {}) {
  const [assets, setAssets] = useState<Asset[]>([]);

  const mapAssetFromApi = useCallback((asset: Record<string, unknown>): Asset => {
    const filePath = (asset.file_path as string) || '';
    const filename = String(asset.filename || '').trim();
    const fallbackTitle =
      filename || filePath.replace(/\\/g, '/').split('/').pop() || '未命名素材';
    const segments = (asset.segments as VideoSegment[]) || [];
    return {
      id: asset.asset_id as string,
      title: fallbackTitle,
      filename: filename || fallbackTitle,
      duration: formatAssetDuration(Number(asset.duration || 0)),
      durationSeconds: Number(asset.duration || 0),
      tags: [],
      filePath,
      proxyPath: (asset.proxy_path as string) || undefined,
      proxyPaths: (asset.proxy_paths as PreviewProxyPaths) || undefined,
      thumbnail: asset.thumbnail as string | undefined,
      segments,
      segmentCount: Number(asset.segment_count ?? segments.length ?? 0),
      processingStatus: (asset.processing_status as Asset['processingStatus']) || 'ready',
      processingProgress: Number(asset.processing_progress ?? 100),
    };
  }, []);

  const loadAssets = useCallback(async () => {
    try {
      const resp = await fetch(apiUrl('/api/assets/list'), { headers: apiHeaders() });
      const data = await resp.json();
      if (resp.ok) {
        setAssets((data as Record<string, unknown>[]).map(mapAssetFromApi));
      }
    } catch (error) {
      console.warn('加载素材列表失败', error);
    }
  }, [mapAssetFromApi]);

  useEffect(() => {
    if (autoLoad) void loadAssets();
  }, [autoLoad, loadAssets]);

  return { assets, setAssets, loadAssets, mapAssetFromApi };
}
