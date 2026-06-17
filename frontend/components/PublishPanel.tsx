'use client';

import { useEffect, useState } from 'react';
import { apiHeaders, apiUrl, toMediaUrl } from '@/lib/api';

type PublishPanelProps = {
  exportUrl?: string | null;
};

export default function PublishPanel({ exportUrl }: PublishPanelProps) {
  const [configured, setConfigured] = useState(false);
  const [tokenId, setTokenId] = useState('');
  const [title, setTitle] = useState('AI Travel Cut 成片');
  const [message, setMessage] = useState('');

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const t = params.get('publish_token');
    if (t) setTokenId(t);
  }, []);

  useEffect(() => {
    void (async () => {
      const resp = await fetch(apiUrl('/api/publish/douyin/status'), { headers: apiHeaders() });
      const data = await resp.json();
      if (resp.ok) setConfigured(!!data.configured);
    })();
  }, []);

  const authorize = () => {
    window.open(apiUrl('/api/publish/douyin/authorize'), '_blank');
  };

  const upload = async () => {
    if (!exportUrl) {
      setMessage('请先导出成片');
      return;
    }
    if (!tokenId) {
      setMessage('请先 OAuth 授权抖音');
      return;
    }
    const resp = await fetch(apiUrl('/api/publish/douyin/upload'), {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({
        token_id: tokenId,
        video_url: toMediaUrl(exportUrl),
        title,
      }),
    });
    const data = await resp.json();
    setMessage(resp.ok ? data.message || '已提交发布' : data.detail || '发布失败');
  };

  return (
    <div className="space-y-2 border-t border-[#2e2e2e] p-3 text-xs">
      <div className="font-medium text-[#face15]">抖音直推</div>
      <div className="text-[#8b8b8b]">
        OAuth {configured ? '已配置' : '未配置（可用 stub 模式测试）'}
      </div>
      <button type="button" onClick={authorize} className="w-full rounded bg-[#2c2c2e] py-1.5 hover:bg-[#3a3a3c]">
        抖音授权登录
      </button>
      <input
        value={tokenId}
        onChange={(e) => setTokenId(e.target.value)}
        placeholder="publish_token"
        className="w-full rounded border border-[#3a3a3c] bg-[#1c1c1e] px-2 py-1"
      />
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="发布标题"
        className="w-full rounded border border-[#3a3a3c] bg-[#1c1c1e] px-2 py-1"
      />
      <button type="button" onClick={() => void upload()} className="w-full rounded bg-[#face15] py-1.5 text-black">
        发布到抖音
      </button>
      {message ? <div className="text-[#8b8b8b]">{message}</div> : null}
    </div>
  );
}
