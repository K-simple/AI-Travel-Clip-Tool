import { API_BASE, apiHeaders, apiUrl } from '@/lib/api';

export type CapCutMateStatus = {
  enabled: boolean;
  base_url: string;
  reachable: boolean;
  ready: boolean;
  public_media_base_url: string;
  detected_lan_host?: string;
  api_key_required_for_storage?: boolean;
  hint?: string;
};

export type CapCutExportMode = 'filled' | 'replaceable_template';

export type CapCutExportResult = {
  success: boolean;
  draft_url?: string;
  clips_count?: number;
  captions_count?: number;
  duration_sec?: number;
  skipped_slots?: string[];
  warnings?: string[];
  open_hint?: string;
  replace_guide?: string;
  capcut_export_mode?: CapCutExportMode;
  slot_manifest_url?: string;
  message?: string;
  detail?: string | string[];
};

export const REPLACEABLE_TEMPLATE_STEPS = [
  '时间轴每段为模板占位视频，原视频字幕与人声已按槽位分割对齐',
  '选中某段视频 → 右键「替换素材」或工具栏替换，选择你的成片',
  '替换后时长会自动适配，可逐段替换全部槽位',
  '也可在本编辑器先 AI 匹配素材，再用「成片模式」导出已填好的草稿',
];

export function guessMediaBaseUrl(): string {
  if (typeof window === 'undefined') {
    return API_BASE || 'http://127.0.0.1:8000';
  }
  let base: string;
  if (API_BASE) {
    base = API_BASE.replace(/\/$/, '');
  } else {
    const { protocol, hostname } = window.location;
    const host = hostname === 'localhost' ? '127.0.0.1' : hostname;
    const port = process.env.NEXT_PUBLIC_BACKEND_PORT || '8000';
    base = `${protocol}//${host}:${port}`;
  }
  return base.replace('://localhost', '://127.0.0.1');
}

export async function fetchCapCutStatus(): Promise<CapCutMateStatus | null> {
  try {
    const resp = await fetch(apiUrl('/api/export/capcut-status'), {
      headers: apiHeaders(),
      cache: 'no-store',
    });
    if (!resp.ok) return null;
    return (await resp.json()) as CapCutMateStatus;
  } catch {
    return null;
  }
}

export async function fetchCapCutStatusWithRetry(
  attempts = 2,
  delayMs = 400
): Promise<CapCutMateStatus | null> {
  for (let i = 0; i < attempts; i++) {
    const status = await fetchCapCutStatus();
    if (status?.ready) return status;
    if (i < attempts - 1) {
      await new Promise((r) => setTimeout(r, delayMs));
    } else if (status) {
      return status;
    }
  }
  return null;
}

/** 同步导出剪映草稿（直接等待结果，避免 async 内存任务丢失导致“假导出”） */
export async function exportCapCutDraftSync(
  body: Record<string, unknown>,
  callbacks?: {
    onProgress?: (progress: number) => void;
    onStatus?: (message: string) => void;
  }
): Promise<CapCutExportResult> {
  callbacks?.onStatus?.('正在裁剪并写入剪映草稿（约 1–3 分钟，请勿关闭页面）…');
  callbacks?.onProgress?.(8);

  let progress = 8;
  const tick =
    typeof window !== 'undefined'
      ? window.setInterval(() => {
          progress = Math.min(92, progress + 2);
          callbacks?.onProgress?.(progress);
        }, 4000)
      : undefined;

  try {
    const resp = await fetch(apiUrl('/api/export/capcut-draft'), {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify(body),
    });
    const data = (await resp.json()) as CapCutExportResult;
    if (!resp.ok || !data.success) {
      throw new Error(formatCapCutError(data));
    }
    if (!data.draft_url?.trim()) {
      throw new Error('剪映草稿生成失败：未返回 draft_url，请查看 CapCut Mate 日志');
    }
    callbacks?.onProgress?.(100);
    return data;
  } finally {
    if (tick !== undefined) window.clearInterval(tick);
  }
}

