'use client';

import type { MouseEvent as ReactMouseEvent } from 'react';
import { formatTimecode } from '@/lib/timelineLayout';
import { RULER_H, TIMELINE_THEME } from './timelineTheme';

type TimelineRulerProps = {
  pxPerSec: number;
  totalDuration: number;
  tickStep: number;
  onSeek: (clientX: number) => void;
  onScrubStart?: (clientX: number) => void;
};

export function TimelineRuler({
  pxPerSec,
  totalDuration,
  tickStep,
  onSeek,
  onScrubStart,
}: TimelineRulerProps) {
  const tickCount = Math.ceil(totalDuration / tickStep) + 2;

  const handleMouseDown = (e: ReactMouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (onScrubStart) onScrubStart(e.clientX);
    else onSeek(e.clientX);
  };

  return (
    <div
      className="relative cursor-pointer select-none"
      data-timeline-ruler
      style={{
        height: RULER_H,
        backgroundColor: TIMELINE_THEME.rulerBg,
        borderBottom: `1px solid ${TIMELINE_THEME.border}`,
      }}
      onMouseDown={handleMouseDown}
    >
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage: [
            `linear-gradient(to right, rgba(255,255,255,0.025) 1px, transparent 1px)`,
            `linear-gradient(to right, rgba(255,255,255,0.06) 1px, transparent 1px)`,
          ].join(', '),
          backgroundSize: `${pxPerSec}px 100%, ${pxPerSec * 5}px 100%`,
        }}
      />

      {Array.from({ length: tickCount }).map((_, i) => {
        const t = i * tickStep;
        const isMajor = t % 10 === 0;
        const isMid = !isMajor && t % 5 === 0;
        const left = t * pxPerSec;

        return (
          <div key={i} className="pointer-events-none absolute top-0" style={{ left, height: '100%' }}>
            <div
              className="w-px"
              style={{
                height: isMajor ? '50%' : isMid ? '35%' : '22%',
                marginTop: isMajor ? '50%' : isMid ? '65%' : '78%',
                backgroundColor: isMajor ? '#5a5a5e' : isMid ? '#3a3a3e' : '#2a2a2e',
              }}
            />
            {isMajor && t <= totalDuration ? (
              <span
                className="absolute left-1 top-[3px] font-mono text-[9px] tabular-nums text-[#6e6e72]"
                style={{ transform: 'translateX(-1px)' }}
              >
                {formatTimecode(t)}
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
