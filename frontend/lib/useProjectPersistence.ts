import { useCallback, useEffect, useRef, useState } from 'react';
import { apiHeaders, apiUrl } from '@/lib/api';
import {
  overlayTracksToPayload,
  parseOverlayTracksFromEdl,
  type OverlayTracks,
} from '@/lib/edlModel';
import type { PreviewProxyPaths } from '@/lib/previewSettings';
import { DEFAULT_MATCH_STRATEGY, type MatchStrategy } from '@/lib/matchStrategy';
import { slotsToTimeline, timelineToSlots, type TemplateSlot } from '@/lib/timeline';
import {
  embedTrackHeights,
  extractTrackHeights,
  type TrackHeightMap,
} from '@/lib/trackHeights';
import {
  mergeTrackControls,
  type TrackControls,
  type TrackKey,
} from '@/lib/trackControls';
import type { SfxMarker } from '@/lib/slotEdit';

type AssetMap = Record<string, { id?: string; filePath?: string; title?: string }>;

type UseProjectPersistenceOptions = {
  projectId: string | null;
  setProjectId: (id: string | null) => void;
  setTemplateId: (id: string | null) => void;
  slots: TemplateSlot[];
  replaceSlots: (slots: TemplateSlot[]) => void;
  resetHistory: () => void;
  setSelectedSlotId: (id: string) => void;
  assetMap: AssetMap;
  trackControls: Record<TrackKey, TrackControls>;
  trackHeights: TrackHeightMap;
  matchStrategy: MatchStrategy;
  overlayTracks: OverlayTracks;
  coverThumbnail: string;
  setTemplateName: (name: string) => void;
  setCoverThumbnail: (url: string) => void;
  setTemplateAudioPath: (path: string) => void;
  setTemplateVideoPath: (path: string) => void;
  setTemplateProxyPaths: (paths: PreviewProxyPaths) => void;
  setBeatMarkers: (markers: number[]) => void;
  setSfxMarkers: (markers: SfxMarker[]) => void;
  setMatchStrategy: (strategy: MatchStrategy) => void;
  setTrackControls: (controls: Record<TrackKey, TrackControls>) => void;
  setTrackHeights: (heights: TrackHeightMap) => void;
  setOverlayTracks: (tracks: OverlayTracks) => void;
};

export function useProjectPersistence({
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
}: UseProjectPersistenceOptions) {
  const [loadingProject, setLoadingProject] = useState(false);
  const [savingProject, setSavingProject] = useState(false);
  const [autosaveStatus, setAutosaveStatus] = useState<
    'idle' | 'pending' | 'saving' | 'saved' | 'error'
  >('idle');

  const skipAutosaveRef = useRef(true);
  const autosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveProjectRef = useRef<() => Promise<boolean>>(async () => false);

  const loadProject = useCallback(
    async (id: string) => {
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
          if (Array.isArray(data.template?.sfx_markers)) {
            setSfxMarkers(data.template.sfx_markers as SfxMarker[]);
          }
          if (data.match_strategy && typeof data.match_strategy === 'object') {
            setMatchStrategy({ ...DEFAULT_MATCH_STRATEGY, ...(data.match_strategy as MatchStrategy) });
          }
          if (data.track_controls && typeof data.track_controls === 'object') {
            setTrackControls(
              mergeTrackControls(data.track_controls as Partial<Record<TrackKey, TrackControls>>)
            );
            setTrackHeights(extractTrackHeights(data.track_controls));
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
    },
    [
      replaceSlots,
      resetHistory,
      setBeatMarkers,
      setCoverThumbnail,
      setMatchStrategy,
      setOverlayTracks,
      setProjectId,
      setSelectedSlotId,
      setSfxMarkers,
      setTemplateAudioPath,
      setTemplateId,
      setTemplateName,
      setTemplateProxyPaths,
      setTemplateVideoPath,
      setTrackControls,
      setTrackHeights,
    ]
  );

  const saveProject = useCallback(
    async (options?: { silent?: boolean }) => {
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
            track_controls: embedTrackHeights(trackControls, trackHeights),
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
    },
    [
      projectId,
      slots,
      assetMap,
      trackControls,
      trackHeights,
      matchStrategy,
      overlayTracks,
      coverThumbnail,
      replaceSlots,
    ]
  );

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
    projectId,
    loadingProject,
    slots,
    overlayTracks,
    trackControls,
    trackHeights,
    matchStrategy,
    coverThumbnail,
  ]);

  const createProjectFromTemplate = useCallback(
    async (templateIdValue: string) => {
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
    },
    [replaceSlots, resetHistory, setProjectId, setSelectedSlotId]
  );

  const pauseAutosave = useCallback((ms = 1500) => {
    skipAutosaveRef.current = true;
    setTimeout(() => {
      skipAutosaveRef.current = false;
    }, ms);
  }, []);

  useEffect(() => {
    pauseAutosave(2500);
  }, [pauseAutosave]);

  return {
    loadingProject,
    savingProject,
    autosaveStatus,
    setAutosaveStatus,
    loadProject,
    saveProject,
    createProjectFromTemplate,
    pauseAutosave,
    skipAutosaveRef,
  };
}
