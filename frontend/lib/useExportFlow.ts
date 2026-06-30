import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiHeaders, apiUrl } from '@/lib/api';
import { buildExportPayload } from '@/lib/exportSettings';
import {
  buildExportPrecheck,
  formatExportPrecheckDialog,
} from '@/lib/exportPrecheck';
import { formatExportError } from '@/lib/formatExportError';
import type { TrackControls, TrackKey } from '@/lib/trackControls';
import type { TemplateSlot } from '@/lib/timeline';
import type { TemplateProcessingState } from '@/lib/useTemplateProcessing';
import {
  exportCapCutDraftSync,
  fetchCapCutStatusWithRetry,
  guessMediaBaseUrl,
  installAndOpenCapCutDraft,
  pollCapCutExportTask,
  type CapCutExportResult,
  type CapCutMateStatus,
} from '@/lib/capcutExport';

type AssetLike = {
  id: string;
  title: string;
  processingStatus?: 'processing' | 'ready' | 'failed';
};

type UseExportFlowOptions = {
  projectId: string | null;
  templateId: string | null;
  slots: TemplateSlot[];
  assets: AssetLike[];
  templateProcessing: TemplateProcessingState;
  matching: boolean;
  subtitleRecognizing?: boolean;
  saveProject: () => Promise<boolean>;
  trackControls: Record<TrackKey, TrackControls>;
  templateMusicEnabled: boolean;
};

