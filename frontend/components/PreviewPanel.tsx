'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react';
import { toMediaUrl } from '@/lib/api';
import {
  ASPECT_RATIO_PRESETS,
  fitPreviewStageSize,
  PREVIEW_QUALITY_PRESETS,
  getQualityAvailability,
  loadStoredPreviewQuality,
  normalizeProxyPaths,
  previewPreloadForQuality,
  previewQualityBadge,
  resolvePreviewStream,
  storePreviewQuality,
  type AspectRatioId,
  type PreviewProxyPaths,
  type PreviewQualityId,
} from '@/lib/previewSettings';
import { parseSubtitleSegments } from '@/lib/slotEdit';
import { buildClipLayouts, findClipAtTime, getTotalDuration } from '@/lib/timelineLayout';
import {
  findLayoutIndex,
  findNextPlayableIndex,
  isContiguousSameStream,
  PREVIEW_CLIP_PRELOAD_LEAD,
  PREVIEW_CLIP_SWITCH_EPSILON,
  preparePreviewVideo,
  resolveSlotPreviewMedia,
  timelineToVideoTime,
  videoToTimelineTime,
  type SlotPreviewMedia,
} from '@/lib/previewPlayback';
import type { TemplateSlot } from '@/lib/timeline';
import { colorGradeToCssFilter } from '@/lib/slotEffects';
import PublishPanel from '@/components/PublishPanel';
import { capCutSetupSteps, REPLACEABLE_TEMPLATE_STEPS, type CapCutMateStatus } from '@/lib/capcutExport';
import { resolvePreviewMix, type TrackControls, type TrackKey, TRACK_KEYS, TRACK_LABELS } from '@/lib/trackControls';

const FPS = 30;
const FRAME_STEP = 1 / FPS;

type AssetPreviewInfo = {
  filePath?: string;
  proxyPath?: string;
  proxyPaths?: PreviewProxyPaths;
  thumbnail?: string;
};

type PreviewPanelProps = {
  slots: TemplateSlot[];
  selectedSlot: TemplateSlot | null;
  playheadTime?: number;
  isPlaying?: boolean;
  trackControls: Record<TrackKey, TrackControls>;
  assetMap?: Record<string, AssetPreviewInfo>;
  templateAudioUrl?: string;
  templateVideoPath?: string;
  templateProxyPaths?: PreviewProxyPaths;
  templateMusicEnabled?: boolean;
  processingProgress?: number;
  processingStatus?: string;
  exportUrl?: string | null;
  exportStatus?: string;
  exportError?: string;
  exportResolution?: string;
  onExportResolutionChange?: (resolution: string) => void;
  addSubtitles?: boolean;
  onAddSubtitlesChange?: (value: boolean) => void;
  exportProgress?: number;
  exporting?: boolean;
  onTogglePlay?: () => void;
  onExport?: () => void;
  onExportCapCut?: () => void;
  capCutDraftUrl?: string | null;
  capCutExporting?: boolean;
  capCutExportProgress?: number;
  capCutStatus?: string;
  capCutReplaceableMode?: boolean;
  onCapCutReplaceableModeChange?: (value: boolean) => void;
  capCutMateStatus?: CapCutMateStatus | null;
  onRefreshCapCutMate?: () => void;
  onOpenCapCutDraft?: () => void;
  canExport?: boolean;
  onPlayheadChange?: (time: number) => void;
  onPlayheadStep?: (deltaSec: number) => void;
  timelineName?: string;
};

function formatTimecode(seconds: number, fps = FPS): string {
  const safe = Math.max(0, seconds);
  const h = Math.floor(safe / 3600);
  const m = Math.floor((safe % 3600) / 60);
  const s = Math.floor(safe % 60);
  const f = Math.floor((safe % 1) * fps);
  const pad = (n: number, len = 2) => n.toString().padStart(len, '0');
  return `${pad(h)}:${pad(m)}:${pad(s)}:${pad(f)}`;
}

function PlayIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <path d="M6 5h4v14H6V5zm8 0h4v14h-4V5z" />
    </svg>
  );
}

function useClickOutside(
  ref: RefObject<HTMLElement | null>,
  open: boolean,
  onClose: () => void
) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current?.contains(e.target as Node)) return;
      onClose();
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open, onClose, ref]);
}

function CompactMenu({ open, children, width }: { open: boolean; children: ReactNode; width: string }) {
  if (!open) return null;
  return (
    <div
      className={`absolute bottom-[calc(100%+4px)] right-0 z-40 overflow-hidden rounded-md border border-[#3a3a3c] bg-[#2a2a2c] py-0.5 shadow-lg ${width}`}
    >
      {children}
    </div>
  );
}

