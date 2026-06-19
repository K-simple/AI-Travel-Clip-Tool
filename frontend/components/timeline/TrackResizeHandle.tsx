'use client';

import type { PointerEvent as ReactPointerEvent } from 'react';

type TrackResizeHandleProps = {
  onResizeStart: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onResizeReset?: () => void;
};

export function TrackResizeHandle({ onResizeStart, onResizeReset }: TrackResizeHandleProps) {
  return (
    <div
      role="separator"
      aria-orientation="horizontal"
      title="拖动调整轨道高度，双击恢复默认"
      className="absolute bottom-0 left-0 right-0 z-30 h-2 -translate-y-1/2 cursor-ns-resize"
      onPointerDown={onResizeStart}
      onDoubleClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onResizeReset?.();
      }}
    >
      <div className="pointer-events-none absolute inset-x-1 top-1/2 h-[2px] -translate-y-1/2 rounded-full bg-[#face15]/0 transition-colors group-hover:bg-[#face15]/50 hover:bg-[#face15]" />
    </div>
  );
}
