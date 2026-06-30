import { toMediaUrl } from '@/lib/api';
import {
  normalizeProxyPaths,
  resolvePreviewStream,
  type PreviewProxyPaths,
  type PreviewQualityId,
} from '@/lib/previewSettings';
import type { PreviewMix } from '@/lib/trackControls';
import { colorGradeToCssFilter } from '@/lib/slotEffects';
import type { ClipLayout } from '@/lib/timelineLayout';

export const PREVIEW_FRAME_SEC = 1 / 30;
export const PREVIEW_CLIP_PRELOAD_LEAD = 0.55;
export const PREVIEW_CLIP_SWITCH_EPSILON = 0.02;
/** 墙钟模式下：小于该漂移用 playbackRate 微调，避免频繁 seek */
export const PREVIEW_PLAY_RATE_NUDGE_MAX = 0.28;
/** 墙钟模式下：超过该漂移才 seek */
export const PREVIEW_PLAY_SEEK_THRESHOLD = 0.38;

export type PreviewAudioPolicy = {
  muteVideo: boolean;
  videoVolume: number;
};

export type ResolvedPreviewAudio = PreviewAudioPolicy & {
  playTemplateBgm: boolean;
  playClipAudio: boolean;
  playTemplateVideoAudio: boolean;
};

export function resolvePreviewAudioPolicy(options: {
  useOriginalAudio: boolean;
  hasMatchedAsset: boolean;
  templateMusicEnabled: boolean;
  hasTemplateAudioUrl: boolean;
  hasTemplateVideoPath: boolean;
  previewMix: PreviewMix;
}): ResolvedPreviewAudio {
  const voiceAudible = options.previewMix.videoAudible;
  const bgmAudible = options.previewMix.audioAudible;
  const useOriginalAudio = options.useOriginalAudio;

  const playClipAudio = useOriginalAudio && voiceAudible;
  const playTemplateBgm =
    options.templateMusicEnabled &&
    options.hasTemplateAudioUrl &&
    bgmAudible &&
    !useOriginalAudio;
  const activeUsesTemplateVideo =
    !options.hasMatchedAsset && Boolean(options.hasTemplateVideoPath);
  const playTemplateVideoAudio =
    !playTemplateBgm &&
    activeUsesTemplateVideo &&
    bgmAudible &&
    voiceAudible &&
    !useOriginalAudio;
  const muteVideo = playTemplateBgm || (!playClipAudio && !playTemplateVideoAudio);

  return {
    playTemplateBgm,
    playClipAudio,
    playTemplateVideoAudio,
    muteVideo,
    videoVolume: playClipAudio || playTemplateVideoAudio ? 0.9 : 0,
  };
}

export function applyPreviewVideoAudio(
  el: HTMLVideoElement,
  policy: PreviewAudioPolicy
): void {
  el.muted = policy.muteVideo;
  el.volume = policy.muteVideo ? 0 : policy.videoVolume;
}

export function unloadPreviewVideo(el: HTMLVideoElement): void {
  el.pause();
  el.removeAttribute('src');
  delete el.dataset.stream;
  delete el.dataset.filter;
  el.load();
  applyPreviewVideoAudio(el, { muteVideo: true, videoVolume: 0 });
}

export type PreviewPlayClock = {
  wall: number;
  timeline: number;
};

export type PreviewVideoSyncState = {
  pendingKey: string;
};

/** 播放中唯一主时钟：墙钟驱动时间轴（BGM 只出声，不驱动时间轴） */
export function resolveWallClockTimelineTime(
  clock: PreviewPlayClock,
  playing: boolean,
  fallbackTime: number,
  totalDuration: number
): number {
  if (playing && clock.wall > 0) {
    const elapsed = (performance.now() - clock.wall) / 1000;
    return Math.min(Math.max(0, clock.timeline + elapsed), totalDuration);
  }
  return Math.min(Math.max(0, fallbackTime), totalDuration);
}

/** 播放中的主时间轴：墙钟驱动（BGM/模板预览）；仅「素材原声」槽位跟视频元素 */
export function resolveMasterTimelineTime(options: {
  playing: boolean;
  media: SlotPreviewMedia;
  frontEl: HTMLVideoElement;
  policy: ResolvedPreviewAudio;
  clock: PreviewPlayClock;
  fallbackTime: number;
  totalDuration: number;
}): number {
  const { playing, media, frontEl, policy, clock, fallbackTime, totalDuration } = options;

  if (policy.playClipAudio) {
    return Math.min(videoToTimelineTime(media, frontEl.currentTime), totalDuration);
  }

  return resolveWallClockTimelineTime(clock, playing, fallbackTime, totalDuration);
}

export type PreviewVideoSyncOptions = {
  /** 播放中 true；拖拽预览 false，避免 play→pause 卡顿 */
  autoplay?: boolean;
  /** 与目标时间差小于该值则跳过 seek（拖拽逐帧预览） */
  seekEpsilon?: number;
};

