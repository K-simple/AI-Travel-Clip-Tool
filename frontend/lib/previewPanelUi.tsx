'use client';

import { useEffect, type ReactNode, type RefObject } from 'react';

export const PREVIEW_FPS = 30;
export const PREVIEW_FRAME_STEP = 1 / PREVIEW_FPS;

export function formatPreviewTimecode(seconds: number, fps = PREVIEW_FPS): string {
  const safe = Math.max(0, seconds);
  const h = Math.floor(safe / 3600);
  const m = Math.floor((safe % 3600) / 60);
  const s = Math.floor(safe % 60);
  const f = Math.floor((safe % 1) * fps);
  const pad = (n: number, len = 2) => n.toString().padStart(len, '0');
  return `${pad(h)}:${pad(m)}:${pad(s)}:${pad(f)}`;
}

export function PlayIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

export function PauseIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <path d="M6 5h4v14H6V5zm8 0h4v14h-4V5z" />
    </svg>
  );
}

export function useClickOutside(
  ref: RefObject<HTMLElement | null>,
  open: boolean,
  onClose: () => void
) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current?.contains(e.target as Node)) return;
      onClose();
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open, onClose, ref]);
}

export function CompactMenu({
  open,
  children,
  width,
}: {
  open: boolean;
  children: ReactNode;
  width: string;
}) {
  if (!open) return null;
  return (
    <div
      className={`absolute bottom-[calc(100%+4px)] right-0 z-40 overflow-hidden rounded-md border border-[#3a3a3c] bg-[#2a2a2c] py-0.5 shadow-lg ${width}`}
    >
      {children}
    </div>
  );
}
