import type { ClipLayout } from './timelineLayout';

const VIDEO_EXT = new Set(['.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v']);

export function isVideoFile(file: File): boolean {
  if (file.type.startsWith('video/')) return true;
  const name = file.name.toLowerCase();
  return [...VIDEO_EXT].some((ext) => name.endsWith(ext));
}

export function getVideoFilesFromDataTransfer(dt: DataTransfer): File[] {
  const files: File[] = [];
  if (dt.files?.length) {
    for (let i = 0; i < dt.files.length; i++) {
      const file = dt.files[i];
      if (isVideoFile(file)) files.push(file);
    }
  }
  return files;
}

export function isFileDrag(dt: DataTransfer): boolean {
  return dt.types.includes('Files');
}

export function isInternalAssetDrag(dt: DataTransfer): boolean {
  return dt.types.includes('text/plain') && !dt.types.includes('Files');
}

export function canAcceptTimelineDrop(dt: DataTransfer): boolean {
  return isFileDrag(dt) || isInternalAssetDrag(dt);
}

export function findSlotIdAtTime(layouts: ClipLayout[], time: number): string | null {
  const hit = layouts.find((l) => time >= l.start && time < l.end);
  return hit?.slot.id ?? layouts[layouts.length - 1]?.slot.id ?? null;
}

export function findFirstEmptySlotId(
  layouts: ClipLayout[],
  slots: { id: string; matchedAssetId?: string }[]
): string | null {
  const empty = slots.find((s) => !s.matchedAssetId);
  return empty?.id ?? layouts[0]?.slot.id ?? null;
}
