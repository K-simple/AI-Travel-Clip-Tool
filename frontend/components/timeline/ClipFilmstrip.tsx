'use client';

import { useEffect, useState } from 'react';
import { toMediaUrl } from '@/lib/api';

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

type ClipFilmstripProps = {
  videoSrc: string;
  clipStart: number;
  duration: number;
  width: number;
  pxPerSec?: number;
  fallbackThumb?: string;
};

/** 剪映风格：整段胶片条无缝铺满片段宽度 */
export function ClipFilmstrip({
  videoSrc,
  clipStart,
  duration,
  width,
  pxPerSec = 48,
  fallbackThumb,
}: ClipFilmstripProps) {
  const frameW = Math.max(16, Math.min(52, Math.round(pxPerSec * 0.55)));
  const frameCount = Math.max(2, Math.ceil(width / frameW));
  const captureKey = `${videoSrc}|${clipStart.toFixed(2)}|${duration.toFixed(2)}|${frameCount}|${frameW}`;
  const fallbackUrl = fallbackThumb ? toMediaUrl(fallbackThumb) : '';
  const [stripUrl, setStripUrl] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!videoSrc || frameCount < 1) return;

    let cancelled = false;
    setLoading(true);
    setStripUrl('');

    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.preload = 'auto';
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

      const stripCanvas = document.createElement('canvas');
      stripCanvas.width = frameW * frameCount;
      stripCanvas.height = h;
      const stripCtx = stripCanvas.getContext('2d');
      if (!stripCtx) return;

      for (let i = 0; i < frameUrls.length; i++) {
        const img = await loadImage(frameUrls[i]);
        if (cancelled) return;
        stripCtx.drawImage(img, i * frameW, 0, frameW, h);
      }

      if (!cancelled) {
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
  }, [captureKey, clipStart, duration, fallbackUrl, frameCount, frameW, videoSrc]);

  if (stripUrl) {
    return (
      <div
        className="h-full w-full bg-[#0a1a16] bg-cover bg-left bg-no-repeat"
        style={{ backgroundImage: `url(${stripUrl})` }}
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
        <span className="text-[9px] text-white/35">拖入素材</span>
      )}
    </div>
  );
}
