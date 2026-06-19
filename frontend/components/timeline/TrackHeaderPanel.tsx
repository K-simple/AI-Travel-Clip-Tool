'use client';

import { useEffect, useRef, useState } from 'react';
import { toMediaUrl } from '@/lib/api';
import type { TrackControls, TrackKey } from '@/lib/trackControls';
import type { TimelineTrackDef } from '@/lib/timelineTracks';
import { HEADER_W, RULER_H, TIMELINE_THEME } from './timelineTheme';
import { TrackResizeHandle } from '@/components/timeline/TrackResizeHandle';
import type { PointerEvent as ReactPointerEvent } from 'react';

export type TrackMeta = {
  key: TrackKey;
  label: string;
  height: number;
  group?: 'video' | 'effect' | 'meta' | 'text' | 'audio';
};

function cn(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ');
}

const TRACK_ICON: Record<TrackKey, { bg: string; fg: string; content: React.ReactNode }> = {
  video: {
    bg: TIMELINE_THEME.trackIcon.video.bg,
    fg: TIMELINE_THEME.trackIcon.video.fg,
    content: (
      <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
        <path d="M4 6h12v12H4V6zm14 3l4 2.5v5L18 17V9z" />
      </svg>
    ),
  },
  subtitle: {
    bg: TIMELINE_THEME.trackIcon.subtitle.bg,
    fg: TIMELINE_THEME.trackIcon.subtitle.fg,
    content: <span className="text-[12px] font-bold leading-none">T</span>,
  },
  overlay: {
    bg: TIMELINE_THEME.trackIcon.overlay.bg,
    fg: TIMELINE_THEME.trackIcon.overlay.fg,
    content: (
      <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
        <path d="M12 2l2.4 7.4H22l-6 4.6 2.3 7L12 17.8 5.7 21.2 8 14 2 9.4h7.6L12 2z" />
      </svg>
    ),
  },
  sticker: {
    bg: TIMELINE_THEME.trackIcon.sticker.bg,
    fg: TIMELINE_THEME.trackIcon.sticker.fg,
    content: (
      <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
        <path d="M12 2C8 2 5 5 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-4-3-7-7-7z" />
      </svg>
    ),
  },
  video2: {
    bg: TIMELINE_THEME.trackIcon.video2.bg,
    fg: TIMELINE_THEME.trackIcon.video2.fg,
    content: (
      <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
        <path d="M3 5h8v8H3V5zm10 0h8v5h-8V5zm0 7h8v7h-8v-7zM3 15h8v4H3v-4z" />
      </svg>
    ),
  },
  filter: {
    bg: TIMELINE_THEME.trackIcon.filter.bg,
    fg: TIMELINE_THEME.trackIcon.filter.fg,
    content: (
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="3" />
        <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
      </svg>
    ),
  },
  transition: {
    bg: TIMELINE_THEME.trackIcon.transition.bg,
    fg: TIMELINE_THEME.trackIcon.transition.fg,
    content: (
      <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
        <path d="M8 5v14l8-7-8-7zM16 19V5l8 7-8 7z" opacity="0.85" />
      </svg>
    ),
  },
  adjust: {
    bg: TIMELINE_THEME.trackIcon.adjust.bg,
    fg: TIMELINE_THEME.trackIcon.adjust.fg,
    content: (
      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3" />
        <circle cx="4" cy="14" r="2" fill="currentColor" stroke="none" />
        <circle cx="12" cy="12" r="2" fill="currentColor" stroke="none" />
        <circle cx="20" cy="16" r="2" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
  audio: {
    bg: TIMELINE_THEME.trackIcon.audio.bg,
    fg: TIMELINE_THEME.trackIcon.audio.fg,
    content: (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
        <path d="M9 18V5l12-2v13" />
        <circle cx="6" cy="18" r="3" fill="currentColor" stroke="none" />
        <circle cx="18" cy="16" r="3" fill="currentColor" stroke="none" />
      </svg>
    ),
  },
  audioVoice: {
    bg: TIMELINE_THEME.trackIcon.audioVoice.bg,
    fg: TIMELINE_THEME.trackIcon.audioVoice.fg,
    content: (
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
        <path d="M4 14v-4M8 16V8M12 18V6M16 14V10M20 12V12" />
      </svg>
    ),
  },
};

function TrackTypeIcon({
  trackKey,
  label,
  selected,
  onSelect,
}: {
  trackKey: TrackKey;
  label: string;
  selected: boolean;
  onSelect: () => void;
}) {
  const icon = TRACK_ICON[trackKey];
  return (
    <button
      type="button"
      title={`${label}轨`}
      onClick={onSelect}
      className="track-type-btn shrink-0 border-none bg-transparent p-0"
    >
      <span
        className={cn(
          'flex h-[22px] w-[22px] items-center justify-center rounded-[4px] transition-shadow',
          selected && 'shadow-[0_0_0_1px_rgba(250,206,21,0.55)]'
        )}
        style={{ backgroundColor: icon.bg, color: icon.fg }}
      >
        {icon.content}
      </span>
    </button>
  );
}

type ControlVariant = 'lock' | 'hide' | 'mute' | 'solo';

function MiniControlBtn({
  variant,
  active,
  title,
  onClick,
}: {
  variant: ControlVariant;
  active: boolean;
  title: string;
  onClick: () => void;
}) {
  const activeColor: Record<ControlVariant, string> = {
    lock: 'text-[#ffb300]',
    hide: 'text-[#98989d]',
    mute: 'text-[#60a5fa]',
    solo: 'text-[#4ade80]',
  };

  return (
    <button
      type="button"
      title={title}
      aria-pressed={active}
      className={cn(
        'track-control-btn relative z-10 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-[3px] transition-all duration-100',
        active
          ? `bg-[#2e2e32] ${activeColor[variant]}`
          : 'bg-transparent text-[#7c7c80] hover:bg-[#2a2a2e] hover:text-[#c7c7cc]'
      )}
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => {
        e.stopPropagation();
        e.preventDefault();
        onClick();
      }}
    >
      {variant === 'lock' && (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
          {active ? (
            <>
              <rect x="5" y="11" width="14" height="9" rx="1.5" />
              <path d="M8 11V8a4 4 0 018 0v3" />
            </>
          ) : (
            <>
              <path d="M8 11V8a4 4 0 018 0" />
              <rect x="5" y="11" width="14" height="9" rx="1.5" />
            </>
          )}
        </svg>
      )}
      {variant === 'hide' && (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
          {active ? (
            <>
              <path d="M3 3l18 18" />
              <path d="M10.6 10.6a2 2 0 002.8 2.8M9.9 5.1A10.7 10.7 0 0112 5c5 0 9.3 3.1 11 7.5a11.2 11.2 0 01-2.1 3.6M6.1 6.1A11.5 11.5 0 003 12.5" />
            </>
          ) : (
            <>
              <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7" />
              <circle cx="12" cy="12" r="2.5" />
            </>
          )}
        </svg>
      )}
      {variant === 'mute' && (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
          {active ? (
            <>
              <path d="M11 5L6 9H3v6h3l5 4V5z" />
              <path d="M16 9l4 4M20 9l-4 4" />
            </>
          ) : (
            <>
              <path d="M11 5L6 9H3v6h3l5 4V5z" />
              <path d="M15.5 8.5a5 5 0 010 7" />
            </>
          )}
        </svg>
      )}
      {variant === 'solo' && <span className="text-[9px] font-bold leading-none">S</span>}
    </button>
  );
}

function CoverHeaderRow({
  coverThumb,
  onCoverClick,
}: {
  coverThumb: string;
  onCoverClick?: () => void;
}) {
  return (
    <div
      className="flex items-center justify-center border-b px-2"
      style={{
        height: RULER_H,
        backgroundColor: TIMELINE_THEME.headerBg,
        borderColor: TIMELINE_THEME.border,
      }}
    >
      <button
        type="button"
        title="设置封面（点击上传图片）"
        onClick={onCoverClick}
        className="track-type-btn flex items-center gap-1.5 rounded-[4px] border-none bg-transparent px-1 py-0.5 transition-colors hover:bg-[#252528]"
      >
        <span className="relative flex h-[22px] w-[22px] shrink-0 items-center justify-center overflow-hidden rounded-[3px] border border-[#343438] bg-[#222224]">
          {coverThumb ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={toMediaUrl(coverThumb)} alt="" className="h-full w-full object-cover" />
          ) : (
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#7c7c80" strokeWidth="1.5">
              <rect x="3" y="5" width="18" height="14" rx="2" />
              <circle cx="8.5" cy="10.5" r="1.5" fill="#7c7c80" stroke="none" />
            </svg>
          )}
        </span>
        <span className="text-[10px] text-[#c7c7cc]">封面</span>
      </button>
    </div>
  );
}

