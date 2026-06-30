export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '';

export function apiUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`;
  // 浏览器内走同源 /api 代理，避免 CORS 与 API_BASE 端口配错
  if (typeof window !== 'undefined') {
    return normalized;
  }
  if (!API_BASE) {
    return normalized;
  }
  return `${API_BASE.replace(/\/$/, '')}${normalized}`;
}

/** 长耗时字幕请求：浏览器走同源 API Route 代理，避免 CORS 与直连失败 */
export function longRunningApiUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`;
  if (typeof window !== 'undefined') {
    return normalized;
  }
  const base = API_BASE || 'http://127.0.0.1:8000';
  return `${base.replace(/\/$/, '')}${normalized}`;
}

export function toMediaUrl(path?: string | null): string {
  if (!path) return '';
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path;
  }
  const normalized = path.replace(/\\/g, '/');
  if (!API_BASE) {
    return normalized.startsWith('/') ? normalized : `/${normalized}`;
  }
  if (normalized.startsWith('/')) {
    return `${API_BASE}${normalized}`;
  }
  return `${API_BASE}/${normalized}`;
}

export function apiHeaders(): HeadersInit {
  const headers: HeadersInit = { 'Content-Type': 'application/json' };
  const apiKey = process.env.NEXT_PUBLIC_API_KEY;
  if (apiKey) {
    headers['X-API-Key'] = apiKey;
  }
  return headers;
}

/** 批量识别：整段 Whisper 一次 + 每槽 OCR，可整批提交 */
export const SUBTITLE_BATCH_CHUNK_SIZE = 25;

export function formatApiDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((item) => {
        if (typeof item === 'string') return item;
        if (item && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg?: string }).msg || '');
        }
        return '';
      })
      .filter(Boolean);
    if (msgs.length) return msgs.join('；');
  }
  return fallback;
}

export async function readApiJson(resp: Response): Promise<Record<string, unknown>> {
  const text = await resp.text();
  if (!text.trim()) return {};
  try {
    return JSON.parse(text) as Record<string, unknown>;
  } catch {
    const snippet = text.trim().slice(0, 160);
    throw new Error(
      resp.ok
        ? '服务器响应无效（非 JSON），请执行 scripts/restart-all.ps1 重启 backend 后重试'
        : snippet || `请求失败 (${resp.status})`
    );
  }
}
