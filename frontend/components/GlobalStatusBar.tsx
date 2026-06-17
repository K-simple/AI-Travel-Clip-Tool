'use client';

export type GlobalStatusItem = {
  id: string;
  label: string;
  detail?: string;
  progress: number;
  status: 'processing' | 'ready' | 'failed' | 'idle';
};

type GlobalStatusBarProps = {
  items: GlobalStatusItem[];
  autosaveLabel?: string;
};

export default function GlobalStatusBar({ items, autosaveLabel }: GlobalStatusBarProps) {
  const active = items.filter((item) => item.status === 'processing' || item.status === 'failed');
  if (!active.length && !autosaveLabel) return null;

  return (
    <div className="shrink-0 border-b border-[#2e2e2e] bg-[#141414] px-4 py-1.5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {active.map((item) => (
          <div key={item.id} className="flex min-w-[180px] flex-1 items-center gap-2">
            <span
              className={`shrink-0 text-[11px] ${
                item.status === 'failed' ? 'text-[#f87171]' : 'text-[#face15]'
              }`}
            >
              {item.label}
              {item.detail ? ` · ${item.detail}` : ''}
            </span>
            {item.status === 'processing' ? (
              <div className="h-1 min-w-[80px] flex-1 overflow-hidden rounded bg-[#2a2a2a]">
                <div
                  className="h-full bg-[#face15] transition-all duration-300"
                  style={{ width: `${Math.min(100, Math.max(2, item.progress))}%` }}
                />
              </div>
            ) : null}
            {item.status === 'processing' ? (
              <span className="shrink-0 text-[10px] text-[#888]">{item.progress}%</span>
            ) : null}
          </div>
        ))}
        {autosaveLabel ? (
          <span className="ml-auto text-[10px] text-[#666]">{autosaveLabel}</span>
        ) : null}
      </div>
    </div>
  );
}