function TrackHeaderRow({
  track,
  ctrl,
  selected,
  onSelect,
  onToggle,
  onResizeStart,
  onResizeReset,
}: {
  track: TrackMeta;
  ctrl: TrackControls;
  selected: boolean;
  onSelect: () => void;
  onToggle: (field: keyof TrackControls) => void;
  onResizeStart?: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onResizeReset?: () => void;
}) {
  return (
    <div className="group relative shrink-0" style={{ height: track.height }}>
      <div
        className={cn(
          'relative flex h-full items-center gap-1 border-b pl-1.5 pr-1 transition-colors duration-100',
          selected ? 'bg-[#222224]' : 'bg-[#1a1a1c]',
          !ctrl.visible && 'opacity-65'
        )}
        style={{ borderColor: TIMELINE_THEME.border }}
      >
      {selected ? (
        <div className="pointer-events-none absolute inset-y-0 left-0 w-[2px] bg-[#face15]" />
      ) : null}
      {ctrl.locked ? (
        <div className="pointer-events-none absolute inset-0 bg-[repeating-linear-gradient(-45deg,transparent,transparent_5px,rgba(255,179,0,0.035)_5px,rgba(255,179,0,0.035)_10px)]" />
      ) : null}

      <TrackTypeIcon
        trackKey={track.key}
        label={track.label}
        selected={selected}
        onSelect={onSelect}
      />

      <div className="relative z-10 flex flex-1 items-center justify-between">
        <MiniControlBtn
          variant="lock"
          active={ctrl.locked}
          title={ctrl.locked ? '解锁轨道' : '锁定轨道'}
          onClick={() => onToggle('locked')}
        />
        <MiniControlBtn
          variant="hide"
          active={!ctrl.visible}
          title={ctrl.visible ? '隐藏轨道' : '显示轨道'}
          onClick={() => onToggle('visible')}
        />
        <MiniControlBtn
          variant="mute"
          active={ctrl.muted}
          title={ctrl.muted ? '取消静音' : '静音轨道'}
          onClick={() => onToggle('muted')}
        />
        <MiniControlBtn
          variant="solo"
          active={ctrl.solo}
          title={ctrl.solo ? '取消独奏' : '独奏此轨'}
          onClick={() => onToggle('solo')}
        />
      </div>
      </div>
      {onResizeStart ? (
        <TrackResizeHandle onResizeStart={onResizeStart} onResizeReset={onResizeReset} />
      ) : null}
    </div>
  );
}

