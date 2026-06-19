import type { TrackKey } from '@/lib/trackControls';
import { ALL_TRACK_LAYOUT, getTrackDef } from '@/lib/timelineTracks';

export const TRACK_HEIGHTS_STORAGE_KEY = '__heights';

export type TrackHeightMap = Partial<Record<TrackKey, number>>;

export const MIN_TRACK_HEIGHT = 24;
export const MAX_TRACK_HEIGHT = 220;

export function getDefaultTrackHeight(key: TrackKey): number {
  return getTrackDef(key)?.height ?? 32;
}

export function clampTrackHeight(height: number): number {
  return Math.round(Math.max(MIN_TRACK_HEIGHT, Math.min(MAX_TRACK_HEIGHT, height)));
}

export function resolveTrackHeight(key: TrackKey, overrides?: TrackHeightMap): number {
  const custom = overrides?.[key];
  if (typeof custom === 'number' && Number.isFinite(custom)) {
    return clampTrackHeight(custom);
  }
  return getDefaultTrackHeight(key);
}

export function extractTrackHeights(raw: unknown): TrackHeightMap {
  if (!raw || typeof raw !== 'object') return {};
  const heights = (raw as Record<string, unknown>)[TRACK_HEIGHTS_STORAGE_KEY];
  if (!heights || typeof heights !== 'object') return {};

  const result: TrackHeightMap = {};
  for (const def of ALL_TRACK_LAYOUT) {
    const value = (heights as Record<string, unknown>)[def.key];
    if (typeof value === 'number' && Number.isFinite(value)) {
      result[def.key] = clampTrackHeight(value);
    }
  }
  return result;
}

export function embedTrackHeights(
  controls: Record<TrackKey, unknown>,
  heights: TrackHeightMap
): Record<string, unknown> {
  const payload: Record<string, unknown> = { ...controls };
  const cleaned = Object.fromEntries(
    Object.entries(heights).filter(([, value]) => typeof value === 'number' && Number.isFinite(value))
  ) as TrackHeightMap;

  if (Object.keys(cleaned).length) {
    payload[TRACK_HEIGHTS_STORAGE_KEY] = cleaned;
  } else {
    delete payload[TRACK_HEIGHTS_STORAGE_KEY];
  }
  return payload;
}
