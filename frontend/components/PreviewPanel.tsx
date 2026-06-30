'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import { buildMainVideoClipLayouts, findClipAtTime, getTotalDuration, subtitleTextAtPlayheadGlobal } from '@/lib/timelineLayout';
import { resolveMainTimelineSlots } from '@/lib/slotTimelineHelpers';
import {
  applyPreviewVideoAudio,
  applyBgmPolicyTransition,
  findLayoutIndex,
  findNextPlayableIndex,
  isContiguousSameStream,
  PREVIEW_CLIP_SWITCH_EPSILON,
  PREVIEW_FRAME_SEC,
  PREVIEW_PLAY_RATE_NUDGE_MAX,
  PREVIEW_PLAY_SEEK_THRESHOLD,
  preparePreviewVideo,
  resolveMasterTimelineTime,
  resolvePreviewAudioPolicy,
  resolveSlotPreviewMedia,
  seekVideoElement,
  shouldPreloadNextPreviewSlot,
  seekPreviewBgm,
  syncPreviewVideoToSlot,
  timelineToVideoTime,
  unloadPreviewVideo,
  type PreviewAudioPolicy,
  type PreviewVideoSyncState,
  type ResolvedPreviewAudio,
  type SlotPreviewMedia,
} from '@/lib/previewPlayback';
import type { SubtitleClip, TemplateSlot } from '@/lib/timeline';
import { colorGradeToCssFilter } from '@/lib/slotEffects';
import PreviewExportDrawer from '@/components/PreviewExportDrawer';
import {
  CompactMenu,
  formatPreviewTimecode,
  PauseIcon,
  PlayIcon,
  PREVIEW_FRAME_STEP,
  useClickOutside,
} from '@/lib/previewPanelUi';
import { type CapCutMateStatus } from '@/lib/capcutExport';
import { resolvePreviewMix, type TrackControls, type TrackKey, TRACK_KEYS, TRACK_LABELS } from '@/lib/trackControls';

type AssetPreviewInfo = {
  filePath?: string;
  proxyPath?: string;
  proxyPaths?: PreviewProxyPaths;
  thumbnail?: string;
};

