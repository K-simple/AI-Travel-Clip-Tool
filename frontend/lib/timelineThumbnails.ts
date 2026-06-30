import { apiHeaders, apiUrl } from '@/lib/api';

export type TimelineThumbnail = {
  time: number;
  url: string;
  width: number;
  height: number;
};

/** @deprecated 使用 TimelineThumbnail */
export type TimelineThumbFrame = TimelineThumbnail;

export type TimelineThumbnailProfile = {
  intervalSec: number;
  thumbnails: TimelineThumbnail[];
};

export type TimelineThumbnailProfiles = {
  low?: TimelineThumbnailProfile;
  standard?: TimelineThumbnailProfile;
  high?: TimelineThumbnailProfile;
};

export type TimelineThumbnailsResponse = {
  templateId: string;
  duration: number;
  status: 'ready' | 'processing';
  profiles: TimelineThumbnailProfiles;
};

const cache = new Map<string, TimelineThumbnailsResponse>();

/** 根据 pxPerSec 决定目标采样间隔（秒） */
export function sampleIntervalForZoom(pxPerSec: number): number {
  if (pxPerSec < 30) return 2.0;
  if (pxPerSec < 80) return 1.0;
  if (pxPerSec < 160) return 0.5;
  return 0.25;
}

const PROFILE_ORDER = ['high', 'standard', 'low'] as const;

/** 选择满足当前缩放密度的最佳档位；无 high 时降级 standard/low */
export function selectThumbnailsForZoom(
  profiles: TimelineThumbnailProfiles,
  pxPerSec: number
): { thumbnails: TimelineThumbnail[]; intervalSec: number } {
  const targetInterval = sampleIntervalForZoom(pxPerSec);

  for (const key of PROFILE_ORDER) {
    const profile = profiles[key];
    if (profile?.thumbnails?.length && profile.intervalSec <= targetInterval + 0.001) {
      return { thumbnails: profile.thumbnails, intervalSec: profile.intervalSec };
    }
  }

  for (const key of PROFILE_ORDER) {
    const profile = profiles[key];
    if (profile?.thumbnails?.length) {
      return { thumbnails: profile.thumbnails, intervalSec: profile.intervalSec };
    }
  }

  return { thumbnails: [], intervalSec: targetInterval };
}

export async function fetchTimelineThumbnailProfiles(
  templateId: string,
  options?: { includeHigh?: boolean }
): Promise<TimelineThumbnailsResponse> {
  const includeHigh = options?.includeHigh ?? false;
  const key = `${templateId}:${includeHigh ? 'high' : 'base'}`;
  const cached = cache.get(key);
  if (cached?.profiles?.low?.thumbnails?.length || cached?.profiles?.standard?.thumbnails?.length) {
    return cached;
  }

  try {
    const qs = includeHigh ? '?include_high=true' : '';
    const resp = await fetch(apiUrl(`/api/template/${templateId}/timeline-thumbnails${qs}`), {
      headers: apiHeaders(),
    });
    const data = await resp.json();
    if (!resp.ok || !data.profiles) {
      return {
        templateId,
        duration: 0,
        status: 'processing',
        profiles: {},
      };
    }

    const payload: TimelineThumbnailsResponse = {
      templateId: String(data.templateId ?? data.template_id ?? templateId),
      duration: Number(data.duration) || 0,
      status: data.status === 'ready' ? 'ready' : 'processing',
      profiles: normalizeProfiles(data.profiles),
    };

    if (
      payload.profiles.low?.thumbnails?.length ||
      payload.profiles.standard?.thumbnails?.length
    ) {
      cache.set(key, payload);
    }
    return payload;
  } catch {
    return {
      templateId,
      duration: 0,
      status: 'processing',
      profiles: {},
    };
  }
}

function normalizeProfiles(raw: unknown): TimelineThumbnailProfiles {
  if (!raw || typeof raw !== 'object') return {};
  const src = raw as Record<string, unknown>;
  const out: TimelineThumbnailProfiles = {};

  for (const key of ['low', 'standard', 'high'] as const) {
    const item = src[key];
    if (!item || typeof item !== 'object') continue;
    const profile = item as Record<string, unknown>;
    const list = profile.thumbnails ?? profile.frames;
    if (!Array.isArray(list)) continue;
    out[key] = {
      intervalSec: Number(profile.intervalSec ?? profile.interval_sec) || 0.5,
      thumbnails: list.map(normalizeThumbnail).filter(Boolean) as TimelineThumbnail[],
    };
  }
  return out;
}

function normalizeThumbnail(raw: unknown): TimelineThumbnail | null {
  if (!raw || typeof raw !== 'object') return null;
  const item = raw as Record<string, unknown>;
  const url = String(item.url ?? '').trim();
  if (!url) return null;
  return {
    time: Number(item.time) || 0,
    url,
    width: Number(item.width) || 80,
    height: Number(item.height) || 80,
  };
}

/** 每 60–100px 显示一张 frame */
export function frameWidthForZoom(pxPerSec: number): number {
  return Math.max(48, Math.min(100, Math.round(pxPerSec * 0.72)));
}

/**
 * 从全片缩略图中截取 slot 源视频时间段 [slotStart, slotEnd)，并按像素宽度降采样。
 */
export function pickThumbnailsForSlot(
  thumbnails: TimelineThumbnail[],
  slotStart: number,
  slotEnd: number,
  slotWidthPx: number,
  pxPerSec: number,
  sampleIntervalSec: number
): TimelineThumbnail[] {
  if (!thumbnails.length || slotEnd <= slotStart) return [];

  const start = Math.max(0, slotStart);
  const end = slotEnd;

  let inRange = thumbnails.filter((t) => t.time >= start && t.time < end);

  if (!inRange.length) {
    let best = thumbnails[0];
    let bestDist = Math.abs(thumbnails[0].time - start);
    for (const t of thumbnails) {
      const mid = (start + end) / 2;
      const d = Math.abs(t.time - mid);
      if (d < bestDist) {
        best = t;
        bestDist = d;
      }
    }
    inRange = [best];
  }

  const tileW = frameWidthForZoom(pxPerSec);
  const maxByWidth = Math.max(1, Math.ceil(slotWidthPx / tileW));
  const maxByInterval = Math.max(
    1,
    Math.ceil((end - start) / Math.max(sampleIntervalSec, 0.1))
  );
  const maxTiles = Math.min(maxByWidth, maxByInterval, inRange.length);

  if (inRange.length <= maxTiles) return inRange;

  const step = inRange.length / maxTiles;
  return Array.from({ length: maxTiles }, (_, i) => {
    const idx = Math.min(inRange.length - 1, Math.floor(i * step));
    return inRange[idx];
  });
}

export function countRenderedFilmstripFrames(
  thumbnails: TimelineThumbnail[],
  slots: Array<{ slotStart: number; slotEnd: number; widthPx: number }>,
  pxPerSec: number,
  sampleIntervalSec: number
): number {
  return slots.reduce((sum, slot) => {
    return (
      sum +
      pickThumbnailsForSlot(
        thumbnails,
        slot.slotStart,
        slot.slotEnd,
        slot.widthPx,
        pxPerSec,
        sampleIntervalSec
      ).length
    );
  }, 0);
}
