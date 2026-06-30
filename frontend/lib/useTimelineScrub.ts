import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type RefObject,
} from 'react';
import {
  findClipAtTime,
  isNearPlayheadX,
  snapTime,
  type ClipLayout,
  type SegmentLayout,
} from '@/lib/timelineLayout';
import type { TrackKey } from '@/lib/trackControls';

type UseTimelineScrubOptions = {
  scrollRef: RefObject<HTMLDivElement | null>;
  pxPerSec: number;
  clipLayouts: ClipLayout[];
  subtitleLayouts: SegmentLayout[];
  magnet: boolean;
  scrubMaxDuration: number;
  totalDuration: number;
  slotsLength: number;
  controlledPlayhead?: number;
  onPlayheadChange?: (time: number) => void;
  onScrubStart?: () => void;
  onSlotSelect: (slotId: string) => void;
  setSelectedTrackKey: (key: TrackKey | null) => void;
};

export function useTimelineScrub({
  scrollRef,
  pxPerSec,
  clipLayouts,
  subtitleLayouts,
  magnet,
  scrubMaxDuration,
  totalDuration,
  slotsLength,
  controlledPlayhead,
  onPlayheadChange,
  onScrubStart,
  onSlotSelect,
  setSelectedTrackKey,
}: UseTimelineScrubOptions) {
  const [internalPlayhead, setInternalPlayhead] = useState(0);
  const [draggingPlayhead, setDraggingPlayhead] = useState(false);
  const scrubMovedRef = useRef(false);
  const pendingScrubRef = useRef<{ startX: number; active: boolean } | null>(null);

  const playheadTime = controlledPlayhead ?? internalPlayhead;

  const setPlayhead = useCallback(
    (t: number) => {
      if (onPlayheadChange) onPlayheadChange(t);
      else setInternalPlayhead(t);
    },
    [onPlayheadChange]
  );

  const selectSlot = useCallback(
    (slotId: string, opts?: { force?: boolean }) => {
      if (!opts?.force && scrubMovedRef.current) {
        scrubMovedRef.current = false;
        return;
      }
      onSlotSelect(slotId);
    },
    [onSlotSelect]
  );

  const timeFromClientX = useCallback(
    (clientX: number) => {
      const el = scrollRef.current;
      if (!el) return 0;
      const rect = el.getBoundingClientRect();
      const x = clientX - rect.left + el.scrollLeft;
      return snapTime(x / pxPerSec, clipLayouts, magnet, subtitleLayouts);
    },
    [scrollRef, pxPerSec, clipLayouts, magnet, subtitleLayouts]
  );

  const scrubAtClientX = useCallback(
    (clientX: number, options?: { selectSlot?: boolean }) => {
      const el = scrollRef.current;
      if (el) {
        const rect = el.getBoundingClientRect();
        const edge = 56;
        if (clientX < rect.left + edge) {
          el.scrollLeft = Math.max(
            0,
            el.scrollLeft - Math.max(8, Math.ceil((rect.left + edge - clientX) / 3))
          );
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
    [scrollRef, timeFromClientX, scrubMaxDuration, setPlayhead, clipLayouts, selectSlot]
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
    [onScrubStart, scrubAtClientX, setSelectedTrackKey]
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

  const handleTrackBgMouseDown = useCallback(
    (e: ReactMouseEvent, trackKey: TrackKey) => {
      if (e.button !== 0) return;
      if ((e.target as HTMLElement).closest('[data-trim-handle]')) return;
      const onClip = (e.target as HTMLElement).closest('[data-clip]');
      const el = scrollRef.current;
      if (onClip && el && !isNearPlayheadX(e.clientX, el, playheadTime, pxPerSec)) {
        return;
      }
      e.preventDefault();
      beginScrub(e.clientX, trackKey);
    },
    [scrollRef, playheadTime, pxPerSec, beginScrub]
  );

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
  }, [scrollRef, playheadTime, pxPerSec, beginScrub]);

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
  }, [scrollRef, beginScrub, moveScrub, endScrub]);

  useEffect(() => {
    const max = slotsLength > 0 ? totalDuration : scrubMaxDuration;
    if (playheadTime > max) setPlayhead(max);
  }, [totalDuration, scrubMaxDuration, playheadTime, slotsLength, setPlayhead]);

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
  }, [scrollRef, playheadTime, pxPerSec, draggingPlayhead]);

  return {
    playheadTime,
    draggingPlayhead,
    playheadLeft: playheadTime * pxPerSec,
    selectSlot,
    seekTo,
    beginScrub,
    moveScrub,
    endScrub,
    handleTrackBgMouseDown,
    timeFromClientX,
    setPlayhead,
  };
}
