'use client';

import { memo, useMemo } from 'react';
import { toMediaUrl } from '@/lib/api';
import {
  pickThumbnailsForSlot,
  type TimelineThumbnail,
} from '@/lib/timelineThumbnails';

type TimelineFrameFilmstripProps = {
  thumbnails: TimelineThumbnail[];
  slotStart: number;
  slotEnd: number;
  width: number;
  pxPerSec?: number;
  sampleIntervalSec?: number;
  fallbackThumb?: string;
  loading?: boolean;
};

/** 剪映式：槽位内横向排列离散缩略帧，随缩放自动增减密度 */
export const TimelineFrameFilmstrip = memo(function TimelineFrameFilmstrip({
  thumbnails,
  slotStart,
  slotEnd,
  width,
  pxPerSec = 48,
  sampleIntervalSec = 0.5,
  fallbackThumb,
  loading = false,
}: TimelineFrameFilmstripProps) {
  const picked = useMemo(
    () =>
      pickThumbnailsForSlot(
        thumbnails,
        slotStart,
        slotEnd,
        width,
        pxPerSec,
        sampleIntervalSec
      ),
    [thumbnails, slotStart, slotEnd, width, pxPerSec, sampleIntervalSec]
  );

  const tileW = useMemo(() => {
    if (!picked.length) return Math.max(48, width);
    return Math.max(48, Math.floor(width / picked.length));
  }, [picked.length, width]);

  const fallbackUrl = fallbackThumb ? toMediaUrl(fallbackThumb) : '';

  if (picked.length > 0) {
    return (
      <div className="slot-filmstrip flex h-full w-full overflow-hidden bg-[#0a1a16]">
        {picked.map((frame, index) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={`${frame.time}-${index}`}
            src={toMediaUrl(frame.url)}
            alt=""
            draggable={false}
            loading="lazy"
            decoding="async"
            className="filmstrip-frame h-full shrink-0 select-none object-cover"
            style={{
              width: tileW,
              minWidth: tileW,
              borderRight: index < picked.length - 1 ? '1px solid rgba(0,0,0,0.35)' : undefined,
            }}
          />
        ))}
      </div>
    );
  }

  if (loading) {
    return (
      <div className="h-full w-full animate-pulse bg-gradient-to-r from-[#0f1f1a] via-[#1a2e28] to-[#0f1f1a]" />
    );
  }

  if (fallbackUrl) {
    return (
      <div className="slot-filmstrip flex h-full w-full overflow-hidden bg-[#141414]">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={fallbackUrl}
          alt=""
          draggable={false}
          loading="lazy"
          className="filmstrip-frame h-full w-full object-cover opacity-75"
        />
      </div>
    );
  }

  return <div className="h-full w-full bg-[#141414]" />;
});
