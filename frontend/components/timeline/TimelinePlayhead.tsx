'use client';

import type { PointerEvent as ReactPointerEvent } from 'react';
import { RULER_H } from './timelineTheme';

type TimelinePlayheadProps = {
  left: number;
  height: number;
  onScrubStart: (clientX: number) => void;
  onScrubMove: (clientX: number) => void;
  onScrubEnd: () => void;
};

const HIT_WIDTH = 28;

/** 剪映风格播放头：整根竖线均可拖动（pointer capture 保证拖出热区仍有效） */
export function TimelinePlayhead({
  left,
  height,
  onScrubStart,
  onScrubMove,
  onScrubEnd,
}: TimelinePlayheadProps) {
  const handlePointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const el = e.currentTarget;
    el.setPointerCapture(e.pointerId);
    onScrubStart(e.clientX);
  };

  const handlePointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!e.currentTarget.hasPointerCapture(e.pointerId)) return;
    e.preventDefault();
    onScrubMove(e.clientX);
  };

  const endDrag = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    onScrubEnd();
  };

  return (
    <div
      data-playhead
      className="absolute top-0 z-[200] cursor-ew-resize select-none touch-none"
      style={{ left: left - HIT_WIDTH / 2, width: HIT_WIDTH, height }}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      title="拖动播放头 · 逐帧预览"
    >
      <div
        className="pointer-events-none absolute left-1/2 top-0 -translate-x-1/2 flex flex-col items-center"
        style={{ width: 14, height: RULER_H }}
      >
        <svg width="14" height="11" viewBox="0 0 14 11" className="drop-shadow-[0_1px_3px_rgba(0,0,0,0.5)]">
          <path d="M1 0h12L7 10z" fill="#ffffff" />
          <path d="M5.5 0h3L7 7.5z" fill="rgba(0,0,0,0.08)" />
        </svg>
      </div>

      <div
        className="pointer-events-none absolute left-1/2 top-0 -translate-x-1/2 w-0.5"
        style={{
          height,
          background:
            'linear-gradient(to bottom, #ffffff 0%, rgba(255,255,255,0.92) 60%, rgba(255,255,255,0.75) 100%)',
          boxShadow: '0 0 6px rgba(255,255,255,0.25), 0 0 1px rgba(255,255,255,0.8)',
        }}
      />
    </div>
  );
}
