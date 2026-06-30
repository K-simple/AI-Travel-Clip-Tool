/** 服务端：将长耗时请求代理到 FastAPI 后端 */
export function backendBaseUrl(): string {
  const base = (process.env.NEXT_PUBLIC_API_BASE || 'http://127.0.0.1:8000').replace(/\/$/, '');
  // Windows 上 backend 常监听 127.0.0.1；localhost 可能走 ::1 导致 Next 代理连不上
  return base.replace('://localhost', '://127.0.0.1');
}

export async function proxyToBackend(
  path: string,
  init: RequestInit,
  timeoutMs = 600_000,
): Promise<Response> {
  const normalized = path.startsWith('/') ? path : `/${path}`;
  const url = `${backendBaseUrl()}${normalized}`;
  const headers = new Headers();
  headers.set('Content-Type', 'application/json');
  const apiKey = process.env.NEXT_PUBLIC_API_KEY;
  if (apiKey) {
    headers.set('X-API-Key', apiKey);
  }

  let resp: Response;
  try {
    resp = await fetch(url, {
      method: init.method || 'POST',
      headers,
      body: init.body,
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : '连接失败';
    const hint =
      msg.includes('timeout') || msg.includes('Timeout')
        ? '请求超时，识别仍在进行时可稍后刷新槽位字幕'
        : '请确认 backend 已在 8000 端口运行（scripts/restart-all.ps1）';
    return Response.json({ detail: `无法连接字幕服务：${hint}` }, { status: 502 });
  }

  const text = await resp.text();
  if (!text.trim()) {
    return Response.json(
      {
        detail: resp.ok
          ? '后端返回空响应，请重启 backend 后重试'
          : `后端错误 (${resp.status})，请查看 backend 控制台日志`,
      },
      { status: resp.ok ? 502 : resp.status || 502 },
    );
  }

  try {
    JSON.parse(text);
  } catch {
    const snippet = text.trim().slice(0, 120);
    return Response.json(
      {
        detail: `服务器响应无效（非 JSON，HTTP ${resp.status}）。请执行 scripts/restart-all.ps1 重启 backend 与 frontend。${snippet ? ` 片段：${snippet}` : ''}`,
      },
      { status: 502 },
    );
  }

  return new Response(text, {
    status: resp.status,
    headers: { 'Content-Type': 'application/json' },
  });
}
