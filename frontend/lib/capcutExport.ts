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
  '时间轴每段为模板占位片段，顶部黄色标签标示槽位编号与描述',
  '选中某段视频 → 右键「替换素材」或工具栏替换，选择你的成片',
  '替换后时长会自动适配，可逐段替换全部槽位',
  '也可在本编辑器先 AI 匹配素材，再用「成片模式」导出已填好的草稿',
];

export function guessMediaBaseUrl(): string {
  if (typeof window === 'undefined') {
    return API_BASE || 'http://127.0.0.1:8000';
  }
  if (API_BASE) {
    return API_BASE.replace(/\/$/, '');
  }
  const { protocol, hostname } = window.location;
  const port = process.env.NEXT_PUBLIC_BACKEND_PORT || '8000';
  return `${protocol}//${hostname}:${port}`;
}

export async function fetchCapCutStatus(): Promise<CapCutMateStatus | null> {
  try {
    const resp = await fetch(apiUrl('/api/export/capcut-status'), { headers: apiHeaders() });
    if (!resp.ok) return null;
    return (await resp.json()) as CapCutMateStatus;
  } catch {
    return null;
  }
}

export function formatCapCutError(data: CapCutExportResult | Record<string, unknown>): string {
  const detail = data.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(String).join('；');
  if (typeof data.message === 'string') return data.message;
  return '剪映草稿导出失败';
}

export function openCapCutDraft(draftUrl: string): void {
  if (!draftUrl) return;
  window.open(draftUrl, '_blank', 'noopener,noreferrer');
}

export function capCutSetupSteps(status: CapCutMateStatus | null): string[] {
  const steps = [
    '安装并打开剪映 PC 版',
    '启动剪映小助手 CapCut Mate（默认 http://localhost:30000）',
    '在本编辑器完成槽位匹配后，点击「导出剪映草稿」',
    '可勾选「可替换模板」：导出占位片段，在剪映里逐段替换素材',
    '导出成功后点击 draft_url 链接打开（不要手动新建空白草稿）',
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
