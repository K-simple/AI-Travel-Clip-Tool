'use client';

import { useCallback, useEffect, useState } from 'react';
import { apiHeaders, apiUrl, toMediaUrl } from '@/lib/api';

type CloudItem = {
  id: string;
  title: string;
  url: string;
  thumbnail?: string;
  duration?: number;
  tags?: string[];
  description?: string;
};

type CloudLibraryPanelProps = {
  onImported?: () => void;
};

export default function CloudLibraryPanel({ onImported }: CloudLibraryPanelProps) {
  const [items, setItems] = useState<CloudItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [importingId, setImportingId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [keyword, setKeyword] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const q = keyword ? `?keyword=${encodeURIComponent(keyword)}` : '';
      const resp = await fetch(apiUrl(`/api/cloud/list${q}`), { headers: apiHeaders() });
      const data = await resp.json();
      if (resp.ok) {
        setItems(data.items || []);
      } else {
        setError(data.detail || '加载失败');
        setItems([]);
      }
    } catch {
      setError('云素材库暂不可用，请确认后端已启动');
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [keyword]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleImport = async (itemId: string) => {
    setImportingId(itemId);
    try {
      const resp = await fetch(apiUrl(`/api/cloud/import/${itemId}`), {
        method: 'POST',
        headers: apiHeaders(),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || data.message || '导入失败');
      onImported?.();
      alert(data.message || '已导入本地素材库');
    } catch (err) {
      alert(err instanceof Error ? err.message : '导入失败');
    } finally {
      setImportingId(null);
    }
  };

  return (
    <div className="flex h-full flex-col p-3 text-xs text-[#e5e5e5]">
      <div className="mb-2 font-medium text-[#face15]">云素材库</div>
      <div className="mb-2 flex gap-2">
        <input
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          placeholder="搜索标题/描述"
          className="min-w-0 flex-1 rounded border border-[#3a3a3c] bg-[#1c1c1e] px-2 py-1"
        />
        <button
          type="button"
          onClick={() => void load()}
          className="rounded bg-[#2c2c2e] px-2 py-1 hover:bg-[#3a3a3c]"
        >
          搜索
        </button>
      </div>
      {loading ? <div className="text-[#8b8b8b]">加载中…</div> : null}
      {error ? <div className="mb-2 text-[11px] text-[#f87171]">{error}</div> : null}
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
        {items.map((item) => (
          <div
            key={item.id}
            className="flex gap-2 rounded border border-[#2e2e2e] p-2 hover:border-[#face15]/50"
          >
            {item.thumbnail ? (
              <img src={toMediaUrl(item.thumbnail)} alt="" className="h-10 w-14 rounded object-cover" />
            ) : (
              <div className="flex h-10 w-14 items-center justify-center rounded bg-[#2c2c2e]">☁</div>
            )}
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{item.title}</div>
              <div className="truncate text-[10px] text-[#8b8b8b]">{item.description || item.url}</div>
              <div className="mt-1 flex gap-2">
                <button
                  type="button"
                  disabled={importingId === item.id}
                  onClick={() => void handleImport(item.id)}
                  className="rounded bg-[#face15] px-2 py-0.5 text-[10px] font-medium text-black hover:bg-[#ffe066] disabled:opacity-50"
                >
                  {importingId === item.id ? '导入中…' : '导入本地'}
                </button>
                <a
                  href={toMediaUrl(item.url)}
                  target="_blank"
                  rel="noreferrer"
                  className="text-[10px] text-[#8b8b8b] hover:text-[#ccc]"
                >
                  预览
                </a>
              </div>
            </div>
          </div>
        ))}
        {!loading && items.length === 0 ? (
          <div className="text-[#8b8b8b]">暂无云素材，可通过 API 注册</div>
        ) : null}
      </div>
    </div>
  );
}
