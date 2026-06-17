"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react';
import AssetLibrary from '@/components/AssetLibrary';
import Timeline from '@/components/Timeline';
import PreviewPanel from '@/components/PreviewPanel';
import PropertiesPanel, { type MatchWeights } from '@/components/PropertiesPanel';
import Toolbar from '@/components/Toolbar';
import { apiHeaders, apiUrl, toMediaUrl } from '@/lib/api';
import { getSlotTimeRange, splitSlotAtTime } from '@/lib/slotEdit';
import {
  applyAssetToSlot,
  slotsToTimeline,
  timelineToSlots,
  type TemplateSlot,
} from '@/lib/timeline';
import { snapToFrame } from '@/lib/timelineLayout';
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
  mergeTrackControls,
  type TrackControls,
  type TrackKey,
  toggleTrackControl,
} from '@/lib/trackControls';
import {
  DEFAULT_MATCH_STRATEGY,
  strategyToSettings,
  type MatchStrategy,
} from '@/lib/matchStrategy';
import { rippleClearRight, rippleDeleteSlot, trimClipDuration, trimClipStart, moveSlotById, reorderSlots } from '@/lib/slotOps';
import { useTemplateProcessing } from '@/lib/useTemplateProcessing';
import { useAssetProcessingPoll } from '@/lib/useAssetProcessing';
import { uploadAssetWithProgress, uploadTemplateWithProgress } from '@/lib/uploadAsset';
import type { PreviewProxyPaths } from '@/lib/previewSettings';
import { useSlotHistory } from '@/lib/useSlotHistory';
import {
  createOverlayClip,
  overlayTracksToPayload,
  parseOverlayTracksFromEdl,
  type OverlayTracks,
} from '@/lib/edlModel';
import ProjectListModal from '@/components/ProjectListModal';
import OnboardingGuide from '@/components/OnboardingGuide';
import GlobalStatusBar, { type GlobalStatusItem } from '@/components/GlobalStatusBar';
import { buildExportPayload } from '@/lib/exportSettings';
import {
  buildExportPrecheck,
  formatExportPrecheckDialog,
} from '@/lib/exportPrecheck';
import { formatExportError } from '@/lib/formatExportError';
import { computeOnboardingState, type OnboardingStepId } from '@/lib/onboardingSteps';
import {
  fetchCapCutStatus,
  formatCapCutError,
  guessMediaBaseUrl,
  openCapCutDraft,
  type CapCutMateStatus,
} from '@/lib/capcutExport';

type VideoSegment = {
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
  title: string;
  duration: string;
  durationSeconds: number;
  tags: string[];
  filePath: string;
  proxyPath?: string;
  proxyPaths?: PreviewProxyPaths;
  thumbnail?: string;
  segments?: VideoSegment[];
  processingStatus?: 'processing' | 'ready' | 'failed';
  processingProgress?: number;
};

const formatDuration = (seconds: number) => {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
};