type PreviewPanelProps = {
  slots: TemplateSlot[];
  subtitleClips?: SubtitleClip[];
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

export default function PreviewPanel({
  slots,
  subtitleClips = [],
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
  const lastBgmPolicyRef = useRef<ResolvedPreviewAudio | null>(null);
  const playClockRef = useRef({ wall: 0, timeline: 0 });
  const videoSyncStateRef = useRef<PreviewVideoSyncState>({ pendingKey: '' });
  const lastSyncedIdxRef = useRef(-1);
  const playSessionRef = useRef(0);
  const lastPlayheadReportRef = useRef(-1);
  const onPlayheadChangeRef = useRef(onPlayheadChange);
  const bgmRef = useRef<HTMLAudioElement | null>(null);
  const playheadRef = useRef(playheadTime);
  const scrubSyncRafRef = useRef(0);
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
  const mainTimelineSlots = useMemo(
    () => resolveMainTimelineSlots(slots, subtitleClips),
    [slots, subtitleClips]
  );
  const totalDuration = useMemo(() => getTotalDuration(mainTimelineSlots), [mainTimelineSlots]);
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

  const clipLayouts = useMemo(
    () => buildMainVideoClipLayouts(slots, subtitleClips, 1),
    [slots, subtitleClips]
  );

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
  /** 播放中强制走 video 元素，避免缩略图占位导致无画面/无法切镜 */
  const blockVideoForPoster = (useLowResPoster || useLowResPosterForPlay) && !isPlaying;
  const hasPreviewVideo = Boolean(
    previewSrc || (!finalExportUrl && templateVideoPath && previewMix.showVideo)
  );

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

  const slotsMediaKey = useMemo(
    () =>
      slots
        .map(
          (slot) =>
            `${slot.id}:${slot.matchedAssetId ?? ''}:${slot.asset_file_path ?? ''}:${slot.clipStart}:${slot.useOriginalAudio ? 1 : 0}`
        )
        .join('|'),
    [slots]
  );

  const resolveSlotAudio = useCallback(
    (slot: TemplateSlot | null | undefined) =>
      resolvePreviewAudioPolicy({
        useOriginalAudio: Boolean(slot?.useOriginalAudio),
        hasMatchedAsset: Boolean(slot?.asset_file_path || slot?.matchedAssetId),
        templateMusicEnabled,
        hasTemplateAudioUrl: Boolean(templateAudioUrl),
        hasTemplateVideoPath: Boolean(templateVideoPath),
        previewMix,
      }),
    [templateMusicEnabled, templateAudioUrl, templateVideoPath, previewMix]
  );

  const previewAudio = useMemo(
    () => resolveSlotAudio(activeLayout?.slot ?? displaySlot),
    [activeLayout?.slot, displaySlot, resolveSlotAudio]
  );

  const previewAudioPolicyKey = useMemo(() => {
    const p = previewAudio;
    return `${Number(p.playTemplateBgm)}:${Number(p.playClipAudio)}:${Number(p.playTemplateVideoAudio)}:${Number(p.muteVideo)}`;
  }, [previewAudio]);

  const mutedBackBufferPolicy = useMemo<PreviewAudioPolicy>(
    () => ({ muteVideo: true, videoVolume: 0 }),
    []
  );

  // 仅槽位素材变化时重置预览缓冲（勿依赖 previewAudio，否则跨段播放会误触发卸载）
  useEffect(() => {
    playSessionRef.current += 1;
    preloadedNextRef.current = false;
    backBufferReadyRef.current = false;
    lastBgmPolicyRef.current = null;
    videoSyncStateRef.current.pendingKey = '';
    playClockRef.current = { wall: 0, timeline: 0 };
    lastSyncedIdxRef.current = -1;
    layoutIndexRef.current = findLayoutIndex(clipLayouts, playheadRef.current);
    [videoRefA.current, videoRefB.current].forEach((video) => {
      if (!video) return;
      unloadPreviewVideo(video);
    });

    const bgm = bgmRef.current;
    if (bgm && templateAudioUrl && !finalExportUrl) {
      bgm.pause();
      const idx = findLayoutIndex(clipLayouts, playheadRef.current);
      const slot = clipLayouts[idx]?.slot ?? null;
      applyBgmPolicyTransition(
        bgm,
        resolveSlotAudio(slot),
        lastBgmPolicyRef.current,
        playheadRef.current,
        false
      );
      lastBgmPolicyRef.current = resolveSlotAudio(slot);
      try {
        bgm.currentTime = playheadRef.current;
      } catch {
        /* ignore */
      }
    }
  }, [slotsMediaKey, templateAudioUrl, finalExportUrl, resolveSlotAudio, clipLayouts]);

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
      if (!active) {
        applyPreviewVideoAudio(el, { muteVideo: true, videoVolume: 0 });
      }
    });
  }, []);

  const prepareVideoEl = useCallback(
    (
      el: HTMLVideoElement,
      media: SlotPreviewMedia,
      videoTime: number,
      autoplay: boolean,
      audio?: PreviewAudioPolicy
    ) => preparePreviewVideo(el, media, videoTime, autoplay, audio),
    []
  );

  useEffect(() => {
    onPlayheadChangeRef.current = onPlayheadChange;
  }, [onPlayheadChange]);

  useEffect(() => {
    playheadRef.current = playheadTime;
  }, [playheadTime]);

  const { muteVideo: muteVideoAudio } = previewAudio;

  const applyFrontPreviewAudio = useCallback(
    (policy = previewAudio) => {
      const front = frontLayerRef.current === 0 ? videoRefA.current : videoRefB.current;
      const back = frontLayerRef.current === 0 ? videoRefB.current : videoRefA.current;
      if (front) applyPreviewVideoAudio(front, policy);
      if (back) applyPreviewVideoAudio(back, mutedBackBufferPolicy);
    },
    [previewAudio, mutedBackBufferPolicy]
  );

  useEffect(() => {
    if (isPlaying || finalExportUrl) return;
    applyFrontPreviewAudio();
  }, [applyFrontPreviewAudio, finalExportUrl, isPlaying]);

  // 暂停/拖拽：每帧合并一次同步，避免逐像素 seek 卡顿；BGM 跟播放头不走 0 点
  useEffect(() => {
    if (isPlaying || finalExportUrl || !slotMedias.some(Boolean)) return;

    cancelAnimationFrame(scrubSyncRafRef.current);
    scrubSyncRafRef.current = requestAnimationFrame(() => {
      const t = playheadTime;
      const idx = findLayoutIndex(clipLayouts, t);
      const media = slotMedias[idx];
      if (!media) return;

      if (idx !== layoutIndexRef.current) {
        preloadedNextRef.current = false;
        backBufferReadyRef.current = false;
        videoSyncStateRef.current.pendingKey = '';
      }
      layoutIndexRef.current = idx;
      lastSyncedIdxRef.current = idx;

      const front = frontLayerRef.current === 0 ? videoRefA.current : videoRefB.current;
      if (!front) return;

      const policy = resolveSlotAudio(media.layout.slot);
      seekPreviewBgm(bgmRef.current, policy, t);

      void syncPreviewVideoToSlot(
        front,
        media,
        t,
        policy,
        videoSyncStateRef.current,
        { autoplay: false, seekEpsilon: PREVIEW_FRAME_SEC }
      ).then(() => {
        setLayerVisibility(frontLayerRef.current);
      });
    });

    return () => cancelAnimationFrame(scrubSyncRafRef.current);
  }, [clipLayouts, finalExportUrl, isPlaying, playheadTime, resolveSlotAudio, setLayerVisibility, slotMedias]);

  // 播放：BGM/墙钟驱动时间轴，视频跟随时间轴切镜（全程连续，无需手动切下一段）
  useEffect(() => {
    if (!isPlaying || finalExportUrl || !slotMedias.some(Boolean)) return;

    const session = ++playSessionRef.current;
    let raf = 0;

    playClockRef.current = { wall: performance.now(), timeline: playheadRef.current };
    videoSyncStateRef.current.pendingKey = '';

    const reportPlayhead = (time: number) => {
      if (Math.abs(time - lastPlayheadReportRef.current) < 1 / 15) return;
      lastPlayheadReportRef.current = time;
      playheadRef.current = time;
      onPlayheadChangeRef.current?.(time);
    };

    const getFrontEl = () =>
      frontLayerRef.current === 0 ? videoRefA.current : videoRefB.current;
    const getBackEl = () =>
      frontLayerRef.current === 0 ? videoRefB.current : videoRefA.current;

    const tick = () => {
      if (session !== playSessionRef.current) return;

      const frontEl = getFrontEl();
      if (!frontEl) {
        raf = requestAnimationFrame(tick);
        return;
      }

      const bgm = bgmRef.current;
      let idx = layoutIndexRef.current;
      let media = slotMedias[idx];
      if (!media) {
        raf = requestAnimationFrame(tick);
        return;
      }

      let policy = resolveSlotAudio(media.layout.slot);

      let timelineT = resolveMasterTimelineTime({
        playing: true,
        media,
        frontEl,
        policy,
        clock: playClockRef.current,
        fallbackTime: playheadRef.current,
        totalDuration,
      });

      // 原声槽位：视频播完自动进入下一段
      if (policy.playClipAudio && frontEl.ended) {
        const nextIdx = findNextPlayableIndex(slotMedias, idx);
        const nextMedia = nextIdx >= 0 ? slotMedias[nextIdx] : null;
        if (nextMedia && timelineT >= media.layout.end - PREVIEW_CLIP_SWITCH_EPSILON) {
          timelineT = nextMedia.layout.start;
        }
      }

      idx = findLayoutIndex(clipLayouts, timelineT);
      layoutIndexRef.current = idx;
      media = slotMedias[idx];
      if (!media) {
        raf = requestAnimationFrame(tick);
        return;
      }

      policy = resolveSlotAudio(media.layout.slot);
      reportPlayhead(timelineT);
      applyBgmPolicyTransition(bgm, policy, lastBgmPolicyRef.current, timelineT, true);
      lastBgmPolicyRef.current = policy;

      const backEl = getBackEl();
      if (backEl) {
        applyPreviewVideoAudio(backEl, mutedBackBufferPolicy);
      }

      const nextIdx = findNextPlayableIndex(slotMedias, idx);
      const nextMedia = nextIdx >= 0 ? slotMedias[nextIdx] : null;

      if (
        nextMedia &&
        backEl &&
        !isContiguousSameStream(media, nextMedia) &&
        shouldPreloadNextPreviewSlot(media, timelineT) &&
        !preloadedNextRef.current
      ) {
        preloadedNextRef.current = true;
        backBufferReadyRef.current = false;
        void prepareVideoEl(
          backEl,
          nextMedia,
          timelineToVideoTime(nextMedia, nextMedia.layout.start),
          true,
          mutedBackBufferPolicy
        )
          .then(() => {
            if (session === playSessionRef.current) {
              applyPreviewVideoAudio(backEl, mutedBackBufferPolicy);
              backBufferReadyRef.current = true;
            }
          })
          .catch(() => {
            if (session === playSessionRef.current) {
              preloadedNextRef.current = false;
              backBufferReadyRef.current = false;
            }
          });
      }

      const targetVideoT = timelineToVideoTime(media, timelineT);
      const streamMismatch = frontEl.dataset.stream !== media.streamUrl;
      const idxChanged = lastSyncedIdxRef.current !== idx;
      const prevMedia =
        lastSyncedIdxRef.current >= 0 ? slotMedias[lastSyncedIdxRef.current] : null;
      const contiguousHandoff =
        idxChanged &&
        prevMedia &&
        !streamMismatch &&
        isContiguousSameStream(prevMedia, media) &&
        Math.abs(frontEl.currentTime - targetVideoT) <= 0.2;
      const backReady =
        backBufferReadyRef.current &&
        backEl &&
        backEl.dataset.stream === media.streamUrl;
      const canSwapBack =
        backReady && backEl && backEl.dataset.stream === media.streamUrl;
      const needsVideoSync =
        !contiguousHandoff &&
        (idxChanged ||
          streamMismatch ||
          frontEl.ended ||
          Math.abs(frontEl.currentTime - targetVideoT) > PREVIEW_PLAY_SEEK_THRESHOLD);

      const drift = targetVideoT - frontEl.currentTime;
      const canRateNudge =
        !policy.playClipAudio &&
        !contiguousHandoff &&
        !idxChanged &&
        !streamMismatch &&
        !frontEl.ended &&
        Math.abs(drift) > PREVIEW_FRAME_SEC &&
        Math.abs(drift) <= PREVIEW_PLAY_RATE_NUDGE_MAX;

      if (contiguousHandoff) {
        frontEl.playbackRate = 1;
        lastSyncedIdxRef.current = idx;
        applyPreviewVideoAudio(frontEl, policy);
        if (frontEl.paused && !frontEl.ended) {
          void frontEl.play().catch(() => undefined);
        }
      } else if (canRateNudge && !needsVideoSync) {
        frontEl.playbackRate = drift > 0 ? Math.min(1.12, 1 + drift * 0.35) : Math.max(0.88, 1 + drift * 0.35);
        applyPreviewVideoAudio(frontEl, policy);
        if (frontEl.paused && !frontEl.ended) {
          void frontEl.play().catch(() => undefined);
        }
      } else if (needsVideoSync) {
        frontEl.playbackRate = 1;
        if ((streamMismatch || idxChanged) && canSwapBack) {
          frontLayerRef.current = (1 - frontLayerRef.current) as 0 | 1;
          frontEl.pause();
          applyPreviewVideoAudio(frontEl, mutedBackBufferPolicy);
          backEl.dataset.filter = media.cssFilter || '';
          applyPreviewVideoAudio(backEl, policy);
          setLayerVisibility(frontLayerRef.current);
          preloadedNextRef.current = false;
          backBufferReadyRef.current = false;
          lastSyncedIdxRef.current = idx;
          if (backEl.paused) {
            void backEl.play().catch(() => undefined);
          }
        } else {
          if (idxChanged) {
            videoSyncStateRef.current.pendingKey = '';
          }
          void syncPreviewVideoToSlot(
            frontEl,
            media,
            timelineT,
            policy,
            videoSyncStateRef.current,
            { autoplay: true, seekEpsilon: PREVIEW_PLAY_SEEK_THRESHOLD }
          ).then(() => {
            if (session === playSessionRef.current) {
              lastSyncedIdxRef.current = idx;
            }
          });
        }
      } else {
        frontEl.playbackRate = 1;
        applyPreviewVideoAudio(frontEl, policy);
        if (frontEl.paused && !frontEl.ended) {
          void frontEl.play().catch(() => undefined);
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
    lastBgmPolicyRef.current = null;
    lastSyncedIdxRef.current = startIdx;

    const startMedia = slotMedias[startIdx];

    raf = requestAnimationFrame(tick);

    if (startMedia) {
      const startPolicy = resolveSlotAudio(startMedia.layout.slot);
      const bgm = bgmRef.current;
      if (startPolicy.playTemplateBgm && bgm) {
        try {
          bgm.currentTime = playheadRef.current;
        } catch {
          /* ignore */
        }
        bgm.volume = 0.85;
        bgm.muted = false;
        void bgm.play().catch(() => undefined);
        lastBgmPolicyRef.current = startPolicy;
      }
    }

    return () => {
      playSessionRef.current += 1;
      if (raf) cancelAnimationFrame(raf);
      videoSyncStateRef.current.pendingKey = '';
      [videoRefA.current, videoRefB.current].forEach((v) => v?.pause());
    };
  }, [
    clipLayouts,
    finalExportUrl,
    isPlaying,
    mutedBackBufferPolicy,
    prepareVideoEl,
    resolveSlotAudio,
    setLayerVisibility,
    slotMedias,
    totalDuration,
  ]);

  useEffect(() => {
    if (!bgmRef.current || finalExportUrl || isPlaying) return;
    applyBgmPolicyTransition(
      bgmRef.current,
      previewAudio,
      lastBgmPolicyRef.current,
      playheadRef.current,
      false
    );
    lastBgmPolicyRef.current = previewAudio;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed by previewAudioPolicyKey
  }, [finalExportUrl, isPlaying, previewAudioPolicyKey, templateAudioUrl]);

  const subtitleText = useMemo(() => {
    if (!previewMix.showSubtitle) return '';
    return subtitleTextAtPlayheadGlobal(slots, playheadTime, subtitleClips);
  }, [previewMix.showSubtitle, slots, playheadTime, subtitleClips]);

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
          ) : hasPreviewVideo && !blockVideoForPoster ? (
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
          ) : blockVideoForPoster ? (
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
            {formatPreviewTimecode(playheadTime)}
          </span>
          <span className="font-mono text-[13px] tabular-nums text-[#8e8e93]">
            {formatPreviewTimecode(totalDuration)}
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
                onClick={() => onPlayheadStep(-PREVIEW_FRAME_STEP)}
                className="flex h-6 w-6 items-center justify-center rounded text-[#6e6e72] hover:bg-[#2a2a2c] hover:text-[#b8b8bc]"
                title="上一帧"
              >
                ‹
              </button>
              <button
                type="button"
                onClick={() => onPlayheadStep(PREVIEW_FRAME_STEP)}
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

      <PreviewExportDrawer
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        exportUrl={exportUrl}
        exportResolution={exportResolution}
        onExportResolutionChange={onExportResolutionChange}
        addSubtitles={addSubtitles}
        onAddSubtitlesChange={onAddSubtitlesChange}
        exportProgress={exportProgress}
        exporting={exporting}
        onExport={onExport}
        onExportCapCut={onExportCapCut}
        capCutDraftUrl={capCutDraftUrl}
        capCutExporting={capCutExporting}
        capCutExportProgress={capCutExportProgress}
        capCutStatus={capCutStatus}
        capCutReplaceableMode={capCutReplaceableMode}
        onCapCutReplaceableModeChange={onCapCutReplaceableModeChange}
        capCutMateStatus={capCutMateStatus}
        onRefreshCapCutMate={onRefreshCapCutMate}
        onOpenCapCutDraft={onOpenCapCutDraft}
        canExport={canExport}
      />
    </section>
  );
}
