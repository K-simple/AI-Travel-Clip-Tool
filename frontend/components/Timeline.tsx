'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from 'react';
import { buildClipLayouts,
  buildSubtitleSegmentLayouts,
  findClipAtTime,
  getTotalDuration,
  isNearPlayheadX,
  snapTime,
  type ClipLayout,
  type SegmentLayout,
} from '@/lib/timelineLayout';
import { describeSfxMarker } from '@/lib/slotEdit';
import {
  isTrackContentVisible,
  isTrackLocked,
  isTrackMuted,
  type TrackControls,
  type TrackKey,
} from '@/lib/trackControls';
import { TrackHeaderPanel, trackLaneClass } from '@/components/timeline/TrackHeaderPanel';
import { TimelinePlayhead } from '@/components/timeline/TimelinePlayhead';
import { TimelineRuler } from '@/components/timeline/TimelineRuler';
import { TimelineToolbar } from '@/components/timeline/TimelineToolbar';
import {
  CapCutAudioClip,
  CapCutStickerClip,
  CapCutSubtitleClip,
  CapCutVideoClip,
  laneGridStyle,
} from '@/components/timeline/TimelineTrackClips';
import { canAcceptTimelineDrop, isFileDrag, isInternalAssetDrag } from '@/lib/timelineDrop';
import type { TemplateSlot } from '@/lib/timeline';
import { overlayLayouts, type OverlayClip, type OverlayTracks } from '@/lib/edlModel';
import { CLIP_GAP, CLIP_INSET, RULER_H, TIMELINE_THEME } from '@/components/timeline/timelineTheme';
import {
  DEFAULT_VISIBLE_TRACK_KEYS,
  buildActiveTrackLayout,
  getAddableTracks,
  getTrackDef,
  sortTrackKeys,
} from '@/lib/timelineTracks';
import {
  adjustLabelForSlot,
  filterLabelForSlot,
  hasActiveAdjust,
  hasActiveColorGrade,
  hasActiveMask,
} from '@/lib/slotEffects';
import { fetchTemplateWaveform, sliceWaveformPeaks } from '@/lib/waveform';
import { clampTrackHeight, type TrackHeightMap } from '@/lib/trackHeights';
import { TrackResizeHandle } from '@/components/timeline/TrackResizeHandle';
import type { PointerEvent as ReactPointerEvent } from 'react';

const SLOT_REORDER_MIME = 'application/x-slot-reorder';

type TimelineProps = {
  slots: TemplateSlot[];
  assetMap: Record<string, { title: string; thumbnail?: string; filePath?: string }>;
  templateVideoPath?: string;
  selectedSlotId?: string;
  playheadTime?: number;
  isPlaying?: boolean;
  canUndo?: boolean;
  canRedo?: boolean;
  trackControls: Record<TrackKey, TrackControls>;
  trackControlMessage?: string;
  onTrackControlToggle: (key: TrackKey, field: keyof TrackControls) => void;
  onPlayheadChange?: (time: number) => void;
  onScrubStart?: () => void;
  onTogglePlay?: () => void;
  onUndo?: () => void;
  onRedo?: () => void;
  onSplit?: () => void;
  onDeleteSlot?: (slotId: string) => void;
  onSlotSelect: (slotId: string) => void;
  onTimelineDrop: (event: DragEvent<HTMLDivElement>, time: number, slotId?: string | null) => void;
  onTimelineDropHint?: (message: string) => void;
  onTrimSlot?: (slotId: string, mode: 'start' | 'end', deltaSec: number) => void;
  overlayTracks?: OverlayTracks;
  onOverlayDrop?: (track: 'v2' | 'v3', time: number, assetId: string) => void;
  onOverlayDelete?: (track: 'v2' | 'v3', clipId: string) => void;
  beatMarkers?: number[];
  sfxMarkers?: import('@/lib/slotEdit').SfxMarker[];
  loading?: boolean;
  coverThumb?: string;
  onCoverClick?: () => void;
  templateMusicEnabled?: boolean;
  templateId?: string | null;
  onReorderSlots?: (fromSlotId: string, toSlotId: string) => void;
  trackHeights?: TrackHeightMap;
  onTrackHeightChange?: (key: TrackKey, height: number | null) => void;
};

const BASE_PX_PER_SEC = 56;

function HiddenTrackHint({
  label,
  selected,
}: {
  label: string;
  selected?: boolean;
}) {
  return (
    <div
      className={trackLaneClass(!!selected, 'flex h-full items-center px-3 text-[10px] text-[#636366]')}
      style={{ borderColor: TIMELINE_THEME.border }}
    >
      {label} · 已隐藏
    </div>
  );
}

function SoloFilteredHint({ selected }: { selected?: boolean }) {
  return (
    <div
      className={trackLaneClass(!!selected, 'flex h-full items-center px-3 text-[10px] text-[#636366]')}
      style={{ borderColor: TIMELINE_THEME.border }}
    >
      独奏模式中已隐藏
    </div>
  );
}

function LaneDropHint({ text }: { text: string }) {
  return (
    <div className="pointer-events-none absolute inset-0 z-[1] flex items-center justify-center px-3">
      <span className="rounded border border-dashed border-[#2a2a2e] bg-[#141416]/60 px-2 py-0.5 text-center text-[9px] text-[#505054]">
        {text}
      </span>
    </div>
  );
}

