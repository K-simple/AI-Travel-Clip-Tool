'use client';

import { useCallback, useEffect, useState } from 'react';
import { apiHeaders, apiUrl } from '@/lib/api';

type Listing = {
  id: string;
  title: string;
  description?: string;
  category?: string;
  price?: number;
  slot_count?: number;
  duration?: number;
  author?: string;
};

type MarketplacePanelProps = {
  templateId?: string | null;
  onInstalled?: (templateId: string) => void;
};

export default function MarketplacePanel({ templateId, onInstalled }: MarketplacePanelProps) {
  const [listings, setListings] = useState<Listing[]>([]);
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    const resp = await fetch(apiUrl('/api/marketplace/list'), { headers: apiHeaders() });
    const data = await resp.json();
    if (resp.ok) setListings(data.listings || []);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const publish = async () => {
    if (!templateId) {
      setMessage('请先选择模板');
      return;
    }
    const resp = await fetch(apiUrl('/api/marketplace/publish'), {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({ template_id: templateId, title: '我的旅行模板' }),
    });
    const data = await resp.json();
    setMessage(resp.ok ? '已上架' : data.detail || '上架失败');
    if (resp.ok) void load();
  };

  const install = async (listingId: string) => {
    const resp = await fetch(apiUrl(`/api/marketplace/install/${listingId}`), {
      method: 'POST',
      headers: apiHeaders(),
    });
    const data = await resp.json();
    if (resp.ok && data.template_id) {
      setMessage('安装成功');
      onInstalled?.(data.template_id);
    } else {
      setMessage(data.detail || '安装失败');
    }
  };

  return (
    <div className="flex h-full flex-col p-3 text-xs">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-medium text-[#face15]">模板市场</span>
        <button type="button" onClick={() => void publish()} className="rounded bg-[#face15] px-2 py-1 text-black">
          上架当前模板
        </button>
      </div>
      {message ? <div className="mb-2 text-[#8b8b8b]">{message}</div> : null}
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
        {listings.map((l) => (
          <div key={l.id} className="rounded border border-[#2e2e2e] p-2">
            <div className="font-medium text-[#e5e5e5]">{l.title}</div>
            <div className="text-[10px] text-[#8b8b8b]">
              {l.category} · {l.slot_count} 槽 · {l.author}
            </div>
            <button
              type="button"
              onClick={() => void install(l.id)}
              className="mt-1 rounded bg-[#2c2c2e] px-2 py-0.5 hover:bg-[#3a3a3c]"
            >
              安装到本地
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
