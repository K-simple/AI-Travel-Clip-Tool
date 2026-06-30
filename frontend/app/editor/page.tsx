"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type DragEvent } from 'react';
import AssetLibrary from '@/components/AssetLibrary';
import Timeline from '@/components/Timeline';
import { PanelSplitter } from '@/components/editor/PanelSplitter';
import { useEditorPanelSizes } from '@/components/editor/useEditorPanelSizes';
import PreviewPanel from '@/components/PreviewPanel';
import PropertiesPanel, { type MatchWeights } from '@/components/PropertiesPanel';
import Toolbar from '@/components/Toolbar';
import { apiHeaders, apiUrl, formatApiDetail, longRunningApiUrl, readApiJson, toMediaUrl } from '@/lib/api';
import {
  DEFAULT_ASSET_PANEL_WIDTH,
  DEFAULT_PLAYER_PANEL_WIDTH,
  DEFAULT_TIMELINE_PANEL_HEIGHT,
} from '@/lib/editorLayout';
import { getSlotSourceTimeRange, getSlotSourceTimeRangeById, splitSlotAtTime, syncSubtitleTextUpdate, type SfxMarker } from '@/lib/slotEdit';
import {
  applyAssetToSlot,
  timelineToSlots,
  type TemplateSlot,
} from '@/lib/timeline';
import {
  findFirstEmptySlotId,
  findSlotIdAtTime,
  getVideoFilesFromDataTransfer,
} from '@/lib/timelineDrop';
import { buildClipLayouts, getTotalDuration } from '@/lib/timelineLayout';
import {
  DEFAULT_TRACK_CONTROLS,
  describeTrackToggle,
  isTrackLocked,
  type TrackControls,
  type TrackKey,
  toggleTrackControl,
} from '@/lib/trackControls';
import {
  clampTrackHeight,
  getDefaultTrackHeight,
  type TrackHeightMap,
} from '@/lib/trackHeights';
import {
  DEFAULT_MATCH_STRATEGY,
  type MatchStrategy,
} from '@/lib/matchStrategy';
import { rippleClearRight, rippleDeleteSlot, trimClipDuration, trimClipStart, moveSlotById, reorderSlots } from '@/lib/slotOps';
import { useTemplateProcessing } from '@/lib/useTemplateProcessing';
import { useMatchFlow } from '@/lib/useMatchFlow';
import { useSubtitleFlow } from '@/lib/useSubtitleFlow';
import { useAssetProcessingPoll } from '@/lib/useAssetProcessing';
import { useAssetUpload } from '@/lib/useAssetUpload';
import { useTemplateFlow } from '@/lib/useTemplateFlow';
import type { PreviewProxyPaths } from '@/lib/previewSettings';
import { useSlotHistory } from '@/lib/useSlotHistory';
import {
  createOverlayClip,
  type OverlayTracks,
} from '@/lib/edlModel';
import ProjectListModal from '@/components/ProjectListModal';
import OnboardingGuide from '@/components/OnboardingGuide';
import GlobalStatusBar, { type GlobalStatusItem } from '@/components/GlobalStatusBar';
import { useProjectPersistence } from '@/lib/useProjectPersistence';
import { useExportFlow } from '@/lib/useExportFlow';
import { useAssetList, type Asset, formatAssetDuration } from '@/lib/useAssetList';
import { useEditorPlayback } from '@/lib/useEditorPlayback';
import { formatExportPrecheckDialog } from '@/lib/exportPrecheck';
import { computeOnboardingState, type OnboardingStepId } from '@/lib/onboardingSteps';

