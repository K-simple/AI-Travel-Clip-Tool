'use client';

import { useCallback, useMemo, useState } from 'react';
import type { DragEvent } from 'react';
import CloudLibraryPanel from '@/components/CloudLibraryPanel';
import MarketplacePanel from '@/components/MarketplacePanel';
import TemplateLibraryPanel from '@/components/TemplateLibraryPanel';
import SubtitleLibraryPanel from '@/components/SubtitleLibraryPanel';
import AudioLibraryPanel from '@/components/AudioLibraryPanel';
import { toMediaUrl } from '@/lib/api';
import type { TemplateSlot } from '@/lib/timeline';
import { getVideoFilesFromDataTransfer, isVideoFile } from '@/lib/timelineDrop';

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

type Asset = {
  id: string;
  filename?: string;
  title?: string;
  duration?: number | string;
  durationSeconds?: number;
  filePath?: string;
  thumbnail?: string;
  tags?: string[];
  segments?: VideoSegment[];
  processingStatus?: 'processing' | 'ready' | 'failed';
  processingProgress?: number;
};

type AssetLibraryProps = {
  assets: Asset[];
  usedAssetIds?: Set<string> | null;
  loading?: boolean;
  templateId?: string | null;
  onAssetDragStart: (event: DragEvent<HTMLDivElement>, dragKey: string) => void;
  onAssetUpload: (files: File | File[]) => void;
  onTemplateUpload?: (file: File) => void;
  hasTemplate?: boolean;
  onPreviewAsset?: (asset: Asset) => void;
  onTemplateInstalled?: (templateId: string) => void;
  onAssetDelete?: (assetId: string) => void;
  onAssetsRefresh?: () => void;
  slots?: TemplateSlot[];
  selectedSlotId?: string;
  onSelectSlot?: (slotId: string) => void;
  onUpdateSlotSubtitle?: (slotId: string, text: string) => void;
  templateMusicEnabled?: boolean;
  templateAudioUrl?: string;
  onToggleTemplateMusic?: () => void;
  onToggleSlotOriginalAudio?: (slotId: string) => void;
  onBatchRecognizeSubtitles?: () => void;
  recognizingAllSubtitles?: boolean;
  onTemplateLibrarySelect?: (templateId: string) => void;
  onTemplateLibraryImported?: (templateId: string) => void;
};

const SIDEBAR_ITEMS = [
  { id: 'import', label: '导入', icon: '📁' },
  { id: 'templates', label: '模板库', icon: '📋' },
  { id: 'media', label: '素材', icon: '🎬' },
  { id: 'cloud', label: '云库', icon: '☁' },
  { id: 'market', label: '市场', icon: '🛒' },
  { id: 'subtitle', label: '文本', icon: 'T' },
  { id: 'audio', label: '音频', icon: '♪' },
] as const;

