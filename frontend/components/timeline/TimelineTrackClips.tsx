'use client';

import type { DragEvent, MouseEvent as ReactMouseEvent } from 'react';
import { toMediaUrl } from '@/lib/api';
import { pseudoWaveform } from '@/lib/timelineLayout';
import { ClipFilmstrip } from '@/components/timeline/ClipFilmstrip';
import { TIMELINE_THEME } from './timelineTheme';

function cn(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ');
}

function ClipTrimHandles({
  selected,
  onTrimStart,
  onTrimEnd,
  pxPerSec = 48,
}: {
  selected: boolean;
  onTrimStart?: (deltaPx: number, pxPerSec: number) => void;
  onTrimEnd?: (deltaPx: number, pxPerSec: number) => void;
  pxPerSec?: number;
}) {
  if (!selected) return null;

  const startDrag = (side: 'left' | 'right', e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    const startX = e.clientX;
    let lastDelta = 0;
    const move = (ev: MouseEvent) => {
      lastDelta = ev.clientX - startX;
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
      if (Math.abs(lastDelta) < 2) return;
      if (side === 'left') onTrimStart?.(lastDelta, pxPerSec);
      else onTrimEnd?.(lastDelta, pxPerSec);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };

  return (
    <>
      <div
        className="absolute bottom-0 left-0 top-0 z-20 w-[4px] cursor-ew-resize rounded-l-[2px] border-r border-[#face15]/60 bg-white/95 shadow-[inset_0_0_0_1px_rgba(250,206,21,0.5)]"
        data-trim-handle
        onMouseDown={(e) => startDrag('left', e)}
      />
      <div
        className="absolute bottom-0 right-0 top-0 z-20 w-[4px] cursor-ew-resize rounded-r-[2px] border-l border-[#face15]/60 bg-white/95 shadow-[inset_0_0_0_1px_rgba(250,206,21,0.5)]"
        data-trim-handle
        onMouseDown={(e) => startDrag('right', e)}
      />
    </>
  );
}

export function CapCutSubtitleIcon() {
  return (
    <span className="mr-1 inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-[2px] bg-black/25 text-[8px] font-bold leading-none text-white">
      T
    </span>
  );
}

export function CapCutStickerIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" className="mr-1 shrink-0 text-[#86efac]">
      <path d="M12 2l2.4 7.4H22l-6 4.6 2.3 7L12 17.8 5.7 21.2 8 14 2 9.4h7.6L12 2z" fill="currentColor" />
    </svg>
  );
}

export function CapCutWaveform({
  seed,
  width,
  dimmed,
  peaks,
}: {
  seed: string;
  width: number;
  dimmed?: boolean;
  peaks?: number[];
}) {
  const bars =
    peaks && peaks.length > 0
      ? peaks
      : pseudoWaveform(seed, Math.max(20, Math.floor(width / 2.5)));
  const color = dimmed ? TIMELINE_THEME.audio.waveDim : TIMELINE_THEME.audio.wave;

  return (
    <div className="flex h-full w-full items-center gap-px px-0.5 py-1">
      {bars.map((h, i) => {
        const barH = Math.max(18, h * 88);
        return (
          <div key={i} className="flex flex-1 flex-col items-center justify-center" style={{ minWidth: 1.5 }}>
            <div
              className="w-full rounded-[1px]"
              style={{
                height: `${barH / 2}%`,
                backgroundColor: color,
                opacity: dimmed ? 0.35 : 0.88,
              }}
            />
            <div
              className="w-full rounded-[1px]"
              style={{
                height: `${barH / 2}%`,
                backgroundColor: color,
                opacity: dimmed ? 0.35 : 0.88,
              }}
            />
          </div>
        );
      })}
    </div>
  );
}

type VideoClipProps = {
  thumb: string;
  videoSrc?: string;
  clipStart?: number;
  title: string;
  tags: string;
  duration: number;
  width: number;
  selected: boolean;
  locked: boolean;
  dimmed?: boolean;
  onClick: () => void;
  onTrimStart?: (deltaPx: number, pxPerSec: number) => void;
  onTrimEnd?: (deltaPx: number, pxPerSec: number) => void;
  pxPerSec?: number;
  onDragOver?: (e: DragEvent<HTMLDivElement>) => void;
  onDrop?: (e: DragEvent<HTMLDivElement>) => void;
  slotId?: string;
  onSlotReorderDragStart?: (e: DragEvent<HTMLDivElement>, slotId: string) => void;
  onSlotReorderDrop?: (e: DragEvent<HTMLDivElement>, targetSlotId: string) => void;
};

