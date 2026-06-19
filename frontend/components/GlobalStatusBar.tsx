'use client';

export type GlobalStatusItem = {
  id: string;
  label: string;
  detail?: string;
  progress: number;
  indeterminate?: boolean;
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
    <div className="shrink-0 border-b border-editor-border bg-editor-bg/80 px-3 py-2 backdrop-blur-sm sm:px-5">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        {active.map((item) => (
          <div
            key={item.id}
            className={`flex min-w-0 max-w-full flex-1 basis-[min(100%,280px)] items-center gap-2.5 rounded-lg border px-3 py-1.5 sm:min-w-[200px] sm:basis-auto ${
              item.status === 'failed'
                ? 'border-red-500/25 bg-red-500/10'
                : 'border-editor-border bg-editor-panel-2/80'
            }`}
          >
            <span
              className={`min-w-0 truncate text-[11px] font-medium ${
                item.status === 'failed' ? 'text-editor-danger' : 'text-editor-accent'
              }`}
              title={item.detail ? `${item.label} · ${item.detail}` : item.label}
            >
              {item.label}
              {item.detail ? ` · ${item.detail}` : ''}
            </span>
            {item.status === 'processing' ? (
              <div className="ui-progress-track min-w-[72px] flex-1">
                {item.indeterminate ? (
                  <div className="status-indeterminate-bar ui-progress-fill w-2/5" />
                ) : (
                  <div
                    className="ui-progress-fill"
                    style={{ width: `${Math.min(100, Math.max(2, item.progress))}%` }}
                  />
                )}
              </div>
            ) : null}
            {item.status === 'processing' && !item.indeterminate ? (
              <span className="shrink-0 text-[10px] tabular-nums text-editor-subtle">{item.progress}%</span>
            ) : null}
          </div>
        ))}
        {autosaveLabel ? (
          <span className="w-full text-[10px] text-editor-subtle sm:ml-auto sm:w-auto">{autosaveLabel}</span>
        ) : null}
      </div>
    </div>
  );
}