function formatAssetDuration(asset: Asset): string {
  if (typeof asset.duration === 'string' && asset.duration.includes(':')) {
    return asset.duration;
  }
  const seconds =
    typeof asset.durationSeconds === 'number' && asset.durationSeconds > 0
      ? asset.durationSeconds
      : Number(asset.duration || 0);
  if (seconds <= 0) return '--:--';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

function DeleteAssetButton({
  onClick,
  title = '删除素材',
  alwaysVisible = false,
}: {
  onClick: () => void;
  title?: string;
  alwaysVisible?: boolean;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onPointerDown={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={`absolute right-1 top-1 z-10 flex h-5 w-5 items-center justify-center rounded bg-black/75 text-[11px] text-white transition hover:bg-red-600 ${
        alwaysVisible ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
      }`}
    >
      ×
    </button>
  );
}

export default function AssetLibrary({
  assets,
  usedAssetIds,
  loading,
  onAssetDragStart,
  onAssetUpload,
  onTemplateUpload,
  hasTemplate = false,
  onPreviewAsset,
  templateId,
  onTemplateInstalled,
  onAssetDelete,
  onAssetsRefresh,
  slots = [],
  selectedSlotId,
  onSelectSlot,
  onUpdateSlotSubtitle,
  templateMusicEnabled = true,
  templateAudioUrl = '',
  onToggleTemplateMusic,
  onToggleSlotOriginalAudio,
  onBatchRecognizeSubtitles,
  recognizingAllSubtitles = false,
  onTemplateLibrarySelect,
  onTemplateLibraryImported,
}: AssetLibraryProps) {
  const [activeTab, setActiveTab] = useState<(typeof SIDEBAR_ITEMS)[number]['id']>('import');
  const [keyword, setKeyword] = useState('');
  const [dragOver, setDragOver] = useState(false);

  /** 导入 Tab = 模板视频；素材 Tab = 旅途素材 */
  const importAsTemplate = activeTab === 'import';

  const handleFilesImport = useCallback(
    (files: File[]) => {
      if (!files.length) return;
      if (importAsTemplate && onTemplateUpload) {
        onTemplateUpload(files[0]);
        return;
      }
      onAssetUpload(files.length === 1 ? files[0] : files);
    },
    [importAsTemplate, onTemplateUpload, onAssetUpload]
  );

  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    if (!e.dataTransfer.types.includes('Files')) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    const related = e.relatedTarget as Node | null;
    if (related && e.currentTarget.contains(related)) return;
    setDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragOver(false);
      const files = getVideoFilesFromDataTransfer(e.dataTransfer);
      if (!files.length) {
        alert('请拖入视频文件（mp4 / mov / mkv 等）');
        return;
      }
      handleFilesImport(files);
    },
    [handleFilesImport]
  );

  const filtered = useMemo(() => {
    return (assets || []).filter((asset) => {
      if (!keyword) return true;
      return (asset.filename || asset.title || '').toLowerCase().includes(keyword.toLowerCase());
    });
  }, [assets, keyword]);

  type GridItem =
    | { kind: 'processing'; asset: Asset }
    | { kind: 'segment'; asset: Asset; segment: VideoSegment; index: number };

  const gridItems = useMemo((): GridItem[] => {
    const items: GridItem[] = [];
    for (const asset of filtered) {
      const segs = asset.segments?.filter((s) => s.type !== 'image') ?? [];
      const showSegments =
        segs.length > 0 &&
        asset.processingStatus !== 'failed' &&
        (asset.processingStatus === 'ready' ||
          (asset.processingProgress ?? 0) >= 20);

      if (asset.processingStatus === 'processing' || !showSegments) {
        items.push({ kind: 'processing', asset });
        continue;
      }

      segs.forEach((segment, index) => {
        items.push({ kind: 'segment', asset, segment, index });
      });
    }
    return items;
  }, [filtered]);

  const renderAssetGridItems = () =>
    gridItems.map((item) => {
      if (item.kind === 'processing') {
        const asset = item.asset;
        const isUsed = usedAssetIds?.has(asset.id);
        const thumb = asset.thumbnail || asset.filePath || '';
        const name = asset.filename || asset.title || '未命名';
        return (
          <div
            key={asset.id}
            draggable={Boolean(asset.filePath)}
            onDragStart={(e) => onAssetDragStart(e as DragEvent<HTMLDivElement>, asset.id)}
            onDoubleClick={() => onPreviewAsset?.(asset)}
            className={`group cursor-grab overflow-hidden rounded-md border bg-[#252525] active:cursor-grabbing ${
              isUsed ? 'border-[#face15]' : 'border-[#3a3a3a] hover:border-[#555]'
            }`}
          >
            <div className="relative aspect-video bg-black">
              {onAssetDelete ? (
                <DeleteAssetButton
                  title={asset.id.startsWith('uploading-') ? '取消上传' : '删除素材'}
                  alwaysVisible={asset.processingStatus === 'failed'}
                  onClick={() => onAssetDelete(asset.id)}
                />
              ) : null}
              {thumb ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={toMediaUrl(thumb)} alt={name} className="h-full w-full object-cover" />
              ) : (
                <div className="flex h-full items-center justify-center text-[10px] text-[#666]">无预览</div>
              )}
              <span className="absolute bottom-1 right-1 rounded bg-black/70 px-1 text-[10px] text-white">
                {formatAssetDuration(asset)}
              </span>
              {asset.processingStatus === 'processing' ? (
                <span className="absolute inset-0 flex flex-col items-center justify-center bg-black/55 text-[10px] text-[#face15]">
                  <span>{(asset.processingProgress ?? 0) < 100 ? '上传/分析中' : '镜头切分中'}</span>
                  <span>{asset.processingProgress ?? 0}%</span>
                </span>
              ) : null}
              {asset.processingStatus === 'failed' ? (
                <span className="absolute left-1 top-1 rounded bg-red-600 px-1 text-[9px] text-white">
                  分析失败
                </span>
              ) : null}
            </div>
            <div className="truncate px-1.5 py-1 text-[10px] text-[#ccc]" title={name}>
              {name}
            </div>
          </div>
        );
      }

      const { asset, segment, index } = item;
      const dragKey = `${asset.id}:${segment.segment_id}`;
      const useSegmentClip = Boolean(segment.segment_file_path?.trim());
      const previewVideo = segment.segment_file_path || segment.file_path || asset.filePath || '';
      const previewStart = useSegmentClip ? 0 : Number(segment.start || 0);
      const thumb = segment.thumbnail || asset.thumbnail || '';
      const segSec = Number(segment.duration || 0);
      const segM = Math.floor(segSec / 60);
      const segS = Math.round(segSec % 60);
      const segDuration = `${segM.toString().padStart(2, '0')}:${segS.toString().padStart(2, '0')}`;
      const name = `${asset.filename || asset.title || '素材'} · 镜头${index + 1}`;

      return (
        <div
          key={dragKey}
          draggable
          onDragStart={(e) => onAssetDragStart(e as DragEvent<HTMLDivElement>, dragKey)}
          onDoubleClick={() =>
            onPreviewAsset?.({ ...asset, filePath: previewVideo, thumbnail: thumb })
          }
          className="group cursor-grab overflow-hidden rounded-md border border-[#3a3a3a] bg-[#252525] hover:border-[#555] active:cursor-grabbing"
        >
          <div className="relative aspect-video bg-black">
            {onAssetDelete ? (
              <DeleteAssetButton title="删除素材" onClick={() => onAssetDelete(asset.id)} />
            ) : null}
            {previewVideo ? (
              <video
                src={toMediaUrl(previewVideo)}
                poster={thumb ? toMediaUrl(thumb) : undefined}
                className="h-full w-full object-cover"
                muted
                playsInline
                preload="metadata"
                onLoadedData={(e) => {
                  const v = e.currentTarget;
                  if (previewStart > 0 && Math.abs(v.currentTime - previewStart) > 0.2) {
                    v.currentTime = previewStart;
                  }
                }}
                onMouseEnter={(e) => {
                  const v = e.currentTarget;
                  if (previewStart > 0) v.currentTime = previewStart;
                  void v.play().catch(() => undefined);
                }}
                onMouseLeave={(e) => {
                  const v = e.currentTarget;
                  v.pause();
                  v.currentTime = previewStart;
                }}
              />
            ) : thumb ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={toMediaUrl(thumb)} alt={name} className="h-full w-full object-cover" />
            ) : (
              <div className="flex h-full items-center justify-center text-[10px] text-[#666]">无预览</div>
            )}
            {asset.processingStatus === 'processing' && (asset.processingProgress ?? 0) < 100 ? (
              <span className="absolute right-1 top-1 rounded bg-black/70 px-1 text-[9px] text-[#face15]">
                {asset.processingProgress ?? 0}%
              </span>
            ) : null}
            <span className="absolute bottom-1 right-1 rounded bg-black/70 px-1 text-[10px] text-white">
              {segDuration}
            </span>
          </div>
          <div className="truncate px-1.5 py-1 text-[10px] text-[#ccc]" title={name}>
            {name}
          </div>
        </div>
      );
    });

  const renderUploadShell = (
    title: string,
    options: {
      multiple: boolean;
      dropHint: string;
      emptyPrimary: string;
      emptySecondary: string;
      showSearch: boolean;
      showAssetGrid: boolean;
    }
  ) => (
    <div
      className="relative flex min-h-0 flex-1 flex-col"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="flex items-center justify-between border-b border-[#2e2e2e] px-3 py-2">
        <span className="text-sm font-medium text-white">{title}</span>
        <label className="cursor-pointer rounded bg-[#face15] px-2.5 py-1 text-xs font-medium text-black hover:bg-[#ffe066]">
          + 上传
          <input
            type="file"
            accept="video/*"
            className="hidden"
            multiple={options.multiple}
            onChange={(e) => {
              const picked = Array.from(e.target.files || []).filter(isVideoFile);
              if (!picked.length) return;
              if (importAsTemplate && hasTemplate) {
                if (!window.confirm('更换模板将重建时间线，是否继续？')) return;
              }
              handleFilesImport(picked);
              e.target.value = '';
            }}
          />
        </label>
      </div>

      {options.showSearch ? (
        <div className="px-3 py-2">
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索素材"
            className="w-full rounded-md border border-[#3a3a3a] bg-[#141414] px-2.5 py-1.5 text-xs text-white placeholder:text-[#666] focus:border-[#face15] focus:outline-none"
          />
        </div>
      ) : null}

      {loading ? <div className="px-3 text-xs text-[#8b8b8b]">正在上传…</div> : null}

      <div className="relative grid min-h-0 flex-1 grid-cols-2 gap-2 overflow-y-auto px-3 pb-3 content-start">
        {dragOver ? (
          <div className="pointer-events-none absolute inset-2 z-10 flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-[#face15] bg-[#face15]/10">
            <span className="text-sm text-[#face15]">{options.dropHint}</span>
            <span className="mt-1 text-[10px] text-[#8b8b8b]">支持 mp4 / mov / mkv 等</span>
          </div>
        ) : null}

        {!options.showAssetGrid || gridItems.length === 0 ? (
          <div className="col-span-2 flex flex-col items-center justify-center py-10 text-center text-xs text-[#666]">
            <p>{options.emptyPrimary}</p>
            <p className="mt-1 text-[#555]">{options.emptySecondary}</p>
          </div>
        ) : (
          renderAssetGridItems()
        )}
      </div>
    </div>
  );

  return (
    <div className="flex h-full min-h-0 border-r border-[#2e2e2e] bg-[#1a1a1a]">
      <nav className="flex w-14 shrink-0 flex-col items-center gap-1 border-r border-[#2e2e2e] py-3">
        {SIDEBAR_ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setActiveTab(item.id)}
            className={`flex w-11 flex-col items-center gap-0.5 rounded-lg py-2 text-[10px] ${
              activeTab === item.id ? 'bg-[#2e2e2e] text-[#face15]' : 'text-[#8b8b8b] hover:bg-[#252525]'
            }`}
          >
            <span className="text-base leading-none">{item.icon}</span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        {activeTab === 'cloud' ? <CloudLibraryPanel onImported={onAssetsRefresh} /> : null}
        {activeTab === 'templates' ? (
          <TemplateLibraryPanel
            currentTemplateId={templateId}
            onSelectTemplate={onTemplateLibrarySelect}
            onImported={onTemplateLibraryImported}
          />
        ) : null}
        {activeTab === 'market' ? (
          <MarketplacePanel templateId={templateId} onInstalled={onTemplateInstalled} />
        ) : null}
        {activeTab === 'subtitle' ? (
          <SubtitleLibraryPanel
            slots={slots}
            selectedSlotId={selectedSlotId}
            onSelectSlot={(id) => onSelectSlot?.(id)}
            onUpdateSubtitle={(id, text) => onUpdateSlotSubtitle?.(id, text)}
            onBatchRecognize={onBatchRecognizeSubtitles}
            batchRecognizing={recognizingAllSubtitles}
            disabled={!templateId}
          />
        ) : null}
        {activeTab === 'audio' ? (
          <AudioLibraryPanel
            slots={slots}
            templateMusicEnabled={templateMusicEnabled}
            templateAudioUrl={templateAudioUrl}
            onToggleTemplateMusic={() => onToggleTemplateMusic?.()}
            onToggleSlotOriginalAudio={(id) => onToggleSlotOriginalAudio?.(id)}
            selectedSlotId={selectedSlotId}
            onSelectSlot={(id) => onSelectSlot?.(id)}
          />
        ) : null}
        {activeTab === 'import'
          ? renderUploadShell(hasTemplate ? '更换模板' : '导入模板', {
              multiple: false,
              dropHint: '松手导入模板视频',
              emptyPrimary: hasTemplate ? '拖入新模板视频以更换' : '拖入模板视频开始剪辑',
              emptySecondary: '或点击「+ 上传」选择 mp4 / mov / mkv',
              showSearch: false,
              showAssetGrid: false,
            })
          : null}
        {activeTab === 'media'
          ? renderUploadShell('素材库', {
              multiple: true,
              dropHint: '松手导入素材',
              emptyPrimary: '暂无素材',
              emptySecondary: '或点击「+ 上传」批量导入旅途素材',
              showSearch: true,
              showAssetGrid: true,
            })
          : null}
      </div>
    </div>
  );
}
