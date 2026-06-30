'use client';

import { useCallback, useEffect, useState } from 'react';
import { apiHeaders, apiUrl } from '@/lib/api';

type LibraryTemplate = {
  template_id: string;
  filename?: string;
  duration?: number;
  slot_count?: number;
  processing_status?: string;
};

type DeleteAction =
  | { type: 'single'; template: LibraryTemplate }
  | { type: 'batch'; ids: string[] };

type TemplateLibraryPanelProps = {
  currentTemplateId?: string | null;
  onSelectTemplate?: (templateId: string) => void;
  onImported?: (templateId: string) => void;
  onTemplateDeleted?: (templateId: string) => void;
};

function templateLabel(template: LibraryTemplate): string {
  return template.filename || template.template_id.slice(0, 8);
}

export default function TemplateLibraryPanel({
  currentTemplateId,
  onSelectTemplate,
  onImported,
  onTemplateDeleted,
}: TemplateLibraryPanelProps) {
  const [templates, setTemplates] = useState<LibraryTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [pendingDeleteAction, setPendingDeleteAction] = useState<DeleteAction | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());

  const refresh = useCallback(async () => {
    setLoading(true);
    setMessage('');
    try {
      const resp = await fetch(apiUrl('/api/template-library/list'), { headers: apiHeaders() });
      let data: { templates?: LibraryTemplate[]; detail?: string } = {};
      try {
        data = await resp.json();
      } catch {
        throw new Error('服务器响应异常');
      }
      if (resp.ok && Array.isArray(data.templates)) {
        setTemplates(data.templates);
        return;
      }
      const detail =
        typeof data.detail === 'string'
          ? data.detail
          : resp.status === 401
            ? '未授权，请检查 NEXT_PUBLIC_API_KEY 是否与后端 API_KEY 一致'
            : resp.status >= 500
              ? '后端不可用，请确认 backend 已在 8000 端口运行'
              : `加载失败 (HTTP ${resp.status})`;
      setMessage(detail);
    } catch (error) {
      setMessage(
        error instanceof Error && error.message
          ? error.message
          : '加载模板库失败，请确认 backend 已启动 (http://localhost:8000)'
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const exitSelectMode = useCallback(() => {
    setSelectMode(false);
    setSelectedIds(new Set());
  }, []);

  const toggleSelected = useCallback((templateId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(templateId)) next.delete(templateId);
      else next.add(templateId);
      return next;
    });
  }, []);

  const selectAllTemplates = useCallback(() => {
    setSelectedIds(new Set(templates.map((t) => t.template_id)));
  }, [templates]);

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const exportCtpl = async (templateId: string) => {
    setBusyId(templateId);
    setMessage('');
    try {
      const resp = await fetch(apiUrl(`/api/template-library/${templateId}/export-ctpl`), {
        headers: apiHeaders(),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || '导出失败');
      const blob = new Blob([JSON.stringify(data.ctpl ?? data, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${templateId}.ctpl.json`;
      a.click();
      URL.revokeObjectURL(url);
      setMessage('已导出 .ctpl 模板包');
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '导出失败');
    } finally {
      setBusyId(null);
    }
  };

  const reprocessTemplate = async (templateId: string) => {
    setBusyId(templateId);
    setMessage('');
    try {
      const resp = await fetch(apiUrl(`/api/template/${templateId}/reprocess`), {
        method: 'POST',
        headers: apiHeaders(),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error((data.detail as string) || '重新切分失败');
      setMessage('正在重新对齐字幕（保留镜头槽），约 2–3 分钟，完成后请点刷新');
      const poll = async (attempt = 0): Promise<void> => {
        if (attempt > 120) return;
        await new Promise((r) => setTimeout(r, 3000));
        const statusResp = await fetch(apiUrl(`/api/template/${templateId}/status`), {
          headers: apiHeaders(),
        });
        const status = await statusResp.json();
        if (!statusResp.ok) return poll(attempt + 1);
        const processing = status.processing_status === 'processing';
        const count = Number(status.slot_count ?? 0);
        if (!processing && count > 0) {
          await refresh();
          setMessage(`重新切分完成：${count} 槽位（请点「载入」同步到编辑器）`);
          return;
        }
        return poll(attempt + 1);
      };
      void poll();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '重新切分失败');
    } finally {
      setBusyId(null);
    }
  };

  const importCtplFile = async (file: File) => {
    setMessage('');
    try {
      const text = await file.text();
      const payload = JSON.parse(text) as Record<string, unknown>;
      const resp = await fetch(apiUrl('/api/template-library/import-ctpl'), {
        method: 'POST',
        headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || '导入失败');
      setMessage(`已导入模板（${data.slot_count ?? 0} 槽位）`);
      await refresh();
      if (data.template_id) onImported?.(data.template_id);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '导入失败');
    }
  };

  const deleteTemplateApi = async (templateId: string): Promise<void> => {
    const resp = await fetch(apiUrl(`/api/template/${templateId}`), {
      method: 'DELETE',
      headers: apiHeaders(),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error((data.detail as string) || '删除失败');
  };

  const removeTemplatesFromList = useCallback((ids: string[]) => {
    if (!ids.length) return;
    const idSet = new Set(ids);
    setTemplates((prev) => prev.filter((t) => !idSet.has(t.template_id)));
    ids.forEach((id) => onTemplateDeleted?.(id));
  }, [onTemplateDeleted]);

  const executeDeleteAction = async (action: DeleteAction) => {
    if (action.type === 'single') {
      const template = action.template;
      const label = templateLabel(template);
      setBusyId(template.template_id);
      setMessage('');
      try {
        await deleteTemplateApi(template.template_id);
        removeTemplatesFromList([template.template_id]);
        setMessage(`已删除「${label}」`);
      } catch (err) {
        setMessage(err instanceof Error ? err.message : '删除失败');
      } finally {
        setBusyId(null);
        setPendingDeleteAction(null);
      }
      return;
    }

    setBatchDeleting(true);
    setMessage('');
    const ids = action.ids;
    const succeeded: string[] = [];
    let failed = 0;
    try {
      for (const id of ids) {
        try {
          await deleteTemplateApi(id);
          succeeded.push(id);
        } catch {
          failed += 1;
        }
      }
      removeTemplatesFromList(succeeded);
      if (succeeded.length) {
        setMessage(
          failed
            ? `已删除 ${succeeded.length} 个模板，${failed} 个删除失败`
            : `已删除 ${succeeded.length} 个模板`
        );
      } else {
        setMessage('批量删除失败，请重试');
      }
      exitSelectMode();
    } finally {
      setBatchDeleting(false);
      setPendingDeleteAction(null);
    }
  };

  const pendingIncludesCurrent =
    pendingDeleteAction?.type === 'single'
      ? pendingDeleteAction.template.template_id === currentTemplateId
      : pendingDeleteAction?.type === 'batch'
        ? pendingDeleteAction.ids.includes(currentTemplateId ?? '')
        : false;

  const pendingCount =
    pendingDeleteAction?.type === 'single'
      ? 1
      : pendingDeleteAction?.type === 'batch'
        ? pendingDeleteAction.ids.length
        : 0;

  const deleteDialogBusy =
    batchDeleting ||
    (pendingDeleteAction?.type === 'single' &&
      busyId === pendingDeleteAction.template.template_id);

  return (
    <>
      {pendingDeleteAction ? (
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/60 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="template-delete-title"
            className="w-full max-w-sm rounded-lg border border-[#3a3a3c] bg-[#1e1e1e] shadow-2xl"
          >
            <div className="border-b border-[#2e2e2e] px-4 py-3">
              <h3 id="template-delete-title" className="text-sm font-medium text-white">
                {pendingDeleteAction.type === 'batch' ? '批量删除模板' : '删除模板'}
              </h3>
            </div>
            <div className="px-4 py-4 text-xs leading-relaxed text-[#b8b8bc]">
              {pendingDeleteAction.type === 'single' ? (
                pendingIncludesCurrent ? (
                  <>
                    「{templateLabel(pendingDeleteAction.template)}」正在编辑中，删除后时间线将被清空。
                    <span className="mt-2 block text-[#f87171]">此操作无法恢复，请确认是否继续。</span>
                  </>
                ) : (
                  <>
                    确定从模板库删除「{templateLabel(pendingDeleteAction.template)}」？
                    <span className="mt-2 block text-[#888]">删除后无法恢复。</span>
                  </>
                )
              ) : (
                <>
                  确定删除选中的 {pendingCount} 个模板？
                  {pendingIncludesCurrent ? (
                    <span className="mt-2 block text-[#f87171]">
                      其中包含当前正在编辑的模板，删除后时间线将被清空。
                    </span>
                  ) : null}
                  <span className="mt-2 block text-[#888]">删除后无法恢复。</span>
                </>
              )}
            </div>
            <div className="flex justify-end gap-2 border-t border-[#2e2e2e] px-4 py-3">
              <button
                type="button"
                disabled={deleteDialogBusy}
                onClick={() => setPendingDeleteAction(null)}
                className="rounded bg-[#2a2a2a] px-4 py-1.5 text-xs text-[#ccc] hover:bg-[#333] disabled:opacity-50"
              >
                取消
              </button>
              <button
                type="button"
                disabled={deleteDialogBusy}
                onClick={() => void executeDeleteAction(pendingDeleteAction)}
                className="rounded bg-[#dc2626] px-4 py-1.5 text-xs font-medium text-white hover:bg-[#ef4444] disabled:opacity-50"
              >
                {deleteDialogBusy ? '删除中…' : '确定'}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#2e2e2e] px-3 py-2">
          <span className="text-sm font-medium text-white">我的模板库</span>
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            {templates.length > 0 ? (
              !selectMode ? (
                <button
                  type="button"
                  onClick={() => setSelectMode(true)}
                  className="rounded bg-[#2a2a2a] px-2 py-1 text-[11px] text-[#ccc] hover:bg-[#333]"
                >
                  多选
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={selectAllTemplates}
                    className="rounded bg-[#2a2a2a] px-2 py-1 text-[11px] text-[#ccc] hover:bg-[#333]"
                  >
                    全选
                  </button>
                  <button
                    type="button"
                    onClick={clearSelection}
                    className="rounded bg-[#2a2a2a] px-2 py-1 text-[11px] text-[#ccc] hover:bg-[#333]"
                  >
                    清空
                  </button>
                  <button
                    type="button"
                    disabled={selectedIds.size === 0 || batchDeleting}
                    onClick={() =>
                      setPendingDeleteAction({ type: 'batch', ids: Array.from(selectedIds) })
                    }
                    className="rounded bg-[#8b2020] px-2 py-1 text-[11px] text-white hover:bg-[#a82828] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    删除{selectedIds.size > 0 ? ` (${selectedIds.size})` : ''}
                  </button>
                  <button
                    type="button"
                    onClick={exitSelectMode}
                    className="rounded bg-[#2a2a2a] px-2 py-1 text-[11px] text-[#face15] hover:bg-[#333]"
                  >
                    完成
                  </button>
                </>
              )
            ) : null}
            {!selectMode ? (
              <>
                <label className="cursor-pointer rounded bg-[#2a2a2a] px-2 py-1 text-xs text-[#ccc] hover:bg-[#333]">
                  导入 .ctpl
                  <input
                    type="file"
                    accept=".json,.ctpl,application/json"
                    className="hidden"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) void importCtplFile(file);
                      e.target.value = '';
                    }}
                  />
                </label>
                <button
                  type="button"
                  onClick={() => void refresh()}
                  className="rounded bg-[#2a2a2a] px-2 py-1 text-xs text-[#ccc] hover:bg-[#333]"
                >
                  刷新
                </button>
              </>
            ) : null}
          </div>
        </div>

        {selectMode ? (
          <div className="border-b border-[#2e2e2e] px-3 py-1.5 text-[10px] text-[#888]">
            点击模板卡片勾选，已选 {selectedIds.size} 项
          </div>
        ) : null}

        {message ? <div className="px-3 py-2 text-xs text-[#f87171]">{message}</div> : null}
        {loading ? <div className="px-3 py-2 text-xs text-[#666]">加载中…</div> : null}

        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
          {templates.length === 0 && !loading ? (
            <div className="py-10 text-center text-xs text-[#666]">
              <p>暂无已保存模板</p>
              <p className="mt-1 text-[#555]">上传模板视频后出现在此列表，可导出 .ctpl 分享</p>
            </div>
          ) : (
            <ul className="space-y-2 pt-2">
              {templates.map((t) => {
                const active = t.template_id === currentTemplateId;
                const isSelected = selectedIds.has(t.template_id);
                const cardBusy = busyId === t.template_id || batchDeleting;

                return (
                  <li
                    key={t.template_id}
                    className={`group relative rounded-lg border p-2 transition-colors ${
                      selectMode && isSelected
                        ? 'border-[#face15]/70 bg-[#face15]/10'
                        : active
                          ? 'border-[#face15]/60 bg-[#face15]/10'
                          : 'border-[#333] bg-[#141414]'
                    } ${selectMode ? 'cursor-pointer' : ''}`}
                    onClick={
                      selectMode
                        ? () => {
                            if (!cardBusy) toggleSelected(t.template_id);
                          }
                        : undefined
                    }
                  >
                    {selectMode ? (
                      <span
                        className={`absolute left-1.5 top-1.5 z-10 flex h-4 w-4 items-center justify-center rounded border text-[10px] ${
                          isSelected
                            ? 'border-[#face15] bg-[#face15] text-black'
                            : 'border-white/70 bg-black/50 text-transparent'
                        }`}
                      >
                        ✓
                      </span>
                    ) : (
                      <button
                        type="button"
                        title="删除模板"
                        aria-label="删除模板"
                        disabled={cardBusy}
                        onClick={() => setPendingDeleteAction({ type: 'single', template: t })}
                        className="absolute right-1.5 top-1.5 flex h-5 w-5 items-center justify-center rounded bg-black/60 text-[11px] text-[#ccc] opacity-0 transition hover:bg-red-600 hover:text-white disabled:opacity-40 group-hover:opacity-100"
                      >
                        ×
                      </button>
                    )}
                    <div
                      className={`truncate text-xs font-medium text-white ${selectMode ? 'pl-5 pr-2' : 'pr-6'}`}
                    >
                      {templateLabel(t)}
                    </div>
                    <div className={`mt-1 text-[10px] text-[#888] ${selectMode ? 'pl-5' : ''}`}>
                      {t.slot_count ?? 0} 槽位 · {Math.round(t.duration ?? 0)}s ·{' '}
                      {t.processing_status || 'ready'}
                    </div>
                    {!selectMode ? (
                      <div className="mt-2 flex flex-wrap gap-2">
                        <button
                          type="button"
                          disabled={cardBusy}
                          onClick={() => onSelectTemplate?.(t.template_id)}
                          className="min-w-[3.5rem] flex-1 rounded bg-[#face15] py-1 text-[10px] font-medium text-black hover:bg-[#ffe066] disabled:opacity-50"
                        >
                          载入
                        </button>
                        <button
                          type="button"
                          disabled={cardBusy || t.processing_status === 'processing'}
                          onClick={() => void reprocessTemplate(t.template_id)}
                          className="min-w-[3.5rem] flex-1 rounded bg-[#2a2a2a] py-1 text-[10px] text-[#ccc] hover:bg-[#333] disabled:opacity-50"
                          title="按烧录字幕重新识别并对齐槽位（默认保留镜头数）"
                        >
                          重切分
                        </button>
                        <button
                          type="button"
                          disabled={cardBusy}
                          onClick={() => void exportCtpl(t.template_id)}
                          className="min-w-[3.5rem] flex-1 rounded bg-[#2a2a2a] py-1 text-[10px] text-[#ccc] hover:bg-[#333] disabled:opacity-50"
                        >
                          导出
                        </button>
                        <button
                          type="button"
                          disabled={cardBusy}
                          onClick={() => setPendingDeleteAction({ type: 'single', template: t })}
                          className="rounded bg-[#2a2a2a] px-2 py-1 text-[10px] text-[#f87171] hover:bg-[#3a2020] disabled:opacity-50"
                        >
                          删除
                        </button>
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </>
  );
}
