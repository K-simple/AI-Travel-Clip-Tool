import type { SlotEffects } from '@/lib/slotEffects';

export type OverlayClip = {
  id: string;
  assetId: string;
  assetFilePath?: string;
  label?: string;
  thumbnail?: string;
  dstIn: number;
  dstOut: number;
  srcIn?: number;
  speed?: number;
  opticalFlow?: boolean;
  keyframes?: SlotEffects['keyframes'];
  colorGrade?: SlotEffects['colorGrade'];
  mask?: SlotEffects['mask'];
  transitionOut?: { type: string; duration: number };
};

export type OverlayTracks = {
  v2: OverlayClip[];
  v3: OverlayClip[];
};

export function overlayClipToEdl(clip: OverlayClip) {
  const dur = Math.max(0.1, clip.dstOut - clip.dstIn);
  return {
    clip_id: clip.id,
    asset_seg_id: clip.assetId,
    asset_file_path: clip.assetFilePath || '',
    src_in: clip.srcIn ?? 0,
    src_out: (clip.srcIn ?? 0) + dur,
    dst_in: clip.dstIn,
    dst_out: clip.dstOut,
    speed: clip.speed ?? 1,
    optical_flow: clip.opticalFlow ?? false,
    keyframes: clip.keyframes ?? [],
    color_grade: clip.colorGrade,
    mask: clip.mask,
    transition_out: clip.transitionOut,
  };
}

export function overlayTracksToPayload(tracks: OverlayTracks) {
  return {
    v2: tracks.v2.map(overlayClipToEdl),
    v3: tracks.v3.map(overlayClipToEdl),
  };
}

export function overlayLayouts(clips: OverlayClip[], pxPerSec: number) {
  return clips.map((clip) => ({
    clip,
    left: clip.dstIn * pxPerSec,
    width: Math.max(24, (clip.dstOut - clip.dstIn) * pxPerSec),
  }));
}

export function createOverlayClip(
  asset: { id: string; filePath?: string; title?: string; thumbnail?: string },
  dstIn: number,
  duration: number
): OverlayClip {
  return {
    id: `ov-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    assetId: asset.id,
    assetFilePath: asset.filePath,
    label: asset.title,
    thumbnail: asset.thumbnail,
    dstIn,
    dstOut: dstIn + duration,
    srcIn: 0,
    speed: 1,
  };
}

export function parseOverlayTracksFromEdl(edl: Record<string, unknown> | null): OverlayTracks {
  const tracks = (edl?.tracks as Record<string, unknown>)?.video as
    | Array<{ track_id: string; clips: Record<string, unknown>[] }>
    | undefined;
  if (!tracks?.length) return { v2: [], v3: [] };

  const toClip = (raw: Record<string, unknown>): OverlayClip => ({
    id: String(raw.clip_id || raw.id || ''),
    assetId: String(raw.asset_seg_id || raw.asset_id || ''),
    assetFilePath: String(raw.asset_file_path || ''),
    label: String(raw.label || ''),
    thumbnail: String(raw.thumbnail || ''),
    dstIn: Number(raw.dst_in ?? 0),
    dstOut: Number(raw.dst_out ?? 0),
    srcIn: Number(raw.src_in ?? 0),
    speed: Number(raw.speed ?? 1),
    opticalFlow: Boolean(raw.optical_flow),
    keyframes: (raw.keyframes as OverlayClip['keyframes']) || [],
    colorGrade: raw.color_grade as OverlayClip['colorGrade'],
    mask: raw.mask as OverlayClip['mask'],
    transitionOut: raw.transition_out as OverlayClip['transitionOut'],
  });

  const v2 = tracks.find((t) => t.track_id === 'v2')?.clips?.map(toClip) ?? [];
  const v3 = tracks.find((t) => t.track_id === 'v3')?.clips?.map(toClip) ?? [];
  return { v2, v3 };
}
