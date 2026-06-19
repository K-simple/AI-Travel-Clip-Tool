'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { DragEvent } from 'react';
import CloudLibraryPanel from '@/components/CloudLibraryPanel';
import MarketplacePanel from '@/components/MarketplacePanel';
import TemplateLibraryPanel from '@/components/TemplateLibraryPanel';
import SubtitleLibraryPanel from '@/components/SubtitleLibraryPanel';
import AudioLibraryPanel from '@/components/AudioLibraryPanel';
import { toMediaUrl } from '@/lib/api';
import type { PreviewProxyPaths } from '@/lib/previewSettings';
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
  filename?: string;
  type?: string;
};

type Asset = {
  id: string;
  filename?: string;
  title?: string;
  duration?: number | string;
  durationSeconds?: number;
  filePath?: string;
  proxyPath?: string;
  proxyPaths?: PreviewProxyPaths;
  thumbnail?: string;
  tags?: string[];
  segments?: VideoSegment[];
  segmentCount?: number;
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
  onAssetsDelete?: (assetIds: string[]) => void | Promise<boolean | void>;
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
  onRecognizeSlotSubtitle?: () => void;
  recognizingSlotSubtitle?: boolean;
  onTemplateLibrarySelect?: (templateId: string) => void;
  onTemplateLibraryImported?: (templateId: string) => void;
  onTemplateLibraryDeleted?: (templateId: string) => void;
};

const SIDEBAR_ITEMS = [
  { id: 'import', label: '导入', icon: 'upload' },
  { id: 'templates', label: '模板库', icon: 'template' },
  { id: 'media', label: '素材', icon: 'media' },
  { id: 'cloud', label: '云库', icon: 'cloud' },
  { id: 'market', label: '市场', icon: 'market' },
  { id: 'subtitle', label: '字幕', icon: 'text' },
  { id: 'audio', label: '音频', icon: 'audio' },
] as const;

function SidebarIcon({ name }: { name: (typeof SIDEBAR_ITEMS)[number]['icon'] }) {
  const cls = 'h-[18px] w-[18px]';
  switch (name) {
    case 'upload':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M12 16V4m0 0L8 8m4-4 4 4M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case 'template':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <path d="M3 9h18M8 4v16" strokeLinecap="round" />
        </svg>
      );
    case 'media':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <path d="M10 10l4 2.5L10 15V10z" fill="currentColor" stroke="none" />
        </svg>
      );
    case 'cloud':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M7 18h11a4 4 0 000-8 5.5 5.5 0 00-10.6-1.8A3.5 3.5 0 007 18z" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case 'market':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M6 6h15l-1.5 9h-12L6 6z" strokeLinejoin="round" />
          <circle cx="10" cy="19" r="1.5" fill="currentColor" />
          <circle cx="17" cy="19" r="1.5" fill="currentColor" />
        </svg>
      );
    case 'text':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M6 6h12M12 6v14M9 20h6" strokeLinecap="round" />
        </svg>
      );
    case 'audio':
      return (
        <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M9 18V6l10-2v14" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="7" cy="18" r="2.5" />
          <circle cx="17" cy="16" r="2.5" />
        </svg>
      );
    default:
      return null;
  }
}

function isImagePreviewPath(path: string): boolean {
  if (!path) return false;
  if (path.startsWith('blob:')) return true;
  return /\.(jpe?g|png|webp|gif)$/i.test(path) || path.includes('/thumbnails/');
}

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

function basenameFromPath(path: string): string {
  if (!path || path.startsWith('blob:')) return '';
  return path.replace(/\\/g, '/').split('/').pop() || '';
}

function resolveAssetDisplayName(asset: Asset): string {
  const fromMeta = (asset.filename || asset.title || '').trim();
  if (fromMeta) return fromMeta;

  const fromSegment = asset.segments
    ?.map((s) => s.filename)
    .find((name) => Boolean(name?.trim()));
  if (fromSegment?.trim()) return fromSegment.trim();

  const fromPath = basenameFromPath(asset.filePath || '');
  if (fromPath) {
    try {
      return decodeURIComponent(fromPath);
    } catch {
      return fromPath;
    }
  }
  return '未命名素材';
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
      className={`absolute right-1 top-1 z-10 flex h-4 w-4 items-center justify-center rounded bg-black/70 text-[10px] text-white transition hover:bg-red-600 ${
        alwaysVisible ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
      }`}
    >
      ×
    </button>
  );
}