type TrackHeaderPanelProps = {
  tracks: ReadonlyArray<TrackMeta>;
  trackControls: Record<TrackKey, TrackControls>;
  selectedTrackKey: TrackKey | null;
  coverThumb: string;
  statusMessage?: string;
  lanesScrollRef?: React.RefObject<HTMLDivElement | null>;
  onSelectTrack: (key: TrackKey) => void;
  onTrackControlToggle: (key: TrackKey, field: keyof TrackControls) => void;
  addableTracks?: TimelineTrackDef[];
  onAddTrack?: (key: TrackKey) => void;
  onCoverClick?: () => void;
  onTrackResizeStart?: (key: TrackKey, event: ReactPointerEvent<HTMLDivElement>) => void;
  onTrackResizeReset?: (key: TrackKey) => void;
};

function TrackHeaderFooter({
  trackCount,
  addableTracks,
  onAddTrack,
}: {
  trackCount: number;
  addableTracks: TimelineTrackDef[];
  onAddTrack?: (key: TrackKey) => void;
}) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  return (
    <div
      ref={menuRef}
      className="flex shrink-0 items-center justify-between border-t px-2 py-1.5"
      style={{ borderColor: TIMELINE_THEME.border, backgroundColor: TIMELINE_THEME.headerBg }}
    >
      <span className="text-[9px] tabular-nums text-[#6e6e72]">{trackCount} 轨</span>
      {addableTracks.length > 0 && onAddTrack ? (
        <div className="relative">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="rounded px-1.5 py-0.5 text-[9px] text-[#93c5fd] hover:bg-[#252528]"
          >
            + 添加轨道
          </button>
          {open ? (
            <div
              className="absolute bottom-full right-0 z-30 mb-1 min-w-[128px] rounded border py-1 shadow-lg"
              style={{
                borderColor: TIMELINE_THEME.border,
                backgroundColor: TIMELINE_THEME.headerBg,
              }}
            >
              {addableTracks.map((track) => (
                <button
                  key={track.key}
                  type="button"
                  className="block w-full px-2.5 py-1.5 text-left text-[10px] text-[#d4d4d8] hover:bg-[#252528]"
                  onClick={() => {
                    onAddTrack(track.key);
                    setOpen(false);
                  }}
                >
                  {track.addLabel ?? track.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <span className="text-[9px] text-[#454548]">导轨</span>
      )}
    </div>
  );
}

export function TrackHeaderPanel({
  tracks,
  trackControls,
  selectedTrackKey,
  coverThumb,
  statusMessage,
  lanesScrollRef,
  onSelectTrack,
  onTrackControlToggle,
  addableTracks = [],
  onAddTrack,
  onCoverClick,
  onTrackResizeStart,
  onTrackResizeReset,
}: TrackHeaderPanelProps) {
  const headerTracksRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const lanes = lanesScrollRef?.current;
    const header = headerTracksRef.current;
    if (!lanes || !header) return;

    const syncFromLanes = () => {
      header.scrollTop = lanes.scrollTop;
    };
    lanes.addEventListener('scroll', syncFromLanes, { passive: true });
    return () => lanes.removeEventListener('scroll', syncFromLanes);
  }, [lanesScrollRef]);

  return (
    <div
      className="relative z-20 flex min-h-0 shrink-0 flex-col border-r shadow-[2px_0_8px_rgba(0,0,0,0.25)]"
      style={{
        width: HEADER_W,
        backgroundColor: TIMELINE_THEME.headerBg,
        borderColor: TIMELINE_THEME.border,
      }}
    >
      <CoverHeaderRow coverThumb={coverThumb} onCoverClick={onCoverClick} />
      <div ref={headerTracksRef} className="min-h-0 flex-1 overflow-hidden">
        {tracks.map((track, index) => {
          const prev = tracks[index - 1];
          const showGroupGap = prev && prev.group && track.group && prev.group !== track.group;
          return (
            <div key={track.key}>
              {showGroupGap ? (
                <div
                  className="h-px shrink-0"
                  style={{ backgroundColor: TIMELINE_THEME.borderLight }}
                />
              ) : null}
              <TrackHeaderRow
                track={track}
                ctrl={trackControls[track.key]}
                selected={selectedTrackKey === track.key}
                onSelect={() => onSelectTrack(track.key)}
                onToggle={(field) => onTrackControlToggle(track.key, field)}
                onResizeStart={
                  onTrackResizeStart
                    ? (event) => onTrackResizeStart(track.key, event)
                    : undefined
                }
                onResizeReset={
                  onTrackResizeReset ? () => onTrackResizeReset(track.key) : undefined
                }
              />
            </div>
          );
        })}
      </div>
      <TrackHeaderFooter
        trackCount={tracks.length}
        addableTracks={addableTracks}
        onAddTrack={onAddTrack}
      />
      {statusMessage ? (
        <div className="border-t border-[#28282c] px-2 py-1 text-[9px] leading-snug text-[#face15]/90">
          {statusMessage}
        </div>
      ) : null}
    </div>
  );
}

export function trackLaneClass(selected: boolean, extra?: string) {
  return cn(
    'relative cursor-crosshair border-b transition-colors duration-75',
    selected ? 'bg-[#1a1a1e]' : 'bg-[#121214]',
    extra
  );
}

export { HEADER_W, RULER_H };