export async function pollCapCutExportTask(
  taskId: string,
  syncFallback: () => Promise<CapCutExportResult>,
  callbacks?: {
    onProgress?: (progress: number) => void;
    onStatus?: (message: string) => void;
  }
): Promise<CapCutExportResult> {
  let lostTaskPolls = 0;
  for (let i = 0; i < 600; i++) {
    await new Promise((r) => setTimeout(r, i === 0 ? 800 : 2000));
    const resp = await fetch(apiUrl(`/api/export/tasks/${taskId}`), {
      headers: apiHeaders(),
      cache: 'no-store',
    });
    if (resp.status === 404) {
      lostTaskPolls += 1;
      if (lostTaskPolls >= 2) {
        callbacks?.onStatus?.('后台导出任务已丢失，改用同步导出…');
        return syncFallback();
      }
      continue;
    }
    const data = await resp.json().catch(() => ({} as Record<string, unknown>));
    if (data.status === 'completed' && (data.result as CapCutExportResult | undefined)?.draft_url) {
      callbacks?.onProgress?.(100);
      return data.result as CapCutExportResult;
    }
    if (data.status === 'failed') {
      throw new Error(formatCapCutError({ detail: data.error || data.message }));
    }
    const progress = typeof data.progress === 'number' ? data.progress : 0;
    callbacks?.onProgress?.(progress);
    if (typeof data.message === 'string' && data.message.trim()) {
      callbacks?.onStatus?.(data.message);
    }
  }
  throw new Error('剪映草稿导出超时，请稍后重试');
}

export function formatCapCutError(data: CapCutExportResult | Record<string, unknown>): string {
  const detail = data.detail;
  if (typeof detail === 'string') {
    if (/not found/i.test(detail)) {
      return '后端接口未就绪，请重启 backend 服务后重试（需包含 capcut-draft-async 接口）';
    }
    return detail.includes('timed out') || detail.includes('超时')
      ? '导出耗时过长已超时。槽位较多时请稍候重试，或在 backend/.env 设置 CAPCUT_MATE_TIMEOUT_SEC=900 后重启后端'
      : detail;
  }
  if (Array.isArray(detail)) return detail.map(String).join('；');
  if (typeof data.message === 'string') return data.message;
  return '剪映草稿导出失败';
}

export function openCapCutDraft(draftUrl: string): void {
  if (!draftUrl) return;
  window.open(draftUrl, '_blank', 'noopener,noreferrer');
}

export async function installCapCutDraftToJianying(
  draftUrl: string
): Promise<{ success: boolean; message: string; installed_path?: string }> {
  const resp = await fetch(apiUrl('/api/export/capcut-install-draft'), {
    method: 'POST',
    headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ draft_url: draftUrl }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : '安装剪映草稿失败';
    throw new Error(detail);
  }
  return {
    success: Boolean(data.success),
    message: (data.message as string) || '草稿已安装到剪映目录',
    installed_path: data.installed_path as string | undefined,
  };
}

export async function installAndOpenCapCutDraft(
  draftUrl: string,
  onStatus?: (message: string) => void
): Promise<void> {
  if (!draftUrl) return;
  onStatus?.('正在将草稿安装到剪映目录…');
  const result = await installCapCutDraftToJianying(draftUrl);
  onStatus?.(result.message);
  alert(
    `${result.message}\n\n` +
      '请打开剪映 PC 版，在首页草稿列表中找到该项目（可能需要等待几秒刷新）。\n' +
      '若未出现，请重启剪映后再查看。'
  );
}

export function capCutSetupSteps(status: CapCutMateStatus | null): string[] {
  const steps = [
    '安装并打开剪映 PC 版',
    '启动剪映小助手 CapCut Mate（默认 http://localhost:30000）',
    '在本编辑器完成槽位匹配后，点击「导出剪映草稿」',
    '可勾选「可替换模板」：导出占位片段，在剪映里逐段替换素材',
    '导出成功后点击「在剪映中打开草稿」，将自动安装到剪映目录',
  ];
  if (status?.api_key_required_for_storage) {
    steps.splice(
      2,
      0,
      'backend/.env 已启用 API_KEY，导出时会自动在素材 URL 附带 api_key 供小助手拉取'
    );
  }
  if (status?.public_media_base_url) {
    steps.push(`素材地址：${status.public_media_base_url}/storage/...`);
  }
  return steps;
}