export default function PreviewPanel({
  slots,
  selectedSlot,
  playheadTime = 0,
  isPlaying = false,
  trackControls,
  assetMap = {},
  templateAudioUrl = '',
  templateVideoPath = '',
  templateProxyPaths = {},
  templateMusicEnabled = true,
  processingProgress = 100,
  processingStatus = 'ready',
  exportUrl,
  exportStatus = '',
  exportError = '',
  exportResolution = '1080x1920',
  onExportResolutionChange,
  addSubtitles = true,
  onAddSubtitlesChange,
  exportProgress = 0,
  exporting = false,
  onTogglePlay,
  onExport,
  onExportCapCut,
  capCutDraftUrl = null,
  capCutExporting = false,
  capCutExportProgress = 0,
  capCutStatus = '',
  capCutReplaceableMode = false,
  onCapCutReplaceableModeChange,
  capCutMateStatus = null,
  onRefreshCapCutMate,
  onOpenCapCutDraft,
  canExport = false,
  onPlayheadChange,
  onPlayheadStep,
  timelineName = '时间线01',
}: PreviewPanelProps) {
  const videoRefA = useRef<HTMLVideoElement | null>(null);
  const videoRefB = useRef<HTMLVideoElement | null>(null);
  const frontLayerRef = useRef<0 | 1>(0);
  const layoutIndexRef = useRef(0);
  const preloadedNextRef = useRef(false);
  const backBufferReadyRef = useRef(false);
  const playSessionRef = useRef(0);
  const lastPlayheadReportRef = useRef(-1);
  const onPlayheadChangeRef = useRef(onPlayheadChange);
  const bgmRef = useRef<HTMLAudioElement | null>(null);
  const wasPlayingRef = useRef(false);
  const playheadRef = useRef(playheadTime);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const qualityWrapRef = useRef<HTMLDivElement | null>(null);
  const aspectWrapRef = useRef<HTMLDivElement | null>(null);

  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (menuOpen) onRefreshCapCutMate?.();
  }, [menuOpen, onRefreshCapCutMate]);
  const [trackListOpen, setTrackListOpen] = useState(false);
  const trackListRef = useRef<HTMLDivElement | null>(null);
  const [previewZoom, setPreviewZoom] = useState(1);
  const [aspectId, setAspectId] = useState<AspectRatioId>('auto');
  const [videoAspectRatio, setVideoAspectRatio] = useState<number | null>(null);
  const [qualityId, setQualityId] = useState<PreviewQualityId>('smooth');

  useEffect(() => {
    setQualityId(loadStoredPreviewQuality());
  }, []);
  const [qualityOpen, setQualityOpen] = useState(false);
  const [aspectOpen, setAspectOpen] = useState(false);
  const [viewportSize, setViewportSize] = useState({ width: 0, height: 0 });

  useClickOutside(qualityWrapRef, qualityOpen, () => setQualityOpen(false));
  useClickOutside(aspectWrapRef, aspectOpen, () => setAspectOpen(false));
  useClickOutside(trackListRef, trackListOpen, () => setTrackListOpen(false));

  const trackStatusRows = useMemo(() => {
    return TRACK_KEYS.map((key) => {
      const ctrl = trackControls[key];
      const flags: string[] = [];
      if (ctrl.locked) flags.push('锁定');
      if (!ctrl.visible) flags.push('隐藏');
      if (ctrl.muted) flags.push('静音');
      if (ctrl.solo) flags.push('独奏');
      return {
        key,
        label: TRACK_LABELS[key],
        status: flags.length ? flags.join(' · ') : '正常',
        ok: flags.length === 0,
      };
    });
  }, [trackControls]);

  const previewMix = useMemo(() => resolvePreviewMix(trackControls), [trackControls]);
  const totalDuration = useMemo(() => getTotalDuration(slots), [slots]);
  const aspectPreset = ASPECT_RATIO_PRESETS.find((p) => p.id === aspectId) ?? ASPECT_RATIO_PRESETS[0];
  const stageAspectRatio =
    aspectId === 'auto' ? videoAspectRatio ?? aspectPreset.ratio : aspectPreset.ratio;

  const stageSize = useMemo(
    () => fitPreviewStageSize(viewportSize.width, viewportSize.height, stageAspectRatio),
    [viewportSize.width, viewportSize.height, stageAspectRatio]
  );

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const update = () => {
      const rect = el.getBoundingClientRect();
      setViewportSize({ width: rect.width, height: rect.height });
    };
    update();
    const ro = new ResizeObserver(() => update());
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const previewMediaClass = 'absolute inset-0 h-full w-full object-contain';
  const qualityPreset =
    PREVIEW_QUALITY_PRESETS.find((p) => p.id === qualityId) ?? PREVIEW_QUALITY_PRESETS[0];

  const clipLayouts = useMemo(() => buildClipLayouts(slots, 1), [slots]);

  const activeLayout = useMemo(
    () => findClipAtTime(clipLayouts, playheadTime),
    [clipLayouts, playheadTime]
  );

  const displaySlot = activeLayout?.slot ?? selectedSlot;

  const previewCssFilter = useMemo(
    () => colorGradeToCssFilter(displaySlot?.colorGrade),
    [displaySlot?.colorGrade]
  );

  const hasMatchedAsset = Boolean(displaySlot?.asset_file_path || displaySlot?.matchedAssetId);

  const originalAssetUrl = useMemo(() => {
    if (!previewMix.showVideo) return '';
    if (displaySlot?.asset_file_path) return toMediaUrl(displaySlot.asset_file_path);
    if (!hasMatchedAsset && templateVideoPath) return toMediaUrl(templateVideoPath);
    return '';
  }, [displaySlot?.asset_file_path, hasMatchedAsset, templateVideoPath, previewMix.showVideo]);

  const proxyAssetPaths = useMemo(() => {
    const aid = displaySlot?.matchedAssetId;
    if (aid && assetMap[aid]?.proxyPaths) {
      return normalizeProxyPaths(assetMap[aid].proxyPaths);
    }
    if (aid && assetMap[aid]?.proxyPath) {
      return normalizeProxyPaths({ smooth: assetMap[aid].proxyPath });
    }
    if (!hasMatchedAsset && templateVideoPath) {
      return normalizeProxyPaths(templateProxyPaths);
    }
    return {};
  }, [displaySlot?.matchedAssetId, assetMap, hasMatchedAsset, templateVideoPath, templateProxyPaths]);

  const templateThumbUrl = useMemo(() => {
    if (!previewMix.showVideo) return '';
    const thumb = displaySlot?.template_thumbnail || displaySlot?.asset_thumbnail || '';
    return thumb ? toMediaUrl(thumb) : '';
  }, [displaySlot?.template_thumbnail, displaySlot?.asset_thumbnail, previewMix.showVideo]);

  const overlayThumbUrl = useMemo(() => {
    if (!previewMix.showOverlay || !displaySlot) return '';
    const thumb = displaySlot.template_thumbnail || displaySlot.asset_thumbnail || '';
    return thumb ? toMediaUrl(thumb) : '';
  }, [displaySlot, previewMix.showOverlay]);

  const proxyMediaPaths = useMemo(() => {
    const raw = proxyAssetPaths;
    return {
      clear: raw.clear ? toMediaUrl(raw.clear) : '',
      smooth: raw.smooth ? toMediaUrl(raw.smooth) : '',
      low: raw.low ? toMediaUrl(raw.low) : '',
    };
  }, [proxyAssetPaths]);

  const previewStream = useMemo(() => {
    if (!originalAssetUrl) {
      return resolvePreviewStream('', {}, qualityId);
    }
    return resolvePreviewStream(originalAssetUrl, proxyMediaPaths, qualityId, {
      hasPoster: Boolean(templateThumbUrl || overlayThumbUrl),
    });
  }, [
    originalAssetUrl,
    proxyMediaPaths,
    qualityId,
    templateThumbUrl,
    overlayThumbUrl,
  ]);

  const qualityAvailability = useMemo(
    () =>
      getQualityAvailability(
        proxyAssetPaths,
        Boolean(originalAssetUrl),
        Boolean(templateThumbUrl || overlayThumbUrl)
      ),
    [proxyAssetPaths, originalAssetUrl, templateThumbUrl, overlayThumbUrl]
  );

  const assetUrl = previewStream.url;
  const useLowResPoster = previewStream.isPoster;
  const qualityBadge = previewQualityBadge(previewStream);

  const finalExportUrl = exportUrl ? toMediaUrl(exportUrl) : '';
  const previewSrc = finalExportUrl || assetUrl;
  const useLowResPosterForPlay = !finalExportUrl && previewStream.isPoster;

  useEffect(() => {
    setAspectId('auto');
    setVideoAspectRatio(null);
  }, [templateVideoPath]);

  useEffect(() => {
    const syncAspectFromVideo = (video: HTMLVideoElement | null) => {
      if (!video || video.videoWidth <= 0 || video.videoHeight <= 0) return;
      setVideoAspectRatio(video.videoWidth / video.videoHeight);
    };

    const videos = [videoRefA.current, videoRefB.current].filter(Boolean) as HTMLVideoElement[];
    if (!videos.length) return;

    const onMeta = (ev: Event) => syncAspectFromVideo(ev.currentTarget as HTMLVideoElement);
    videos.forEach((video) => {
      video.addEventListener('loadedmetadata', onMeta);
      syncAspectFromVideo(video);
    });
    return () => {
      videos.forEach((video) => video.removeEventListener('loadedmetadata', onMeta));
    };
  }, [previewSrc, templateVideoPath, displaySlot?.id]);

  const slotMedias = useMemo(() => {
    const mediaOpts = {
      assetMap,
      templateVideoPath,
      templateProxyPaths,
      qualityId,
      showVideo: previewMix.showVideo,
    };
    return clipLayouts.map((layout) => resolveSlotPreviewMedia(layout, mediaOpts));
  }, [
    clipLayouts,
    assetMap,
    templateVideoPath,
    templateProxyPaths,
    qualityId,
    previewMix.showVideo,
  ]);

  const videoPreload = previewPreloadForQuality(qualityId);

  const setLayerVisibility = useCallback((front: 0 | 1) => {
    frontLayerRef.current = front;
    const layers = [videoRefA.current, videoRefB.current];
    layers.forEach((el, idx) => {
      if (!el) return;
      const active = idx === front;
      el.style.opacity = active ? '1' : '0';
      el.style.zIndex = active ? '2' : '1';
      el.style.filter = active ? el.dataset.filter || '' : '';
    });
  }, []);

  const prepareVideoEl = useCallback(
    (el: HTMLVideoElement, media: SlotPreviewMedia, videoTime: number, autoplay: boolean) =>
      preparePreviewVideo(el, media, videoTime, autoplay),
    []
  );

  useEffect(() => {
    onPlayheadChangeRef.current = onPlayheadChange;
  }, [onPlayheadChange]);

  useEffect(() => {
    playheadRef.current = playheadTime;
  }, [playheadTime]);

  const slotUsesOriginalAudio = Boolean(displaySlot?.useOriginalAudio) && previewMix.audioAudible;
  const activeUsesTemplateVideo = Boolean(
    displaySlot &&
      !displaySlot.matchedAssetId &&
      !displaySlot.asset_file_path?.trim() &&
      templateVideoPath
  );
  const playTemplateBgm =
    templateMusicEnabled && !!templateAudioUrl && previewMix.audioAudible && !slotUsesOriginalAudio;
  const playTemplateVideoAudio =
    !playTemplateBgm &&
    activeUsesTemplateVideo &&
    previewMix.audioAudible &&
    previewMix.videoAudible &&
    !slotUsesOriginalAudio;
  const playClipAudio = slotUsesOriginalAudio && previewMix.videoAudible;
  const muteVideoAudio = playTemplateBgm || (!playClipAudio && !playTemplateVideoAudio);

  useEffect(() => {
    [videoRefA.current, videoRefB.current].forEach((video) => {
      if (!video) return;
      video.muted = muteVideoAudio;
      video.volume = playClipAudio || playTemplateVideoAudio ? 0.9 : 0;
    });
  }, [muteVideoAudio, playClipAudio, playTemplateVideoAudio]);

  // 暂停/拖拽：同步前台视频
  useEffect(() => {
    if (isPlaying || finalExportUrl || !slotMedias.some(Boolean)) return;

    const idx = findLayoutIndex(clipLayouts, playheadTime);
    const media = slotMedias[idx];
    if (!media) return;

    layoutIndexRef.current = idx;
    preloadedNextRef.current = false;
    backBufferReadyRef.current = false;
    const front = frontLayerRef.current === 0 ? videoRefA.current : videoRefB.current;
    if (!front) return;

    void prepareVideoEl(front, media, timelineToVideoTime(media, playheadTime), false).then(() => {
      front.pause();
      setLayerVisibility(frontLayerRef.current);
    });
  }, [clipLayouts, finalExportUrl, isPlaying, playheadTime, prepareVideoEl, setLayerVisibility, slotMedias]);

  // 播放：双缓冲切镜；勿将 playheadTime 放入依赖，避免每帧重启导致抽搐
  useEffect(() => {
    if (!isPlaying || finalExportUrl || !slotMedias.some(Boolean)) return;

    const session = ++playSessionRef.current;
    let raf = 0;

    const reportPlayhead = (time: number) => {
      if (Math.abs(time - lastPlayheadReportRef.current) < 1 / 30) return;
      lastPlayheadReportRef.current = time;
      playheadRef.current = time;
      onPlayheadChangeRef.current?.(time);
    };

    const tick = () => {
      if (session !== playSessionRef.current) return;

      const frontEl = frontLayerRef.current === 0 ? videoRefA.current : videoRefB.current;
      if (!frontEl) {
        raf = requestAnimationFrame(tick);
        return;
      }

      const idx = layoutIndexRef.current;
      const media = slotMedias[idx];
      if (!media) {
        raf = requestAnimationFrame(tick);
        return;
      }

      const timelineT = videoToTimelineTime(media, frontEl.currentTime);
      reportPlayhead(timelineT);

      const nextIdx = findNextPlayableIndex(slotMedias, idx);
      const nextMedia = nextIdx >= 0 ? slotMedias[nextIdx] : null;
      const switchAt = media.layout.end - PREVIEW_CLIP_SWITCH_EPSILON;
      const preloadAt = media.layout.end - PREVIEW_CLIP_PRELOAD_LEAD;

      if (
        nextMedia &&
        !isContiguousSameStream(media, nextMedia) &&
        timelineT >= preloadAt &&
        !preloadedNextRef.current
      ) {
        preloadedNextRef.current = true;
        backBufferReadyRef.current = false;
        const backIdx = (1 - frontLayerRef.current) as 0 | 1;
        const backEl = backIdx === 0 ? videoRefA.current : videoRefB.current;
        if (backEl) {
          void prepareVideoEl(
            backEl,
            nextMedia,
            timelineToVideoTime(nextMedia, nextMedia.layout.start),
            true
          ).then(() => {
            if (session === playSessionRef.current) {
              backBufferReadyRef.current = true;
            }
          });
        }
      }

      if (nextMedia && timelineT >= switchAt) {
        if (isContiguousSameStream(media, nextMedia)) {
          layoutIndexRef.current = nextIdx;
          preloadedNextRef.current = false;
          backBufferReadyRef.current = false;
          if (nextMedia.cssFilter !== media.cssFilter) {
            frontEl.dataset.filter = nextMedia.cssFilter || '';
          }
        } else if (backBufferReadyRef.current) {
          const backIdx = (1 - frontLayerRef.current) as 0 | 1;
          frontLayerRef.current = backIdx;
          layoutIndexRef.current = nextIdx;
          preloadedNextRef.current = false;
          backBufferReadyRef.current = false;

          const newFront = backIdx === 0 ? videoRefA.current : videoRefB.current;
          if (newFront) {
            newFront.dataset.filter = nextMedia.cssFilter || '';
            if (newFront.paused) {
              void prepareVideoEl(
                newFront,
                nextMedia,
                timelineToVideoTime(nextMedia, nextMedia.layout.start),
                true
              );
            }
          }
          setLayerVisibility(backIdx);
        }
      }

      if (timelineT >= totalDuration - PREVIEW_CLIP_SWITCH_EPSILON) {
        reportPlayhead(totalDuration);
        onPlayheadChangeRef.current?.(totalDuration);
        return;
      }

      raf = requestAnimationFrame(tick);
    };

    const startIdx = findLayoutIndex(clipLayouts, playheadRef.current);
    layoutIndexRef.current = startIdx;
    preloadedNextRef.current = false;
    backBufferReadyRef.current = false;
    lastPlayheadReportRef.current = -1;
    const startMedia = slotMedias[startIdx];
    const frontEl = frontLayerRef.current === 0 ? videoRefA.current : videoRefB.current;

    if (startMedia && frontEl) {
      void prepareVideoEl(
        frontEl,
        startMedia,
        timelineToVideoTime(startMedia, playheadRef.current),
        true
      ).then(() => {
        if (session !== playSessionRef.current) return;
        setLayerVisibility(frontLayerRef.current);
        raf = requestAnimationFrame(tick);
      });
    } else {
      raf = requestAnimationFrame(tick);
    }

    return () => {
      playSessionRef.current += 1;
      if (raf) cancelAnimationFrame(raf);
      [videoRefA.current, videoRefB.current].forEach((v) => v?.pause());
    };
  }, [
    clipLayouts,
    finalExportUrl,
    isPlaying,
    prepareVideoEl,
    setLayerVisibility,
    slotMedias,
    totalDuration,
  ]);

  // 暂停/拖拽时同步 BGM 到播放头；播放中不逐帧 seek，避免爆音
  useEffect(() => {
    if (!bgmRef.current || !templateAudioUrl || finalExportUrl || isPlaying) return;
    const audio = bgmRef.current;
    try {
      if (Math.abs(audio.currentTime - playheadTime) > 0.05) {
        audio.currentTime = playheadTime;
      }
    } catch {
      /* ignore */
    }
  }, [templateAudioUrl, playheadTime, finalExportUrl, isPlaying]);

  useEffect(() => {
    if (!bgmRef.current || finalExportUrl) return;
    const audio = bgmRef.current;
    audio.volume = playTemplateBgm ? 0.85 : 0;
    audio.muted = !playTemplateBgm;

    if (isPlaying && playTemplateBgm) {
      if (!wasPlayingRef.current) {
        try {
          audio.currentTime = playheadTime;
        } catch {
          /* ignore */
        }
      }
      void audio.play().catch(() => undefined);
    } else {
      audio.pause();
    }
    wasPlayingRef.current = isPlaying;
  }, [isPlaying, playTemplateBgm, templateAudioUrl, finalExportUrl, playheadTime]);

  // 播放中仅在大偏差时校正 BGM，防止与 RAF 时钟长期漂移
  useEffect(() => {
    if (!isPlaying || !playTemplateBgm) return;
    const audio = bgmRef.current;
    if (!audio) return;

    const id = window.setInterval(() => {
      if (audio.paused) return;
      try {
        const drift = Math.abs(audio.currentTime - playheadRef.current);
        if (drift > 0.35) {
          audio.currentTime = playheadRef.current;
        }
      } catch {
        /* ignore */
      }
    }, 500);

    return () => window.clearInterval(id);
  }, [isPlaying, playTemplateBgm]);

  const subtitleText = useMemo(() => {
    if (!previewMix.showSubtitle || !displaySlot || !activeLayout) return '';
    const segments = parseSubtitleSegments(displaySlot.subtitle_segments);
    if (segments.length) {
      const hit = segments.find((s) => playheadTime >= s.start && playheadTime < s.end);
      return hit?.text ?? '';
    }
    if (playheadTime >= activeLayout.start && playheadTime < activeLayout.end) {
      return displaySlot.subtitleText || '';
    }
    return '';
  }, [previewMix.showSubtitle, displaySlot, activeLayout, playheadTime]);

  const handleQualityChange = useCallback((next: PreviewQualityId) => {
    setQualityId(next);
    storePreviewQuality(next);
    setQualityOpen(false);
  }, []);

  // 有视频时禁止叠静态缩略图，否则播放会出现多帧重影
  const showOverlayPreview =
    Boolean(overlayThumbUrl) &&
    previewMix.showOverlay &&
    !finalExportUrl &&
    !previewSrc &&
    !isPlaying;

  const toggleFullscreen = useCallback(() => {
    const el = stageRef.current;
    if (!el) return;
    if (document.fullscreenElement) {
      void document.exitFullscreen();
    } else {
      void el.requestFullscreen?.();
    }
  }, []);

  const cycleZoom = () => setPreviewZoom((z) => (z >= 1.5 ? 1 : z + 0.25));

  return (
    <section className="relative flex h-full min-h-0 min-w-0 flex-col bg-editor-panel">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-editor-border bg-editor-panel-2/80 px-2 py-2 sm:px-3">
        <span className="min-w-0 truncate text-[12px] text-[#b8b8bc] sm:text-[13px]">
          播放器 - {timelineName}
          {processingStatus === 'processing' ? (
            <span className="ml-2 text-[11px] text-[#face15]">处理中 {processingProgress}%</span>
          ) : null}
        </span>
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          className="flex h-7 w-7 items-center justify-center rounded text-[#9a9a9e] hover:bg-[#2e2e30] hover:text-white"
          title="导出与发布"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M4 6h16v2H4V6zm0 5h16v2H4v-2zm0 5h16v2H4v-2z" />
          </svg>
        </button>
      </div>

      {(exportStatus || exportError) && (
        <div
          className={`shrink-0 px-3 py-1 text-[11px] ${exportError ? 'bg-[#3a2020] text-[#f87171]' : 'bg-[#1a2e1a] text-[#4ade80]'}`}
        >
          {exportError || exportStatus}
          {exporting && exportProgress > 0 ? (
            <div className="mt-1 h-1 overflow-hidden rounded bg-[#1a3a1a]">
              <div
                className="h-full bg-[#4ade80] transition-all"
                style={{ width: `${exportProgress}%` }}
              />
            </div>
          ) : null}
        </div>
      )}

      <div
        ref={viewportRef}
        className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-editor-bg p-2"
      >
        <div
          ref={stageRef}
          className="relative isolate shrink-0 overflow-hidden bg-black shadow-[0_0_0_1px_#2a2a2c]"
          style={{
            width: stageSize.width > 0 ? stageSize.width : undefined,
            height: stageSize.height > 0 ? stageSize.height : undefined,
            aspectRatio: stageSize.width > 0 ? undefined : String(stageAspectRatio),
            minWidth: stageSize.width > 0 ? undefined : 120,
            minHeight: stageSize.height > 0 ? undefined : 160,
            transform: `scale(${previewZoom})`,
            transformOrigin: 'center center',
          }}
        >
          {qualityBadge && (previewSrc || useLowResPoster) && !finalExportUrl ? (
            <div
              className="pointer-events-none absolute left-2 top-2 z-20 max-w-[70%] rounded bg-black/55 px-1.5 py-0.5 text-[10px] text-[#e5e5ea]"
              title={previewStream.statusText}
            >
              预览 {qualityBadge}
              {previewStream.isFallback ? (
                <span className="ml-1 text-[#face15]">({qualityPreset.label})</span>
              ) : null}
            </div>
          ) : null}

          {useLowResPoster ? (
            <div
              className="pointer-events-none absolute bottom-2 left-2 z-20 rounded bg-black/55 px-1.5 py-0.5 text-[10px] text-[#9a9a9e]"
            >
              {previewStream.statusText}
            </div>
          ) : null}

          {finalExportUrl ? (
            <video
              src={finalExportUrl}
              playsInline
              controls
              className={previewMediaClass}
            />
          ) : previewSrc && !useLowResPoster && !useLowResPosterForPlay ? (
            <>
              <video
                ref={videoRefA}
                playsInline
                preload={isPlaying ? 'auto' : videoPreload}
                muted={muteVideoAudio}
                className={previewMediaClass}
                style={{
                  opacity: 1,
                  zIndex: 2,
                  filter: previewCssFilter || undefined,
                }}
              />
              <video
                ref={videoRefB}
                playsInline
                preload="auto"
                muted={muteVideoAudio}
                className={previewMediaClass}
                style={{
                  opacity: 0,
                  zIndex: 1,
                }}
              />
            </>
          ) : useLowResPoster || useLowResPosterForPlay ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={templateThumbUrl || overlayThumbUrl}
              alt="低清预览"
              className="h-full w-full object-contain"
            />
          ) : templateThumbUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={templateThumbUrl} alt="模板预览" className="h-full w-full object-contain" />
          ) : (
            <div className="flex h-full min-h-[200px] w-full min-w-[120px] items-center justify-center bg-black text-xs text-[#555]">
              {!previewMix.showVideo ? '视频轨已隐藏' : '匹配素材后预览'}
            </div>
          )}

          {showOverlayPreview ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={overlayThumbUrl}
              alt=""
              className={`pointer-events-none ${previewMediaClass}`}
            />
          ) : null}

          {subtitleText && !finalExportUrl ? (
            <div className="pointer-events-none absolute inset-x-0 bottom-[10%] px-5 text-center">
              <p
                className="text-[15px] font-bold leading-snug text-white"
                style={{
                  textShadow:
                    '0 1px 2px rgba(0,0,0,0.9), 0 0 8px rgba(0,0,0,0.6), 1px 1px 0 #000, -1px -1px 0 #000',
                }}
              >
                {subtitleText}
              </p>
            </div>
          ) : null}

          {templateAudioUrl && !finalExportUrl ? (
            // eslint-disable-next-line jsx-a11y/media-has-caption
            <audio ref={bgmRef} src={toMediaUrl(templateAudioUrl)} preload="auto" className="hidden" />
          ) : null}
        </div>
      </div>

      <div className="relative flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-editor-border bg-editor-panel-2/60 px-2 py-2 sm:flex-nowrap sm:px-3">
        <div className="flex min-w-0 flex-1 items-center gap-1.5 sm:gap-2">
          <span className="font-mono text-[13px] font-medium tabular-nums text-[#5ec8d8]">
            {formatTimecode(playheadTime)}
          </span>
          <span className="font-mono text-[13px] tabular-nums text-[#8e8e93]">
            {formatTimecode(totalDuration)}
          </span>
          <div ref={trackListRef} className="relative">
            <button
              type="button"
              onClick={() => {
                setTrackListOpen((v) => !v);
                setQualityOpen(false);
                setAspectOpen(false);
              }}
              className={`ml-1 flex h-6 w-6 items-center justify-center rounded hover:bg-[#2a2a2c] ${
                trackListOpen ? 'bg-[#2a2a2c] text-[#face15]' : 'text-[#6e6e72] hover:text-[#b8b8bc]'
              }`}
              title="轨道状态"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                <path d="M4 6h4v4H4V6zm6 0h10v4H10V6zM4 14h4v4H4v-4zm6 0h10v4H10v-4z" />
              </svg>
            </button>
            <CompactMenu open={trackListOpen} width="w-[188px]">
              {trackStatusRows.map((row) => (
                <div
                  key={row.key}
                  className="flex items-center justify-between gap-2 px-2 py-1 text-[11px]"
                >
                  <span className="text-[#e5e5ea]">{row.label}</span>
                  <span className={row.ok ? 'text-[#4ade80]' : 'text-[#face15]'}>{row.status}</span>
                </div>
              ))}
            </CompactMenu>
          </div>
          {onPlayheadStep ? (
            <>
              <button
                type="button"
                onClick={() => onPlayheadStep(-FRAME_STEP)}
                className="flex h-6 w-6 items-center justify-center rounded text-[#6e6e72] hover:bg-[#2a2a2c] hover:text-[#b8b8bc]"
                title="上一帧"
              >
                ‹
              </button>
              <button
                type="button"
                onClick={() => onPlayheadStep(FRAME_STEP)}
                className="flex h-6 w-6 items-center justify-center rounded text-[#6e6e72] hover:bg-[#2a2a2c] hover:text-[#b8b8bc]"
                title="下一帧"
              >
                ›
              </button>
            </>
          ) : null}
        </div>

        <button
          type="button"
          onClick={onTogglePlay}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[#e5e5ea] transition-colors hover:bg-[#2a2a2c] hover:text-white"
          title={isPlaying ? '暂停' : '播放'}
        >
          {isPlaying ? <PauseIcon /> : <PlayIcon />}
        </button>

        <div className="relative flex items-center gap-1.5">
          <div ref={qualityWrapRef} className="relative">
            <button
              type="button"
              onClick={() => {
                setQualityOpen((v) => !v);
                setAspectOpen(false);
              }}
              className={`rounded px-1.5 py-0.5 text-[11px] hover:bg-[#2a2a2c] ${
                qualityOpen ? 'bg-[#2a2a2c] text-[#face15]' : 'text-[#9a9a9e] hover:text-[#e5e5ea]'
              }`}
              title={qualityPreset.hint}
            >
              {qualityPreset.label}
            </button>
            <CompactMenu open={qualityOpen} width="w-[240px]">
              {PREVIEW_QUALITY_PRESETS.map((q) => {
                const avail = qualityAvailability.find((a) => a.id === q.id);
                const selected = qualityId === q.id;
                const disabled = !avail?.playable;
                return (
                  <button
                    key={q.id}
                    type="button"
                    title={q.hint}
                    disabled={disabled}
                    onClick={() => handleQualityChange(q.id)}
                    className={`block w-full px-2 py-1.5 text-left hover:bg-[#353538] disabled:cursor-not-allowed disabled:opacity-40 ${
                      selected ? 'bg-[#353538] text-[#face15]' : 'text-[#e5e5ea]'
                    }`}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="text-[11px]">{q.label}</span>
                      <span
                        className={`shrink-0 text-[9px] ${
                          avail?.proxyReady ? 'text-[#4ade80]' : 'text-[#6e6e72]'
                        }`}
                      >
                        {avail?.statusText}
                      </span>
                    </span>
                    <span className="block text-[9px] text-[#6e6e72]">
                      {q.resolutionLabel} · {q.description}
                    </span>
                  </button>
                );
              })}
            </CompactMenu>
          </div>

          <button
            type="button"
            onClick={cycleZoom}
            className="flex h-6 w-6 items-center justify-center rounded text-[#6e6e72] hover:bg-[#2a2a2c] hover:text-[#b8b8bc]"
            title={`缩放 ${Math.round(previewZoom * 100)}%`}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="7" />
              <path d="M21 21l-4.35-4.35M11 8v6M8 11h6" />
            </svg>
          </button>

          <div ref={aspectWrapRef} className="relative">
            <button
              type="button"
              onClick={() => {
                setAspectOpen((v) => !v);
                setQualityOpen(false);
              }}
              className={`rounded px-1.5 py-0.5 font-mono text-[11px] hover:bg-[#2a2a2c] ${
                aspectOpen ? 'bg-[#2a2a2c] text-[#face15]' : 'text-[#9a9a9e] hover:text-[#e5e5ea]'
              }`}
              title={aspectId === 'auto' ? '原画：按视频实际比例显示' : '画幅比例'}
            >
              {aspectPreset.label}
            </button>
            <CompactMenu open={aspectOpen} width="w-[72px]">
              <div className="max-h-[168px] overflow-y-auto">
                {ASPECT_RATIO_PRESETS.map((a) => (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => {
                      setAspectId(a.id);
                      setAspectOpen(false);
                    }}
                    className={`block w-full px-2 py-0.5 text-center font-mono text-[11px] hover:bg-[#353538] ${
                      aspectId === a.id ? 'bg-[#353538] text-[#face15]' : 'text-[#e5e5ea]'
                    }`}
                  >
                    {a.label}
                  </button>
                ))}
              </div>
            </CompactMenu>
          </div>

          <button
            type="button"
            onClick={toggleFullscreen}
            className="flex h-6 w-6 items-center justify-center rounded text-[#6e6e72] hover:bg-[#2a2a2c] hover:text-[#b8b8bc]"
            title="全屏"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5" />
            </svg>
          </button>
        </div>
      </div>

      {menuOpen ? (
        <div className="absolute inset-y-0 right-0 z-20 flex w-[min(280px,85%)] flex-col border-l border-[#2a2a2c] bg-[#1e1e20] shadow-2xl">
          <div className="flex items-center justify-between border-b border-[#2a2a2c] px-3 py-2">
            <span className="text-xs font-medium text-[#e5e5ea]">导出与发布</span>
            <button type="button" onClick={() => setMenuOpen(false)} className="text-[#8e8e93] hover:text-white">
              ✕
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            <label className="mb-3 flex items-center gap-2 text-[11px] text-[#8b8b8b]">
              <input
                type="checkbox"
                checked={addSubtitles}
                onChange={(e) => onAddSubtitlesChange?.(e.target.checked)}
                className="accent-[#face15]"
              />
              导出时烧录字幕
            </label>
            <label className="mb-3 flex flex-col gap-1 text-[11px] text-[#8b8b8b]">
              导出分辨率
              <select
                value={exportResolution}
                onChange={(e) => onExportResolutionChange?.(e.target.value)}
                className="rounded border border-[#3a3a3c] bg-[#141416] px-2 py-1.5 text-xs text-[#e5e5e5]"
              >
                <option value="1080x1920">1080×1920</option>
                <option value="2160x3840">4K 竖屏</option>
                <option value="3840x2160">4K 横屏</option>
              </select>
            </label>
            {finalExportUrl ? (
              <a
                href={finalExportUrl}
                target="_blank"
                rel="noreferrer"
                className="mb-3 block rounded bg-[#2a2a2c] py-2 text-center text-xs text-[#face15] hover:bg-[#333]"
              >
                下载导出视频 →
              </a>
            ) : null}
            {onExport ? (
              <button
                type="button"
                disabled={!canExport || exporting}
                onClick={onExport}
                className="mb-3 w-full rounded bg-[#face15] py-2 text-xs font-semibold text-black hover:bg-[#ffe066] disabled:cursor-not-allowed disabled:bg-[#665c20] disabled:text-[#999]"
              >
                {exporting ? `导出中… ${exportProgress > 0 ? `${exportProgress}%` : ''}` : '开始导出'}
              </button>
            ) : null}
            {onExportCapCut ? (
              <>
                {onCapCutReplaceableModeChange ? (
                  <label className="mb-2 flex cursor-pointer items-start gap-2 rounded border border-[#3a3a3c] bg-[#1a1a1c] px-2 py-2 text-[10px] leading-relaxed text-[#b0b0b0]">
                    <input
                      type="checkbox"
                      checked={capCutReplaceableMode}
                      onChange={(e) => onCapCutReplaceableModeChange(e.target.checked)}
                      className="mt-0.5 shrink-0"
                    />
                    <span>
                      <span className="font-medium text-[#e5e5e5]">可替换模板</span>
                      <span className="block text-[#8b8b8b]">
                        导出模板占位片段与槽位标签，在剪映中逐段「替换素材」套用你的成片
                      </span>
                    </span>
                  </label>
                ) : null}
                <button
                  type="button"
                  disabled={!canExport || capCutExporting || exporting || capCutMateStatus?.ready === false}
                  onClick={onExportCapCut}
                  className="mb-2 w-full rounded border border-[#face15]/40 bg-[#2a2a2c] py-2 text-xs font-medium text-[#face15] hover:bg-[#333] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {capCutExporting
                    ? `生成剪映草稿… ${capCutExportProgress > 0 ? `${capCutExportProgress}%` : ''}`
                    : capCutReplaceableMode
                      ? '导出可替换模板草稿'
                      : '导出剪映草稿（成片）'}
                </button>
                {capCutExporting ? (
                  <div className="mb-3 h-1.5 overflow-hidden rounded bg-[#1a3a1a]">
                    <div
                      className={`h-full transition-all ${capCutExportProgress <= 0 ? 'w-1/3 animate-pulse bg-[#face15]/60' : 'bg-[#4ade80]'}`}
                      style={
                        capCutExportProgress > 0
                          ? { width: `${Math.max(5, capCutExportProgress)}%` }
                          : undefined
                      }
                    />
                  </div>
                ) : null}
                {capCutMateStatus && !capCutMateStatus.ready ? (
                  <div className="mb-3 rounded border border-[#5c3a20] bg-[#2a1f14] px-2 py-2 text-[10px] leading-relaxed text-[#fbbf24]">
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <p className="font-medium">剪映小助手未就绪</p>
                      {onRefreshCapCutMate ? (
                        <button
                          type="button"
                          onClick={onRefreshCapCutMate}
                          className="shrink-0 rounded bg-[#3a2a14] px-2 py-0.5 text-[9px] text-[#face15] hover:bg-[#4a3518]"
                        >
                          重新检测
                        </button>
                      ) : null}
                    </div>
                    <ul className="list-inside list-disc space-y-0.5 text-[#d4a574]">
                      {capCutSetupSteps(capCutMateStatus).map((step) => (
                        <li key={step}>{step}</li>
                      ))}
                    </ul>
                  </div>
                ) : capCutMateStatus?.ready ? (
                  <p className="mb-3 text-[10px] text-[#4ade80]">剪映小助手已连接</p>
                ) : null}
              </>
            ) : null}
            {capCutStatus ? (
              <p
                className={`mb-3 text-[10px] leading-relaxed ${
                  capCutDraftUrl
                    ? 'rounded border border-[#2d4a2d] bg-[#142014] px-2 py-2 text-[#4ade80]'
                    : capCutExporting
                      ? 'text-[#face15]'
                      : 'rounded border border-[#4a2020] bg-[#2a1414] px-2 py-2 text-[#f87171]'
                }`}
              >
                {capCutStatus}
              </p>
            ) : null}
            {capCutDraftUrl ? (
              <div className="mb-3 space-y-2">
                <button
                  type="button"
                  onClick={onOpenCapCutDraft}
                  className="w-full rounded bg-[#face15] py-2 text-xs font-semibold text-black hover:bg-[#ffe066]"
                >
                  在剪映中打开草稿
                </button>
                <button
                  type="button"
                  onClick={onOpenCapCutDraft}
                  className="w-full rounded border border-[#444] bg-[#2a2a2c] py-2 text-[10px] text-[#ccc] hover:bg-[#333]"
                >
                  重新安装到剪映
                </button>
                <p className="text-[10px] leading-relaxed text-[#6e6e72]">
                  点击后将草稿安装到剪映目录；请打开剪映 PC 版在草稿列表中查看，不要手动新建空白项目。
                </p>
                {capCutReplaceableMode ? (
                  <div className="rounded border border-[#5c4a20] bg-[#2a2414] px-2 py-2 text-[10px] leading-relaxed text-[#d4a574]">
                    <p className="mb-1 font-medium text-[#face15]">剪映内替换素材</p>
                    <ol className="list-inside list-decimal space-y-0.5">
                      {REPLACEABLE_TEMPLATE_STEPS.map((step) => (
                        <li key={step}>{step}</li>
                      ))}
                    </ol>
                  </div>
                ) : null}
              </div>
            ) : null}
            {exporting && exportProgress > 0 ? (
              <div className="mb-3 h-1 overflow-hidden rounded bg-[#1a3a1a]">
                <div
                  className="h-full bg-[#4ade80] transition-all"
                  style={{ width: `${exportProgress}%` }}
                />
              </div>
            ) : null}
            <PublishPanel exportUrl={exportUrl} />
          </div>
        </div>
      ) : null}
      {menuOpen ? (
        <button
          type="button"
          className="absolute inset-0 z-10 bg-black/40"
          aria-label="关闭菜单"
          onClick={() => setMenuOpen(false)}
        />
      ) : null}
    </section>
  );
}