function resolveAssetPreviewVideoSrc(asset: Asset, segs: VideoSegment[]): string {
  if (asset.proxyPath?.trim()) return asset.proxyPath;
  const proxies = asset.proxyPaths;
  if (proxies?.smooth?.trim()) return proxies.smooth;
  if (proxies?.low?.trim()) return proxies.low;
  if (proxies?.clear?.trim()) return proxies.clear;
  const segFile = segs.find((s) => s.segment_file_path?.trim())?.segment_file_path;
  return segFile?.trim() || '';
}

function resolveAssetSegmentCount(asset: Asset): number {
  const fromMeta = asset.segmentCount ?? 0;
  if (fromMeta > 0) return fromMeta;
  return asset.segments?.filter((s) => s.type !== 'image').length ?? 0;
}

function AssetPreviewMedia({
  thumb,
  videoSrc,
  alt,
  className = 'h-full w-full object-cover',
}: {
  thumb: string;
  videoSrc?: string;
  alt: string;
  className?: string;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [mode, setMode] = useState<'img' | 'video' | 'empty'>(
    thumb && isImagePreviewPath(thumb) ? 'img' : videoSrc ? 'video' : 'empty'
  );

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setVisible(true);
          io.disconnect();
        }
      },
      { rootMargin: '160px' }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  if (!visible) {
    return (
      <div ref={rootRef} className="h-full w-full bg-[#1a1a1a]" aria-hidden />
    );
  }

  if (mode === 'img' && thumb) {
    return (
      <div ref={rootRef} className="h-full w-full">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={toMediaUrl(thumb)}
          alt={alt}
          className={className}
          loading="lazy"
          decoding="async"
          onError={() => setMode(videoSrc ? 'video' : 'empty')}
        />
      </div>
    );
  }

  if (mode === 'video' && videoSrc) {
    return (
      <div ref={rootRef} className="h-full w-full">
        <video
          src={`${toMediaUrl(videoSrc)}#t=0.05`}
          className={className}
          muted
          playsInline
          preload="metadata"
          onLoadedData={(e) => {
            const v = e.currentTarget;
            if (v.currentTime < 0.04) v.currentTime = 0.05;
          }}
          onError={() => setMode('empty')}
        />
      </div>
    );
  }

  return (
    <div
      ref={rootRef}
      className="flex h-full flex-col items-center justify-center gap-1 bg-[#1a1a1a] px-2 text-center"
    >
      <span className="text-lg opacity-40">🎬</span>
      <span className="text-[9px] leading-snug text-[#666]">封面生成中</span>
    </div>
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
  onAssetsDelete,
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
  onRecognizeSlotSubtitle,
  recognizingSlotSubtitle = false,
  onTemplateLibrarySelect,
  onTemplateLibraryImported,
  onTemplateLibraryDeleted,
}: AssetLibraryProps) {
  const [activeTab, setActiveTab] = useState<(typeof SIDEBAR_ITEMS)[number]['id']>('import');
  const [keyword, setKeyword] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());

  const toggleAssetSelected = useCallback((assetId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(assetId)) next.delete(assetId);
      else next.add(assetId);
      return next;
    });
  }, []);

  const clearAssetSelection = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const exitSelectMode = useCallback(() => {
    setSelectMode(false);
    setSelectedIds(new Set());
  }, []);

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
      const name = resolveAssetDisplayName(asset).toLowerCase();
      return name.includes(keyword.toLowerCase());
    });
  }, [assets, keyword]);

  type GridItem = { kind: 'asset'; asset: Asset };

  const gridItems = useMemo((): GridItem[] => filtered.map((asset) => ({ kind: 'asset', asset })), [filtered]);

  const selectAllFiltered = useCallback(() => {
    setSelectedIds(new Set(filtered.map((a) => a.id)));
  }, [filtered]);

  const handleBatchDelete = useCallback(async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    let shouldExit = true;
    if (onAssetsDelete) {
      const result = await onAssetsDelete(ids);
      if (result === false) shouldExit = false;
    } else if (onAssetDelete) {
      for (const id of ids) {
        onAssetDelete(id);
      }
    }
    if (shouldExit) exitSelectMode();
  }, [selectedIds, onAssetsDelete, onAssetDelete, exitSelectMode]);

  const renderAssetGridItems = () =>
    gridItems.map(({ asset }) => {
      const isUsed = usedAssetIds?.has(asset.id);
      const segs = asset.segments?.filter((s) => s.type !== 'image') ?? [];
      const thumb =
        asset.thumbnail ||
        segs.find((s) => s.thumbnail)?.thumbnail ||
        '';
      const videoSrc = resolveAssetPreviewVideoSrc(asset, segs);
      const name = resolveAssetDisplayName(asset);
      const segmentCount = resolveAssetSegmentCount(asset);
      const segmentHint = segmentCount > 1 ? `${segmentCount} 个镜头` : '';
      const isSelected = selectedIds.has(asset.id);
      return (
        <div
          key={asset.id}
          role="button"
          tabIndex={0}
          draggable={!selectMode && !asset.id.startsWith('uploading-')}
          onClick={() => {
            if (selectMode) toggleAssetSelected(asset.id);
          }}
          onKeyDown={(e) => {
            if (selectMode && (e.key === 'Enter' || e.key === ' ')) {
              e.preventDefault();
              toggleAssetSelected(asset.id);
            }
          }}
          onDragStart={(e) => {
            if (selectMode) {
              e.preventDefault();
              return;
            }
            onAssetDragStart(e as DragEvent<HTMLDivElement>, asset.id);
          }}
          onDoubleClick={() => {
            if (selectMode) return;
            onPreviewAsset?.(asset);
          }}
          className={`group flex w-full min-w-0 flex-col overflow-hidden rounded-md border bg-editor-panel-2 ${
            selectMode ? 'cursor-pointer' : 'cursor-grab active:cursor-grabbing'
          } ${
            isSelected
              ? 'border-editor-accent ring-1 ring-editor-accent/60'
              : isUsed
                ? 'border-editor-accent/70'
                : 'border-editor-border hover:border-editor-muted/40'
          }`}
        >
          <div className="relative aspect-[3/2] w-full shrink-0 bg-[#0a1628]">
            {selectMode ? (
              <span
                className={`absolute left-1 top-1 z-10 flex h-3.5 w-3.5 items-center justify-center rounded border text-[8px] ${
                  isSelected
                    ? 'border-editor-accent bg-editor-accent text-[#141414]'
                    : 'border-white/70 bg-black/50 text-transparent'
                }`}
              >
                ✓
              </span>
            ) : null}
            {!selectMode && onAssetDelete ? (
              <DeleteAssetButton
                title={asset.id.startsWith('uploading-') ? '取消上传' : '删除素材'}
                alwaysVisible={asset.processingStatus === 'failed'}
                onClick={() => onAssetDelete(asset.id)}
              />
            ) : null}
            <AssetPreviewMedia
              thumb={thumb}
              videoSrc={videoSrc}
              alt={name}
              className="h-full w-full object-contain"
            />
            {segmentHint ? (
              <span className="absolute left-1 top-1 max-w-[85%] truncate rounded bg-black/75 px-1 py-px text-[8px] leading-tight text-white">
                {segmentHint}
              </span>
            ) : null}
            <span className="absolute right-1 top-1 rounded bg-black/55 px-1 text-[9px] leading-none text-white">
              {formatAssetDuration(asset)}
            </span>
            {asset.processingStatus === 'processing' && (asset.processingProgress ?? 0) < 100 ? (
              <span className="absolute bottom-0.5 left-0.5 rounded bg-black/80 px-1 py-px text-[8px] text-editor-accent">
                {asset.processingProgress ?? 0}%
              </span>
            ) : null}
            {asset.processingStatus === 'failed' ? (
              <span className="absolute bottom-0.5 left-0.5 rounded bg-red-600 px-0.5 text-[8px] text-white">
                失败
              </span>
            ) : null}
          </div>
          <div className="shrink-0 border-t border-editor-border bg-editor-panel px-1 py-0.5">
            <p
              className="truncate text-left text-[9px] leading-tight text-editor-muted"
              title={name}
            >
              {name}
            </p>
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
      showMultiSelect?: boolean;
    }
  ) => (
    <div
      className="relative flex min-h-0 flex-1 flex-col"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-editor-border px-3 py-2.5">
        <span className="text-sm font-semibold text-editor-text">{title}</span>
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          {options.showMultiSelect && gridItems.length > 0 ? (
            <>
              {!selectMode ? (
                <button
                  type="button"
                  onClick={() => setSelectMode(true)}
                  className="rounded bg-[#2a2a2a] px-2 py-1 text-[11px] text-[#ccc] hover:bg-[#333]"
                >
                  多选
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={selectAllFiltered}
                    className="rounded bg-[#2a2a2a] px-2 py-1 text-[11px] text-[#ccc] hover:bg-[#333]"
                  >
                    全选
                  </button>
                  <button
                    type="button"
                    onClick={clearAssetSelection}
                    className="rounded bg-[#2a2a2a] px-2 py-1 text-[11px] text-[#ccc] hover:bg-[#333]"
                  >
                    清空
                  </button>
                  <button
                    type="button"
                    disabled={selectedIds.size === 0}
                    onClick={() => void handleBatchDelete()}
                    className="rounded bg-[#8b2020] px-2 py-1 text-[11px] text-white hover:bg-[#a82828] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    删除{selectedIds.size > 0 ? ` (${selectedIds.size})` : ''}
                  </button>
                  <button
                    type="button"
                    onClick={exitSelectMode}
                    className="rounded bg-[#2a2a2a] px-2 py-1 text-[11px] text-[#face15] hover:bg-[#333]"
                  >
                    完成
                  </button>
                </>
              )}
            </>
          ) : null}
          {!selectMode ? (
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
          ) : null}
        </div>
      </div>

      {selectMode && options.showMultiSelect ? (
        <div className="border-b border-[#2e2e2e] px-3 py-1.5 text-[10px] text-[#888]">
          点击素材卡片勾选，已选 {selectedIds.size} 项
        </div>
      ) : null}

      {options.showSearch ? (
        <div className="px-3 py-2">
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索素材"
            className="ui-input"
          />
        </div>
      ) : null}

      {loading ? <div className="px-3 text-xs text-[#8b8b8b]">正在上传…</div> : null}

      <div className="panel-scroll relative grid min-h-0 flex-1 auto-rows-min grid-cols-7 items-start gap-1.5 overflow-y-auto px-1.5 pb-2">
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
    <div className="ui-panel flex h-full min-h-0 w-full min-w-0 border-r border-editor-border">
      <nav className="flex w-[60px] shrink-0 flex-col items-center gap-1 border-r border-editor-border bg-editor-panel/80 py-3">
        {SIDEBAR_ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => {
              if (item.id !== 'media') exitSelectMode();
              setActiveTab(item.id);
            }}
            className={`ui-nav-item ${activeTab === item.id ? 'ui-nav-item-active' : ''}`}
          >
            <SidebarIcon name={item.icon} />
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
            onTemplateDeleted={onTemplateLibraryDeleted}
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
            onRecognizeSelected={onRecognizeSlotSubtitle}
            batchRecognizing={recognizingAllSubtitles}
            recognizingSelected={recognizingSlotSubtitle}
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
              emptySecondary: '上传后拖到下方视频轨槽位；也可直接拖视频文件到时间轴',
              showSearch: true,
              showAssetGrid: true,
              showMultiSelect: true,
            })
          : null}
      </div>
    </div>
  );
}
