/** 预览区画幅与画质（仅影响播放，不影响导出） */

export type AspectRatioId =
  | '9:16'
  | '16:9'
  | '4:3'
  | '2:1'
  | '3:4'
  | '5.8'
  | '1:1'
  | '1:2'
  | '2.35:1'
  | '1.85:1';

export type PreviewQualityId = 'original' | 'clear' | 'smooth' | 'low';

/** 实际播放使用的流档位（可能与所选画质不同，表示回退） */
export type PreviewActiveTier = 'original' | 'clear' | 'smooth' | 'low' | 'poster';

export type PreviewProxyPaths = {
  clear?: string;
  smooth?: string;
  low?: string;
};

export type AspectRatioPreset = {
  id: AspectRatioId;
  label: string;
  /** CSS aspect-ratio 宽/高 */
  ratio: number;
};

export type PreviewQualityPreset = {
  id: PreviewQualityId;
  label: string;
  hint: string;
  description: string;
  resolutionLabel: string;
};

export type PreviewStreamInfo = {
  /** 所选画质档位 */
  requestedQuality: PreviewQualityId;
  /** 实际播放档位 */
  activeTier: PreviewActiveTier;
  /** 播放 URL；poster 模式为空 */
  url: string;
  /** 是否回退到低于所选档位的流 */
  isFallback: boolean;
  /** 低清档缩略图占位 */
  isPoster: boolean;
  /** 左上角角标 */
  badge: string;
  /** 状态说明（菜单 / tooltip） */
  statusText: string;
};

export type QualityAvailability = {
  id: PreviewQualityId;
  /** 该档位是否可立即使用（含合理回退） */
  playable: boolean;
  /** 代理是否已生成 */
  proxyReady: boolean;
  /** 菜单右侧状态文案 */
  statusText: string;
};

export const PREVIEW_QUALITY_STORAGE_KEY = 'editor-preview-quality';

export const ASPECT_RATIO_PRESETS: AspectRatioPreset[] = [
  { id: '9:16', label: '9:16', ratio: 9 / 16 },
  { id: '16:9', label: '16:9', ratio: 16 / 9 },
  { id: '4:3', label: '4:3', ratio: 4 / 3 },
  { id: '2:1', label: '2:1', ratio: 2 / 1 },
  { id: '3:4', label: '3:4', ratio: 3 / 4 },
  { id: '5.8', label: '5.8寸', ratio: 9 / 19.5 },
  { id: '1:1', label: '1:1', ratio: 1 },
  { id: '1:2', label: '1:2', ratio: 1 / 2 },
  { id: '2.35:1', label: '2.35:1', ratio: 2.35 },
  { id: '1.85:1', label: '1.85:1', ratio: 1.85 },
];

export const PREVIEW_QUALITY_PRESETS: PreviewQualityPreset[] = [
  {
    id: 'original',
    label: '原画',
    hint: '始终播放原始上传文件',
    description: '完整源文件，细节最多，占用带宽最大',
    resolutionLabel: '源分辨率',
  },
  {
    id: 'clear',
    label: '清晰画质',
    hint: '1080p 专用代理（源片>1080p 时生成）',
    description: '1080p 预览流；源片≤1080p 时直接播放原片',
    resolutionLabel: '1080p',
  },
  {
    id: 'smooth',
    label: '流畅画质',
    hint: '720p 专用代理，编辑默认推荐',
    description: '720p 预览流，兼顾流畅度与清晰度',
    resolutionLabel: '720p',
  },
  {
    id: 'low',
    label: '低清画质',
    hint: '480p 专用代理，加载最快',
    description: '480p 预览流；未就绪时缩略图占位，不拉原片',
    resolutionLabel: '480p',
  },
];

export function normalizeProxyPaths(raw?: PreviewProxyPaths | null): PreviewProxyPaths {
  if (!raw) return {};
  return {
    clear: raw.clear || '',
    smooth: raw.smooth || '',
    low: raw.low || '',
  };
}

export function isPreviewQualityId(value: string): value is PreviewQualityId {
  return value === 'original' || value === 'clear' || value === 'smooth' || value === 'low';
}

export function loadStoredPreviewQuality(): PreviewQualityId {
  if (typeof window === 'undefined') return 'smooth';
  try {
    const stored = window.localStorage.getItem(PREVIEW_QUALITY_STORAGE_KEY);
    if (stored && isPreviewQualityId(stored)) return stored;
  } catch {
    /* ignore */
  }
  return 'smooth';
}

export function storePreviewQuality(quality: PreviewQualityId): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(PREVIEW_QUALITY_STORAGE_KEY, quality);
  } catch {
    /* ignore */
  }
}

/**
 * 严格按档位解析预览流：
 * - 原画：仅原片
 * - 清晰：1080p 代理 → 原片
 * - 流畅：720p 代理 → 1080p 代理 → 原片
 * - 低清：480p 代理 → 缩略图占位（不降级到更高码率流）
 */
