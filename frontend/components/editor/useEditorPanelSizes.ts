'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  clampAssetPanelWidth,
  clampPlayerPanelWidth,
  clampTimelinePanelHeight,
  DEFAULT_ASSET_PANEL_WIDTH,
  DEFAULT_PLAYER_PANEL_WIDTH,
  DEFAULT_TIMELINE_PANEL_HEIGHT,
  loadAssetPanelWidth,
  loadPlayerPanelWidth,
  loadTimelinePanelHeight,
  saveAssetPanelWidth,
  savePlayerPanelWidth,
  saveTimelinePanelHeight,
} from '@/lib/editorLayout';

export function useEditorPanelSizes() {
  const [timelinePanelHeight, setTimelineHeightState] = useState(DEFAULT_TIMELINE_PANEL_HEIGHT);
  const [assetPanelWidth, setAssetWidthState] = useState(DEFAULT_ASSET_PANEL_WIDTH);
  const [playerPanelWidth, setPlayerWidthState] = useState(DEFAULT_PLAYER_PANEL_WIDTH);

  useEffect(() => {
    setTimelineHeightState(loadTimelinePanelHeight());
    setAssetWidthState(loadAssetPanelWidth());
    setPlayerWidthState(loadPlayerPanelWidth());
  }, []);

  useEffect(() => {
    const onResize = () => {
      setTimelineHeightState((current) => {
        const clamped = clampTimelinePanelHeight(current);
        if (clamped !== current) saveTimelinePanelHeight(clamped);
        return clamped;
      });
      setAssetWidthState((current) => {
        const clamped = clampAssetPanelWidth(current);
        if (clamped !== current) saveAssetPanelWidth(clamped);
        return clamped;
      });
      setPlayerWidthState((current) => {
        const clamped = clampPlayerPanelWidth(current);
        if (clamped !== current) savePlayerPanelWidth(clamped);
        return clamped;
      });
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const setTimelinePanelHeight = useCallback((next: number, workspaceHeight?: number) => {
    const clamped = clampTimelinePanelHeight(next, workspaceHeight);
    setTimelineHeightState(clamped);
    saveTimelinePanelHeight(clamped, workspaceHeight);
  }, []);

  const setAssetPanelWidth = useCallback((next: number) => {
    const clamped = clampAssetPanelWidth(next);
    setAssetWidthState(clamped);
    saveAssetPanelWidth(clamped);
  }, []);

  const setPlayerPanelWidth = useCallback((next: number) => {
    const clamped = clampPlayerPanelWidth(next);
    setPlayerWidthState(clamped);
    savePlayerPanelWidth(clamped);
  }, []);

  const resetTimelinePanelHeight = useCallback(() => {
    setTimelinePanelHeight(DEFAULT_TIMELINE_PANEL_HEIGHT);
  }, [setTimelinePanelHeight]);

  const resetAssetPanelWidth = useCallback(() => {
    setAssetPanelWidth(DEFAULT_ASSET_PANEL_WIDTH);
  }, [setAssetPanelWidth]);

  const resetPlayerPanelWidth = useCallback(() => {
    setPlayerPanelWidth(DEFAULT_PLAYER_PANEL_WIDTH);
  }, [setPlayerPanelWidth]);

  return {
    timelinePanelHeight,
    setTimelinePanelHeight,
    resetTimelinePanelHeight,
    assetPanelWidth,
    setAssetPanelWidth,
    resetAssetPanelWidth,
    playerPanelWidth,
    setPlayerPanelWidth,
    resetPlayerPanelWidth,
  };
}