export function useExportFlow({
  projectId,
  templateId,
  slots,
  assets,
  templateProcessing,
  matching,
  subtitleRecognizing = false,
  saveProject,
  trackControls,
  templateMusicEnabled,
}: UseExportFlowOptions) {
  const [exportUrl, setExportUrl] = useState<string | null>(null);
  const [exportStatus, setExportStatus] = useState('');
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState('');
  const [exportResolution, setExportResolution] = useState('1080x1920');
  const [addSubtitles, setAddSubtitles] = useState(true);
  const [exportProgress, setExportProgress] = useState(0);

  const [capCutDraftUrl, setCapCutDraftUrl] = useState<string | null>(null);
  const [capCutExporting, setCapCutExporting] = useState(false);
  const [capCutExportProgress, setCapCutExportProgress] = useState(0);
  const [capCutStatus, setCapCutStatus] = useState('');
  const [capCutReplaceableMode, setCapCutReplaceableMode] = useState(false);
  const [capCutMateStatus, setCapCutMateStatus] = useState<CapCutMateStatus | null>(null);

  const exportBusy = exporting || capCutExporting;

  const refreshCapCutMateStatus = useCallback(async () => {
    const status = await fetchCapCutStatusWithRetry(2, 300);
    setCapCutMateStatus(status);
    if (status?.ready) {
      setCapCutStatus((prev) =>
        prev.includes('剪映小助手未连接') || prev.includes('剪映小助手未就绪') ? '' : prev
      );
    }
    return status;
  }, []);

  useEffect(() => {
    void refreshCapCutMateStatus();
    const timer = setInterval(() => void refreshCapCutMateStatus(), 8000);
    return () => clearInterval(timer);
  }, [refreshCapCutMateStatus]);

  const exportPrecheck = useMemo(
    () =>
      buildExportPrecheck(slots, assets, templateProcessing, {
        matching,
        exporting: exportBusy,
        capcutReplaceable: capCutReplaceableMode,
        subtitleRecognizing,
      }),
    [slots, assets, templateProcessing, matching, exportBusy, capCutReplaceableMode, subtitleRecognizing]
  );

  const pollExportTask = useCallback(async (taskId: string) => {
    for (let i = 0; i < 120; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      const resp = await fetch(apiUrl(`/api/export/tasks/${taskId}`), { headers: apiHeaders() });
      const data = await resp.json();
      if (data.status === 'completed' && data.result?.output_url) {
        setExportProgress(100);
        return data.result.output_url as string;
      }
      if (data.status === 'failed') {
        throw new Error(formatExportError(data.error || '导出失败'));
      }
      const progress = data.progress ?? Math.min(95, Math.round(((i + 1) / 120) * 100));
      setExportProgress(progress);
      setExportStatus(`云渲染中… ${progress}%`);
    }
    throw new Error('导出超时');
  }, []);

  const handleExportCapCut = useCallback(async () => {
    if (!projectId || !templateId || !slots.length) {
      alert('请先导入模板并完成时间线后再导出');
      return;
    }

    const precheck = buildExportPrecheck(slots, assets, templateProcessing, {
      matching,
      exporting: exportBusy,
      capcutReplaceable: capCutReplaceableMode,
      subtitleRecognizing,
    });
    if (!precheck.canProceed) {
      alert(formatExportPrecheckDialog(precheck));
      return;
    }
    const confirmLabel = capCutReplaceableMode ? '是否继续导出可替换模板草稿？' : '是否继续导出剪映草稿？';
    if (precheck.warnings.length && !window.confirm(`${formatExportPrecheckDialog(precheck)}\n\n${confirmLabel}`)) {
      return;
    }

    const status = await fetchCapCutStatusWithRetry(3, 500);
    setCapCutMateStatus(status);
    if (!status?.ready) {
      setCapCutStatus(
        '剪映小助手未连接。请先运行 scripts/start-capcut-mate.ps1 启动服务（默认 http://127.0.0.1:30000），然后点「重新检测」'
      );
      return;
    }

    setCapCutExporting(true);
    setCapCutExportProgress(5);
    setCapCutDraftUrl(null);
    setCapCutStatus(
      capCutReplaceableMode ? '正在生成可替换模板草稿…' : '正在保存并生成剪映草稿…'
    );

    let exportSucceeded = false;

    try {
      const saved = await saveProject();
      if (!saved) {
        alert('保存项目失败，无法导出剪映草稿');
        return;
      }

      const exportPayload = buildExportPayload({
        trackControls,
        templateMusicEnabled,
        useAssetAudio: slots.some((slot) => slot.useOriginalAudio),
        addSubtitles,
      });

      const capCutRequestBody = {
        project_id: projectId,
        ...exportPayload,
        template_music_enabled: templateMusicEnabled,
        resolution: exportResolution,
        include_template_slots: true,
        capcut_export_mode: capCutReplaceableMode ? 'replaceable_template' : 'filled',
        media_base_url: guessMediaBaseUrl(),
      };

      const capCutCallbacks = {
        onProgress: setCapCutExportProgress,
        onStatus: setCapCutStatus,
      };

      const runSyncExport = () => exportCapCutDraftSync(capCutRequestBody, capCutCallbacks);

      let result: CapCutExportResult;

      const asyncResp = await fetch(apiUrl('/api/export/capcut-draft-async'), {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify(capCutRequestBody),
      });
      const asyncData = (await asyncResp.json()) as CapCutExportResult & { task_id?: string };
      const asyncUnavailable =
        asyncResp.status === 404 ||
        String(asyncData.detail || '').toLowerCase().includes('not found');

      if (asyncUnavailable || !asyncResp.ok || !asyncData.task_id) {
        result = await runSyncExport();
      } else {
        setCapCutStatus('导出任务已提交，正在裁剪并写入剪映草稿…');
        result = await pollCapCutExportTask(asyncData.task_id, runSyncExport, capCutCallbacks);
      }

      const draftUrl = (result.draft_url as string) || null;
      setCapCutDraftUrl(draftUrl);
      const skipped = (result.skipped_slots as string[] | undefined) || [];
      const warnings = (result.warnings as string[] | undefined) || [];
      const skipHint = skipped.length ? `（跳过 ${skipped.length} 个槽位）` : '';
      const warnHint = warnings.length ? `；${warnings[0]}` : '';
      const modeHint = capCutReplaceableMode
        ? '。打开后在剪映中选中片段 → 替换素材'
        : '。正在安装到剪映…';
      setCapCutExportProgress(100);
      const captionHint =
        (result.captions_count ?? 0) > 0 ? `、${result.captions_count} 条字幕` : '';
      setCapCutStatus(
        `已生成 ${result.clips_count ?? 0} 个片段${captionHint}${skipHint}${warnHint}${modeHint}`
      );
      exportSucceeded = true;

      if (draftUrl) {
        void installAndOpenCapCutDraft(draftUrl, setCapCutStatus).catch((err) => {
          const msg = err instanceof Error ? err.message : '安装剪映草稿失败';
          setCapCutStatus(msg);
          alert(msg);
        });
      }
    } catch (error) {
      const message = formatExportError(error);
      setCapCutStatus(message);
      setCapCutDraftUrl(null);
      alert(`剪映草稿导出失败\n\n${message}`);
    } finally {
      setCapCutExporting(false);
      if (!exportSucceeded) {
        setCapCutExportProgress(0);
      }
    }
  }, [
    projectId,
    templateId,
    slots,
    assets,
    templateProcessing,
    matching,
    exportBusy,
    capCutReplaceableMode,
    saveProject,
    trackControls,
    templateMusicEnabled,
    addSubtitles,
    exportResolution,
  ]);

  const handleOpenCapCutDraft = useCallback(() => {
    if (!capCutDraftUrl) return;
    void installAndOpenCapCutDraft(capCutDraftUrl, setCapCutStatus).catch((err) => {
      const msg = err instanceof Error ? err.message : '打开剪映草稿失败';
      setCapCutStatus(msg);
      alert(msg);
    });
  }, [capCutDraftUrl]);

  const resetExportState = useCallback(() => {
    setExportUrl(null);
    setExportStatus('');
    setExportError('');
    setCapCutDraftUrl(null);
    setCapCutStatus('');
    setExportProgress(0);
    setCapCutExportProgress(0);
  }, []);

  const handleExport = useCallback(async () => {
    if (!projectId || !templateId || !slots.length) {
      alert('请先导入模板并完成时间线后再导出');
      return;
    }

    const precheck = buildExportPrecheck(slots, assets, templateProcessing, {
      matching,
      exporting: exportBusy,
      subtitleRecognizing,
    });
    if (!precheck.canProceed) {
      alert(formatExportPrecheckDialog(precheck));
      return;
    }
    if (precheck.warnings.length && !window.confirm(`${formatExportPrecheckDialog(precheck)}\n\n是否继续导出？`)) {
      return;
    }

    setExporting(true);
    setExportError('');
    setExportUrl(null);
    setExportProgress(0);
    setExportStatus('正在保存并导出...');

    try {
      const saved = await saveProject();
      if (!saved) {
        setExportError('保存项目失败');
        setExportStatus('保存项目失败');
        return;
      }

      const exportPayload = buildExportPayload({
        trackControls,
        templateMusicEnabled,
        useAssetAudio: slots.some((slot) => slot.useOriginalAudio),
        addSubtitles,
      });

      const resp = await fetch(apiUrl('/api/export/render-async'), {
        method: 'POST',
        headers: apiHeaders(),
        body: JSON.stringify({
          project_id: projectId,
          ...exportPayload,
          template_music_enabled: templateMusicEnabled,
          resolution: exportResolution,
          use_edl: true,
          use_nvenc: true,
        }),
      });
      const data = await resp.json();
      if (!resp.ok || !data.task_id) {
        throw new Error(formatExportError(data.detail || '导出任务创建失败'));
      }
      setExportStatus('导出任务已提交…');
      const outputUrl = await pollExportTask(data.task_id);
      setExportUrl(outputUrl);
      setExportStatus('导出完成，点击下载查看成片。');
    } catch (error) {
      console.warn('导出失败', error);
      setExportUrl(null);
      const message = formatExportError(error);
      setExportError(message);
      setExportStatus(message);
    } finally {
      setExporting(false);
    }
  }, [
    projectId,
    templateId,
    slots,
    assets,
    templateProcessing,
    matching,
    exportBusy,
    saveProject,
    trackControls,
    templateMusicEnabled,
    addSubtitles,
    exportResolution,
    pollExportTask,
  ]);

  return {
    exportUrl,
    exportStatus,
    exporting,
    exportError,
    exportResolution,
    setExportResolution,
    addSubtitles,
    setAddSubtitles,
    exportProgress,
    capCutDraftUrl,
    capCutExporting,
    capCutExportProgress,
    capCutStatus,
    capCutReplaceableMode,
    setCapCutReplaceableMode,
    capCutMateStatus,
    refreshCapCutMateStatus,
    exportPrecheck,
    exportBusy,
    handleExport,
    handleExportCapCut,
    handleOpenCapCutDraft,
    resetExportState,
  };
}
