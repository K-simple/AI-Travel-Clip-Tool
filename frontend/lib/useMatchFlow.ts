import type { Dispatch, SetStateAction } from 'react';
import { useCallback, useState } from 'react';
import { apiHeaders, apiUrl } from '@/lib/api';
import { strategyToSettings, type MatchStrategy } from '@/lib/matchStrategy';
import { isBaseOnlyTimeline } from '@/lib/slotTimelineHelpers';
import { timelineToSlots, type TemplateSlot } from '@/lib/timeline';
import type { MatchWeights } from '@/components/PropertiesPanel';

type UseMatchFlowOptions = {
  projectId: string | null;
  templateId: string | null;
  slots: TemplateSlot[];
  assets: Array<{ id: string }>;
  matchStrategy: MatchStrategy;
  matchWeights: MatchWeights;
  saveProject: () => Promise<boolean>;
  setSlots: Dispatch<SetStateAction<TemplateSlot[]>>;
  setIsPlaying: (playing: boolean) => void;
};

export function useMatchFlow({
  projectId,
  templateId,
  slots,
  assets,
  matchStrategy,
  matchWeights,
  saveProject,
  setSlots,
  setIsPlaying,
}: UseMatchFlowOptions) {
  const [matching, setMatching] = useState(false);
  const [matchMessage, setMatchMessage] = useState('');
  const [matchError, setMatchError] = useState('');

  const runAutoMatch = useCallback(async () => {
    if (!projectId || !templateId) {
      alert('请先上传模板并创建项目');
      return;
    }
    if (!assets.length) {
      alert('请先上传素材');
      return;
    }
    if (isBaseOnlyTimeline(slots)) {
      alert('请先点击「按原视频画面切分」或「按字幕一句一画面」，再进行素材匹配。');
      return;
    }

    setMatching(true);
    setMatchError('');
    setMatchMessage('');

    try {
      const saved = await saveProject();
      if (!saved) {
        throw new Error('保存当前项目失败');
      }

      const resp = await fetch(apiUrl('/api/match/run'), {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({
          project_id: projectId,
          template_id: templateId,
          asset_ids: assets.map((asset) => asset.id),
          overwrite: true,
          settings: strategyToSettings(matchStrategy),
          strategy: matchStrategy,
          weights: matchWeights,
        }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.success) {
        throw new Error(data.detail || data.error || 'AI 自动匹配失败');
      }

      if (Array.isArray(data.timeline)) {
        setSlots(timelineToSlots(data.timeline as Record<string, unknown>[]));
      }
      setIsPlaying(false);

      const parts = [
        `智能匹配完成：成功 ${data.matched_count || 0} 个，未匹配 ${data.unmatched_count || 0} 个`,
        data.understanding_warning as string | undefined,
      ].filter(Boolean);
      setMatchMessage(parts.join('；'));
    } catch (err: unknown) {
      console.error(err);
      setMatchError(err instanceof Error ? err.message : 'AI 自动匹配失败');
    } finally {
      setMatching(false);
    }
  }, [
    projectId,
    templateId,
    slots,
    assets,
    matchStrategy,
    matchWeights,
    saveProject,
    setSlots,
    setIsPlaying,
  ]);

  return {
    matching,
    matchMessage,
    matchError,
    setMatchMessage,
    setMatchError,
    runAutoMatch,
  };
}
