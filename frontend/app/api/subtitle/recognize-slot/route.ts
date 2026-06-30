import { proxyToBackend } from '@/lib/backendProxy';

export const runtime = 'nodejs';
export const maxDuration = 600;

export async function POST(request: Request) {
  try {
    const body = await request.text();
    return proxyToBackend('/api/subtitle/recognize-slot', {
      method: 'POST',
      body,
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : '代理请求失败';
    return Response.json({ detail: `无法连接字幕服务：${msg}` }, { status: 502 });
  }
}