export async function syncPreviewVideoToSlot(
  el: HTMLVideoElement,
  media: SlotPreviewMedia,
  timelineT: number,
  policy: PreviewAudioPolicy,
  state: PreviewVideoSyncState,
  options: PreviewVideoSyncOptions = {}
): Promise<void> {
  const autoplay = options.autoplay ?? true;
  const seekEpsilon = options.seekEpsilon ?? 0.12;
  const targetT = timelineToVideoTime(media, timelineT);
  const key = `${media.streamUrl}|${media.layout.start.toFixed(3)}|${targetT.toFixed(2)}|${autoplay ? 1 : 0}`;

  if (state.pendingKey === key) return;
  state.pendingKey = key;

  try {
    applyPreviewVideoAudio(el, policy);

    if (el.dataset.stream !== media.streamUrl) {
      await preparePreviewVideo(el, media, targetT, autoplay, policy);
      return;
    }

    if (el.ended || Math.abs(el.currentTime - targetT) > seekEpsilon) {
      await seekVideoElement(el, targetT);
    }
    if (autoplay && el.paused) {
      await el.play().catch(() => undefined);
    } else if (!autoplay) {
      el.pause();
    }
  } finally {
    if (state.pendingKey === key) state.pendingKey = '';
  }
}

/** 暂停/拖拽：将 BGM 定位到时间轴位置（不重置到 0） */
export function seekPreviewBgm(
  bgm: HTMLAudioElement | null | undefined,
  policy: ResolvedPreviewAudio,
  timelineT: number
): void {
  if (!bgm || !policy.playTemplateBgm) return;
  bgm.pause();
  if (bgm.muted || bgm.volume < 0.1) {
    bgm.volume = 0.85;
    bgm.muted = false;
  }
  try {
    if (Math.abs(bgm.currentTime - timelineT) > PREVIEW_FRAME_SEC) {
      bgm.currentTime = timelineT;
    }
  } catch {
    /* ignore */
  }
}

export function applyBgmPolicyTransition(
  bgm: HTMLAudioElement | null | undefined,
  policy: ResolvedPreviewAudio,
  prevPolicy: ResolvedPreviewAudio | null,
  timelineT: number,
  playing: boolean
): void {
  if (!bgm) return;

  const wasBgm = Boolean(prevPolicy?.playTemplateBgm);
  const isBgm = policy.playTemplateBgm;

  if (isBgm && !wasBgm) {
    try {
      bgm.currentTime = timelineT;
    } catch {
      /* ignore */
    }
    bgm.volume = 0.85;
    bgm.muted = false;
    if (playing) void bgm.play().catch(() => undefined);
    return;
  }

  if (!isBgm && wasBgm) {
    bgm.volume = 0;
    bgm.muted = true;
    bgm.pause();
    return;
  }

  if (isBgm) {
    if (bgm.muted || bgm.volume < 0.1) {
      bgm.volume = 0.85;
      bgm.muted = false;
    }
    if (playing && bgm.paused) {
      void bgm.play().catch(() => undefined);
    }
    return;
  }

  if (!bgm.muted || bgm.volume > 0 || !bgm.paused) {
    bgm.volume = 0;
    bgm.muted = true;
    bgm.pause();
  }
}

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
  autoplay: boolean,
  audio?: PreviewAudioPolicy
): Promise<void> {
  if (audio) {
    applyPreviewVideoAudio(el, audio);
  }

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
  if (audio) {
    applyPreviewVideoAudio(el, audio);
  }
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
  const capped = Math.min(videoLocal, media.timelineDuration, media.sourceDuration);
  return media.layout.start + capped;
}

export function findLayoutIndex(layouts: ClipLayout[], time: number): number {
  const idx = layouts.findIndex((l) => time >= l.start && time < l.end);
  if (idx >= 0) return idx;
  if (time >= (layouts[layouts.length - 1]?.end ?? 0)) {
    return Math.max(0, layouts.length - 1);
  }
  return 0;
}

export function findNextPlayableIndex(medias: Array<SlotPreviewMedia | null>, from: number): number {
  let next = from + 1;
  while (next < medias.length && !medias[next]) next += 1;
  return next < medias.length ? next : -1;
}

export function getEffectivePlayDuration(media: SlotPreviewMedia): number {
  return Math.min(media.timelineDuration, media.sourceDuration);
}

export function shouldPreloadNextPreviewSlot(
  media: SlotPreviewMedia,
  timelineT: number
): boolean {
  const effectiveDur = getEffectivePlayDuration(media);
  const preloadAt =
    media.layout.start + effectiveDur - PREVIEW_CLIP_PRELOAD_LEAD - PREVIEW_CLIP_SWITCH_EPSILON;
  return timelineT >= preloadAt;
}

export function shouldAdvancePreviewSlot(
  media: SlotPreviewMedia,
  frontEl: HTMLVideoElement,
  timelineT: number
): boolean {
  const effectiveDur = getEffectivePlayDuration(media);
  const switchAt = media.layout.start + effectiveDur - PREVIEW_CLIP_SWITCH_EPSILON;
  const videoLocal = Math.max(0, frontEl.currentTime - media.clipStart);
  const atSourceEnd = videoLocal >= effectiveDur - PREVIEW_CLIP_SWITCH_EPSILON;
  return timelineT >= switchAt - 1e-3 || atSourceEnd || frontEl.ended;
}

/** 同一视频文件且源时间首尾相接时可连续播放，无需切缓冲 */
export function isContiguousSameStream(
  current: SlotPreviewMedia,
  next: SlotPreviewMedia
): boolean {
  if (current.streamUrl !== next.streamUrl) return false;
  const expected = current.clipStart + getEffectivePlayDuration(current);
  return Math.abs(next.clipStart - expected) < 0.08;
}
