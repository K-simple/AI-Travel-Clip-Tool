'use client';

import { useCallback, useEffect, useState } from 'react';
import { apiHeaders, apiUrl } from '@/lib/api';

export type ProjectListItem = {
  project_id: string;
  template_id: string;
  name: string;
  cover_thumbnail?: string;
  created_at: number;
  updated_at?: number;
};

type ProjectListModalProps = {
  open: boolean;
  currentProjectId: string | null;
  onClose: () => void;
  onLoad: (projectId: string) => void;
  onRenamed?: () => void;
};

export default function ProjectListModal({
  open,
  currentProjectId,
  onClose,
  onLoad,
  onRenamed,
}: ProjectListModalProps) {
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');

  const loadProjects = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const resp = await fetch(apiUrl('/api/projects/list'), { headers: apiHeaders() });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || '加载失败');
      setProjects(data.projects || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
      setProjects([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void loadProjects();
  }, [open, loadProjects]);

  const handleDelete = async (projectId: string) => {
    if (!confirm('确定删除该项目？此操作不可恢复。')) return;
    try {
      const resp = await fetch(apiUrl(`/api/projects/${projectId}`), {
        method: 'DELETE',
        headers: apiHeaders(),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || '删除失败');
      setProjects((list) => list.filter((p) => p.project_id !== projectId));
      onRenamed?.();
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  const handleRename = async (projectId: string) => {
    const name = editName.trim();
    if (!name) return;
    try {
      const resp = await fetch(apiUrl(`/api/projects/${projectId}`), {
        method: 'PATCH',
        headers: apiHeaders(),
        body: JSON.stringify({ name }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || '重命名失败');
      setProjects((list) =>
        list.map((p) => (p.project_id === projectId ? { ...p, name } : p))
      );
      setEditingId(null);
      onRenamed?.();
    } catch (err) {
      alert(err instanceof Error ? err.message : '重命名失败');
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4">
      <div className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-lg border border-[#3a3a3c] bg-[#1e1e1e] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[#2e2e2e] px-4 py-3">
          <h2 className="text-sm font-medium text-white">我的项目</h2>
          <button type="button" onClick={onClose} className="text-[#8b8b8b] hover:text-white">
            ✕
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-2">
          {loading ? <div className="py-6 text-center text-xs text-[#8b8b8b]">加载中…</div> : null}
          {error ? <div className="py-2 text-xs text-[#f87171]">{error}</div> : null}
          {!loading && projects.length === 0 ? (
            <div className="py-6 text-center text-xs text-[#8b8b8b]">暂无项目，上传模板后会自动创建</div>
          ) : null}
          <ul className="space-y-2">
            {projects.map((p) => (
              <li
                key={p.project_id}
                className={`rounded border px-3 py-2 ${
                  p.project_id === currentProjectId
                    ? 'border-[#face15]/60 bg-[#2a2a1a]'
                    : 'border-[#2e2e2e] bg-[#252525]'
                }`}
              >
                {editingId === p.project_id ? (
                  <div className="flex gap-2">
                    <input
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      className="min-w-0 flex-1 rounded border border-[#3a3a3c] bg-[#141416] px-2 py-1 text-xs text-white"
                      autoFocus
                    />
                    <button
                      type="button"
                      onClick={() => void handleRename(p.project_id)}
                      className="rounded bg-[#face15] px-2 py-1 text-xs font-medium text-black"
                    >
                      保存
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        onLoad(p.project_id);
                        onClose();
                      }}
                      className="min-w-0 flex-1 text-left"
                    >
                      <div className="truncate text-xs font-medium text-[#e5e5e5]">
                        {p.name || '未命名项目'}
                      </div>
                      <div className="truncate text-[10px] text-[#666]">{p.project_id}</div>
                    </button>
                    <div className="flex shrink-0 gap-1">
                      <button
                        type="button"
                        title="重命名"
                        onClick={() => {
                          setEditingId(p.project_id);
                          setEditName(p.name || '');
                        }}
                        className="rounded px-2 py-1 text-[10px] text-[#8b8b8b] hover:bg-[#333] hover:text-white"
                      >
                        改名
                      </button>
                      <button
                        type="button"
                        title="删除"
                        onClick={() => void handleDelete(p.project_id)}
                        className="rounded px-2 py-1 text-[10px] text-[#f87171] hover:bg-[#3a2020]"
                      >
                        删除
                      </button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>

        <div className="border-t border-[#2e2e2e] px-4 py-2 text-right">
          <button
            type="button"
            onClick={() => void loadProjects()}
            className="mr-2 rounded bg-[#2a2a2a] px-3 py-1.5 text-xs text-[#ccc] hover:bg-[#333]"
          >
            刷新
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded bg-[#2a2a2a] px-3 py-1.5 text-xs text-[#ccc] hover:bg-[#333]"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
