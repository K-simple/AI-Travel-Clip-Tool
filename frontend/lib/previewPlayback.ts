import { toMediaUrl } from '@/lib/api';
import {
  normalizeProxyPaths,
  resolvePreviewStream,
  type PreviewProxyPaths,
  type PreviewQualityId,
} from '@/lib/previewSettings';
import type { TemplateSlot } from '@/lib/timeline';
import { colorGradeToCssFilter } from '@/lib/slotEffects';
import type { ClipLayout } from '@/lib/timelineLayout';

export const PREVIEW_FRAME_SEC = 1 / 30;
export const PREVIEW_CLIP_PRELOAD_LEAD = 0.55;
export const PREVIEW_CLIP_SWITCH_EPSILON = 0.02;

export type SlotPreviewMedia = {
  layout: ClipLayout;
  streamUrl: string;
  clipStart: number;
  /** 时间轴槽位时长 */
  timelineDuration: number;
  /** 素材源内可用片段时长 */
  sourceDuration: number;
  cssFilter: string;
};

type AssetPreviewInfo = {
  filePath?: string;
  proxyPath?: string;
  proxyPaths?: PreviewProxyPaths;
};

export function seekVideoElement(el: HTMLVideoElement, time: number): Promise<void> {
  const safe = Math.max(0, time);
  if (Math.abs(el.currentTime - safe) < 0.015 && el.readyState >= 2) {
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      el.removeEventListener('seeked', onSeeked);
      window.clearTimeout(timer);
      resolve();
    };
    const onSeeked = () => finish();
    const timer = window.setTimeout(finish, 240);
    el.addEventListener('seeked', onSeeked);
    try {
      el.currentTime = safe;
    } catch {
      finish();
    }
  });
}

export async function preparePreviewVideo(
  el: HTMLVideoElement,
  media: SlotPreviewMedia,
  videoTime: number,
  autoplay: boolean
): Promise<void> {
  if (el.dataset.stream !== media.streamUrl) {
    el.dataset.stream = media.streamUrl;
    el.dataset.filter = media.cssFilter;
    el.src = media.streamUrl;
    await new Promise<void>((resolve) => {
      if (el.readyState >= 2) {
        resolve();
        return;
      }
      const onReady = () => {
        el.removeEventListener('loadeddata', onReady);
        el.removeEventListener('error', onReady);
        resolve();
      };
      el.addEventListener('loadeddata', onReady);
      el.addEventListener('error', onReady);
    });
  } else if (el.dataset.filter !== media.cssFilter) {
    el.dataset.filter = media.cssFilter;
  }

  await seekVideoElement(el, videoTime);
  if (autoplay && el.paused) {
    await el.play().catch(() => undefined);
  }
}

export function resolveSlotPreviewMedia(
  layout: ClipLayout,
  options: {
    assetMap: Record<string, AssetPreviewInfo>;
    templateVideoPath: string;
    templateProxyPaths: PreviewProxyPaths;
    qualityId: PreviewQualityId;
    showVideo: boolean;
  }
): SlotPreviewMedia | null {
  const { assetMap, templateVideoPath, templateProxyPaths, qualityId, showVideo } = options;
  const slot = layout.slot;
  if (!showVideo) return null;

  const hasAsset = Boolean(slot.asset_file_path || slot.matchedAssetId);
  let originalUrl = '';
  if (slot.asset_file_path) {
    originalUrl = toMediaUrl(slot.asset_file_path);
  } else if (!hasAsset && templateVideoPath) {
    originalUrl = toMediaUrl(templateVideoPath);
  }
  if (!originalUrl) return null;

  let proxyPaths: PreviewProxyPaths = {};
  const aid = slot.matchedAssetId;
  if (aid && assetMap[aid]?.proxyPaths) {
    proxyPaths = normalizeProxyPaths(assetMap[aid].proxyPaths);
  } else if (aid && assetMap[aid]?.proxyPath) {
    proxyPaths = normalizeProxyPaths({ smooth: assetMap[aid].proxyPath });
  } else if (!hasAsset && templateVideoPath) {
    proxyPaths = normalizeProxyPaths(templateProxyPaths);
  }

  const proxyMediaPaths = {
    clear: proxyPaths.clear ? toMediaUrl(proxyPaths.clear) : '',
    smooth: proxyPaths.smooth ? toMediaUrl(proxyPaths.smooth) : '',
    low: proxyPaths.low ? toMediaUrl(proxyPaths.low) : '',
  };

  const stream = resolvePreviewStream(originalUrl, proxyMediaPaths, qualityId, {
    hasPoster: Boolean(slot.template_thumbnail || slot.asset_thumbnail),
  });
  const streamUrl = stream.url || (stream.isPoster ? originalUrl : '');
  if (!streamUrl) return null;

  const clipStart = Number(slot.clipStart || 0);
  const timelineDuration = Math.max(layout.end - layout.start, 0.1);
  const sourceDuration = Math.max(
    Number(slot.clip_duration ?? slot.duration ?? timelineDuration),
    0.1
  );

  return {
    layout,
    streamUrl,
    clipStart,
    timelineDuration,
    sourceDuration,
    cssFilter: colorGradeToCssFilter(slot.colorGrade) || '',
  };
}

export function timelineToVideoTime(media: SlotPreviewMedia, timelineTime: number): number {
  const local = Math.min(
    Math.max(timelineTime - media.layout.start, 0),
    media.timelineDuration
  );
  const maxSource = Math.max(media.sourceDuration - PREVIEW_FRAME_SEC, 0);
  return media.clipStart + Math.min(local, maxSource);
}

export function videoToTimelineTime(media: SlotPreviewMedia, videoTime: number): number {
  const videoLocal = Math.max(0, videoTime - media.clipStart);
  const capped = Math.min(videoLocal, media.timelineDuration);
  return media.layout.start + capped;
}

export function findLayoutIndex(layouts: ClipLayout[], time: number): number {
  const idx = layouts.findIndex((l) => time >= l.start && time < l.end - 1e-4);
  if (idx >= 0) return idx;
  return Math.max(0, layouts.length - 1);
}

export function findNextPlayableIndex(medias: Array<SlotPreviewMedia | null>, from: number): number {
  let next = from + 1;
  while (next < medias.length && !medias[next]) next += 1;
  return next < medias.length ? next : -1;
}

/** 同一视频文件且源时间首尾相接时可连续播放，无需切缓冲 */
export function isContiguousSameStream(
  current: SlotPreviewMedia,
  next: SlotPreviewMedia
): boolean {
  if (current.streamUrl !== next.streamUrl) return false;
  const expected = current.clipStart + current.timelineDuration;
  return Math.abs(next.clipStart - expected) < 0.08;
}
