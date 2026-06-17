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

export type SlotPreviewMedia = {
  layout: ClipLayout;
  streamUrl: string;
  clipStart: number;
  clipDuration: number;
  cssFilter: string;
};

type AssetPreviewInfo = {
  filePath?: string;
  proxyPath?: string;
  proxyPaths?: PreviewProxyPaths;
};

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
  if (!stream.url || stream.isPoster) return null;

  const usesTemplateVideo = !hasAsset && !!templateVideoPath;
  const clipStart = usesTemplateVideo
    ? Number(slot.slotStart ?? layout.start)
    : Number(slot.clipStart || 0);
  const clipDuration = Math.max(Number(slot.duration || 0), 0.1);

  return {
    layout,
    streamUrl: stream.url,
    clipStart,
    clipDuration,
    cssFilter: colorGradeToCssFilter(slot.colorGrade) || '',
  };
}

export function timelineToVideoTime(media: SlotPreviewMedia, timelineTime: number): number {
  const local = timelineTime - media.layout.start;
  const maxLocal = Math.max(media.clipDuration - 1 / 30, 0);
  return media.clipStart + Math.min(Math.max(local, 0), maxLocal);
}

export function videoToTimelineTime(media: SlotPreviewMedia, videoTime: number): number {
  const local = videoTime - media.clipStart;
  return media.layout.start + Math.max(0, local);
}

export function findLayoutIndex(layouts: ClipLayout[], time: number): number {
  const idx = layouts.findIndex((l) => time >= l.start && time < l.end - 1e-4);
  if (idx >= 0) return idx;
  return Math.max(0, layouts.length - 1);
}