export function CapCutVideoClip({
  thumb,
  videoSrc = '',
  clipStart = 0,
  title,
  tags,
  duration,
  width,
  selected,
  locked,
  dimmed,
  onClick,
  onTrimStart,
  onTrimEnd,
  pxPerSec = 48,
  onDragOver,
  onDrop,
  slotId,
  onSlotReorderDragStart,
  onSlotReorderDrop,
}: VideoClipProps) {
  const label = tags || title;
  const safeDuration = Math.max(duration, 0.5);

  const renderBody = () => {
    if (videoSrc) {
      return (
        <ClipFilmstrip
          videoSrc={videoSrc}
          clipStart={clipStart}
          duration={safeDuration}
          width={width}
          pxPerSec={pxPerSec}
          fallbackThumb={thumb}
        />
      );
    }

    if (thumb) {
      return (
        <div
          className="h-full w-full bg-cover bg-left bg-no-repeat"
          style={{ backgroundImage: `url(${toMediaUrl(thumb)})` }}
        />
      );
    }

    return (
      <div className="flex h-full w-full items-center justify-center bg-[#0f1f1a] text-[9px] text-white/40">
        拖入素材
      </div>
    );
  };

  return (
    <div
      onClick={onClick}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes('application/x-slot-reorder')) {
          e.preventDefault();
          e.dataTransfer.dropEffect = 'move';
        }
        onDragOver?.(e);
      }}
      onDrop={(e) => {
        if (e.dataTransfer.types.includes('application/x-slot-reorder') && slotId) {
          e.preventDefault();
          e.stopPropagation();
          onSlotReorderDrop?.(e, slotId);
          return;
        }
        onDrop?.(e);
      }}
      className={cn(
        'relative h-full overflow-hidden rounded-[3px]',
        locked ? 'cursor-not-allowed opacity-45' : 'cursor-pointer',
        dimmed && !locked && 'opacity-50',
        selected
          ? 'shadow-[inset_0_0_0_2px_#face15]'
          : 'shadow-[inset_0_0_0_1px_rgba(255,255,255,0.08)]'
      )}
      style={{ backgroundColor: TIMELINE_THEME.video.body }}
    >
      <ClipTrimHandles
        selected={selected && !locked}
        onTrimStart={onTrimStart}
        onTrimEnd={onTrimEnd}
        pxPerSec={pxPerSec}
      />

      <div className="absolute inset-0">{renderBody()}</div>

      {/* 底部渐变标签 — 剪映风格 */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 via-black/40 to-transparent px-1 pb-[3px] pt-5">
        <div className="flex items-end justify-between gap-1">
          <span className="min-w-0 flex-1 truncate text-[9px] font-medium leading-tight text-white/92 drop-shadow-sm">
            {label}
          </span>
          <span className="shrink-0 rounded-[2px] bg-black/35 px-0.5 font-mono text-[8px] tabular-nums text-white/55">
            {duration.toFixed(1)}s
          </span>
        </div>
      </div>

      {title && title !== label ? (
        <div className="pointer-events-none absolute left-0.5 top-0.5 max-w-[65%] truncate rounded-[2px] bg-black/50 px-1 py-px text-[8px] text-white/75 backdrop-blur-[1px]">
          {title}
        </div>
      ) : null}
      {slotId && !locked && onSlotReorderDragStart ? (
        <div
          draggable
          title="拖拽调整槽位顺序"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
          onDragStart={(e) => {
            e.stopPropagation();
            onSlotReorderDragStart(e, slotId);
          }}
          className="absolute right-0.5 top-0.5 z-30 flex h-4 w-4 cursor-grab items-center justify-center rounded bg-black/55 text-[8px] text-white/80 active:cursor-grabbing"
        >
          ⋮⋮
        </div>
      ) : null}
    </div>
  );
}

