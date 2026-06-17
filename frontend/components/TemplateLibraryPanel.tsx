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

type TemplateLibraryPanelProps = {
  currentTemplateId?: string | null;
  onSelectTemplate?: (templateId: string) => void;
  onImported?: (templateId: string) => void;
};

export default function TemplateLibraryPanel({
  currentTemplateId,
  onSelectTemplate,
  onImported,
}: TemplateLibraryPanelProps) {
  const [templates, setTemplates] = useState<LibraryTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch(apiUrl('/api/template-library/list'), { headers: apiHeaders() });
      const data = await resp.json();
      if (resp.ok && Array.isArray(data.templates)) {
        setTemplates(data.templates);
      }
    } catch {
      setMessage('加载模板库失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

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

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b border-[#2e2e2e] px-3 py-2">
        <span className="text-sm font-medium text-white">我的模板库</span>
        <div className="flex gap-2">
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
        </div>
      </div>

      {message ? <div className="px-3 py-2 text-xs text-[#93c5fd]">{message}</div> : null}
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
              return (
                <li
                  key={t.template_id}
                  className={`rounded-lg border p-2 ${
                    active ? 'border-[#face15]/60 bg-[#face15]/10' : 'border-[#333] bg-[#141414]'
                  }`}
                >
                  <div className="truncate text-xs font-medium text-white">
                    {t.filename || t.template_id.slice(0, 8)}
                  </div>
                  <div className="mt-1 text-[10px] text-[#888]">
                    {t.slot_count ?? 0} 槽位 · {Math.round(t.duration ?? 0)}s ·{' '}
                    {t.processing_status || 'ready'}
                  </div>
                  <div className="mt-2 flex gap-2">
                    <button
                      type="button"
                      disabled={busyId === t.template_id}
                      onClick={() => onSelectTemplate?.(t.template_id)}
                      className="flex-1 rounded bg-[#face15] py-1 text-[10px] font-medium text-black hover:bg-[#ffe066] disabled:opacity-50"
                    >
                      载入
                    </button>
                    <button
                      type="button"
                      disabled={busyId === t.template_id}
                      onClick={() => void exportCtpl(t.template_id)}
                      className="flex-1 rounded bg-[#2a2a2a] py-1 text-[10px] text-[#ccc] hover:bg-[#333] disabled:opacity-50"
                    >
                      导出
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