export default function EditorPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
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
  const [selectedSlotId, setSelectedSlotId] = useState<string>('');
  const [templateMusicEnabled, setTemplateMusicEnabled] = useState(true);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [templateName, setTemplateName] = useState<string>('未选择模板');
  const [projectId, setProjectId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [uploadingCount, setUploadingCount] = useState(0);
  const [savingProject, setSavingProject] = useState(false);
  const [loadingProject, setLoadingProject] = useState(false);
  const [matching, setMatching] = useState(false);
  const [recognizingSubtitle, setRecognizingSubtitle] = useState(false);
  const [matchMessage, setMatchMessage] = useState<string>('');
  const [matchError, setMatchError] = useState<string>('');
  const [matchWeights, setMatchWeights] = useState<MatchWeights>({
    tags_weight: 0.35,
    visual_weight: 0.35,
    duration_tolerance: 2.0,
  });
  const [exportUrl, setExportUrl] = useState<string | null>(null);
  const [exportStatus, setExportStatus] = useState<string>('');
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string>('');
  const [playheadTime, setPlayheadTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const playRafRef = useRef<number | null>(null);
  const playStartRef = useRef({ wall: 0, time: 0 });
  const playheadRef = useRef(0);
  const [trackControls, setTrackControls] = useState<Record<TrackKey, TrackControls>>(
    DEFAULT_TRACK_CONTROLS
  );
  const [matchStrategy, setMatchStrategy] = useState<MatchStrategy>(DEFAULT_MATCH_STRATEGY);
  const [templateAudioPath, setTemplateAudioPath] = useState('');
  const [templateVideoPath, setTemplateVideoPath] = useState('');
  const [templateProxyPaths, setTemplateProxyPaths] = useState<PreviewProxyPaths>({});
  const [beatMarkers, setBeatMarkers] = useState<number[]>([]);
  const templateProcessing = useTemplateProcessing(templateId);
  const lastTemplateSlotCountRef = useRef(0);
  const templateStuckPollsRef = useRef(0);
  const lastTemplateProgressRef = useRef<{ progress: number; at: number }>({
    progress: -1,
    at: 0,
  });
  const lastEnhanceStatusRef = useRef<string>('ready');
  const [trackControlMessage, setTrackControlMessage] = useState('');
  const trackControlTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [overlayTracks, setOverlayTracks] = useState<OverlayTracks>({ v2: [], v3: [] });
  const [exportResolution, setExportResolution] = useState('1080x1920');
  const [addSubtitles, setAddSubtitles] = useState(true);
  const [exportProgress, setExportProgress] = useState(0);
  const [capCutDraftUrl, setCapCutDraftUrl] = useState<string | null>(null);
  const [capCutExporting, setCapCutExporting] = useState(false);
  const [capCutStatus, setCapCutStatus] = useState('');
  const [capCutReplaceableMode, setCapCutReplaceableMode] = useState(false);
  const [capCutMateStatus, setCapCutMateStatus] = useState<CapCutMateStatus | null>(null);
  const [projectListOpen, setProjectListOpen] = useState(false);
  const [coverThumbnail, setCoverThumbnail] = useState('');
  const [recognizingAllSubtitles, setRecognizingAllSubtitles] = useState(false);
  const templateFileInputRef = useRef<HTMLInputElement>(null);
  const skipAutosaveRef = useRef(true);
  const autosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveProjectRef = useRef<() => Promise<boolean>>(async () => false);
  const [autosaveStatus, setAutosaveStatus] = useState<
    'idle' | 'pending' | 'saving' | 'saved' | 'error'
  >('idle');

  useEffect(() => {
    void fetchCapCutStatus().then(setCapCutMateStatus);
  }, []);

  useEffect(() => {
    if (templateProcessing.beatMarkers.length) {
      setBeatMarkers(templateProcessing.beatMarkers);
    }
  }, [templateProcessing.beatMarkers]);

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

  useEffect(() => {
    const timer = setTimeout(() => {
      skipAutosaveRef.current = false;
    }, 2500);
    return () => clearTimeout(timer);
  }, []);

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

  const assetMap = useMemo(
    () => Object.fromEntries(assets.map((asset) => [asset.id, asset])),
    [assets]
  );

  const selectedSlot = useMemo(
    () => slots.find((slot) => slot.id === selectedSlotId) ?? slots[0] ?? null,
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

  const handlePreviewAsset = (asset: { filePath?: string; thumbnail?: string }) => {
    const url = asset.filePath || asset.thumbnail || '';
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

  useEffect(() => {
    return () => {
      if (trackControlTimerRef.current) clearTimeout(trackControlTimerRef.current);
    };
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

  const handleAssetDragStart = (event: DragEvent<HTMLDivElement>, assetId: string) => {
    event.dataTransfer.setData('text/plain', assetId);
    event.dataTransfer.setData('application/x-asset-id', assetId);
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
    (asset: Asset, slotId: string, segmentId?: string) => {
      if (isTrackLocked(trackControls, 'video')) return;
      const binding = resolveSegmentBinding(asset, segmentId);
      setSlots((current) =>
        current.map((slot) =>
          slot.id === slotId ? applyAssetToSlot(slot, binding) : slot
        )
      );
      setSelectedSlotId(slotId);
    },
    [trackControls, setSlots, resolveSegmentBinding]
  );

  const loadAssets = useCallback(async () => {
    try {
      const resp = await fetch(apiUrl('/api/assets/list'), { headers: apiHeaders() });
      const data = await resp.json();
      if (resp.ok) {
        setAssets(
          data.map((asset: Record<string, unknown>) => ({
            id: asset.asset_id as string,
            title: asset.filename as string,
            duration: formatDuration(Number(asset.duration || 0)),
            durationSeconds: Number(asset.duration || 0),
            tags: [],
            filePath: (asset.file_path as string) || '',
            proxyPath: (asset.proxy_path as string) || undefined,
            proxyPaths: (asset.proxy_paths as PreviewProxyPaths) || undefined,
            thumbnail: asset.thumbnail as string | undefined,
            segments: (asset.segments as VideoSegment[]) || [],
            processingStatus: (asset.processing_status as Asset['processingStatus']) || 'ready',
            processingProgress: Number(asset.processing_progress ?? 100),
          }))
        );
      }
    } catch (error) {
      console.warn('加载素材列表失败', error);
    }
  }, []);

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
        return {
          ...a,
          processingStatus: state.status,
          processingProgress: Math.max(a.processingProgress ?? 0, state.progress),
          segments: state.segments?.length ? state.segments : a.segments,
          durationSeconds: durationSec > 0 ? durationSec : a.durationSeconds,
          duration: durationSec > 0 ? formatDuration(durationSec) : a.duration,
          thumbnail: thumb || a.thumbnail,
          proxyPath: state.proxyPath || a.proxyPath,
          proxyPaths: state.proxyPaths || a.proxyPaths,
        };
      })
    );
  });

  const loadProject = useCallback(async (id: string) => {
    skipAutosaveRef.current = true;
    setLoadingProject(true);
    try {
      const resp = await fetch(apiUrl(`/api/projects/${id}`), { headers: apiHeaders() });
      const data = await resp.json();
      if (resp.ok) {
        const project = data.project ?? data;
        const timeline = (project.timeline || data.timeline || []) as Record<string, unknown>[];
        setProjectId((project.project_id as string) ?? id);
        setTemplateId((project.template_id as string) ?? null);
        setTemplateName(
          (data.name as string) ||
            (project.name as string) ||
            (data.template_name as string) ||
            (data.template?.filename as string) ||
            '已加载项目'
        );
        if (data.cover_thumbnail) setCoverThumbnail(data.cover_thumbnail as string);
        else if (project.cover_thumbnail) setCoverThumbnail(project.cover_thumbnail as string);
        if (data.template?.audio_path) setTemplateAudioPath(data.template.audio_path as string);
        if (data.template?.file_path) setTemplateVideoPath(data.template.file_path as string);
        if (data.template?.proxy_paths && typeof data.template.proxy_paths === 'object') {
          setTemplateProxyPaths(data.template.proxy_paths as PreviewProxyPaths);
        }
        if (Array.isArray(data.template?.beat_markers)) {
          setBeatMarkers(data.template.beat_markers as number[]);
        }
        if (data.match_strategy && typeof data.match_strategy === 'object') {
          setMatchStrategy({ ...DEFAULT_MATCH_STRATEGY, ...(data.match_strategy as MatchStrategy) });
        }
        if (data.track_controls && typeof data.track_controls === 'object') {
          setTrackControls(
            mergeTrackControls(data.track_controls as Partial<Record<TrackKey, TrackControls>>)
          );
        }
        if (data.edl) {
          setOverlayTracks(parseOverlayTracksFromEdl(data.edl as Record<string, unknown>));
        }
        const nextSlots = timelineToSlots(timeline);
        replaceSlots(nextSlots);
        resetHistory();
        setSelectedSlotId(nextSlots[0]?.id ?? '');
      } else {
        alert(data.detail || '加载项目失败');
      }
    } catch (error) {
      console.warn('加载项目失败', error);
      alert('加载项目失败，请重试');
    } finally {
      setLoadingProject(false);
      setTimeout(() => {
        skipAutosaveRef.current = false;
      }, 1500);
    }
  }, []);

  useEffect(() => {
    loadAssets();
    const params = new URLSearchParams(window.location.search);
    const id = params.get('project_id');
    if (id) {
      loadProject(id);
    }
  }, [loadAssets, loadProject]);

  const saveProject = async (options?: { silent?: boolean }) => {
    if (!projectId) {
      if (!options?.silent) alert('请先创建项目');
      return false;
    }

    const timelinePayload = slotsToTimeline(slots, assetMap);

    if (!options?.silent) setSavingProject(true);
    try {
      const resp = await fetch(apiUrl(`/api/projects/${projectId}/timeline`), {
        method: 'PUT',
        headers: apiHeaders(),
        body: JSON.stringify({
          timeline: timelinePayload,
          track_controls: trackControls,
          match_strategy: matchStrategy,
          overlay_tracks: overlayTracksToPayload(overlayTracks),
          cover_thumbnail: coverThumbnail || undefined,
        }),
      });
      const data = await resp.json();
      if (resp.ok && data.success) {
        if (Array.isArray(data.timeline)) {
          replaceSlots(timelineToSlots(data.timeline as Record<string, unknown>[]));
        }
        return true;
      }
      if (!options?.silent) alert(data.detail || '保存项目失败');
      return false;
    } catch (error) {
      console.warn('保存项目失败', error);
      if (!options?.silent) alert('保存项目失败，请重试');
      return false;
    } finally {
      if (!options?.silent) setSavingProject(false);
    }
  };

  saveProjectRef.current = () => saveProject({ silent: true });

  useEffect(() => {
    if (!projectId || skipAutosaveRef.current || loadingProject) return;

    setAutosaveStatus('pending');
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    autosaveTimerRef.current = setTimeout(async () => {
      setAutosaveStatus('saving');
      skipAutosaveRef.current = true;
      const ok = await saveProjectRef.current();
      setTimeout(() => {
        skipAutosaveRef.current = false;
      }, 500);
      setAutosaveStatus(ok ? 'saved' : 'error');
    }, 2000);

    return () => {
      if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    };
  }, [
    slots,
    overlayTracks,
    trackControls,
    matchStrategy,
    matchWeights,
    coverThumbnail,
    projectId,
    loadingProject,
  ]);

  const handleSaveProject = async () => {
    if (await saveProject()) {
      setAutosaveStatus('saved');
      alert('项目已保存');
    }
  };

  const runAutoMatch = async () => {
    if (!projectId || !templateId) {
      alert('请先上传模板并创建项目');
      return;
    }

    if (!assets.length) {
      alert('请先上传素材');
      return;
    }

    setMatching(true);
    setMatchError('');
    setMatchMessage('');

    try {
      const saved = await saveProject();
      if (!saved) {
        throw new Error('保存当前项目失败');
      }

      const resp = await fetch(apiUrl('/api/match/run'), {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({
          project_id: projectId,
          template_id: templateId,
          asset_ids: assets.map((asset) => asset.id),
          overwrite: true,
          settings: strategyToSettings(matchStrategy),
          strategy: matchStrategy,
          weights: matchWeights,
        }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.success) {
        throw new Error(data.detail || data.error || 'AI 自动匹配失败');
      }

      if (Array.isArray(data.timeline)) {
        setSlots(timelineToSlots(data.timeline as Record<string, unknown>[]));
      }

      setMatchMessage(`匹配完成：成功 ${data.matched_count || 0} 个，未匹配 ${data.unmatched_count || 0} 个`);
    } catch (err: unknown) {
      console.error(err);
      setMatchError(err instanceof Error ? err.message : 'AI 自动匹配失败');
    } finally {
      setMatching(false);
    }
  };

  const handleLoadProjectClick = () => {
    setProjectListOpen(true);
  };

  const handleBatchRecognizeSubtitles = async () => {
    if (!templateId || !slots.length) {
      alert('请先上传模板');
      return;
    }
    setRecognizingAllSubtitles(true);
    try {
      const payload = slots
        .map((slot) => {
          const range = getSlotTimeRange(slots, slot.id);
          if (!range) return null;
          return { slot_id: slot.id, slot_start: range.start, slot_end: range.end };
        })
        .filter(Boolean);
      const resp = await fetch(apiUrl('/api/subtitle/recognize-slot-batch'), {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({ template_id: templateId, slots: payload }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || '批量识别失败');
      const resultMap = new Map(
        (data.results || []).map((r: { slot_id: string; subtitle_text?: string; subtitle_segments?: unknown[] }) => [
          r.slot_id,
          r,
        ])
      );
      setSlots((prev) =>
        prev.map((slot) => {
          const hit = resultMap.get(slot.id) as { success?: boolean; subtitle_text?: string; subtitle_segments?: unknown[] } | undefined;
          if (!hit?.success) return slot;
          return {
            ...slot,
            subtitleText: hit.subtitle_text || slot.subtitleText,
            subtitle_segments: hit.subtitle_segments || slot.subtitle_segments,
          };
        })
      );
      alert(`批量识别完成：${data.recognized_count}/${data.total_count} 个槽位`);
    } catch (err) {
      alert(err instanceof Error ? err.message : '批量识别失败');
    } finally {
      setRecognizingAllSubtitles(false);
    }
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

  const createProjectFromTemplate = async (templateIdValue: string) => {
    const resp = await fetch(apiUrl('/api/projects/from-template'), {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({ template_id: templateIdValue }),
    });
    const data = await resp.json();
    if (!resp.ok || !data.success) {
      throw new Error(data.detail || '创建项目失败');
    }

    setProjectId(data.project_id);
    const nextSlots = timelineToSlots((data.timeline || []) as Record<string, unknown>[]);
    replaceSlots(nextSlots);
    resetHistory();
    setSelectedSlotId(nextSlots[0]?.id ?? '');

    return data;
  };

  const handleTemplateUpload = async (file: File) => {
    const localPreview = URL.createObjectURL(file);
    setTemplateVideoPath(localPreview);
    skipAutosaveRef.current = true;
    setUploadingCount((n) => n + 1);
    try {
      const data = await uploadTemplateWithProgress(file, () => undefined);
      URL.revokeObjectURL(localPreview);
      setTemplateId(data.template_id as string);
      setTemplateName((data.filename as string) || '已上传模板');
      if (data.file_path) setTemplateVideoPath(data.file_path as string);
      await createProjectFromTemplate(data.template_id as string);
      lastTemplateSlotCountRef.current = Number(data.slot_count ?? 1);
    } catch (error) {
      URL.revokeObjectURL(localPreview);
      console.warn('模板上传失败', error);
      alert(error instanceof Error ? error.message : '模板上传失败，请重试');
    } finally {
      setUploadingCount((n) => Math.max(0, n - 1));
      setTimeout(() => {
        skipAutosaveRef.current = false;
      }, 1500);
    }
  };

  const uploadAssetFile = useCallback(async (file: File): Promise<Asset | null> => {
    const tempId = `uploading-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const localPreview = URL.createObjectURL(file);
    const optimistic: Asset = {
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

      const asset: Asset = {
        id: data.asset_id as string,
        title: (data.filename as string) || file.name,
        duration: formatDuration(Number(data.duration || 0)),
        durationSeconds: Number(data.duration || 0),
        tags: [],
        filePath: (data.file_path as string) || '',
        segments: (data.segments as VideoSegment[]) || [],
        proxyPath: (data.proxy_path as string) || undefined,
        proxyPaths: (data.proxy_paths as PreviewProxyPaths) || undefined,
        thumbnail: (data.thumbnail as string) || undefined,
        processingStatus: data.processing ? 'processing' : 'ready',
        processingProgress: Number(data.processing_progress ?? 5),
      };

      setAssets((current) => current.map((a) => (a.id === tempId ? asset : a)));
      return asset;
    } catch (error) {
      console.warn('素材上传失败', error);
      setAssets((current) => current.filter((a) => a.id !== tempId));
      alert(error instanceof Error ? error.message : '素材上传失败，请重试');
      return null;
    } finally {
      URL.revokeObjectURL(localPreview);
      setUploadingCount((n) => Math.max(0, n - 1));
    }
  }, []);

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
      if (isTrackLocked(trackControls, 'video')) return;

      const files = getVideoFilesFromDataTransfer(event.dataTransfer);
      if (files.length > 0) {
        const file = files[0];
        if (slots.length === 0) {
          await handleTemplateUpload(file);
          return;
        }
        const asset = await uploadAssetFile(file);
        if (!asset) return;
        const slotId = resolveDropSlotId(time, preferredSlotId);
        if (slotId) assignAssetToSlot(asset, slotId);
        return;
      }

      const dragKey = event.dataTransfer.getData('text/plain');
      if (!dragKey) return;
      const [assetId, segmentId] = dragKey.includes(':') ? dragKey.split(':', 2) : [dragKey, ''];
      const asset = assetMap[assetId];
      if (!asset) return;
      if (slots.length === 0) {
        alert('请先拖入模板视频，或从顶部「导入模板」创建时间线');
        return;
      }
      const slotId = resolveDropSlotId(time, preferredSlotId);
      if (slotId) assignAssetToSlot(asset, slotId, segmentId || undefined);
    },
    [
      trackControls,
      slots.length,
      uploadAssetFile,
      resolveDropSlotId,
      assignAssetToSlot,
      assetMap,
      handleTemplateUpload,
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
    setSlots((current) =>
      current.map((slot) => (slot.id === selectedSlot.id ? { ...slot, ...updates } : slot))
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
        prev.map((slot) => (slot.id === slotId ? { ...slot, subtitleText: text } : slot))
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

  const handleTemplateInstalled = async (tid: string) => {
    setLoading(true);
    try {
      setTemplateId(tid);
      const tplResp = await fetch(apiUrl(`/api/template/${tid}`), { headers: apiHeaders() });
      const tplData = await tplResp.json();
      if (tplResp.ok) {
        setTemplateName((tplData.filename as string) || '市场模板');
        if (tplData.audio_path) setTemplateAudioPath(tplData.audio_path as string);
        if (tplData.file_path) setTemplateVideoPath(tplData.file_path as string);
      }
      await createProjectFromTemplate(tid);
      setExportStatus('');
    } catch (err) {
      alert(err instanceof Error ? err.message : '安装模板失败');
    } finally {
      setLoading(false);
    }
  };

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

  const handleRecognizeSlotSubtitle = async () => {
    if (!selectedSlot || !templateId) {
      alert('请先导入模板并选择槽位');
      return;
    }
    if (isTrackLocked(trackControls, 'subtitle')) return;

    const range = getSlotTimeRange(slots, selectedSlot.id);
    if (!range || range.end <= range.start) {
      alert('无法确定当前槽位的时间范围');
      return;
    }

    setRecognizingSubtitle(true);
    try {
      const resp = await fetch(apiUrl('/api/subtitle/recognize-slot'), {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({
          template_id: templateId,
          slot_start: range.start,
          slot_end: range.end,
          slot_id: selectedSlot.originalSlotId,
        }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.success) {
        throw new Error(data.detail || '人声识别失败');
      }

      handleUpdateSlot({
        subtitleText: data.subtitle_text || '',
        subtitle_segments: data.subtitle_segments || [],
      });
    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : '人声识别失败');
    } finally {
      setRecognizingSubtitle(false);
    }
  };

  const totalDuration = useMemo(() => getTotalDuration(slots), [slots]);

  const handlePlayheadStep = useCallback(
    (deltaSec: number) => {
      setIsPlaying(false);
      setPlayheadTime((t) => snapToFrame(Math.max(0, Math.min(totalDuration, t + deltaSec))));
    },
    [totalDuration]
  );

  useEffect(() => {
    playheadRef.current = playheadTime;
  }, [playheadTime]);

  const handleTogglePlay = useCallback(() => {
    setIsPlaying((playing) => {
      if (!playing) {
        playStartRef.current = { wall: performance.now(), time: playheadRef.current };
      }
      return !playing;
    });
  }, []);

  const handlePlayheadChange = useCallback(
    (time: number) => {
      const snapped = snapToFrame(time);
      setPlayheadTime(snapped);
      playheadRef.current = snapped;
      if (snapped >= totalDuration - 1 / 30) {
        setIsPlaying(false);
      }
    },
    [totalDuration]
  );

  const handleScrubStart = useCallback(() => {
    setIsPlaying(false);
  }, []);

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

  const handleTemplateLibraryLoad = useCallback(
    async (tid: string) => {
      if (
        projectId &&
        slots.some((s) => s.matchedAssetId || s.asset_file_path) &&
        !window.confirm('切换模板将重建时间线，已匹配素材会丢失，是否继续？')
      ) {
        return;
      }
      try {
        const tplResp = await fetch(apiUrl(`/api/template/${tid}`), { headers: apiHeaders() });
        const tpl = await tplResp.json();
        if (!tplResp.ok) throw new Error(tpl.detail || '模板加载失败');
        setTemplateId(tid);
        setTemplateName((tpl.filename as string) || '模板');
        if (tpl.file_path) setTemplateVideoPath(tpl.file_path as string);
        if (tpl.audio_path) setTemplateAudioPath(tpl.audio_path as string);
        await createProjectFromTemplate(tid);
        setExportStatus('');
      } catch (err) {
        alert(err instanceof Error ? err.message : '载入模板失败');
      }
    },
    [projectId, slots, createProjectFromTemplate]
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
    // 播放时由 PreviewPanel 视频时钟驱动播放头，避免双时钟打架导致切镜卡顿
    if (isPlaying) {
      if (playRafRef.current != null) {
        cancelAnimationFrame(playRafRef.current);
        playRafRef.current = null;
      }
      return;
    }

    if (playRafRef.current != null) {
      cancelAnimationFrame(playRafRef.current);
      playRafRef.current = null;
    }
  }, [isPlaying]);

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

  const pollExportTask = async (taskId: string) => {
    for (let i = 0; i < 120; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      const resp = await fetch(apiUrl(`/api/export/tasks/${taskId}`), { headers: apiHeaders() });
      const data = await resp.json();
      if (data.status === 'completed' && data.result?.output_url) {
        setExportProgress(100);
        return data.result.output_url as string;
      }
      if (data.status === 'failed') {
        throw new Error(formatExportError(data.error || '导出失败'));
      }
      const progress = data.progress ?? Math.min(95, Math.round(((i + 1) / 120) * 100));
      setExportProgress(progress);
      setExportStatus(`云渲染中… ${progress}%`);
    }
    throw new Error('导出超时');
  };

  const handleOverlayDelete = useCallback((track: 'v2' | 'v3', clipId: string) => {
    setOverlayTracks((prev) => ({
      ...prev,
      [track]: prev[track].filter((clip) => clip.id !== clipId),
    }));
  }, []);

  const handleExportCapCut = async () => {
    if (!projectId || !templateId || !slots.length) {
      alert('请先导入模板并完成时间线后再导出');
      return;
    }

    const precheck = buildExportPrecheck(slots, assets, templateProcessing, {
      matching,
      exporting: exporting || capCutExporting,
      capcutReplaceable: capCutReplaceableMode,
    });
    if (!precheck.canProceed) {
      alert(formatExportPrecheckDialog(precheck));
      return;
    }
    const confirmLabel = capCutReplaceableMode ? '是否继续导出可替换模板草稿？' : '是否继续导出剪映草稿？';
    if (precheck.warnings.length && !window.confirm(`${formatExportPrecheckDialog(precheck)}\n\n${confirmLabel}`)) {
      return;
    }

    const status = await fetchCapCutStatus();
    setCapCutMateStatus(status);
    if (status && !status.ready) {
      setCapCutStatus('剪映小助手未连接，请先启动 CapCut Mate（默认端口 30000）');
      return;
    }

    setCapCutExporting(true);
    setCapCutDraftUrl(null);
    setCapCutStatus(
      capCutReplaceableMode ? '正在生成可替换模板草稿…' : '正在保存并生成剪映草稿…'
    );

    try {
      const saved = await saveProject();
      if (!saved) {
        setCapCutStatus('保存项目失败');
        return;
      }

      const exportPayload = buildExportPayload({
        trackControls,
        templateMusicEnabled,
        useAssetAudio: slots.some((slot) => slot.useOriginalAudio),
        addSubtitles,
      });

      const resp = await fetch(apiUrl('/api/export/capcut-draft'), {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({
          project_id: projectId,
          ...exportPayload,
          template_music_enabled: templateMusicEnabled,
          resolution: exportResolution,
          include_template_slots: true,
          capcut_export_mode: capCutReplaceableMode ? 'replaceable_template' : 'filled',
          media_base_url: guessMediaBaseUrl(),
        }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.success) {
        throw new Error(formatCapCutError(data));
      }

      const draftUrl = (data.draft_url as string) || null;
      setCapCutDraftUrl(draftUrl);
      const skipped = (data.skipped_slots as string[] | undefined) || [];
      const warnings = (data.warnings as string[] | undefined) || [];
      const skipHint = skipped.length ? `（跳过 ${skipped.length} 个槽位）` : '';
      const warnHint = warnings.length ? `；${warnings[0]}` : '';
      const modeHint = capCutReplaceableMode
        ? '。打开后在剪映中选中片段 → 替换素材'
        : '。正在打开剪映…';
      setCapCutStatus(
        `已生成 ${data.clips_count ?? 0} 个片段、${data.captions_count ?? 0} 条标签/字幕${skipHint}${warnHint}${modeHint}`
      );
      if (draftUrl) {
        openCapCutDraft(draftUrl);
      }
    } catch (error) {
      const message = formatExportError(error);
      setCapCutStatus(message);
      setCapCutDraftUrl(null);
    } finally {
      setCapCutExporting(false);
    }
  };

  const handleOpenCapCutDraft = useCallback(() => {
    if (capCutDraftUrl) {
      openCapCutDraft(capCutDraftUrl);
    }
  }, [capCutDraftUrl]);

  const handleExport = async () => {
    if (!projectId || !templateId || !slots.length) {
      alert('请先导入模板并完成时间线后再导出');
      return;
    }

    const precheck = buildExportPrecheck(slots, assets, templateProcessing, {
      matching,
      exporting: exporting || capCutExporting,
    });
    if (!precheck.canProceed) {
      alert(formatExportPrecheckDialog(precheck));
      return;
    }
    if (precheck.warnings.length && !window.confirm(`${formatExportPrecheckDialog(precheck)}\n\n是否继续导出？`)) {
      return;
    }

    setExporting(true);
    setExportError('');
    setExportUrl(null);
    setExportProgress(0);
    setExportStatus('正在保存并导出...');

    try {
      const saved = await saveProject();
      if (!saved) {
        setExportError('保存项目失败');
        setExportStatus('保存项目失败');
        return;
      }

      const exportPayload = buildExportPayload({
        trackControls,
        templateMusicEnabled,
        useAssetAudio: slots.some((slot) => slot.useOriginalAudio),
        addSubtitles,
      });

      const resp = await fetch(apiUrl('/api/export/render-async'), {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({
          project_id: projectId,
          ...exportPayload,
          template_music_enabled: templateMusicEnabled,
          resolution: exportResolution,
          use_edl: true,
          use_nvenc: true,
        }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.task_id) {
        throw new Error(formatExportError(data.detail || '导出任务创建失败'));
      }
      setExportStatus('导出任务已提交…');
      const outputUrl = await pollExportTask(data.task_id);
      setExportUrl(outputUrl);
      setExportStatus('导出完成，点击下载查看成片。');
    } catch (error) {
      console.warn('导出失败', error);
      setExportUrl(null);
      const message = formatExportError(error);
      setExportError(message);
      setExportStatus(message);
    } finally {
      setExporting(false);
    }
  };

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

  const exportPrecheck = useMemo(
    () =>
      buildExportPrecheck(slots, assets, templateProcessing, {
        matching,
        exporting: exporting || capCutExporting,
      }),
    [slots, assets, templateProcessing, matching, exporting, capCutExporting]
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
            ? '按画面切分槽位（约 10 秒内可编辑）'
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
      items.push({
        id: 'template-enhance',
        label: 'AI 镜头修正',
        detail: '后台优化切分边界、生成缩略图与预览代理',
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
        progress: 50,
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
    exporting,
    exportProgress,
    capCutExporting,
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
        case 'assets':
          alert('请在左侧「素材库」标签页上传你的旅行视频，等待分析完成');
          break;
        case 'match':
          void runAutoMatch();
          break;
        case 'export':
          void handleExport();
          break;
        default:
          break;
      }
    },
    [triggerTemplateImport, runAutoMatch, handleExport]
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
    <div className="flex h-screen flex-col overflow-hidden bg-[#141414]">
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
      />

      <GlobalStatusBar items={globalStatusItems} autosaveLabel={autosaveLabel} />

      <div className="flex min-h-0 flex-1">
        <div className="w-[min(360px,32vw)] shrink-0">
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
            onAssetsRefresh={() => void loadAssets()}
            slots={slots}
            selectedSlotId={selectedSlotId}
            onSelectSlot={handleSlotSelect}
            onUpdateSlotSubtitle={handleUpdateSlotSubtitle}
            templateMusicEnabled={templateMusicEnabled}
            templateAudioUrl={templateAudioPath}
            onToggleTemplateMusic={handleToggleTemplateMusic}
            onToggleSlotOriginalAudio={handleToggleSlotOriginalAudio}
            onBatchRecognizeSubtitles={() => void handleBatchRecognizeSubtitles()}
            recognizingAllSubtitles={recognizingAllSubtitles}
            onTemplateLibrarySelect={(tid) => void handleTemplateLibraryLoad(tid)}
            onTemplateLibraryImported={(tid) => void handleTemplateLibraryLoad(tid)}
          />
        </div>

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
          onRecognizeSlotSubtitle={handleRecognizeSlotSubtitle}
          onRecognizeAllSubtitles={handleBatchRecognizeSubtitles}
          recognizingAllSubtitles={recognizingAllSubtitles}
          onImportTemplate={triggerTemplateImport}
          onMoveSlot={handleMoveSlot}
          slotOrderIndex={selectedSlotOrderIndex}
          slotOrderTotal={slots.length}
        />

        <PreviewPanel
          slots={slots}
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
          capCutStatus={capCutStatus}
          capCutReplaceableMode={capCutReplaceableMode}
          onCapCutReplaceableModeChange={setCapCutReplaceableMode}
          capCutMateStatus={capCutMateStatus}
          onOpenCapCutDraft={handleOpenCapCutDraft}
          canExport={canExport}
          onPlayheadChange={handlePlayheadChange}
          onPlayheadStep={handlePlayheadStep}
        />
      </div>

      <div className="h-[260px] shrink-0 border-t border-[#242428]">
        <Timeline
          slots={slots}
          assetMap={assetMap}
          templateVideoPath={templateVideoPath}
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
          onTrimSlot={handleTrimSlot}
          overlayTracks={overlayTracks}
          onOverlayDrop={handleOverlayDrop}
          onOverlayDelete={handleOverlayDelete}
          beatMarkers={beatMarkers}
          loading={loading}
          templateMusicEnabled={templateMusicEnabled}
          templateId={templateId}
          onReorderSlots={handleReorderSlots}
        />
      </div>
    </div>
  );
}
