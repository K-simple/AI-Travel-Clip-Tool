const TIMELINE_HEIGHT_KEY = 'editor-timeline-panel-height';
const ASSET_WIDTH_KEY = 'editor-asset-panel-width';
const PLAYER_WIDTH_KEY = 'editor-player-panel-width';

export const DEFAULT_TIMELINE_PANEL_HEIGHT = 260;
export const MIN_TIMELINE_PANEL_HEIGHT = 120;
export const MIN_WORKSPACE_TOP_HEIGHT = 200;

export const DEFAULT_ASSET_PANEL_WIDTH = 320;
export const MIN_ASSET_PANEL_WIDTH = 240;
export const MAX_ASSET_PANEL_WIDTH = 520;

export const DEFAULT_PLAYER_PANEL_WIDTH = 420;
export const MIN_PLAYER_PANEL_WIDTH = 300;
export const MAX_PLAYER_PANEL_WIDTH = 640;

export function maxTimelinePanelHeight(
  workspaceHeight?: number,
  viewportHeight = typeof window !== 'undefined' ? window.innerHeight : 900
): number {
  if (workspaceHeight && workspaceHeight > MIN_WORKSPACE_TOP_HEIGHT + MIN_TIMELINE_PANEL_HEIGHT) {
    return Math.max(MIN_TIMELINE_PANEL_HEIGHT, workspaceHeight - MIN_WORKSPACE_TOP_HEIGHT);
  }
  return Math.max(MIN_TIMELINE_PANEL_HEIGHT, Math.floor(viewportHeight * 0.55));
}

export function clampTimelinePanelHeight(
  height: number,
  workspaceHeight?: number,
  viewportHeight?: number
): number {
  const max = maxTimelinePanelHeight(workspaceHeight, viewportHeight);
  return Math.round(Math.max(MIN_TIMELINE_PANEL_HEIGHT, Math.min(max, height)));
}

export function clampAssetPanelWidth(width: number, viewportWidth = typeof window !== 'undefined' ? window.innerWidth : 1280): number {
  const max = Math.min(MAX_ASSET_PANEL_WIDTH, Math.floor(viewportWidth * 0.42));
  return Math.round(Math.max(MIN_ASSET_PANEL_WIDTH, Math.min(max, width)));
}

export function clampPlayerPanelWidth(width: number, viewportWidth = typeof window !== 'undefined' ? window.innerWidth : 1280): number {
  const max = Math.min(MAX_PLAYER_PANEL_WIDTH, Math.floor(viewportWidth * 0.52));
  return Math.round(Math.max(MIN_PLAYER_PANEL_WIDTH, Math.min(max, width)));
}

function readStoredNumber(key: string, fallback: number, clamp: (n: number) => number): number {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) return fallback;
    return clamp(parsed);
  } catch {
    return fallback;
  }
}

export function loadTimelinePanelHeight(workspaceHeight?: number): number {
  return readStoredNumber(TIMELINE_HEIGHT_KEY, DEFAULT_TIMELINE_PANEL_HEIGHT, (n) =>
    clampTimelinePanelHeight(n, workspaceHeight)
  );
}

export function saveTimelinePanelHeight(height: number, workspaceHeight?: number): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(
      TIMELINE_HEIGHT_KEY,
      String(clampTimelinePanelHeight(height, workspaceHeight))
    );
  } catch {
    /* ignore */
  }
}

export function loadAssetPanelWidth(): number {
  return readStoredNumber(ASSET_WIDTH_KEY, DEFAULT_ASSET_PANEL_WIDTH, clampAssetPanelWidth);
}

export function saveAssetPanelWidth(width: number): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(ASSET_WIDTH_KEY, String(clampAssetPanelWidth(width)));
  } catch {
    /* ignore */
  }
}

export function loadPlayerPanelWidth(): number {
  return readStoredNumber(PLAYER_WIDTH_KEY, DEFAULT_PLAYER_PANEL_WIDTH, clampPlayerPanelWidth);
}

export function savePlayerPanelWidth(width: number): void {
  if (typeof window === 'undefined') return;
  try {
    localStorage.setItem(PLAYER_WIDTH_KEY, String(clampPlayerPanelWidth(width)));
  } catch {
    /* ignore */
  }
}
