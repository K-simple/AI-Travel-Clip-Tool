'use client';

import { useEffect, useState } from 'react';
import { toMediaUrl } from '@/lib/api';
import type { TimelineThumbnail } from '@/lib/timelineThumbnails';
import { TimelineFrameFilmstrip } from '@/components/timeline/TimelineFrameFilmstrip';

function waitSeek(video: HTMLVideoElement, time: number): Promise<void> {
  return new Promise((resolve) => {
    if (Math.abs(video.currentTime - time) < 0.04) {
      resolve();
      return;
    }
    const onSeeked = () => {
      video.removeEventListener('seeked', onSeeked);
      resolve();
    };
    video.addEventListener('seeked', onSeeked);
    try {
      video.currentTime = time;
    } catch {
      video.removeEventListener('seeked', onSeeked);
      resolve();
    }
  });
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

type PrecomputedFilmstripProps = {
  url: string;
  width: number;
  clipStart?: number;
  duration?: number;
  sourceDuration?: number;
};

/** 服务端 ffmpeg 预生成的横向胶片条，铺满槽位宽度 */
export function PrecomputedFilmstrip({
  url,
  width,
  clipStart = 0,
  duration,
  sourceDuration,
}: PrecomputedFilmstripProps) {
  const src = toMediaUrl(url);
  const total = sourceDuration && sourceDuration > 0 ? sourceDuration : duration;
  const canCrop =
    total != null && total > 0 && duration != null && duration > 0 && clipStart > 0;
  if (canCrop && total) {
    const startPct = (clipStart / total) * 100;
    const spanPct = (duration! / total) * 100;
    return (
      <div
        className="h-full w-full bg-[#0a1a16] bg-no-repeat"
        style={{
          backgroundImage: `url(${src})`,
          backgroundSize: `${(100 / spanPct) * 100}% 100%`,
          backgroundPosition: `${startPct}% center`,
        }}
      />
    );
  }

  return (
    <img
      src={src}
      alt=""
      draggable={false}
      className="h-full w-full select-none object-fill"
      style={{ minWidth: width }}
    />
  );
}

type ClipFilmstripProps = {
  videoSrc: string;
  clipStart: number;
  duration: number;
  width: number;
  pxPerSec?: number;
  fallbackThumb?: string;
  filmstripUrl?: string;
  filmstripFrames?: number;
  filmstripTileWidth?: number;
  timelineThumbnails?: TimelineThumbnail[];
  timelineThumbnailsLoading?: boolean;
  sampleIntervalSec?: number;
  slotSourceStart?: number;
  slotSourceEnd?: number;
};

const MAX_CAPTURE_FRAMES = 400;
const MIN_FRAME_W = 10;

/** 剪映风格：整段胶片条无缝铺满片段宽度 */
export function ClipFilmstrip({
  videoSrc,
  clipStart,
  duration,
  width,
  pxPerSec = 48,
  fallbackThumb,
  filmstripUrl,
  filmstripFrames,
  filmstripTileWidth,
  timelineThumbnails,
  timelineThumbnailsLoading = false,
  sampleIntervalSec = 0.5,
  slotSourceStart,
  slotSourceEnd,
}: ClipFilmstripProps) {
  const sourceStart = slotSourceStart ?? clipStart;
  const sourceEnd = slotSourceEnd ?? clipStart + duration;

  const useFrameFilmstrip =
    timelineThumbnails?.length ||
    timelineThumbnailsLoading ||
    (!videoSrc && !filmstripUrl && !!fallbackThumb);

  if (useFrameFilmstrip) {
    return (
      <TimelineFrameFilmstrip
        thumbnails={timelineThumbnails ?? []}
        slotStart={sourceStart}
        slotEnd={sourceEnd}
        width={width}
        pxPerSec={pxPerSec}
        sampleIntervalSec={sampleIntervalSec}
        fallbackThumb={fallbackThumb}
        loading={timelineThumbnailsLoading}
      />
    );
  }

  if (
    filmstripUrl &&
    filmstripFrames &&
    filmstripFrames > 1 &&
    filmstripTileWidth
  ) {
    return (
      <PrecomputedFilmstrip
        url={filmstripUrl}
        width={width}
        clipStart={clipStart}
        duration={duration}
      />
    );
  }

  const frameW = Math.max(MIN_FRAME_W, Math.min(36, Math.round(pxPerSec * 0.38)));
  const frameCount = Math.min(MAX_CAPTURE_FRAMES, Math.max(4, Math.ceil(width / frameW)));
  const captureKey = `${videoSrc}|${clipStart.toFixed(2)}|${duration.toFixed(2)}|${frameCount}|${frameW}|${pxPerSec.toFixed(1)}`;
  const fallbackUrl = fallbackThumb ? toMediaUrl(fallbackThumb) : '';
  const [stripUrl, setStripUrl] = useState('');
  const [stripPixelWidth, setStripPixelWidth] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!videoSrc || frameCount < 1) return;

    let cancelled = false;
    setLoading(true);
    setStripUrl('');
    setStripPixelWidth(0);

    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.preload = 'auto';
    video.crossOrigin = 'anonymous';
    video.src = toMediaUrl(videoSrc);

    const capture = async () => {
      await new Promise<void>((resolve, reject) => {
        const onReady = () => {
          video.removeEventListener('loadeddata', onReady);
          video.removeEventListener('error', onError);
          resolve();
        };
        const onError = () => {
          video.removeEventListener('loadeddata', onReady);
          video.removeEventListener('error', onError);
          reject(new Error('video load failed'));
        };
        video.addEventListener('loadeddata', onReady);
        video.addEventListener('error', onError);
      });

      const frameCanvas = document.createElement('canvas');
      const frameCtx = frameCanvas.getContext('2d');
      if (!frameCtx) return;

      const h = 72;
      frameCanvas.width = frameW;
      frameCanvas.height = h;

      const safeDur = Math.max(duration, 0.5);
      const frameUrls: string[] = [];

      for (let i = 0; i < frameCount; i++) {
        if (cancelled) return;
        const t = clipStart + ((i + 0.5) / frameCount) * safeDur;
        await waitSeek(video, t);
        frameCtx.fillStyle = '#0a1a16';
        frameCtx.fillRect(0, 0, frameW, h);
        const vw = video.videoWidth;
        const vh = video.videoHeight;
        if (vw > 0 && vh > 0) {
          const scale = Math.max(frameW / vw, h / vh);
          const dw = vw * scale;
          const dh = vh * scale;
          frameCtx.drawImage(video, (frameW - dw) / 2, (h - dh) / 2, dw, dh);
        } else {
          frameCtx.drawImage(video, 0, 0, frameW, h);
        }
        frameUrls.push(frameCanvas.toDataURL('image/jpeg', 0.68));
      }

      if (cancelled) return;

      const totalW = frameW * frameCount;
      const stripCanvas = document.createElement('canvas');
      stripCanvas.width = totalW;
      stripCanvas.height = h;
      const stripCtx = stripCanvas.getContext('2d');
      if (!stripCtx) return;

      for (let i = 0; i < frameUrls.length; i++) {
        const img = await loadImage(frameUrls[i]);
        if (cancelled) return;
        stripCtx.drawImage(img, i * frameW, 0, frameW, h);
      }

      if (!cancelled) {
        setStripPixelWidth(totalW);
        setStripUrl(stripCanvas.toDataURL('image/jpeg', 0.72));
        setLoading(false);
      }
    };

    void capture().catch(() => {
      if (!cancelled) {
        setStripUrl(fallbackUrl);
        setLoading(false);
      }
    });

    return () => {
      cancelled = true;
      video.pause();
      video.removeAttribute('src');
      video.load();
    };
  }, [captureKey, clipStart, duration, fallbackUrl, frameCount, frameW, videoSrc, pxPerSec]);

  if (stripUrl) {
    return (
      <img
        src={stripUrl}
        alt=""
        draggable={false}
        className="h-full w-full select-none object-cover object-left"
        style={stripPixelWidth > 0 ? { minWidth: stripPixelWidth } : undefined}
      />
    );
  }

  if (fallbackUrl) {
    return (
      <div
        className="h-full w-full bg-cover bg-left bg-no-repeat opacity-80"
        style={{ backgroundImage: `url(${fallbackUrl})` }}
      />
    );
  }

  return (
    <div className="flex h-full w-full items-center justify-center bg-[#0f1f1a]">
      {loading ? (
        <div className="h-full w-full animate-pulse bg-gradient-to-r from-[#0f1f1a] via-[#1a2e28] to-[#0f1f1a]" />
      ) : (
        <span className="text-[9px] text-white/35">加载画面…</span>
      )}
    </div>
  );
}
