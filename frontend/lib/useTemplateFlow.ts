import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from 'react';
import { apiHeaders, apiUrl } from '@/lib/api';
import type { PreviewProxyPaths } from '@/lib/previewSettings';
import { uploadTemplateWithProgress } from '@/lib/uploadAsset';
import type { TemplateSlot } from '@/lib/timeline';
import type { SfxMarker } from '@/lib/slotEdit';

type UseTemplateFlowOptions = {
  templateId: string | null;
  projectId: string | null;
  slots: TemplateSlot[];
  setTemplateId: (id: string | null) => void;
  setTemplateName: (name: string) => void;
  setTemplateVideoPath: (path: string) => void;
  setTemplateAudioPath: (path: string) => void;
  setTemplateProxyPaths: (paths: PreviewProxyPaths) => void;
  setBeatMarkers: (markers: number[]) => void;
  setSfxMarkers: (markers: SfxMarker[]) => void;
  setProjectId: (id: string | null) => void;
  setSelectedSlotId: (id: string) => void;
  replaceSlots: (slots: TemplateSlot[]) => void;
  resetHistory: () => void;
  createProjectFromTemplate: (templateId: string) => Promise<unknown>;
  pauseAutosave: (ms?: number) => void;
  resetExportState: () => void;
  setUploadingCount: Dispatch<SetStateAction<number>>;
  setLoading: (loading: boolean) => void;
  lastTemplateSlotCountRef: MutableRefObject<number>;
};

export function useTemplateFlow({
  templateId,
  projectId,
  slots,
  setTemplateId,
  setTemplateName,
  setTemplateVideoPath,
  setTemplateAudioPath,
  setTemplateProxyPaths,
  setBeatMarkers,
  setSfxMarkers,
  setProjectId,
  setSelectedSlotId,
  replaceSlots,
  resetHistory,
  createProjectFromTemplate,
  pauseAutosave,
  resetExportState,
  setUploadingCount,
  setLoading,
  lastTemplateSlotCountRef,
}: UseTemplateFlowOptions) {
  const handleTemplateUpload = useCallback(
    async (file: File) => {
      const localPreview = URL.createObjectURL(file);
      setTemplateVideoPath(localPreview);
      pauseAutosave();
      setUploadingCount((n) => n + 1);
      try {
        const data = await uploadTemplateWithProgress(file, () => undefined);
        URL.revokeObjectURL(localPreview);
        setTemplateId(data.template_id as string);
        setTemplateName((data.filename as string) || '已上传模板');
        if (data.file_path) setTemplateVideoPath(data.file_path as string);
        await createProjectFromTemplate(data.template_id as string);
        lastTemplateSlotCountRef.current = Number(data.slot_count ?? 1);
      } catch (error) {
        URL.revokeObjectURL(localPreview);
        console.warn('模板上传失败', error);
        alert(error instanceof Error ? error.message : '模板上传失败，请重试');
      } finally {
        setUploadingCount((n) => Math.max(0, n - 1));
        pauseAutosave();
      }
    },
    [
      createProjectFromTemplate,
      lastTemplateSlotCountRef,
      pauseAutosave,
      setTemplateId,
      setTemplateName,
      setTemplateVideoPath,
      setUploadingCount,
    ]
  );

  const handleTemplateInstalled = useCallback(
    async (tid: string) => {
      setLoading(true);
      try {
        setTemplateId(tid);
        const tplResp = await fetch(apiUrl(`/api/template/${tid}`), { headers: apiHeaders() });
        const tplData = await tplResp.json();
        if (tplResp.ok) {
          setTemplateName((tplData.filename as string) || '市场模板');
          if (tplData.audio_path) setTemplateAudioPath(tplData.audio_path as string);
          if (tplData.file_path) setTemplateVideoPath(tplData.file_path as string);
        }
        await createProjectFromTemplate(tid);
        resetExportState();
      } catch (err) {
        alert(err instanceof Error ? err.message : '安装模板失败');
      } finally {
        setLoading(false);
      }
    },
    [
      createProjectFromTemplate,
      resetExportState,
      setLoading,
      setTemplateAudioPath,
      setTemplateId,
      setTemplateName,
      setTemplateVideoPath,
    ]
  );

  const handleTemplateLibraryDelete = useCallback(
    (tid: string) => {
      if (templateId !== tid) return;
      setTemplateId(null);
      setTemplateName('未选择模板');
      setTemplateVideoPath('');
      setTemplateAudioPath('');
      setTemplateProxyPaths({});
      setBeatMarkers([]);
      setSfxMarkers([]);
      replaceSlots([]);
      resetHistory();
      setSelectedSlotId('');
      setProjectId(null);
      resetExportState();
    },
    [
      templateId,
      replaceSlots,
      resetHistory,
      resetExportState,
      setBeatMarkers,
      setProjectId,
      setSelectedSlotId,
      setSfxMarkers,
      setTemplateAudioPath,
      setTemplateId,
      setTemplateName,
      setTemplateProxyPaths,
      setTemplateVideoPath,
    ]
  );

  const handleTemplateLibraryLoad = useCallback(
    async (tid: string) => {
      if (
        projectId &&
        slots.some((s) => s.matchedAssetId || s.asset_file_path) &&
        !window.confirm('切换模板将重建时间线，已匹配素材会丢失，是否继续？')
      ) {
        return;
      }
      try {
        const tplResp = await fetch(apiUrl(`/api/template/${tid}`), { headers: apiHeaders() });
        const tpl = await tplResp.json();
        if (!tplResp.ok) throw new Error(tpl.detail || '模板加载失败');
        setTemplateId(tid);
        setTemplateName((tpl.filename as string) || '模板');
        if (tpl.file_path) setTemplateVideoPath(tpl.file_path as string);
        if (tpl.audio_path) setTemplateAudioPath(tpl.audio_path as string);
        await createProjectFromTemplate(tid);
        resetExportState();
      } catch (err) {
        alert(err instanceof Error ? err.message : '载入模板失败');
      }
    },
    [
      projectId,
      slots,
      createProjectFromTemplate,
      resetExportState,
      setTemplateAudioPath,
      setTemplateId,
      setTemplateName,
      setTemplateVideoPath,
    ]
  );

  return {
    handleTemplateUpload,
    handleTemplateInstalled,
    handleTemplateLibraryDelete,
    handleTemplateLibraryLoad,
  };
}