export function CapCutSubtitleClip({
  text,
  selected,
  locked,
  dimmed,
  onClick,
}: {
  text: string;
  selected: boolean;
  locked: boolean;
  dimmed?: boolean;
  onClick: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={cn(
        'relative flex h-full items-center overflow-hidden rounded-[3px] px-1.5',
        locked ? 'cursor-not-allowed opacity-45' : 'cursor-pointer',
        dimmed && !locked && 'opacity-40',
        selected
          ? 'shadow-[inset_0_0_0_2px_#face15]'
          : 'shadow-[inset_0_0_0_1px_rgba(194,65,12,0.5)]'
      )}
      style={{
        background: selected
          ? `linear-gradient(180deg, ${TIMELINE_THEME.subtitle.bgSelected} 0%, ${TIMELINE_THEME.subtitle.bg} 100%)`
          : `linear-gradient(180deg, ${TIMELINE_THEME.subtitle.bgHover} 0%, ${TIMELINE_THEME.subtitle.bg} 100%)`,
      }}
    >
      <ClipTrimHandles selected={selected && !locked} />
      <CapCutSubtitleIcon />
      <span className="truncate text-[9px] font-semibold text-white">{text}</span>
    </div>
  );
}

export function CapCutStickerClip({
  thumb,
  label,
  selected,
  locked,
  dimmed,
  onClick,
}: {
  thumb: string;
  label: string;
  selected: boolean;
  locked: boolean;
  dimmed?: boolean;
  onClick: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={cn(
        'relative flex h-full items-center overflow-hidden rounded-[3px] px-1',
        locked ? 'cursor-not-allowed opacity-45' : 'cursor-pointer',
        dimmed && !locked && 'opacity-40',
        selected
          ? 'shadow-[inset_0_0_0_2px_#face15]'
          : 'shadow-[inset_0_0_0_1px_rgba(34,197,94,0.45)]'
      )}
      style={{ backgroundColor: TIMELINE_THEME.sticker.bg }}
    >
      <ClipTrimHandles selected={selected && !locked} />
      {thumb ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={toMediaUrl(thumb)} alt="" className="mr-1 h-full w-6 shrink-0 rounded-[2px] object-cover" />
      ) : (
        <CapCutStickerIcon />
      )}
      <span className="truncate text-[8px] font-medium" style={{ color: TIMELINE_THEME.sticker.text }}>
        {label || '贴纸'}
      </span>
    </div>
  );
}

export function CapCutAudioClip({
  seed,
  width,
  label,
  selected,
  locked,
  dimmed,
  peaks,
  onClick,
}: {
  seed: string;
  width: number;
  label: string;
  selected: boolean;
  locked: boolean;
  dimmed?: boolean;
  peaks?: number[];
  onClick: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={cn(
        'relative h-full overflow-hidden rounded-[3px]',
        locked ? 'cursor-not-allowed opacity-45' : 'cursor-pointer',
        selected
          ? 'shadow-[inset_0_0_0_2px_#face15]'
          : 'shadow-[inset_0_0_0_1px_rgba(30,58,95,0.7)]'
      )}
      style={{
        background: `linear-gradient(180deg, #102238 0%, ${TIMELINE_THEME.audio.bg} 100%)`,
      }}
    >
      <ClipTrimHandles selected={selected && !locked} />
      <CapCutWaveform seed={seed} width={width} dimmed={dimmed} peaks={peaks} />
      {label ? (
        <span
          className="absolute left-1 top-0.5 max-w-[90%] truncate rounded-[2px] bg-black/30 px-1 text-[7px] font-medium backdrop-blur-[1px]"
          style={{ color: TIMELINE_THEME.audio.label }}
        >
          {label}
        </span>
      ) : null}
    </div>
  );
}

export function laneGridStyle(pxPerSec: number) {
  const major = Math.max(pxPerSec * 5, 48);
  return {
    backgroundImage: [
      `linear-gradient(to right, rgba(255,255,255,0.018) 1px, transparent 1px)`,
      `linear-gradient(to right, rgba(255,255,255,0.04) 1px, transparent 1px)`,
    ].join(', '),
    backgroundSize: `${pxPerSec}px 100%, ${major}px 100%`,
  };
}
