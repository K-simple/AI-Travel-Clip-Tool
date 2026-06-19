'use client';

import { useCallback, type PointerEvent as ReactPointerEvent } from 'react';

type PanelSplitterProps = {
  orientation: 'horizontal' | 'vertical';
  ariaValueNow?: number;
  title?: string;
  className?: string;
  onResizeStart?: () => void;
  onResize: (delta: number) => void;
  onResizeEnd?: () => void;
  onReset?: () => void;
};

export function PanelSplitter({
  orientation,
  ariaValueNow,
  title,
  className = '',
  onResizeStart,
  onResize,
  onResizeEnd,
  onReset,
}: PanelSplitterProps) {
  const isHorizontal = orientation === 'horizontal';

  const beginResize = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      onResizeStart?.();
      const startX = event.clientX;
      const startY = event.clientY;
      const handle = event.currentTarget;
      const pointerId = event.pointerId;
      handle.setPointerCapture(pointerId);

      const onMove = (ev: PointerEvent) => {
        const delta = isHorizontal ? ev.clientY - startY : ev.clientX - startX;
        onResize(delta);
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
        onResizeEnd?.();
      };

      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
      window.addEventListener('pointercancel', onUp);
    },
    [isHorizontal, onResize, onResizeEnd, onResizeStart]
  );

  return (
    <div
      role="separator"
      aria-orientation={orientation}
      aria-valuenow={ariaValueNow}
      title={title}
      className={`group relative z-30 shrink-0 ${
        isHorizontal
          ? 'flex h-2 cursor-ns-resize items-center justify-center border-t border-[#2a2a2e] bg-[#121214] hover:bg-[#1a1a1e]'
          : 'flex w-1.5 cursor-ew-resize items-center justify-center border-l border-[#2a2a2e] bg-[#121214] hover:bg-[#1a1a1e]'
      } ${className}`}
      onPointerDown={beginResize}
      onDoubleClick={(e) => {
        e.preventDefault();
        onReset?.();
      }}
    >
      <div
        className={`rounded-full bg-[#3a3a3e] transition-colors group-hover:bg-[#face15]/80 ${
          isHorizontal ? 'h-1 w-16' : 'h-16 w-1'
        }`}
      />
    </div>
  );
}