export default function EditorPage() {
  const { assets, setAssets, loadAssets } = useAssetList({ autoLoad: false });
  const {
    slots,
    setSlots,
    replaceSlots,
    undo,
    redo,
    canUndo,
    canRedo,
    resetHistory,
  } = useSlotHistory([]);
  const totalDuration = useMemo(() => getTotalDuration(slots), [slots]);
  const {
    playheadTime,
    setPlayheadTime,
    isPlaying,
    setIsPlaying,
    playheadRef,
    playStartRef,
    playRafRef,
    handlePlayheadStep,
    handleTogglePlay,
    handlePlayheadChange,
    handleScrubStart,
  } = useEditorPlayback(totalDuration);
  const [selectedSlotId, setSelectedSlotId] = useState<string>('');
  const [templateMusicEnabled, setTemplateMusicEnabled] = useState(true);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [templateName, setTemplateName] = useState<string>('未选择模板');
  const [projectId, setProjectId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [uploadingCount, setUploadingCount] = useState(0);
  const [recognizingSubtitle, setRecognizingSubtitle] = useState(false);
  const [matchWeights, setMatchWeights] = useState<MatchWeights>({
    tags_weight: 0.35,
    visual_weight: 0.35,
    duration_tolerance: 2.0,
  });
  const [trackControls, setTrackControls] = useState<Record<TrackKey, TrackControls>>(
    DEFAULT_TRACK_CONTROLS
  );
  const [trackHeights, setTrackHeights] = useState<TrackHeightMap>({});
  const workspaceRef = useRef<HTMLDivElement>(null);
  const timelineDragStartRef = useRef(DEFAULT_TIMELINE_PANEL_HEIGHT);
  const assetDragStartRef = useRef(DEFAULT_ASSET_PANEL_WIDTH);
  const playerDragStartRef = useRef(DEFAULT_PLAYER_PANEL_WIDTH);
  const {
    timelinePanelHeight,
    setTimelinePanelHeight,
    resetTimelinePanelHeight,
    assetPanelWidth,
    setAssetPanelWidth,
    resetAssetPanelWidth,
    playerPanelWidth,
    setPlayerPanelWidth,
    resetPlayerPanelWidth,
  } = useEditorPanelSizes();
  const [matchStrategy, setMatchStrategy] = useState<MatchStrategy>(DEFAULT_MATCH_STRATEGY);
  const [templateAudioPath, setTemplateAudioPath] = useState('');
  const [templateVideoPath, setTemplateVideoPath] = useState('');
  const [templateProxyPaths, setTemplateProxyPaths] = useState<PreviewProxyPaths>({});
  const [beatMarkers, setBeatMarkers] = useState<number[]>([]);
  const [sfxMarkers, setSfxMarkers] = useState<SfxMarker[]>([]);
  const templateProcessing = useTemplateProcessing(templateId);
  const lastTemplateSlotCountRef = useRef(0);
  const templateStuckPollsRef = useRef(0);
  const lastTemplateProgressRef = useRef<{ progress: number; at: number }>({
    progress: -1,
    at: 0,
  });
  const lastEnhanceStatusRef = useRef<string>('ready');
  const lastSlotsAiReadyCountRef = useRef(0);
  const lastSubtitleBatchRunningRef = useRef(false);
  const [trackControlMessage, setTrackControlMessage] = useState('');
  const trackControlTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [overlayTracks, setOverlayTracks] = useState<OverlayTracks>({ v2: [], v3: [] });
  const [projectListOpen, setProjectListOpen] = useState(false);
  const [coverThumbnail, setCoverThumbnail] = useState('');
  const [analyzingTemplateEffects, setAnalyzingTemplateEffects] = useState(false);
  const templateFileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (templateProcessing.beatMarkers.length) {
      setBeatMarkers(templateProcessing.beatMarkers);
    }
    if (templateProcessing.sfxMarkers.length) {
      setSfxMarkers(templateProcessing.sfxMarkers);
    }
  }, [templateProcessing.beatMarkers, templateProcessing.sfxMarkers]);

  useEffect(() => {
    if (templateProcessing.proxyPaths && Object.keys(templateProcessing.proxyPaths).length) {
      setTemplateProxyPaths(templateProcessing.proxyPaths);
    }
  }, [templateProcessing.proxyPaths]);

  useEffect(() => {
    if (!templateId) return;
    const now = Date.now();
    const progress = templateProcessing.progress;
    const status = templateProcessing.status;

    if (status !== 'processing') {
      templateStuckPollsRef.current = 0;
      lastTemplateProgressRef.current = { progress: -1, at: now };
      return;
    }

    const last = lastTemplateProgressRef.current;
    if (progress !== last.progress) {
      lastTemplateProgressRef.current = { progress, at: now };
      templateStuckPollsRef.current = 0;
      return;
    }

    const stuckMs = now - last.at;
    // 仅在上传后几乎无进展时尝试 reprocess（避免在 38% 镜头切分阶段误触发）
    if (progress <= 5 && stuckMs > 12_000) {
      templateStuckPollsRef.current += 1;
      if (templateStuckPollsRef.current >= 2) {
        templateStuckPollsRef.current = 0;
        lastTemplateProgressRef.current = { progress, at: now };
        void fetch(apiUrl(`/api/template/${templateId}/reprocess`), {
          method: 'POST',
          headers: apiHeaders(),
        }).catch(() => undefined);
      }
    }
  }, [templateId, templateProcessing.status, templateProcessing.progress]);

  const refreshProjectTimelineFromTemplate = useCallback(async () => {
    if (!projectId) return;
    try {
      const resp = await fetch(apiUrl(`/api/projects/${projectId}/refresh-from-template`), {
        method: 'POST',
        headers: apiHeaders(),
      });
      const data = await resp.json();
      if (!resp.ok || !data.success) return;
      const nextSlots = timelineToSlots((data.timeline || []) as Record<string, unknown>[]);
      if (nextSlots.length) {
        replaceSlots(nextSlots);
        setSelectedSlotId((current) =>
          nextSlots.some((s) => s.id === current) ? current : nextSlots[0]?.id ?? ''
        );
      }
    } catch {
      /* ignore */
    }
  }, [projectId, replaceSlots]);

  useEffect(() => {
    if (!templateId) return;
    if (!templateProcessing.editable && templateProcessing.status !== 'ready') return;
    void (async () => {
      try {
        const resp = await fetch(apiUrl(`/api/template/${templateId}`), { headers: apiHeaders() });
        const data = await resp.json();
        if (!resp.ok) return;
        if (data.audio_path) setTemplateAudioPath(data.audio_path as string);
        if (data.file_path) setTemplateVideoPath(data.file_path as string);
        if (data.proxy_paths && typeof data.proxy_paths === 'object') {
          setTemplateProxyPaths(data.proxy_paths as PreviewProxyPaths);
        }
        if (projectId) {
          void refreshProjectTimelineFromTemplate();
        }
      } catch {
        /* ignore */
      }
    })();
  }, [
    templateId,
    templateProcessing.editable,
    templateProcessing.status,
    projectId,
    refreshProjectTimelineFromTemplate,
  ]);

  useEffect(() => {
    const slotCount = templateProcessing.slotCount;
    if (!projectId || !templateId || slotCount <= 0) return;
    if (!templateProcessing.editable && templateProcessing.status !== 'ready') return;
    if (slotCount === lastTemplateSlotCountRef.current) return;
    lastTemplateSlotCountRef.current = slotCount;
    void refreshProjectTimelineFromTemplate();
  }, [
    projectId,
    templateId,
    templateProcessing.slotCount,
    templateProcessing.editable,
    templateProcessing.status,
    refreshProjectTimelineFromTemplate,
  ]);

  useEffect(() => {
    if (!projectId || !templateId) return;
    const prev = lastEnhanceStatusRef.current;
    const current = templateProcessing.enhanceStatus;
    if (prev === 'processing' && current === 'ready') {
      void refreshProjectTimelineFromTemplate();
    }
    lastEnhanceStatusRef.current = current;
  }, [
    projectId,
    templateId,
    templateProcessing.enhanceStatus,
    refreshProjectTimelineFromTemplate,
  ]);

  useEffect(() => {
    if (!projectId || !templateId) return;
    if (templateProcessing.enhanceStatus !== 'processing') return;
    const count = templateProcessing.slotsAiReadyCount;
    if (count <= lastSlotsAiReadyCountRef.current) return;
    lastSlotsAiReadyCountRef.current = count;
    void refreshProjectTimelineFromTemplate();
  }, [
    projectId,
    templateId,
    templateProcessing.enhanceStatus,
    templateProcessing.slotsAiReadyCount,
    refreshProjectTimelineFromTemplate,
  ]);

  const assetMap = useMemo(
    () => Object.fromEntries(assets.map((asset) => [asset.id, asset])),
    [assets]
  );

  const {
    loadingProject,
    savingProject,
    autosaveStatus,
    setAutosaveStatus,
    loadProject,
    saveProject,
    createProjectFromTemplate,
    pauseAutosave,
  } = useProjectPersistence({
    projectId,
    setProjectId,
    setTemplateId,
    slots,
    replaceSlots,
    resetHistory,
    setSelectedSlotId,
    assetMap,
    trackControls,
    trackHeights,
    matchStrategy,
    overlayTracks,
    coverThumbnail,
    setTemplateName,
    setCoverThumbnail,
    setTemplateAudioPath,
    setTemplateVideoPath,
    setTemplateProxyPaths,
    setBeatMarkers,
    setSfxMarkers,
    setMatchStrategy,
    setTrackControls,
    setTrackHeights,
    setOverlayTracks,
  });

  useEffect(() => {
    loadAssets();
    const params = new URLSearchParams(window.location.search);
    const id = params.get('project_id');
    if (id) {
      void loadProject(id);
    }
  }, [loadAssets, loadProject]);

  const {
    matching,
    matchMessage,
    matchError,
    runAutoMatch,
  } = useMatchFlow({
    projectId,
    templateId,
    slots,
    assets,
    matchStrategy,
    matchWeights,
    saveProject,
    setSlots,
    setIsPlaying,
  });

  const {
    recognizingAllSubtitles,
    recognizeProgress,
    subtitleMode,
    setSubtitleMode,
    spokenCaptions,
    subtitleClips,
    recognitionDebug,
    ttsSegments,
    voiceProfiles,
    selectedVoiceId,
    setSelectedVoiceId,
    generatingTts,
    aligningTimeline,
    runRecognizeAll,
    applyCaptionSlots,
    applyVisualSceneSlots,
    generateTts,
    alignTimelineToTts,
    applyingCaptionSlots,
    updateSubtitleClipAt,
  } = useSubtitleFlow({
    templateId,
    slots,
    setSlots,
    onAfterAiSplit: refreshProjectTimelineFromTemplate,
  });

  const handleRecognizeAllSubtitles = () => runRecognizeAll();

  const {
    exportUrl,
    exportStatus,
    exporting,
    exportError,
    exportResolution,
    setExportResolution,
    addSubtitles,
    setAddSubtitles,
    exportProgress,
    capCutDraftUrl,
    capCutExporting,
    capCutExportProgress,
    capCutStatus,
    capCutReplaceableMode,
    setCapCutReplaceableMode,
    capCutMateStatus,
    refreshCapCutMateStatus,
    exportPrecheck,
    exportBusy,
    handleExport,
    handleExportCapCut,
    handleOpenCapCutDraft,
    resetExportState,
  } = useExportFlow({
    projectId,
    templateId,
    slots,
    assets,
    templateProcessing,
    matching,
    subtitleRecognizing: recognizingAllSubtitles,
    saveProject,
    trackControls,
    templateMusicEnabled,
  });

  const { uploadAssetFile, handleAssetUpload } = useAssetUpload({
    setAssets,
    setUploadingCount,
  });

  const {
    handleTemplateUpload,
    handleTemplateInstalled,
    handleTemplateLibraryDelete,
    handleTemplateLibraryLoad,
  } = useTemplateFlow({
    templateId,
    projectId,
    slots,
    setTemplateId,
    setTemplateName,
    setTemplateVideoPath,
    setTemplateAudioPath,
    setTemplateProxyPaths,
    setBeatMarkers,
    setSfxMarkers,
    setProjectId,
    setSelectedSlotId,
    replaceSlots,
    resetHistory,
    createProjectFromTemplate,
    pauseAutosave,
    resetExportState,
    setUploadingCount,
    setLoading,
    lastTemplateSlotCountRef,
  });

  useEffect(() => {
    if (!projectId || !templateId) return;
    const running = templateProcessing.subtitleBatchRunning;
    if (lastSubtitleBatchRunningRef.current && !running) {
      void refreshProjectTimelineFromTemplate();
    }
    lastSubtitleBatchRunningRef.current = running;
  }, [
    projectId,
    templateId,
    templateProcessing.subtitleBatchRunning,
    refreshProjectTimelineFromTemplate,
  ]);

  const selectedSlot = useMemo(
    () =>
      selectedSlotId
        ? slots.find((slot) => slot.id === selectedSlotId) ?? null
        : null,
    [slots, selectedSlotId]
  );

  const selectedSlotOrderIndex = useMemo(
    () => (selectedSlot ? slots.findIndex((s) => s.id === selectedSlot.id) : -1),
    [slots, selectedSlot]
  );

  const usedAssetIds = useMemo(
    () => new Set(slots.map((s) => s.matchedAssetId).filter((id): id is string => !!id)),
    [slots]
  );

  const handlePreviewAsset = (asset: {
    filePath?: string;
    proxyPath?: string;
    proxyPaths?: PreviewProxyPaths;
    thumbnail?: string;
  }) => {
    const url =
      asset.proxyPath ||
      asset.proxyPaths?.smooth ||
      asset.proxyPaths?.clear ||
      asset.filePath ||
      asset.thumbnail ||
      '';
    if (!url) {
      alert('该素材没有可预览的文件');
      return;
    }
    window.open(toMediaUrl(url), '_blank');
  };

  const handleToggleTrackControl = useCallback((key: TrackKey, field: keyof TrackControls) => {
    setTrackControls((prev) => {
      const next = toggleTrackControl(prev, key, field);
      const msg = describeTrackToggle(key, field, next[key]);
      if (msg) {
        if (trackControlTimerRef.current) clearTimeout(trackControlTimerRef.current);
        setTrackControlMessage(msg);
        trackControlTimerRef.current = setTimeout(() => setTrackControlMessage(''), 2200);
      }
      return next;
    });
  }, []);

  const handleTrackHeightChange = useCallback((key: TrackKey, height: number | null) => {
    setTrackHeights((prev) => {
      const next = { ...prev };
      if (height == null || height === getDefaultTrackHeight(key)) {
        delete next[key];
      } else {
        next[key] = clampTrackHeight(height);
      }
      return next;
    });
  }, []);

  useEffect(() => {
    return () => {
      if (trackControlTimerRef.current) clearTimeout(trackControlTimerRef.current);
    };
  }, []);

  const showTimelineHint = useCallback((message: string) => {
    if (!message) return;
    if (trackControlTimerRef.current) clearTimeout(trackControlTimerRef.current);
    setTrackControlMessage(message);
    trackControlTimerRef.current = setTimeout(() => setTrackControlMessage(''), 2800);
  }, []);

  const handleClearSlotAsset = (slotId: string) => {
    if (isTrackLocked(trackControls, 'video')) {
      alert('视频轨已锁定，无法清空素材');
      return;
    }
    setSlots((prev) =>
      prev.map((slot) =>
        slot.id === slotId
          ? {
              ...slot,
              matchedAssetId: undefined,
              asset_file_path: undefined,
              segment_file_path: undefined,
              asset_filename: undefined,
              asset_thumbnail: undefined,
              clipStart: 0,
              match_score: undefined,
              match_reason: undefined,
            }
          : slot
      )
    );
  };

  const handleAssetDragStart = (event: DragEvent<HTMLDivElement>, dragKey: string) => {
    const baseAssetId = dragKey.includes(':') ? dragKey.split(':', 2)[0] : dragKey;
    event.dataTransfer.setData('text/plain', dragKey);
    event.dataTransfer.setData('application/x-asset-id', baseAssetId);
    event.dataTransfer.effectAllowed = 'copy';
  };

  const clearAssetFromSlots = useCallback((assetId: string) => {
    setSlots((prev) =>
      prev.map((slot) =>
        slot.matchedAssetId === assetId
          ? {
              ...slot,
              matchedAssetId: undefined,
              asset_file_path: undefined,
              segment_file_path: undefined,
              asset_filename: undefined,
              asset_thumbnail: undefined,
              clipStart: 0,
              match_score: undefined,
              match_reason: undefined,
            }
          : slot
      )
    );
    setOverlayTracks((prev) => ({
      v2: prev.v2.filter((clip) => clip.assetId !== assetId),
      v3: prev.v3.filter((clip) => clip.assetId !== assetId),
    }));
  }, [setSlots]);

  const handleDeleteAssets = useCallback(
    async (assetIds: string[]): Promise<boolean> => {
      if (!assetIds.length) return false;

      const uploadingIds = assetIds.filter((id) => id.startsWith('uploading-'));
      const realIds = assetIds.filter((id) => !id.startsWith('uploading-'));

      if (uploadingIds.length) {
        setAssets((prev) => prev.filter((a) => !uploadingIds.includes(a.id)));
      }
      if (!realIds.length) return true;

      const usedIds = realIds.filter(
        (id) =>
          slots.some((s) => s.matchedAssetId === id) ||
          overlayTracks.v2.some((c) => c.assetId === id) ||
          overlayTracks.v3.some((c) => c.assetId === id)
      );
      const msg =
        usedIds.length > 0
          ? `选中有 ${usedIds.length} 个素材已用于时间线，删除后相关片段将被清空。确定删除 ${realIds.length} 个素材？`
          : `确定删除选中的 ${realIds.length} 个素材？`;
      if (!window.confirm(msg)) return false;

      const results = await Promise.all(
        realIds.map(async (assetId) => {
          try {
            const resp = await fetch(apiUrl(`/api/assets/${assetId}`), {
              method: 'DELETE',
              headers: apiHeaders(),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
              return { assetId, ok: false as const, error: (data.detail as string) || '删除失败' };
            }
            return { assetId, ok: true as const };
          } catch {
            return { assetId, ok: false as const, error: '网络错误' };
          }
        })
      );

      const succeeded = results.filter((r) => r.ok).map((r) => r.assetId);
      const failed = results.filter((r) => !r.ok);

      if (succeeded.length) {
        setAssets((prev) => prev.filter((a) => !succeeded.includes(a.id)));
        succeeded.forEach((id) => clearAssetFromSlots(id));
      }
      if (failed.length) {
        alert(`有 ${failed.length} 个素材删除失败，请重试`);
      }
      return true;
    },
    [slots, overlayTracks, clearAssetFromSlots]
  );

  const handleDeleteAsset = useCallback(
    async (assetId: string) => {
      if (assetId.startsWith('uploading-')) {
        setAssets((prev) => prev.filter((a) => a.id !== assetId));
        return;
      }

      const isUsed = slots.some((s) => s.matchedAssetId === assetId);
      const overlayUsed =
        overlayTracks.v2.some((c) => c.assetId === assetId) ||
        overlayTracks.v3.some((c) => c.assetId === assetId);
      const msg = isUsed || overlayUsed
        ? '该素材已用于时间线，删除后相关片段将被清空，确定删除？'
        : '确定删除该素材？';
      if (!window.confirm(msg)) return;

      try {
        const resp = await fetch(apiUrl(`/api/assets/${assetId}`), {
          method: 'DELETE',
          headers: apiHeaders(),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          alert((data.detail as string) || '删除失败');
          return;
        }
        setAssets((prev) => prev.filter((a) => a.id !== assetId));
        clearAssetFromSlots(assetId);
    } catch (error) {
        console.warn('删除素材失败', error);
        alert('删除失败，请重试');
      }
    },
    [slots, overlayTracks, clearAssetFromSlots]
  );

  const handleOverlayDrop = useCallback(
    (track: 'v2' | 'v3', time: number, assetId: string) => {
      const asset = assetMap[assetId] ?? assets.find((a) => a.id === assetId);
      if (!asset) return;
      const clip = createOverlayClip(
        {
          id: asset.id,
          filePath: asset.filePath,
          title: asset.title,
          thumbnail: asset.thumbnail,
        },
        Math.max(0, time),
        Math.min(4, asset.durationSeconds || 3)
      );
      setOverlayTracks((prev) => ({
        ...prev,
        [track]: [...prev[track], clip],
      }));
    },
    [assetMap, assets]
  );

  const resolveSegmentBinding = useCallback((asset: Asset, segmentId?: string) => {
    if (!segmentId) {
      return {
        id: asset.id,
        filePath: asset.filePath,
        title: asset.title,
        thumbnail: asset.thumbnail,
        clipStart: 0,
      };
    }
    const segment = asset.segments?.find((s) => s.segment_id === segmentId);
    if (!segment) {
      return {
        id: asset.id,
        filePath: asset.filePath,
        title: asset.title,
        thumbnail: asset.thumbnail,
        clipStart: 0,
      };
    }
    const segmentFile = segment.segment_file_path?.trim() || '';
    return {
      id: asset.id,
      filePath: asset.filePath,
      title: `${asset.title} · ${segment.segment_id}`,
      thumbnail: segment.thumbnail || asset.thumbnail,
      segmentId: segment.segment_id,
      segmentFilePath: segmentFile || undefined,
      clipStart: segmentFile ? 0 : segment.start,
    };
  }, []);

  const assignAssetToSlot = useCallback(
    (asset: Asset, slotId: string, segmentId?: string): boolean => {
      if (isTrackLocked(trackControls, 'video')) {
        showTimelineHint('视频轨已锁定，请点击左侧轨道头解锁后再拖入素材');
      return false;
      }
      const targetSlot = slots.find((slot) => slot.id === slotId);
      if (targetSlot?.locked) {
        showTimelineHint('该槽位已锁定，请在属性面板取消锁定后再拖入素材');
        return false;
      }
      const binding = resolveSegmentBinding(asset, segmentId);
      setSlots((current) =>
        current.map((slot) =>
          slot.id === slotId ? applyAssetToSlot(slot, binding) : slot
        )
      );
      setIsPlaying(false);
      setSelectedSlotId(slotId);
      const slotIndex = slots.findIndex((slot) => slot.id === slotId);
      showTimelineHint(
        slotIndex >= 0 ? `已将素材填入槽位 ${slotIndex + 1}` : '已将素材填入时间线'
      );
      return true;
    },
    [trackControls, slots, setSlots, setIsPlaying, resolveSegmentBinding, showTimelineHint]
  );

  const processingAssetIds = useMemo(
    () =>
      assets
        .filter(
          (a) =>
            a.processingStatus === 'processing' ||
            ((a.processingProgress ?? 100) < 100 && !a.id.startsWith('uploading-'))
        )
        .map((a) => a.id),
    [assets]
  );

  useAssetProcessingPoll(processingAssetIds, (assetId, state) => {
    setAssets((prev) =>
      prev.map((a) => {
        if (a.id !== assetId) return a;
        const firstSeg = state.segments?.[0];
        const durationSec = Number(
          state.duration || firstSeg?.duration || a.durationSeconds || 0
        );
        const thumb = state.thumbnail || firstSeg?.thumbnail || a.thumbnail;
        const next: Asset = {
          ...a,
          processingStatus: state.status,
          processingProgress: Math.max(a.processingProgress ?? 0, state.progress),
          segments: state.segments?.length ? state.segments : a.segments,
          segmentCount: Math.max(
            a.segmentCount ?? 0,
            state.segmentCount ?? state.segments?.length ?? 0
          ),
          durationSeconds: durationSec > 0 ? durationSec : a.durationSeconds,
          duration: durationSec > 0 ? formatAssetDuration(durationSec) : a.duration,
          thumbnail: thumb || a.thumbnail,
          proxyPath: state.proxyPath || a.proxyPath,
          proxyPaths: state.proxyPaths || a.proxyPaths,
        };
        if (
          a.thumbnail?.startsWith('blob:') &&
          state.thumbnail &&
          !state.thumbnail.startsWith('blob:')
        ) {
          URL.revokeObjectURL(a.thumbnail);
        }
        return next;
      })
    );
  });

  const handleSaveProject = async () => {
    if (await saveProject()) {
      setAutosaveStatus('saved');
      alert('项目已保存');
    }
  };

  const handleLoadProjectClick = () => {
    setProjectListOpen(true);
  };

  const handleCoverUpload = async (file: File) => {
    if (!projectId) {
      alert('请先创建项目');
      return;
    }
    const reader = new FileReader();
    reader.onload = async () => {
      const dataUrl = reader.result as string;
      setCoverThumbnail(dataUrl);
      try {
        await fetch(apiUrl(`/api/projects/${projectId}`), {
          method: 'PATCH',
          headers: apiHeaders(),
          body: JSON.stringify({ cover_thumbnail: dataUrl }),
        });
      } catch {
        /* local preview still works */
      }
    };
    reader.readAsDataURL(file);
  };

  const resolveDropSlotId = useCallback(
    (time: number, preferredSlotId?: string | null) => {
      const layouts = buildClipLayouts(slots, 1);
      if (preferredSlotId) return preferredSlotId;
      return (
        findSlotIdAtTime(layouts, time) ??
        findFirstEmptySlotId(layouts, slots) ??
        layouts[0]?.slot.id ??
        null
      );
    },
    [slots]
  );

  const handleTimelineDrop = useCallback(
    async (
      event: DragEvent<HTMLDivElement>,
      time: number,
      preferredSlotId?: string | null
    ) => {
    event.preventDefault();
      if (isTrackLocked(trackControls, 'video')) {
        showTimelineHint('视频轨已锁定，请点击左侧轨道头解锁后再拖入素材');
        return;
      }

      const files = getVideoFilesFromDataTransfer(event.dataTransfer);
      if (files.length > 0) {
        const file = files[0];
        if (slots.length === 0) {
          await handleTemplateUpload(file);
          return;
        }
        showTimelineHint('正在上传素材…');
        const asset = await uploadAssetFile(file);
        if (!asset) return;
        const slotId = resolveDropSlotId(time, preferredSlotId);
        if (!slotId) {
          showTimelineHint('请将素材拖到视频轨的槽位上');
          return;
        }
        assignAssetToSlot(asset, slotId);
        return;
      }

      const dragKey = event.dataTransfer.getData('text/plain');
      if (!dragKey) return;
      const [assetId, segmentId] = dragKey.includes(':') ? dragKey.split(':', 2) : [dragKey, ''];
      const asset = assetMap[assetId] ?? assets.find((a) => a.id === assetId);
      if (!asset) {
        showTimelineHint('素材未找到，请刷新素材库后重试');
        return;
      }
      if (asset.processingStatus === 'failed') {
        showTimelineHint('该素材分析失败，请删除后重新上传');
        return;
      }
      if (slots.length === 0) {
        showTimelineHint('请先导入模板视频，再将素材拖到下方视频轨');
        return;
      }
      const slotId = resolveDropSlotId(time, preferredSlotId);
      if (!slotId) {
        showTimelineHint('请将素材拖到视频轨的某个槽位上');
        return;
      }
      assignAssetToSlot(asset, slotId, segmentId || undefined);
    },
    [
      trackControls,
      slots.length,
      uploadAssetFile,
      resolveDropSlotId,
      assignAssetToSlot,
      assetMap,
      assets,
      handleTemplateUpload,
      showTimelineHint,
    ]
  );

  const handleSlotSelect = (slotId: string) => {
    setSelectedSlotId(slotId);
    const layouts = slots.reduce<{ id: string; start: number; end: number }[]>((acc, slot) => {
      const start = acc.length ? acc[acc.length - 1].end : 0;
      acc.push({ id: slot.id, start, end: start + slot.duration });
      return acc;
    }, []);
    const layout = layouts.find((l) => l.id === slotId);
    if (layout) setPlayheadTime(layout.start);
  };

  const handleUpdateSlot = (updates: Partial<TemplateSlot>) => {
    if (!selectedSlot) return;
    if (updates.locked !== undefined && isTrackLocked(trackControls, 'video')) return;
    if (
      (updates.clipStart !== undefined || updates.matchedAssetId !== undefined) &&
      isTrackLocked(trackControls, 'video')
    ) {
      return;
    }
    if (
      (updates.subtitleText !== undefined || updates.subtitle_segments !== undefined) &&
      isTrackLocked(trackControls, 'subtitle')
    ) {
      return;
    }
    if (updates.useOriginalAudio !== undefined && isTrackLocked(trackControls, 'audioVoice')) return;
    const mergedUpdates =
      updates.subtitleText !== undefined && updates.subtitle_segments === undefined
        ? { ...updates, ...syncSubtitleTextUpdate(selectedSlot, updates.subtitleText) }
        : updates;
    setSlots((current) =>
      current.map((slot) => (slot.id === selectedSlot.id ? { ...slot, ...mergedUpdates } : slot))
    );
  };

  const handleToggleTemplateMusic = () => {
    setTemplateMusicEnabled((value) => {
      const next = !value;
      setTrackControls((prev) => ({
        ...prev,
        audio: { ...prev.audio, muted: !next },
      }));
      return next;
    });
  };

  const handleUpdateSlotSubtitle = useCallback(
    (slotId: string, text: string) => {
      if (isTrackLocked(trackControls, 'subtitle')) return;
      setSlots((prev) =>
        prev.map((slot) =>
          slot.id === slotId ? { ...slot, ...syncSubtitleTextUpdate(slot, text) } : slot
        )
      );
    },
    [trackControls, setSlots]
  );

  const handleToggleSlotOriginalAudio = useCallback(
    (slotId: string) => {
      if (isTrackLocked(trackControls, 'audio')) return;
      setSlots((prev) =>
        prev.map((slot) =>
          slot.id === slotId ? { ...slot, useOriginalAudio: !slot.useOriginalAudio } : slot
        )
      );
    },
    [trackControls, setSlots]
  );

  const handleApplyEffectPresets = useCallback(
    (updated: TemplateSlot[]) => {
      if (isTrackLocked(trackControls, 'video')) return;
      setSlots(updated);
    },
    [trackControls, setSlots]
  );

  const handleAnalyzeTemplateEffects = useCallback(async () => {
    if (!templateId) return;
    setAnalyzingTemplateEffects(true);
    try {
      const resp = await fetch(apiUrl(`/api/template/${templateId}/analyze-effects`), {
        method: 'POST',
        headers: apiHeaders(),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(typeof data.detail === 'string' ? data.detail : '模板特效分析失败');
      }
      const tplSlots = (data.slots || []) as Record<string, unknown>[];
      setSlots((prev) =>
        prev.map((slot, index) => {
          const tpl =
            tplSlots.find((t) => String(t.slot_id) === String(slot.originalSlotId ?? index + 1)) ||
            tplSlots[index];
          if (!tpl || typeof tpl !== 'object') return slot;
          const auto = tpl.auto_effects as Record<string, unknown> | undefined;
          const subStyle = auto?.subtitle_style as Record<string, unknown> | undefined;
          let subtitle_segments = slot.subtitle_segments;
          if (Array.isArray(tpl.subtitle_segments) && tpl.subtitle_segments.length) {
            subtitle_segments = tpl.subtitle_segments as unknown[];
          }
          return {
            ...slot,
            auto_effects: auto,
            template_effect_label: tpl.template_effect_label as string | undefined,
            subtitle_segments,
            colorGrade:
              slot.colorGrade ||
              (auto?.color_grade as TemplateSlot['colorGrade']) ||
              (tpl.color_grade as TemplateSlot['colorGrade']),
            keyframes:
              slot.keyframes && slot.keyframes.length > 0
                ? slot.keyframes
                : ((auto?.keyframes as TemplateSlot['keyframes']) ||
                    (tpl.keyframes as TemplateSlot['keyframes']) ||
                    []),
            transitionOut:
              slot.transitionOut ||
              (auto?.transition_out as TemplateSlot['transitionOut']) ||
              (tpl.transition_out as TemplateSlot['transitionOut']),
            subtitle_style: subStyle as TemplateSlot['subtitle_style'],
          };
        })
      );
      showTimelineHint('模板特效 AI 分析完成，导出剪映草稿时将烧录进画面');
    } catch (err) {
      showTimelineHint(err instanceof Error ? err.message : '模板特效分析失败');
    } finally {
      setAnalyzingTemplateEffects(false);
    }
  }, [templateId, setSlots, showTimelineHint]);

  const handleRenameProject = async () => {
    if (!projectId) return;
    const name = window.prompt('输入新项目名称', projectTitle);
    if (!name?.trim() || name.trim() === projectTitle) return;
    try {
      const resp = await fetch(apiUrl(`/api/projects/${projectId}`), {
        method: 'PATCH',
        headers: apiHeaders(),
        body: JSON.stringify({ name: name.trim() }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        alert((data.detail as string) || '重命名失败');
        return;
      }
      setTemplateName(name.trim());
    } catch {
      alert('重命名失败，请重试');
    }
  };

  const triggerTemplateImport = useCallback(() => {
    templateFileInputRef.current?.click();
  }, []);

  const handleRecognizeSlotSubtitle = useCallback(
    async () => {
      if (!selectedSlot || !templateId) {
        alert('请先导入模板并选择槽位');
        return;
      }
      if (isTrackLocked(trackControls, 'subtitle')) {
        alert('字幕轨已锁定，请先解锁后再识别');
        return;
      }

      const range = getSlotSourceTimeRangeById(slots, selectedSlot.id);
      if (!range || range.end <= range.start) {
        alert('无法确定当前槽位的时间范围');
        return;
      }

      setRecognizingSubtitle(true);
      try {
        const resp = await fetch(longRunningApiUrl('/api/subtitle/recognize-slot'), {
        method: 'POST',
          headers: apiHeaders(),
          body: JSON.stringify({
            template_id: templateId,
            slot_start: range.start,
            slot_end: range.end,
            slot_id: String(selectedSlot.originalSlotId ?? selectedSlot.id),
            force: true,
            quality: false,
            mode: subtitleMode,
          }),
        });
        const data = await readApiJson(resp);
        if (!resp.ok) {
          throw new Error(formatApiDetail(data.detail, '字幕识别失败'));
        }
        if (data.status === 'error' || (data.success === false && !data.status)) {
          const reason = String(
            data.error || data.reason || data.subtitle_status_reason || '识别异常，请重试或手填'
          );
          handleUpdateSlot({
            subtitleText: String(data.subtitle_text || ''),
            subtitle_segments: (data.subtitle_segments as unknown[]) || [],
            subtitle_source: data.source as string | undefined,
            subtitle_quality: data.subtitle_quality as import('@/lib/timeline').TemplateSlot['subtitle_quality'],
            subtitle_status_reason: data.subtitle_status_reason as string | undefined,
          });
          alert(reason);
          return;
        }

        handleUpdateSlot({
          subtitleText: String(data.subtitle_text || ''),
          subtitle_segments: (data.subtitle_segments as unknown[]) || [],
          subtitle_visual_context: data.subtitle_visual_context as string | undefined,
          subtitle_scene_match:
            data.subtitle_scene_match != null ? Number(data.subtitle_scene_match) : undefined,
          subtitle_scene_match_reason: data.subtitle_scene_match_reason as string | undefined,
          subtitle_effect_label: data.subtitle_effect_label as string | undefined,
          subtitle_style: data.subtitle_style as import('@/lib/slotEdit').SubtitleStyle | undefined,
          ai_effect_understanding: data.ai_effect_understanding as import('@/lib/timeline').AiEffectUnderstanding | undefined,
          applied_effect_presets: (data.applied_effect_presets as string[]) || undefined,
          ai_description: data.ai_description as string | undefined,
          ai_subject: data.ai_subject as string | undefined,
          scene_tags: (data.scene_tags as string[]) || undefined,
          subtitle_source: data.source as string | undefined,
          subtitle_quality: data.subtitle_quality as import('@/lib/timeline').TemplateSlot['subtitle_quality'],
          subtitle_status_reason: (data.reason as string | undefined) ?? data.subtitle_status_reason as string | undefined,
          subtitle_duplicate: Boolean(data.subtitle_duplicate ?? false),
        });
        const slotStatus = String(data.status || '');
        if (slotStatus === 'no_speech' || slotStatus === 'no_overlap') {
          alert('该槽位时间段未检测到人声字幕。');
        } else if (slotStatus === 'filtered') {
          alert('该槽位检测到疑似幻听/低置信度片段，已过滤。');
        } else if (!String(data.subtitle_text || '').trim()) {
          alert(
            String(
              data.reason ||
                data.subtitle_status_reason ||
                '未得到有效字幕，请确认该槽位含人声'
            )
          );
        }
      } catch (err) {
        console.error(err);
        alert(err instanceof Error ? err.message : '字幕识别失败');
    } finally {
        setRecognizingSubtitle(false);
      }
    },
    [selectedSlot, templateId, trackControls, slots, handleUpdateSlot, subtitleMode]
  );

  const handleTrimSlot = useCallback(
    (slotId: string, mode: 'start' | 'end', deltaSec: number) => {
      if (isTrackLocked(trackControls, 'video')) return;
      setSlots((prev) =>
        prev.map((slot) => {
          if (slot.id !== slotId) return slot;
          if (mode === 'start') return trimClipStart(slot, deltaSec);
          return trimClipDuration(slot, deltaSec);
        })
      );
    },
    [trackControls, setSlots]
  );

  const handleDeleteSlot = useCallback(
    (slotId: string) => {
      if (isTrackLocked(trackControls, 'video')) return;
      setSlots((prev) => {
        const next = rippleDeleteSlot(prev, slotId);
        if (next.length && !next.find((s) => s.id === selectedSlotId)) {
          setSelectedSlotId(next[0]?.id ?? '');
        }
        return next;
      });
    },
    [trackControls, setSlots, selectedSlotId]
  );

  const handleMoveSlot = useCallback(
    (slotId: string, direction: -1 | 1) => {
      if (isTrackLocked(trackControls, 'video')) return;
      setSlots((prev) => moveSlotById(prev, slotId, direction));
    },
    [trackControls, setSlots]
  );

  const handleReorderSlots = useCallback(
    (fromSlotId: string, toSlotId: string) => {
      if (isTrackLocked(trackControls, 'video')) return;
      setSlots((prev) => {
        const fromIdx = prev.findIndex((s) => s.id === fromSlotId);
        const toIdx = prev.findIndex((s) => s.id === toSlotId);
        if (fromIdx < 0 || toIdx < 0) return prev;
        return reorderSlots(prev, fromIdx, toIdx);
      });
    },
    [trackControls, setSlots]
  );

  const handleRippleClearRight = useCallback(() => {
    if (!selectedSlotId || isTrackLocked(trackControls, 'video')) return;
    setSlots((prev) => rippleClearRight(prev, selectedSlotId));
  }, [selectedSlotId, trackControls, setSlots]);

  const handleSplitAtPlayhead = useCallback(() => {
    if (isTrackLocked(trackControls, 'video')) {
      alert('视频轨已锁定，无法分割');
      return;
    }
    const next = splitSlotAtTime(slots, playheadTime);
    if (!next) {
      alert('请在槽位中间位置分割（槽位未锁定）');
        return;
      }
    setSlots(next);
  }, [slots, playheadTime, setSlots, trackControls]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      if (e.code === 'Space') {
        e.preventDefault();
        handleTogglePlay();
      } else if (e.key === 's' || e.key === 'S') {
        if (!e.ctrlKey && !e.metaKey) handleSplitAtPlayhead();
      } else if (e.key === 'q' || e.key === 'Q') {
        if (!e.ctrlKey && !e.metaKey) handleRippleClearRight();
      } else if (e.key === 'w' || e.key === 'W') {
        if (!e.ctrlKey && !e.metaKey && selectedSlotId) handleDeleteSlot(selectedSlotId);
      } else if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [handleTogglePlay, handleSplitAtPlayhead, handleRippleClearRight, handleDeleteSlot, selectedSlotId, undo, redo]);

  const handleOverlayDelete = useCallback((track: 'v2' | 'v3', clipId: string) => {
    setOverlayTracks((prev) => ({
      ...prev,
      [track]: prev[track].filter((clip) => clip.id !== clipId),
    }));
  }, []);

  const matchedSlotCount = useMemo(
    () => slots.filter((slot) => slot.matchedAssetId || slot.asset_file_path).length,
    [slots]
  );

  const templateReady =
    !!templateId &&
    (templateProcessing.editable ||
      (templateProcessing.status === 'ready' && templateProcessing.slotCount > 0) ||
      slots.length > 1);

  const onboarding = useMemo(
    () =>
      computeOnboardingState({
        hasTemplate: !!templateId,
        templateReady,
        assetCount: assets.length,
        slots,
        matchedCount: matchedSlotCount,
      }),
    [templateId, templateReady, assets.length, slots, matchedSlotCount]
  );

  const globalStatusItems = useMemo((): GlobalStatusItem[] => {
    const items: GlobalStatusItem[] = [];

    if (uploadingCount > 0) {
      items.push({
        id: 'upload',
        label: '文件上传中',
        progress: 30,
        status: 'processing',
      });
    }

    if (templateId && templateProcessing.status === 'processing') {
      const p = templateProcessing.progress;
      const detail =
        p < 40
          ? '读取视频信息'
          : p < 90
            ? 'AI 分析模板：切分画面 + 识别字幕 + 花字特效（约 30 秒）'
            : '即将完成';
      items.push({
        id: 'template',
        label: '模板切分',
        detail,
        progress: templateProcessing.progress,
        status: 'processing',
      });
    } else if (templateId && templateProcessing.status === 'failed') {
      items.push({
        id: 'template',
        label: '模板分析失败',
        detail: '请重新上传模板',
        progress: 0,
        status: 'failed',
      });
    }

    if (
      templateId &&
      templateProcessing.status === 'ready' &&
      templateProcessing.enhanceStatus === 'processing'
    ) {
      const ep = templateProcessing.enhanceProgress;
      const detail =
        ep < 35
          ? 'AI 修正镜头切分边界'
          : ep < 45
            ? '生成槽位缩略图'
            : ep < 65
              ? `AI 理解模板画面（${templateProcessing.slotsAiReadyCount}/${templateProcessing.slotCount || '?'})`
              : ep < 82
                ? '生成预览代理'
                : '提取模板音频';
      items.push({
        id: 'template-enhance',
        label: 'AI 理解模板',
        detail,
        progress: templateProcessing.enhanceProgress,
        status: 'processing',
      });
    }

    const processingAssets = assets.filter((a) => a.processingStatus === 'processing');
    if (processingAssets.length) {
      const avgProgress = Math.round(
        processingAssets.reduce((sum, a) => sum + (a.processingProgress ?? 0), 0) /
          processingAssets.length
      );
      items.push({
        id: 'assets',
        label: `素材分析 (${processingAssets.length})`,
        detail: processingAssets[0]?.title,
        progress: avgProgress,
        status: 'processing',
      });
    }

    if (matching) {
      items.push({ id: 'match', label: 'AI 匹配中', progress: 0, status: 'processing' });
    }

    if (recognizingAllSubtitles || templateProcessing.subtitleBatchRunning) {
      items.push({
        id: 'subtitle-batch',
        label: '字幕识别中',
        detail: templateProcessing.subtitleBatchRunning
          ? templateProcessing.subtitleProgressLabel ||
            `后台识别 ${templateProcessing.slotsSubtitleReadyCount}/${templateProcessing.slotCount || '?'}`
          : '识别全部槽位字幕',
        progress: templateProcessing.subtitleBatchRunning
          ? Math.round(
              ((templateProcessing.slotCount -
                templateProcessing.subtitleEmptyCount -
                templateProcessing.subtitleLowCount) /
                Math.max(1, templateProcessing.slotCount)) *
                100
            )
          : 0,
        indeterminate: !templateProcessing.subtitleBatchRunning,
        status: 'processing',
      });
    }

    if (
      templateId &&
      templateProcessing.status === 'ready' &&
      !recognizingAllSubtitles &&
      !templateProcessing.subtitleBatchRunning &&
      (templateProcessing.subtitleEmptyCount > 0 ||
        templateProcessing.subtitleLowCount > 0 ||
        templateProcessing.subtitleDuplicateCount > 0)
    ) {
      const parts: string[] = [];
      if (templateProcessing.subtitleEmptyCount > 0) {
        parts.push(`${templateProcessing.subtitleEmptyCount} 个空槽位`);
      }
      if (templateProcessing.subtitleLowCount > 0) {
        parts.push(`${templateProcessing.subtitleLowCount} 个质量偏低`);
      }
      if (templateProcessing.subtitleDuplicateCount > 0) {
        parts.push(`${templateProcessing.subtitleDuplicateCount} 个疑似重复`);
      }
      items.push({
        id: 'subtitle-quality',
        label: '字幕需关注',
        detail:
          templateProcessing.subtitleProgressLabel ||
          `${parts.join('，')} — 可在「字幕」页重识别或手改`,
        progress: Math.round(
          ((templateProcessing.slotCount -
            templateProcessing.subtitleEmptyCount -
            templateProcessing.subtitleLowCount) /
            Math.max(1, templateProcessing.slotCount)) *
            100
        ),
        status: 'warning',
      });
    }

    if (
      templateId &&
      templateProcessing.status === 'ready' &&
      !templateProcessing.aiUnderstandingReady &&
      templateProcessing.slotCount > 0
    ) {
      items.push({
        id: 'ai-understanding',
        label: '模板 AI 理解未完成',
        detail: `已理解 ${templateProcessing.slotsAiReadyCount}/${templateProcessing.slotCount} 镜，匹配准确度可能下降`,
        progress: Math.round(
          (templateProcessing.slotsAiReadyCount / Math.max(1, templateProcessing.slotCount)) * 100
        ),
        status: 'warning',
      });
    }

    if (exporting) {
      items.push({
        id: 'export',
        label: '导出成片',
        progress: exportProgress,
        status: 'processing',
      });
    }

    if (capCutExporting) {
      items.push({
        id: 'capcut',
        label: '生成剪映草稿',
        detail: capCutStatus || '裁剪片段并写入草稿…',
        progress: capCutExportProgress,
        indeterminate: capCutExportProgress <= 0,
        status: 'processing',
      });
    }

    return items;
  }, [
    uploadingCount,
    templateId,
    templateProcessing,
    assets,
    matching,
    recognizingAllSubtitles,
    exporting,
    exportProgress,
    capCutExporting,
    capCutExportProgress,
    capCutStatus,
  ]);

  const autosaveLabel = useMemo(() => {
    if (autosaveStatus === 'saving' || savingProject) return '自动保存中…';
    if (autosaveStatus === 'pending') return '有未保存更改';
    if (autosaveStatus === 'error') return '自动保存失败，请手动保存';
    if (autosaveStatus === 'saved') return '已自动保存';
    return '';
  }, [autosaveStatus, savingProject]);

  const handleOnboardingStepAction = useCallback(
    (stepId: OnboardingStepId) => {
      switch (stepId) {
        case 'template':
          triggerTemplateImport();
          break;
        case 'subtitle':
          void handleRecognizeAllSubtitles();
          break;
        case 'match':
          if (!assets.length) {
            alert('请先在左侧「素材库」上传旅行视频，等待分析完成后再智能匹配');
            break;
          }
          void runAutoMatch();
          break;
        case 'polish':
          alert(
            '第 4 步：在右侧修改字幕文案；左侧「特效库」为槽位应用花字/动效（AI 仅推荐，需您手动点「应用」）。'
          );
          break;
        case 'export':
          void handleExport();
          break;
        default:
          break;
      }
    },
    [triggerTemplateImport, handleRecognizeAllSubtitles, runAutoMatch, handleExport, assets.length]
  );

  const projectTitle = templateName !== '未选择模板' ? templateName : '未命名草稿';
  const canExport =
    !!(projectId && templateId && slots.length > 0) && exportPrecheck.canProceed;
  const exportHint =
    exportPrecheck.blockers[0] ||
    (!projectId
      ? '请先导入模板创建项目'
      : !templateId || slots.length === 0
        ? '请先完成模板解析并生成时间线'
        : undefined);
  const timelineCoverThumb =
    coverThumbnail || slots[0]?.template_thumbnail || slots[0]?.asset_thumbnail || '';

  return (
    <div className="editor-shell flex flex-col overflow-hidden bg-editor-bg">
      <ProjectListModal
        open={projectListOpen}
        currentProjectId={projectId}
        onClose={() => setProjectListOpen(false)}
        onLoad={loadProject}
      />
      <input
        ref={templateFileInputRef}
        type="file"
        accept="video/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void handleTemplateUpload(file);
          e.target.value = '';
        }}
      />
      <Toolbar
        projectTitle={projectTitle}
        projectId={projectId}
        onSaveProject={handleSaveProject}
        onLoadProject={handleLoadProjectClick}
        onExport={handleExport}
        onExportCapCut={handleExportCapCut}
        onTemplateUpload={handleTemplateUpload}
        onRenameProject={handleRenameProject}
        saving={savingProject}
        loadingProject={loadingProject}
        exporting={exporting}
        capCutExporting={capCutExporting}
        canExport={canExport}
        exportHint={exportHint}
        autosaveLabel={autosaveLabel}
      />

      <OnboardingGuide
        steps={onboarding.steps}
        currentStep={onboarding.currentStep}
        progressPercent={onboarding.progressPercent}
        allDone={onboarding.allDone}
        onStepAction={handleOnboardingStepAction}
        exportBusy={
          capCutExporting
            ? {
                label: `剪映导出 ${capCutExportProgress > 0 ? `${capCutExportProgress}%` : '准备中…'}`,
                progress: capCutExportProgress,
              }
            : null
        }
      />

      <GlobalStatusBar items={globalStatusItems} autosaveLabel={autosaveLabel} />

      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden lg:flex-row-reverse">
        <div
          className="editor-layout-player flex min-h-[min(36vh,360px)] flex-col overflow-hidden lg:min-h-0 lg:border-l lg:border-editor-border"
          style={{ '--editor-player-width': `${playerPanelWidth}px` } as CSSProperties}
        >
          <PreviewPanel
            slots={slots}
            subtitleClips={subtitleClips}
            selectedSlot={selectedSlot}
            playheadTime={playheadTime}
            isPlaying={isPlaying}
            onTogglePlay={handleTogglePlay}
            timelineName={projectTitle}
            trackControls={trackControls}
            assetMap={assetMap}
            templateAudioUrl={templateAudioPath}
            templateVideoPath={templateVideoPath}
            templateProxyPaths={templateProxyPaths}
            templateMusicEnabled={templateMusicEnabled}
            processingProgress={templateProcessing.progress}
            processingStatus={templateProcessing.status}
            exportUrl={exportUrl}
            exportStatus={exportStatus}
            exportError={exportError}
            exportResolution={exportResolution}
            onExportResolutionChange={setExportResolution}
            addSubtitles={addSubtitles}
            onAddSubtitlesChange={setAddSubtitles}
            exportProgress={exportProgress}
            exporting={exporting}
            onExport={handleExport}
            onExportCapCut={handleExportCapCut}
            capCutDraftUrl={capCutDraftUrl}
            capCutExporting={capCutExporting}
            capCutExportProgress={capCutExportProgress}
            capCutStatus={capCutStatus}
            capCutReplaceableMode={capCutReplaceableMode}
            onCapCutReplaceableModeChange={setCapCutReplaceableMode}
            capCutMateStatus={capCutMateStatus}
            onRefreshCapCutMate={() => void refreshCapCutMateStatus()}
            onOpenCapCutDraft={handleOpenCapCutDraft}
            canExport={canExport}
            onPlayheadChange={handlePlayheadChange}
            onPlayheadStep={handlePlayheadStep}
          />
        </div>

        <PanelSplitter
          orientation="vertical"
          className="hidden lg:flex"
          ariaValueNow={playerPanelWidth}
          title="拖动调整播放器宽度，双击恢复默认"
          onResizeStart={() => {
            playerDragStartRef.current = playerPanelWidth;
          }}
          onResize={(delta) => setPlayerPanelWidth(playerDragStartRef.current - delta)}
          onReset={resetPlayerPanelWidth}
        />

        {/* 左侧工作区：素材 + 草稿参数 + 时间轴（空间不足时优先压缩此处） */}
        <div
          ref={workspaceRef}
          className="editor-layout-workspace flex min-h-0 min-w-0 flex-col overflow-hidden"
        >
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden lg:min-h-[200px] lg:flex-row lg:shrink">
            <div
              className="editor-layout-asset flex min-h-[min(28vh,240px)] flex-col overflow-hidden border-b border-editor-border lg:min-h-0 lg:border-b-0 lg:border-r"
              style={{ '--editor-asset-width': `${assetPanelWidth}px` } as CSSProperties}
            >
          <AssetLibrary
            assets={assets}
            usedAssetIds={usedAssetIds}
                loading={loading || uploadingCount > 0}
                templateId={templateId}
            onAssetDragStart={handleAssetDragStart}
            onAssetUpload={handleAssetUpload}
                onTemplateUpload={handleTemplateUpload}
                hasTemplate={!!templateId && slots.length > 0}
            onPreviewAsset={handlePreviewAsset}
                onTemplateInstalled={(tid) => void handleTemplateInstalled(tid)}
                onAssetDelete={(id) => void handleDeleteAsset(id)}
                onAssetsDelete={(ids) => handleDeleteAssets(ids)}
                onAssetsRefresh={() => void loadAssets()}
                slots={slots}
                selectedSlotId={selectedSlotId}
                onSelectSlot={handleSlotSelect}
                onUpdateSlotSubtitle={handleUpdateSlotSubtitle}
                templateMusicEnabled={templateMusicEnabled}
                templateAudioUrl={templateAudioPath}
                onToggleTemplateMusic={handleToggleTemplateMusic}
                onToggleSlotOriginalAudio={handleToggleSlotOriginalAudio}
                onRecognizeAllSubtitles={() => void handleRecognizeAllSubtitles()}
                onApplyCaptionSlots={() => void applyCaptionSlots()}
                onApplyVisualSceneSlots={() => void applyVisualSceneSlots()}
                applyingCaptionSlots={applyingCaptionSlots}
                onGenerateTts={() => void generateTts()}
                onAlignTimelineToTts={() => void alignTimelineToTts()}
                generatingTts={generatingTts}
                aligningTimeline={aligningTimeline}
                voiceProfiles={voiceProfiles}
                selectedVoiceId={selectedVoiceId}
                onVoiceChange={setSelectedVoiceId}
                ttsSegments={ttsSegments}
                onUpdateSubtitleClip={updateSubtitleClipAt}
                recognizingAllSubtitles={recognizingAllSubtitles}
                recognizeProgress={recognizeProgress}
                subtitleMode={subtitleMode}
                onSubtitleModeChange={setSubtitleMode}
                spokenCaptions={spokenCaptions}
                subtitleClips={subtitleClips}
                recognitionDebug={recognitionDebug}
                onRecognizeSlotSubtitle={() => void handleRecognizeSlotSubtitle()}
                recognizingSlotSubtitle={recognizingSubtitle}
                onApplyEffectPresets={handleApplyEffectPresets}
                onAnalyzeTemplateEffects={() => void handleAnalyzeTemplateEffects()}
                analyzingTemplateEffects={analyzingTemplateEffects}
                onTemplateLibrarySelect={(tid) => void handleTemplateLibraryLoad(tid)}
                onTemplateLibraryImported={(tid) => void handleTemplateLibraryLoad(tid)}
                onTemplateLibraryDeleted={handleTemplateLibraryDelete}
          />
        </div>

            <PanelSplitter
              orientation="vertical"
              className="hidden lg:flex"
              ariaValueNow={assetPanelWidth}
              title="拖动调整素材库宽度，双击恢复默认"
              onResizeStart={() => {
                assetDragStartRef.current = assetPanelWidth;
              }}
              onResize={(delta) => setAssetPanelWidth(assetDragStartRef.current + delta)}
              onReset={resetAssetPanelWidth}
            />

            <div className="flex min-h-[min(20vh,180px)] min-w-0 flex-1 shrink flex-col overflow-hidden border-b border-editor-border lg:min-h-0 lg:max-h-full lg:border-b-0">
        <PropertiesPanel
          selectedSlot={selectedSlot}
                trackControls={trackControls}
                asset={selectedSlot?.matchedAssetId ? assetMap[selectedSlot.matchedAssetId] : undefined}
                assetDurationSeconds={
                  selectedSlot?.matchedAssetId
                    ? assetMap[selectedSlot.matchedAssetId]?.durationSeconds
                    : undefined
                }
                matchWeights={matchWeights}
                matchStrategy={matchStrategy}
                templateName={templateName}
                slotCount={slots.length}
                templateAiVision={templateProcessing.aiVision}
                sfxMarkers={sfxMarkers}
                templateMusicEnabled={templateMusicEnabled}
                matching={matching}
                matchMessage={matchMessage}
                matchError={matchError}
                onMatchWeightsChange={setMatchWeights}
                onMatchStrategyChange={setMatchStrategy}
          onUpdateSlot={handleUpdateSlot}
                onDeleteSlot={handleDeleteSlot}
                onClearAsset={handleClearSlotAsset}
                onAutoMatch={runAutoMatch}
                onToggleTemplateMusic={handleToggleTemplateMusic}
                templateId={templateId}
                recognizingSubtitle={recognizingSubtitle}
                onRecognizeSlotSubtitle={() => void handleRecognizeSlotSubtitle()}
                onImportTemplate={triggerTemplateImport}
                onMoveSlot={handleMoveSlot}
                slotOrderIndex={selectedSlotOrderIndex}
                slotOrderTotal={slots.length}
              />
            </div>
      </div>

          <PanelSplitter
            orientation="horizontal"
            ariaValueNow={timelinePanelHeight}
            title="拖动调整时间轴高度，双击恢复默认"
            onResizeStart={() => {
              timelineDragStartRef.current = timelinePanelHeight;
            }}
            onResize={(delta) =>
              setTimelinePanelHeight(
                timelineDragStartRef.current + delta,
                workspaceRef.current?.clientHeight
              )
            }
            onReset={() => resetTimelinePanelHeight()}
          />

          <div
            className="min-h-0 shrink-0 overflow-hidden bg-editor-bg"
            style={{ height: timelinePanelHeight }}
          >
        <Timeline
          slots={slots}
          subtitleClips={subtitleClips}
          ttsSegments={ttsSegments}
          assetMap={assetMap}
              templateVideoPath={templateVideoPath}
              templateProxyPaths={templateProxyPaths}
              coverThumb={timelineCoverThumb}
              onCoverClick={() => {
                const input = document.createElement('input');
                input.type = 'file';
                input.accept = 'image/*';
                input.onchange = () => {
                  const file = input.files?.[0];
                  if (file) void handleCoverUpload(file);
                };
                input.click();
              }}
          selectedSlotId={selectedSlotId}
              playheadTime={playheadTime}
              isPlaying={isPlaying}
              canUndo={canUndo}
              canRedo={canRedo}
              trackControls={trackControls}
              trackControlMessage={trackControlMessage}
              onTrackControlToggle={handleToggleTrackControl}
              onPlayheadChange={handlePlayheadChange}
              onScrubStart={handleScrubStart}
              onTogglePlay={handleTogglePlay}
              onUndo={undo}
              onRedo={redo}
              onSplit={handleSplitAtPlayhead}
              onDeleteSlot={handleDeleteSlot}
          onSlotSelect={handleSlotSelect}
              onTimelineDrop={handleTimelineDrop}
              onTimelineDropHint={showTimelineHint}
              onTrimSlot={handleTrimSlot}
              overlayTracks={overlayTracks}
              onOverlayDrop={handleOverlayDrop}
              onOverlayDelete={handleOverlayDelete}
              beatMarkers={beatMarkers}
              sfxMarkers={sfxMarkers}
              loading={loading}
              templateMusicEnabled={templateMusicEnabled}
              templateId={templateId}
              onReorderSlots={handleReorderSlots}
              trackHeights={trackHeights}
              onTrackHeightChange={handleTrackHeightChange}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
