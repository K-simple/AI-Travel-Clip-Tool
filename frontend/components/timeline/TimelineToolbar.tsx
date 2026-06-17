'use client';

import { isTrackLocked } from '@/lib/trackControls';
import type { TrackControls, TrackKey } from '@/lib/trackControls';
import { formatTimecode } from '@/lib/timelineLayout';
import { TIMELINE_THEME, TOOLBAR_H } from './timelineTheme';

type TimelineToolbarProps = {
  isPlaying: boolean;
  canUndo: boolean;
  canRedo: boolean;
  canSplit: boolean;
  magnet: boolean;
  playheadTime: number;
  totalDuration: number;
  zoom: number;
  trackControls: Record<TrackKey, TrackControls>;
  onTogglePlay?: () => void;
  onUndo?: () => void;
  onRedo?: () => void;
  onSplit?: () => void;
  onDelete?: () => void;
  canDelete?: boolean;
  onToggleMagnet: () => void;
  onZoomChange: (zoom: number) => void;
};

function ToolBtn({
  title,
  active,
  disabled,
  onClick,
  children,
}: {
  title: string;
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`timeline-tool-btn flex h-7 w-7 items-center justify-center rounded-[5px] transition-colors ${
        active
          ? 'bg-[#2e2e32] text-[#face15]'
          : disabled
            ? 'cursor-not-allowed text-[#404044]'
            : 'text-[#b0b0b4] hover:bg-[#2a2a2e] hover:text-[#e8e8ec]'
      }`}
    >
      {children}
    </button>
  );
}

export function TimelineToolbar({
  isPlaying,
  canUndo,
  canRedo,
  canSplit,
  magnet,
  playheadTime,
  totalDuration,
  zoom,
  trackControls,
  onTogglePlay,
  onUndo,
  onRedo,
  onSplit,
  onDelete,
  canDelete = false,
  onToggleMagnet,
  onZoomChange,
}: TimelineToolbarProps) {
  const videoLocked = isTrackLocked(trackControls, 'video');

  return (
    <div
      className="flex shrink-0 items-center gap-1 px-2"
      style={{
        height: TOOLBAR_H,
        backgroundColor: TIMELINE_THEME.toolbarBg,
        borderBottom: `1px solid ${TIMELINE_THEME.border}`,
      }}
    >
      <ToolBtn title="选择工具" active>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
          <path d="M3 3l7.07 18.18 2.43-7.43L21 10.5 3 3z" />
        </svg>
      </ToolBtn>

      <ToolBtn title={isPlaying ? '暂停 (Space)' : '播放 (Space)'} onClick={onTogglePlay}>
        {isPlaying ? (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="5" width="4" height="14" rx="0.5" />
            <rect x="14" y="5" width="4" height="14" rx="0.5" />
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M8 5.5v13l10-6.5z" />
          </svg>
        )}
      </ToolBtn>

      <div className="mx-0.5 h-4 w-px bg-[#343438]" />

      <ToolBtn title="撤销 (Ctrl+Z)" disabled={!canUndo} onClick={onUndo}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M9 14H4V9M4 9l4.5-4.5M4 9h4.5a4.5 4.5 0 010 9H8" />
        </svg>
      </ToolBtn>
      <ToolBtn title="重做 (Ctrl+Shift+Z)" disabled={!canRedo} onClick={onRedo}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M15 14h5v-5M20 9l-4.5-4.5M20 9h-4.5a4.5 4.5 0 000 9H16" />
        </svg>
      </ToolBtn>

      <div className="mx-0.5 h-4 w-px bg-[#343438]" />

      <ToolBtn
        title={videoLocked ? '视频轨已锁定' : '分割 (S)'}
        disabled={!canSplit || videoLocked}
        onClick={onSplit}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <circle cx="6" cy="6" r="2.5" />
          <circle cx="6" cy="18" r="2.5" />
          <path d="M19 4L9 14M14 9l5-5M14 19l5-5" />
        </svg>
      </ToolBtn>

      <ToolBtn
        title="删除选中片段 (W)"
        disabled={!canDelete || videoLocked}
        onClick={onDelete}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" />
          <path d="M10 11v6M14 11v6" />
        </svg>
      </ToolBtn>

      <ToolBtn title={magnet ? '关闭磁吸' : '开启磁吸'} active={magnet} onClick={onToggleMagnet}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M10 2v5M10 17v5M2 10h5M17 10h5" />
          <rect x="8" y="8" width="8" height="8" rx="1" fill="currentColor" stroke="none" opacity="0.35" />
        </svg>
      </ToolBtn>

      <div className="ml-auto flex items-center gap-3">
        <span className="font-mono text-[11px] tabular-nums">
          <span className="text-[#face15]">{formatTimecode(playheadTime)}</span>
          <span className="mx-1 text-[#505054]">/</span>
          <span className="text-[#8e8e93]">{formatTimecode(totalDuration)}</span>
        </span>

        <div className="flex items-center gap-1">
          <button
            type="button"
            className="timeline-tool-btn flex h-6 w-5 items-center justify-center rounded text-[11px] text-[#8e8e93] hover:text-[#c7c7cc]"
            onClick={() => onZoomChange(Math.max(0.35, zoom - 0.15))}
          >
            −
          </button>
          <input
            type="range"
            min={0.35}
            max={3.2}
            step={0.05}
            value={zoom}
            onChange={(e) => onZoomChange(Number(e.target.value))}
            className="editor-slider w-[72px]"
            title={`缩放 ${Math.round(zoom * 100)}%`}
          />
          <button
            type="button"
            className="timeline-tool-btn flex h-6 w-5 items-center justify-center rounded text-[11px] text-[#8e8e93] hover:text-[#c7c7cc]"
            onClick={() => onZoomChange(Math.min(3.2, zoom + 0.15))}
          >
            +
          </button>
        </div>
      </div>
    </div>
  );
}
