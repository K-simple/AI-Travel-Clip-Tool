export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '';

export function apiUrl(path: string): string {
  if (!API_BASE) {
    return path;
  }
  return `${API_BASE.replace(/\/$/, '')}${path}`;
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