export function resolvePreviewStream(
  originalUrl: string,
  proxies: PreviewProxyPaths,
  quality: PreviewQualityId,
  options?: { hasPoster?: boolean }
): PreviewStreamInfo {
  const p = normalizeProxyPaths(proxies);
  const preset = PREVIEW_QUALITY_PRESETS.find((q) => q.id === quality)!;
  const empty: PreviewStreamInfo = {
    requestedQuality: quality,
    activeTier: 'original',
    url: '',
    isFallback: false,
    isPoster: false,
    badge: '',
    statusText: '暂无视频',
  };

  if (!originalUrl) return empty;

  switch (quality) {
    case 'original':
      return {
        requestedQuality: quality,
        activeTier: 'original',
        url: originalUrl,
        isFallback: false,
        isPoster: false,
        badge: '源分辨率',
        statusText: '播放原始文件',
      };

    case 'clear':
      if (p.clear) {
        return {
          requestedQuality: quality,
          activeTier: 'clear',
          url: p.clear,
          isFallback: false,
          isPoster: false,
          badge: '1080p',
          statusText: '1080p 预览代理',
        };
      }
      return {
        requestedQuality: quality,
        activeTier: 'original',
        url: originalUrl,
        isFallback: true,
        isPoster: false,
        badge: '原文件',
        statusText: '源片≤1080p 或代理未生成，播放原片',
      };

    case 'smooth':
      if (p.smooth) {
        return {
          requestedQuality: quality,
          activeTier: 'smooth',
          url: p.smooth,
          isFallback: false,
          isPoster: false,
          badge: '720p',
          statusText: '720p 预览代理',
        };
      }
      if (p.clear) {
        return {
          requestedQuality: quality,
          activeTier: 'clear',
          url: p.clear,
          isFallback: true,
          isPoster: false,
          badge: '1080p',
          statusText: '720p 生成中，暂用 1080p',
        };
      }
      return {
        requestedQuality: quality,
        activeTier: 'original',
        url: originalUrl,
        isFallback: true,
        isPoster: false,
        badge: '原文件',
        statusText: '720p 生成中，暂用原片',
      };

    case 'low':
      if (p.low) {
        return {
          requestedQuality: quality,
          activeTier: 'low',
          url: p.low,
          isFallback: false,
          isPoster: false,
          badge: '480p',
          statusText: '480p 预览代理',
        };
      }
      if (options?.hasPoster) {
        return {
          requestedQuality: quality,
          activeTier: 'poster',
          url: '',
          isFallback: true,
          isPoster: true,
          badge: '缩略图',
          statusText: '480p 生成中，缩略图占位',
        };
      }
      return {
        requestedQuality: quality,
        activeTier: 'original',
        url: originalUrl,
        isFallback: true,
        isPoster: false,
        badge: '原文件',
        statusText: '480p 生成中，暂用原片',
      };

    default:
      return { ...empty, statusText: preset.description };
  }
}

export function getQualityAvailability(
  proxies: PreviewProxyPaths,
  hasOriginal: boolean,
  hasPoster: boolean
): QualityAvailability[] {
  const p = normalizeProxyPaths(proxies);

  return PREVIEW_QUALITY_PRESETS.map((preset) => {
    switch (preset.id) {
      case 'original':
        return {
          id: preset.id,
          playable: hasOriginal,
          proxyReady: hasOriginal,
          statusText: hasOriginal ? '源文件' : '暂无',
        };
      case 'clear':
        return {
          id: preset.id,
          playable: hasOriginal,
          proxyReady: Boolean(p.clear),
          statusText: p.clear ? '1080p 就绪' : hasOriginal ? '播放原片' : '暂无',
        };
      case 'smooth':
        return {
          id: preset.id,
          playable: hasOriginal,
          proxyReady: Boolean(p.smooth),
          statusText: p.smooth
            ? '720p 就绪'
            : p.clear
              ? '720p 生成中'
              : hasOriginal
                ? '暂用原片'
                : '暂无',
        };
      case 'low':
        return {
          id: preset.id,
          playable: Boolean(p.low || hasPoster || hasOriginal),
          proxyReady: Boolean(p.low),
          statusText: p.low
            ? '480p 就绪'
            : hasPoster
              ? '缩略图占位'
              : hasOriginal
                ? '480p 生成中'
                : '暂无',
        };
      default:
        return { id: preset.id, playable: false, proxyReady: false, statusText: '' };
    }
  });
}

export function previewPreloadForQuality(quality: PreviewQualityId): 'auto' | 'metadata' | 'none' {
  switch (quality) {
    case 'original':
      return 'auto';
    case 'clear':
      return 'metadata';
    case 'smooth':
      return 'metadata';
    case 'low':
      return 'none';
    default:
      return 'metadata';
  }
}

export function previewQualityBadge(info: PreviewStreamInfo): string {
  if (!info.url && !info.isPoster) return '';
  if (info.isPoster) return '缩略图';
  if (info.isFallback && info.requestedQuality !== info.activeTier) {
    return `${info.badge} · 回退`;
  }
  return info.badge;
}
