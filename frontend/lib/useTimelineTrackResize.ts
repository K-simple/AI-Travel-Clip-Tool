import { useCallback } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import { clampTrackHeight } from '@/lib/trackHeights';
import type { TrackKey } from '@/lib/trackControls';
import { getTrackDef } from '@/lib/timelineTracks';

type UseTimelineTrackResizeOptions = {
  activeTrackLayout: Array<{ key: TrackKey; height: number }>;
  onTrackHeightChange?: (key: TrackKey, height: number | null) => void;
};

export function useTimelineTrackResize({
  activeTrackLayout,
  onTrackHeightChange,
}: UseTimelineTrackResizeOptions) {
  const trackHeight = useCallback(
    (key: TrackKey) =>
      activeTrackLayout.find((t) => t.key === key)?.height ?? getTrackDef(key)?.height ?? 32,
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

  return { trackHeight, beginTrackResize, resetTrackHeight };
}
