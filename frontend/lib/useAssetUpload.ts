import { useCallback, type Dispatch, type SetStateAction } from 'react';
import { uploadAssetWithProgress } from '@/lib/uploadAsset';
import type { PreviewProxyPaths } from '@/lib/previewSettings';

export type UploadableAsset = {
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
  segments?: Array<{
    segment_id: string;
    start: number;
    end: number;
    duration: number;
    thumbnail?: string;
    segment_file_path?: string;
    file_path?: string;
    type?: string;
  }>;
  processingStatus?: 'processing' | 'ready' | 'failed';
  processingProgress?: number;
};

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

type UseAssetUploadOptions = {
  setAssets: Dispatch<SetStateAction<UploadableAsset[]>>;
  setUploadingCount: Dispatch<SetStateAction<number>>;
};

export function useAssetUpload({ setAssets, setUploadingCount }: UseAssetUploadOptions) {
  const uploadAssetFile = useCallback(
    async (file: File): Promise<UploadableAsset | null> => {
      const tempId = `uploading-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const localPreview = URL.createObjectURL(file);
      const optimistic: UploadableAsset = {
        id: tempId,
        title: file.name,
        duration: '--:--',
        durationSeconds: 0,
        tags: [],
        filePath: localPreview,
        thumbnail: localPreview,
        processingStatus: 'processing',
        processingProgress: 0,
      };

      setUploadingCount((n) => n + 1);
      setAssets((current) => [...current, optimistic]);

      try {
        const data = await uploadAssetWithProgress(file, ({ percent }) => {
          setAssets((current) =>
            current.map((a) =>
              a.id === tempId ? { ...a, processingProgress: Math.max(1, percent) } : a
            )
          );
        });

        const asset: UploadableAsset = {
          id: data.asset_id as string,
          title: (data.filename as string) || file.name,
          filename: (data.filename as string) || file.name,
          duration: formatDuration(Number(data.duration || 0)),
          durationSeconds: Number(data.duration || 0),
          tags: [],
          filePath: (data.file_path as string) || '',
          segments: (data.segments as UploadableAsset['segments']) || [],
          proxyPath: (data.proxy_path as string) || undefined,
          proxyPaths: (data.proxy_paths as PreviewProxyPaths) || undefined,
          thumbnail: (data.thumbnail as string) || localPreview,
          processingStatus: data.processing ? 'processing' : 'ready',
          processingProgress: Number(data.processing_progress ?? 12),
        };

        setAssets((current) => current.map((a) => (a.id === tempId ? asset : a)));
        if (data.thumbnail) {
          URL.revokeObjectURL(localPreview);
        }
        return asset;
      } catch (error) {
        console.warn('素材上传失败', error);
        setAssets((current) => current.filter((a) => a.id !== tempId));
        URL.revokeObjectURL(localPreview);
        alert(error instanceof Error ? error.message : '素材上传失败，请重试');
        return null;
      } finally {
        setUploadingCount((n) => Math.max(0, n - 1));
      }
    },
    [setAssets, setUploadingCount]
  );

  const handleAssetUpload = useCallback(
    (fileOrFiles: File | File[]) => {
      const files = Array.isArray(fileOrFiles) ? fileOrFiles : [fileOrFiles];
      const concurrency = 3;
      let index = 0;
      const workers = Array.from({ length: Math.min(concurrency, files.length) }, async () => {
        while (index < files.length) {
          const current = files[index];
          index += 1;
          await uploadAssetFile(current);
        }
      });
      void Promise.all(workers);
    },
    [uploadAssetFile]
  );

  return { uploadAssetFile, handleAssetUpload };
}