export default function Timeline({
  slots,
  assetMap,
  templateVideoPath = '',
  selectedSlotId,
  playheadTime: controlledPlayhead,
  isPlaying = false,
  canUndo = false,
  canRedo = false,
  onPlayheadChange,
  onScrubStart,
  onTogglePlay,
  onUndo,
  onRedo,
  onSplit,
  onDeleteSlot,
  trackControls,
  trackControlMessage,
  onTrackControlToggle,
  onSlotSelect,
  onTimelineDrop,
  onTimelineDropHint,
  onTrimSlot,
  overlayTracks = { v2: [], v3: [] },
  onOverlayDrop,
  onOverlayDelete,
  beatMarkers = [],
  sfxMarkers = [],
  loading = false,
  coverThumb: coverThumbProp,
  onCoverClick,
  templateMusicEnabled = true,
  templateId,
  onReorderSlots,
  trackHeights = {},
  onTrackHeightChange,
}: TimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const reorderDragIdRef = useRef<string | null>(null);
  const [templateWaveform, setTemplateWaveform] = useState<number[]>([]);
  const [zoom, setZoom] = useState(1);
  const [magnet, setMagnet] = useState(true);
  const [internalPlayhead, setInternalPlayhead] = useState(0);
  const [draggingPlayhead, setDraggingPlayhead] = useState(false);
  const [selectedTrackKey, setSelectedTrackKey] = useState<TrackKey | null>('video');
  const [visibleTrackKeys, setVisibleTrackKeys] = useState<TrackKey[]>(DEFAULT_VISIBLE_TRACK_KEYS);
  const [viewportWidth, setViewportWidth] = useState(0);
  const [dragOverVideo, setDragOverVideo] = useState(false);
  const [selectedOverlay, setSelectedOverlay] = useState<{ track: 'v2' | 'v3'; id: string } | null>(
    null
  );
  const scrubMovedRef = useRef(false);
  const pendingScrubRef = useRef<{ startX: number; active: boolean } | null>(null);

  const selectSlot = useCallback(
    (slotId: string, opts?: { force?: boolean }) => {
      if (!opts?.force && scrubMovedRef.current) {
        scrubMovedRef.current = false;
        return;
      }
      setSelectedOverlay(null);
      onSlotSelect(slotId);
    },
    [onSlotSelect]
  );

  useEffect(() => {
    if (!templateId) {
      setTemplateWaveform([]);
      return;
    }
    void fetchTemplateWaveform(templateId, 400).then(setTemplateWaveform);
  }, [templateId]);

  const handleSlotReorderDragStart = useCallback((e: DragEvent<HTMLDivElement>, slotId: string) => {
    reorderDragIdRef.current = slotId;
    e.dataTransfer.setData(SLOT_REORDER_MIME, slotId);
    e.dataTransfer.effectAllowed = 'move';
  }, []);

  const handleSlotReorderDrop = useCallback(
    (e: DragEvent<HTMLDivElement>, targetSlotId: string) => {
      const fromId = reorderDragIdRef.current || e.dataTransfer.getData(SLOT_REORDER_MIME);
      reorderDragIdRef.current = null;
      if (!fromId || fromId === targetSlotId) return;
      onReorderSlots?.(fromId, targetSlotId);
    },
    [onReorderSlots]
  );

  const playheadTime = controlledPlayhead ?? internalPlayhead;
  const setPlayhead = useCallback(
    (t: number) => {
      if (onPlayheadChange) onPlayheadChange(t);
      else setInternalPlayhead(t);
    },
    [onPlayheadChange]
  );

  const pxPerSec = BASE_PX_PER_SEC * zoom;
  const totalDuration = getTotalDuration(slots);
  const activeTrackLayout = useMemo(
    () => buildActiveTrackLayout(visibleTrackKeys, trackHeights),
    [visibleTrackKeys, trackHeights]
  );
  const addableTracks = useMemo(() => getAddableTracks(visibleTrackKeys), [visibleTrackKeys]);
  const contentWidth = Math.max(totalDuration * pxPerSec + 120, viewportWidth, 480);
  const displayDuration = Math.max(totalDuration, contentWidth / pxPerSec);
  const scrubMaxDuration = displayDuration;
  const clipLayouts = useMemo(() => buildClipLayouts(slots, pxPerSec), [slots, pxPerSec]);
  const subtitleLayouts = useMemo(
    () => buildSubtitleSegmentLayouts(slots, pxPerSec),
    [slots, pxPerSec]
  );
  const v2Layouts = useMemo(
    () => overlayLayouts(overlayTracks.v2, pxPerSec),
    [overlayTracks.v2, pxPerSec]
  );
  const v3Layouts = useMemo(
    () => overlayLayouts(overlayTracks.v3, pxPerSec),
    [overlayTracks.v3, pxPerSec]
  );
  const tickStep = zoom >= 1.8 ? 1 : zoom >= 1 ? 2 : 5;
  const gridStyle = useMemo(() => laneGridStyle(pxPerSec), [pxPerSec]);

  const trackHeight = useCallback(
    (key: TrackKey) => activeTrackLayout.find((t) => t.key === key)?.height ?? getTrackDef(key)?.height ?? 32,
    [activeTrackLayout]
  );

  const beginTrackResize = useCallback(
    (key: TrackKey, event: ReactPointerEvent<HTMLDivElement>) => {
      if (!onTrackHeightChange) return;
      event.preventDefault();
      event.stopPropagation();
      const startY = event.clientY;
      const startHeight = trackHeight(key);
      const pointerId = event.pointerId;
      const handle = event.currentTarget;
      handle.setPointerCapture(pointerId);

      const onMove = (ev: PointerEvent) => {
        onTrackHeightChange(key, clampTrackHeight(startHeight + (ev.clientY - startY)));
      };
      const onUp = () => {
        try {
          handle.releasePointerCapture(pointerId);
        } catch {
          /* ignore */
        }
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
        window.removeEventListener('pointercancel', onUp);
      };

      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
      window.addEventListener('pointercancel', onUp);
    },
    [onTrackHeightChange, trackHeight]
  );

  const resetTrackHeight = useCallback(
    (key: TrackKey) => {
      onTrackHeightChange?.(key, null);
    },
    [onTrackHeightChange]
  );

  const handleAddTrack = useCallback(
    (key: TrackKey) => {
      setVisibleTrackKeys((prev) => sortTrackKeys([...prev, key]));
      if (!trackControls[key].visible) {
        onTrackControlToggle(key, 'visible');
      }
      setSelectedTrackKey(key);
    },
    [trackControls, onTrackControlToggle]
  );

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const update = () => setViewportWidth(el.clientWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const timeFromClientX = useCallback(
    (clientX: number) => {
      const el = scrollRef.current;
      if (!el) return 0;
      const rect = el.getBoundingClientRect();
      const x = clientX - rect.left + el.scrollLeft;
      return snapTime(x / pxPerSec, clipLayouts, magnet, subtitleLayouts);
    },
    [pxPerSec, clipLayouts, magnet, subtitleLayouts]
  );

  const scrubAtClientX = useCallback(
    (clientX: number, options?: { selectSlot?: boolean }) => {
      const el = scrollRef.current;
      if (el) {
        const rect = el.getBoundingClientRect();
        const edge = 56;
        if (clientX < rect.left + edge) {
          el.scrollLeft = Math.max(0, el.scrollLeft - Math.max(8, Math.ceil((rect.left + edge - clientX) / 3)));
        } else if (clientX > rect.right - edge) {
          el.scrollLeft += Math.max(8, Math.ceil((clientX - (rect.right - edge)) / 3));
        }
      }
      const t = Math.min(Math.max(0, timeFromClientX(clientX)), scrubMaxDuration);
      setPlayhead(t);
      if (options?.selectSlot !== false) {
        const clip = findClipAtTime(clipLayouts, t);
        if (clip) selectSlot(clip.slot.id, { force: true });
      }
    },
    [timeFromClientX, scrubMaxDuration, setPlayhead, clipLayouts, selectSlot]
  );

  const seekTo = useCallback(
    (clientX: number, options?: { selectSlot?: boolean }) => {
      scrubAtClientX(clientX, options);
    },
    [scrubAtClientX]
  );

  const beginScrub = useCallback(
    (clientX: number, trackKey?: TrackKey) => {
      onScrubStart?.();
      scrubMovedRef.current = false;
      if (trackKey) setSelectedTrackKey(trackKey);
      setDraggingPlayhead(true);
      scrubAtClientX(clientX);
    },
    [onScrubStart, scrubAtClientX]
  );

  const moveScrub = useCallback(
    (clientX: number) => {
      scrubMovedRef.current = true;
      scrubAtClientX(clientX);
    },
    [scrubAtClientX]
  );

  const endScrub = useCallback(() => {
    setDraggingPlayhead(false);
    pendingScrubRef.current = null;
  }, []);

  const handleTrackBgMouseDown = (e: ReactMouseEvent, trackKey: TrackKey) => {
    if (e.button !== 0) return;
    if ((e.target as HTMLElement).closest('[data-trim-handle]')) return;
    const onClip = (e.target as HTMLElement).closest('[data-clip]');
    const el = scrollRef.current;
    if (onClip && el && !isNearPlayheadX(e.clientX, el, playheadTime, pxPerSec)) {
      return;
    }
    e.preventDefault();
    beginScrub(e.clientX, trackKey);
  };

  useEffect(() => {
    if (!draggingPlayhead) return;
    const prevUserSelect = document.body.style.userSelect;
    const prevCursor = document.body.style.cursor;
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'ew-resize';

    const onMove = (e: MouseEvent | PointerEvent) => moveScrub(e.clientX);
    const onUp = () => endScrub();
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      document.body.style.userSelect = prevUserSelect;
      document.body.style.cursor = prevCursor;
    };
  }, [draggingPlayhead, moveScrub, endScrub]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const onPointerDownCapture = (e: PointerEvent) => {
      if (e.button !== 0) return;
      const target = e.target as HTMLElement;
      if (target.closest('[data-playhead]') || target.closest('[data-trim-handle]')) return;
      if (!isNearPlayheadX(e.clientX, el, playheadTime, pxPerSec)) return;
      e.preventDefault();
      e.stopPropagation();
      beginScrub(e.clientX);
    };

    el.addEventListener('pointerdown', onPointerDownCapture, true);
    return () => el.removeEventListener('pointerdown', onPointerDownCapture, true);
  }, [playheadTime, pxPerSec, beginScrub]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const onPointerDown = (e: PointerEvent) => {
      if (e.button !== 0) return;
      const target = e.target as HTMLElement;
      if (target.closest('[data-playhead]') || target.closest('[data-trim-handle]')) return;
      pendingScrubRef.current = { startX: e.clientX, active: false };
    };

    const onPointerMove = (e: PointerEvent) => {
      const pending = pendingScrubRef.current;
      if (!pending || pending.active) return;
      if (Math.abs(e.clientX - pending.startX) < 4) return;
      pending.active = true;
      beginScrub(e.clientX);
      moveScrub(e.clientX);
    };

    const onPointerUp = () => {
      const pending = pendingScrubRef.current;
      if (pending?.active) {
        endScrub();
      }
      pendingScrubRef.current = null;
    };

    el.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    return () => {
      el.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
    };
  }, [beginScrub, moveScrub, endScrub]);

  useEffect(() => {
    const max = slots.length > 0 ? totalDuration : scrubMaxDuration;
    if (playheadTime > max) setPlayhead(max);
  }, [totalDuration, scrubMaxDuration, playheadTime, slots.length, setPlayhead]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || draggingPlayhead) return;
    const playheadX = playheadTime * pxPerSec;
    const margin = 80;
    if (playheadX < el.scrollLeft + margin) {
      el.scrollLeft = Math.max(0, playheadX - margin);
    } else if (playheadX > el.scrollLeft + el.clientWidth - margin) {
      el.scrollLeft = playheadX - el.clientWidth + margin;
    }
  }, [playheadTime, pxPerSec, draggingPlayhead]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      setZoom((z) => Math.min(3, Math.max(0.4, z + (e.deltaY > 0 ? -0.1 : 0.1))));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  const playheadLeft = playheadTime * pxPerSec;
  const coverThumb =
    coverThumbProp || slots[0]?.template_thumbnail || slots[0]?.asset_thumbnail || '';
  const totalTracksHeight = activeTrackLayout.reduce((s, t) => s + t.height, 0);

  const clipWrapper = (
    layout: ClipLayout,
    track: TrackKey,
    index: number,
    total: number,
    render: (layout: ClipLayout, selected: boolean, clipWidth: number) => ReactNode
  ) => {
    if (!isTrackContentVisible(trackControls, track)) return null;
    const h = trackHeight(track) - CLIP_INSET * 2;
    const gapRight = index < total - 1 ? CLIP_GAP : 0;
    const clipWidth = Math.max(layout.width - gapRight, 20);
    return (
      <div
        key={`${layout.slot.id}-${track}`}
        data-clip
        className="absolute"
        style={{
          left: layout.left,
          width: clipWidth,
          top: CLIP_INSET,
          height: h,
        }}
      >
        {render(layout, layout.slot.id === selectedSlotId, clipWidth)}
      </div>
    );
  };

  const renderSubtitleSegment = (layout: SegmentLayout) => {
    if (!isTrackContentVisible(trackControls, 'subtitle')) return null;
    const locked = isTrackLocked(trackControls, 'subtitle');
    return (
      <div
        key={`${layout.slot.id}-${layout.start}-${layout.segment.text.slice(0, 8)}`}
        data-clip
        className="absolute"
        style={{
          left: layout.left,
          width: layout.width,
          top: CLIP_INSET,
          height: trackHeight('subtitle') - CLIP_INSET * 2,
        }}
      >
        <CapCutSubtitleClip
          text={layout.segment.text}
          accentColor={layout.segment.style?.text_color}
          selected={layout.slot.id === selectedSlotId}
          locked={locked}
          dimmed={isTrackMuted(trackControls, 'subtitle')}
          onClick={() => !locked && selectSlot(layout.slot.id)}
        />
      </div>
    );
  };

  const handleVideoDragOver = (e: DragEvent<HTMLDivElement>) => {
    if (isTrackLocked(trackControls, 'video')) return;
    const dt = e.dataTransfer;
    if (!dt || !canAcceptTimelineDrop(dt)) return;
    e.preventDefault();
    dt.dropEffect = 'copy';
    setDragOverVideo(true);
  };

  const forwardAssetDragOver = (e: DragEvent<HTMLDivElement>) => {
    if (isTrackLocked(trackControls, 'video')) return;
    const dt = e.dataTransfer;
    if (!dt || !canAcceptTimelineDrop(dt)) return;
    if (isFileDrag(dt) || isInternalAssetDrag(dt)) {
      e.preventDefault();
      dt.dropEffect = 'copy';
      setDragOverVideo(true);
    }
  };

  const forwardAssetDropToVideo = (e: DragEvent<HTMLDivElement>) => {
    const dt = e.dataTransfer;
    if (!canAcceptTimelineDrop(dt)) return;
    if (isFileDrag(dt) || isInternalAssetDrag(dt)) {
      handleVideoDrop(e);
    }
  };

  const handleVideoDragLeave = (e: DragEvent) => {
    const related = e.relatedTarget as Node | null;
    if (related && e.currentTarget.contains(related)) return;
    setDragOverVideo(false);
  };

  const handleVideoDrop = (
    e: DragEvent<HTMLDivElement>,
    preferredSlotId?: string | null
  ) => {
    if (isTrackLocked(trackControls, 'video')) {
      onTimelineDropHint?.('视频轨已锁定，请点击左侧轨道头解锁后再拖入素材');
      return;
    }
    e.preventDefault();
    setDragOverVideo(false);
    const time = timeFromClientX(e.clientX);
    void onTimelineDrop(e, time, preferredSlotId ?? null);
  };

  const handleOverlayDrop = (
    e: DragEvent<HTMLDivElement>,
    track: 'v2' | 'v3',
    laneKey?: TrackKey
  ) => {
    const lockKey = laneKey ?? (track === 'v2' ? 'overlay' : 'video2');
    if (isTrackLocked(trackControls, lockKey)) return;
    e.preventDefault();
    const raw =
      e.dataTransfer.getData('application/x-asset-id') ||
      e.dataTransfer.getData('text/plain');
    const assetId = raw.includes(':') ? raw.split(':', 2)[0] : raw;
    if (!assetId || !onOverlayDrop) return;
    const time = timeFromClientX(e.clientX);
    onOverlayDrop(track, time, assetId);
  };

  const renderOverlayClip = (
    clip: OverlayClip,
    trackKey: 'overlay' | 'sticker' | 'video2',
    selected: boolean
  ) => {
    const lockKey = trackKey;
    const locked = isTrackLocked(trackControls, lockKey);
    const thumb = clip.thumbnail || '';
    const overlayTrack = trackKey === 'video2' ? 'v3' : 'v2';
    return (
      <CapCutStickerClip
        thumb={thumb}
        label={clip.label || clip.assetId.slice(0, 8)}
        selected={selected}
        locked={locked}
        dimmed={isTrackMuted(trackControls, lockKey)}
        onClick={() => {
          if (locked) return;
          setSelectedOverlay({ track: overlayTrack, id: clip.id });
          setSelectedTrackKey(lockKey);
          setPlayhead(clip.dstIn);
        }}
      />
    );
  };

  const renderMetaPill = (
    trackKey: 'filter' | 'transition' | 'adjust',
    layout: ClipLayout,
    clipWidth: number,
    label: string,
    active: boolean
  ) => {
    const theme = TIMELINE_THEME.meta[trackKey === 'filter' ? 'filter' : trackKey === 'transition' ? 'transition' : 'adjust'];
    const locked = isTrackLocked(trackControls, trackKey);
    return (
      <div
        key={`${trackKey}-${layout.slot.id}`}
        data-clip
        className="absolute flex items-center justify-center overflow-hidden rounded-[2px] border text-[8px] font-medium"
        style={{
          left: layout.left,
          width: Math.max(clipWidth, 16),
          top: CLIP_INSET,
          height: trackHeight(trackKey) - CLIP_INSET * 2,
          backgroundColor: active ? theme.bg : '#1a1a1e',
          borderColor: active ? theme.border : '#2e2e2e',
          color: active ? theme.text : '#555',
          opacity: active ? 1 : 0.45,
        }}
        onClick={() => !locked && selectSlot(layout.slot.id)}
      >
        {active ? label : '—'}
      </div>
    );
  };

  const renderTransitionMarker = (layout: ClipLayout, index: number) => {
    if (index >= clipLayouts.length - 1) return null;
    const locked = isTrackLocked(trackControls, 'transition');
    const hasTransition = Boolean(layout.slot.transitionOut?.type);
    const joinLeft = layout.left + layout.width - CLIP_GAP / 2;
    return (
      <button
        key={`trans-${layout.slot.id}`}
        type="button"
        data-clip
        disabled={locked}
        onClick={() => !locked && selectSlot(layout.slot.id)}
        className="absolute z-[2] flex items-center justify-center"
        style={{
          left: joinLeft - 7,
          top: CLIP_INSET + 1,
          width: 14,
          height: trackHeight('transition') - CLIP_INSET * 2 - 2,
        }}
        title={hasTransition ? `转场：${layout.slot.transitionOut?.type}` : '无转场'}
      >
        <span
          className="block h-2.5 w-2.5 rotate-45 rounded-[1px] border"
          style={{
            backgroundColor: hasTransition ? TIMELINE_THEME.meta.transition.bg : '#1a1a1e',
            borderColor: hasTransition ? TIMELINE_THEME.meta.transition.border : '#333',
          }}
        />
      </button>
    );
  };

  const renderTrackContent = (trackKey: TrackKey): ReactNode => {
    switch (trackKey) {
      case 'video':
        return (
          <>
            {clipLayouts.map((layout, index) =>
              clipWrapper(layout, 'video', index, clipLayouts.length, (l, selected, clipWidth) => {
                const hasMatchedAsset = Boolean(
                  l.slot.matchedAssetId || l.slot.asset_file_path || l.slot.segment_file_path
                );
                const thumb =
                  l.slot.asset_thumbnail ||
                  l.slot.template_thumbnail ||
                  (l.slot.matchedAssetId ? assetMap[l.slot.matchedAssetId]?.thumbnail : '') ||
                  '';
                const segmentFile = l.slot.segment_file_path?.trim() || '';
                const videoSrc = hasMatchedAsset
                  ? segmentFile ||
                    l.slot.asset_file_path ||
                    (l.slot.matchedAssetId ? assetMap[l.slot.matchedAssetId]?.filePath : '') ||
                    ''
                  : templateVideoPath || '';
                const clipStart = segmentFile ? 0 : (l.slot.clipStart ?? 0);
                const locked = isTrackLocked(trackControls, 'video') || !!l.slot.locked;
                const tags = l.slot.ai_tags?.length
                  ? l.slot.ai_tags.map((t) => (t.startsWith('#') ? t : `#${t}`)).join(' ')
                  : l.slot.ai_description
                    ? `#${l.slot.ai_description}`
                    : l.slot.scene_tags?.length
                      ? l.slot.scene_tags.map((t) => (t.startsWith('#') ? t : `#${t}`)).join(' ')
                      : '';
                const title =
                  l.slot.ai_description ||
                  (l.slot.matchedAssetId && assetMap[l.slot.matchedAssetId]?.title) ||
                  l.slot.name;

                return (
                  <CapCutVideoClip
                    slotId={l.slot.id}
                    thumb={thumb}
                    videoSrc={videoSrc}
                    clipStart={clipStart}
                    title={title}
                    tags={tags}
                    duration={l.slot.duration}
                    width={clipWidth}
                    selected={selected}
                    locked={locked}
                    dimmed={isTrackMuted(trackControls, 'video')}
                    pxPerSec={pxPerSec}
                    onTrimStart={(deltaPx, pps) => onTrimSlot?.(l.slot.id, 'start', deltaPx / pps)}
                    onTrimEnd={(deltaPx, pps) => onTrimSlot?.(l.slot.id, 'end', deltaPx / pps)}
                    onClick={() => !locked && selectSlot(l.slot.id)}
                    onSlotReorderDragStart={onReorderSlots ? handleSlotReorderDragStart : undefined}
                    onSlotReorderDrop={onReorderSlots ? handleSlotReorderDrop : undefined}
                    onDragOver={(e) => {
                      if (!locked) handleVideoDragOver(e);
                    }}
                    onDrop={(e) => {
                      if (locked) {
                        e.preventDefault();
                        onTimelineDropHint?.('该槽位已锁定，请在属性面板取消锁定后再拖入素材');
                        return;
                      }
                      e.stopPropagation();
                      setDragOverVideo(false);
                      handleVideoDrop(e, l.slot.id);
                    }}
                  />
                );
              })
            )}
            {clipLayouts.length > 1
              ? clipLayouts.slice(1).map((layout) => (
                  <div
                    key={`join-${layout.slot.id}`}
                    className="pointer-events-none absolute top-0 z-[3] w-px bg-[#face15]/25"
                    style={{
                      left: layout.left,
                      height: trackHeight('video'),
                    }}
                  />
                ))
              : null}
          </>
        );

      case 'overlay':
            return (
          <>
            {v2Layouts.length === 0 && slots.length > 0 ? (
              <LaneDropHint text="拖入素材到特效轨" />
            ) : null}
            {v2Layouts.map(({ clip, left, width }) => (
              <div
                key={clip.id}
                data-clip
                className="absolute"
                style={{
                  left,
                  width,
                  top: CLIP_INSET,
                  height: trackHeight('overlay') - CLIP_INSET * 2,
                }}
              >
                {renderOverlayClip(
                  clip,
                  'overlay',
                  selectedOverlay?.track === 'v2' && selectedOverlay.id === clip.id
                  )}
                </div>
            ))}
          </>
        );

      case 'sticker':
        return (
          <>
            {v2Layouts.length === 0 && slots.length > 0 ? (
              <LaneDropHint text="拖入素材添加贴纸" />
            ) : null}
            {v2Layouts.map(({ clip, left, width }) => (
              <div
                key={`st-${clip.id}`}
                data-clip
                className="absolute"
                style={{
                  left,
                  width,
                  top: CLIP_INSET,
                  height: trackHeight('sticker') - CLIP_INSET * 2,
                }}
              >
                {renderOverlayClip(
                  clip,
                  'sticker',
                  selectedOverlay?.track === 'v2' && selectedOverlay.id === clip.id
                )}
                </div>
            ))}
          </>
        );

      case 'video2':
        return (
          <>
            {v3Layouts.length === 0 && slots.length > 0 ? (
              <LaneDropHint text="拖入素材到画中画轨" />
                ) : null}
            {v3Layouts.map(({ clip, left, width }) => (
              <div
                key={clip.id}
                data-clip
                className="absolute"
                style={{
                  left,
                  width,
                  top: CLIP_INSET,
                  height: trackHeight('video2') - CLIP_INSET * 2,
                }}
              >
                {renderOverlayClip(
                  clip,
                  'video2',
                  selectedOverlay?.track === 'v3' && selectedOverlay.id === clip.id
                )}
              </div>
            ))}
          </>
        );

      case 'filter':
        return slots.length > 0
          ? clipLayouts.map((layout, index) => {
              const gapRight = index < clipLayouts.length - 1 ? CLIP_GAP : 0;
              const clipWidth = Math.max(layout.width - gapRight, 16);
              const active = hasActiveColorGrade(layout.slot.colorGrade) || hasActiveMask(layout.slot.mask);
              return renderMetaPill(
                'filter',
                layout,
                clipWidth,
                filterLabelForSlot(layout.slot),
                active
              );
            })
          : null;

      case 'transition':
        return slots.length > 0
          ? clipLayouts.map((layout, index) => {
              const marker = renderTransitionMarker(layout, index);
              const trans = layout.slot.transitionOut;
              if (!trans?.type || index >= clipLayouts.length - 1) return marker;
              const dur = Math.max(0.1, trans.duration || 0.5);
              const joinLeft = layout.left + layout.width - CLIP_GAP / 2;
              const w = Math.max(dur * pxPerSec, 12);
              return (
                <span key={`trans-wrap-${layout.slot.id}`}>
                  {marker}
                  <button
                    type="button"
                    data-clip
                    className="absolute z-[1] flex items-center justify-center overflow-hidden rounded-[2px] border text-[7px] font-medium"
                    style={{
                      left: joinLeft - w,
                      width: w,
                      top: CLIP_INSET,
                      height: trackHeight('transition') - CLIP_INSET * 2,
                      backgroundColor: TIMELINE_THEME.meta.transition.bg,
                      borderColor: TIMELINE_THEME.meta.transition.border,
                      color: TIMELINE_THEME.meta.transition.text,
                    }}
                    title={`转场 ${trans.type}`}
                    disabled={isTrackLocked(trackControls, 'transition')}
                    onClick={() => selectSlot(layout.slot.id)}
                  >
                    {trans.type.slice(0, 6)}
                  </button>
                </span>
              );
            })
          : null;

      case 'adjust':
        return slots.length > 0
          ? clipLayouts.map((layout, index) => {
              const gapRight = index < clipLayouts.length - 1 ? CLIP_GAP : 0;
              const clipWidth = Math.max(layout.width - gapRight, 16);
              const active = hasActiveAdjust(layout.slot);
              return renderMetaPill(
                'adjust',
                layout,
                clipWidth,
                adjustLabelForSlot(layout.slot),
                active
              );
            })
          : null;

      case 'subtitle':
        return subtitleLayouts.length > 0 ? (
          subtitleLayouts.map(renderSubtitleSegment)
        ) : slots.length > 0 ? (
          <LaneDropHint text="在「字幕」侧栏或属性面板编辑字幕" />
        ) : null;

      case 'audio':
        return slots.length > 0 ? (
          <>
            {beatMarkers.map((t, i) => (
              <div
                key={`audio-beat-${i}-${t}`}
                className="pointer-events-none absolute top-0 z-[2] w-px bg-[#face15]/35"
                style={{
                  left: t * pxPerSec,
                  height: trackHeight('audio'),
                }}
              />
            ))}
            {sfxMarkers.map((marker, i) => (
              <div
                key={`audio-sfx-${i}-${marker.time}`}
                title={describeSfxMarker(marker)}
                className="pointer-events-none absolute top-1 z-[3] h-2 w-2 -translate-x-1/2 rotate-45 bg-[#f97316] shadow-[0_0_6px_rgba(249,115,22,0.8)]"
                style={{ left: marker.time * pxPerSec }}
              />
            ))}
            <div
              data-clip
              className="absolute"
              style={{
                left: CLIP_INSET,
                width: Math.max(totalDuration * pxPerSec - CLIP_INSET * 2, 48),
                top: CLIP_INSET,
                height: trackHeight('audio') - CLIP_INSET * 2,
              }}
            >
              <CapCutAudioClip
                seed="template-bgm"
                width={Math.max(totalDuration * pxPerSec - CLIP_INSET * 2, 48)}
                peaks={templateWaveform.length ? templateWaveform : undefined}
                label={templateMusicEnabled ? '模板音乐' : '音乐已关'}
                selected={selectedTrackKey === 'audio'}
                locked={isTrackLocked(trackControls, 'audio')}
                dimmed={trackControls.audio.muted || !templateMusicEnabled}
                onClick={() => setSelectedTrackKey('audio')}
              />
            </div>
          </>
        ) : (
          <LaneDropHint text="导入模板后显示 BGM 轨" />
        );

      case 'audioVoice':
        return clipLayouts.map((layout, index) =>
          clipWrapper(layout, 'audioVoice', index, clipLayouts.length, (l, selected, clipWidth) => {
            const locked = isTrackLocked(trackControls, 'audioVoice');
            const audible = Boolean(l.slot.matchedAssetId) && l.slot.useOriginalAudio;
            const voicePeaks =
              templateWaveform.length > 0
                ? sliceWaveformPeaks(templateWaveform, totalDuration, l.start, l.end)
                : undefined;
            return (
              <CapCutAudioClip
                seed={l.slot.id + '-voice'}
                width={clipWidth}
                peaks={voicePeaks}
                label={audible ? '素材原声' : '原声关'}
                selected={selected}
                locked={locked}
                dimmed={!audible || trackControls.audioVoice.muted}
                onClick={() => !locked && selectSlot(l.slot.id)}
              />
            );
          })
        );

      default:
        return null;
    }
  };

  const trackDropHandler = (trackKey: TrackKey): ((e: DragEvent<HTMLDivElement>) => void) | undefined => {
    if (trackKey === 'overlay') {
      return (e) => handleOverlayDrop(e, 'v2', 'overlay');
    }
    if (trackKey === 'sticker') {
      return (e) => handleOverlayDrop(e, 'v2', 'sticker');
    }
    if (trackKey === 'video2') {
      return (e) => handleOverlayDrop(e, 'v3', 'video2');
    }
    return undefined;
  };

  const handleToolbarDelete = () => {
    if (selectedOverlay && onOverlayDelete) {
      const lockKey = selectedOverlay.track === 'v2' ? 'overlay' : 'video2';
      if (isTrackLocked(trackControls, lockKey)) return;
      onOverlayDelete(selectedOverlay.track, selectedOverlay.id);
      setSelectedOverlay(null);
      return;
    }
    if (selectedSlotId && onDeleteSlot) {
      onDeleteSlot(selectedSlotId);
    }
  };

  const renderTrackLane = (
    trackKey: TrackKey,
    label: string,
    content: ReactNode,
    dropHandler?: (e: DragEvent<HTMLDivElement>) => void,
    isLast = false
  ) => {
    const height = trackHeight(trackKey);
    const selected = selectedTrackKey === trackKey;
    const ctrl = trackControls[trackKey];
    const isVideo = trackKey === 'video';

    if (!ctrl.visible) {
      return (
        <div className="group relative shrink-0" style={{ height }}>
          <HiddenTrackHint label={label} selected={selected} />
          {onTrackHeightChange ? (
            <TrackResizeHandle
              onResizeStart={(e) => beginTrackResize(trackKey, e)}
              onResizeReset={() => resetTrackHeight(trackKey)}
            />
          ) : null}
        </div>
      );
    }
    if (!isTrackContentVisible(trackControls, trackKey)) {
      return (
        <div className="group relative shrink-0" style={{ height }}>
          <SoloFilteredHint selected={selected} />
          {onTrackHeightChange ? (
            <TrackResizeHandle
              onResizeStart={(e) => beginTrackResize(trackKey, e)}
              onResizeReset={() => resetTrackHeight(trackKey)}
            />
          ) : null}
        </div>
      );
    }

    const laneLocked = ctrl.locked;
    const laneMuted = isTrackMuted(trackControls, trackKey);
    const forwardsAssetDrop =
      !isVideo && trackKey !== 'overlay' && trackKey !== 'video2' && trackKey !== 'sticker';

    return (
      <div className="group relative shrink-0" style={{ height }}>
        <div
          className={trackLaneClass(selected, isLast ? 'border-b-0' : undefined)}
          style={{ height: '100%', borderColor: TIMELINE_THEME.border, ...gridStyle }}
          onMouseDown={(e) => handleTrackBgMouseDown(e, trackKey)}
          onDragOver={
            isVideo
              ? handleVideoDragOver
              : forwardsAssetDrop
                ? forwardAssetDragOver
                : dropHandler
                  ? (e) => {
                      e.preventDefault();
                      e.dataTransfer.dropEffect = 'copy';
                    }
                  : undefined
          }
          onDragLeave={isVideo ? handleVideoDragLeave : undefined}
          onDrop={
            isVideo
              ? (e) => {
                  if ((e.target as HTMLElement).closest('[data-clip]')) return;
                  handleVideoDrop(e);
                }
              : forwardsAssetDrop
                ? forwardAssetDropToVideo
                : dropHandler
          }
        >
          {selected ? (
            <div className="pointer-events-none absolute inset-y-0 left-0 z-[6] w-[2px] bg-[#face15]" />
          ) : null}
          {laneLocked ? (
            <div className="pointer-events-none absolute inset-0 z-[5] bg-[repeating-linear-gradient(-45deg,transparent,transparent_6px,rgba(255,179,0,0.05)_6px,rgba(255,179,0,0.05)_12px)]" />
          ) : null}
          {laneMuted ? (
            <div className="pointer-events-none absolute inset-0 z-[5] bg-black/25" />
          ) : null}
          {isVideo && slots.length === 0 ? (
            <div
              className={`pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center border-2 border-dashed transition-colors ${
                dragOverVideo
                  ? 'border-[#face15] bg-[#face15]/10'
                  : 'border-[#3a3a3c] bg-[#1c1c1e]/80'
              }`}
            >
              <span className="text-xs text-[#e5e5ea]">
                {dragOverVideo ? '松手导入模板视频' : '拖入模板视频以开始'}
              </span>
              <span className="mt-1 text-[10px] text-[#8e8e93]">
                支持 mp4 / mov / mkv 等格式
              </span>
                </div>
          ) : null}
          {isVideo && slots.length > 0 && dragOverVideo ? (
            <div className="pointer-events-none absolute inset-0 z-10 border-2 border-dashed border-[#face15] bg-[#face15]/8" />
          ) : null}
          {isVideo && loading ? (
            <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center bg-black/40 text-xs text-[#face15]">
              上传处理中…
            </div>
          ) : null}
          {content}
          </div>
        {onTrackHeightChange ? (
          <TrackResizeHandle
            onResizeStart={(e) => beginTrackResize(trackKey, e)}
            onResizeReset={() => resetTrackHeight(trackKey)}
          />
        ) : null}
                  </div>
    );
  };

  return (
    <section
      className="flex h-full min-h-0 flex-col select-none"
      style={{ backgroundColor: TIMELINE_THEME.bg }}
    >
      <TimelineToolbar
        isPlaying={isPlaying}
        canUndo={canUndo}
        canRedo={canRedo}
        canSplit={slots.length > 0}
        magnet={magnet}
        playheadTime={playheadTime}
        totalDuration={totalDuration}
        zoom={zoom}
        trackControls={trackControls}
        onTogglePlay={onTogglePlay}
        onUndo={onUndo}
        onRedo={onRedo}
        onSplit={onSplit}
        onDelete={handleToolbarDelete}
        canDelete={
          !!selectedOverlay ||
          (!!selectedSlotId && slots.length > 0 && !isTrackLocked(trackControls, 'video'))
        }
        onToggleMagnet={() => setMagnet((v) => !v)}
        onZoomChange={setZoom}
      />

      <div className="flex min-h-0 flex-1">
        <TrackHeaderPanel
          tracks={activeTrackLayout}
          trackControls={trackControls}
          selectedTrackKey={selectedTrackKey}
          coverThumb={coverThumb}
          lanesScrollRef={scrollRef}
          onCoverClick={onCoverClick}
          statusMessage={trackControlMessage}
          onSelectTrack={setSelectedTrackKey}
          onTrackControlToggle={onTrackControlToggle}
          addableTracks={addableTracks}
          onAddTrack={handleAddTrack}
          onTrackResizeStart={onTrackHeightChange ? beginTrackResize : undefined}
          onTrackResizeReset={onTrackHeightChange ? resetTrackHeight : undefined}
        />

        <div ref={scrollRef} className="timeline-scroll relative min-w-0 flex-1 overflow-x-auto overflow-y-auto">
          <div className="relative min-h-full" style={{ width: contentWidth, minWidth: '100%' }}>
            <TimelineRuler
              pxPerSec={pxPerSec}
              totalDuration={displayDuration}
              tickStep={tickStep}
              onSeek={seekTo}
              onScrubStart={(clientX) => beginScrub(clientX)}
            />

            {activeTrackLayout.map(({ key, label, group }, index) => {
              const prev = activeTrackLayout[index - 1];
              const showGroupGap = prev?.group && group && prev.group !== group;
              return (
                <div key={key}>
                  {showGroupGap ? (
                    <div
                      className="h-px shrink-0"
                      style={{ backgroundColor: TIMELINE_THEME.borderLight }}
                    />
                  ) : null}
                  {renderTrackLane(
                    key,
                    label,
                    renderTrackContent(key),
                    trackDropHandler(key),
                    index === activeTrackLayout.length - 1
                  )}
                </div>
              );
            })}

            {beatMarkers.length > 0
              ? beatMarkers.map((t, i) => (
                  <div
                    key={`beat-${i}-${t}`}
                    className="pointer-events-none absolute top-0 z-[4] w-px"
                    style={{
                      left: t * pxPerSec,
                      height: RULER_H + totalTracksHeight,
                      background:
                        'linear-gradient(to bottom, rgba(250,206,21,0.55) 0%, rgba(250,206,21,0.15) 100%)',
                    }}
                  />
                ))
              : null}

            <TimelinePlayhead
              left={playheadLeft}
              height={RULER_H + totalTracksHeight}
              onScrubStart={(clientX) => beginScrub(clientX)}
              onScrubMove={moveScrub}
              onScrubEnd={endScrub}
            />
          </div>
        </div>
      </div>
    </section>
  );
}
