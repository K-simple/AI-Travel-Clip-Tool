'use client';

import type { TemplateSlot } from '@/lib/timeline';

type SubtitleLibraryPanelProps = {
  slots: TemplateSlot[];
  selectedSlotId?: string;
  onSelectSlot: (slotId: string) => void;
  onUpdateSubtitle: (slotId: string, text: string) => void;
  onBatchRecognize?: () => void;
  batchRecognizing?: boolean;
  disabled?: boolean;
};

export default function SubtitleLibraryPanel({
  slots,
  selectedSlotId,
  onSelectSlot,
  onUpdateSubtitle,
  onBatchRecognize,
  batchRecognizing = false,
  disabled = false,
}: SubtitleLibraryPanelProps) {
  if (!slots.length) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-6 text-center text-xs text-[#666]">
        <p className="text-[#8b8b8b]">文本字幕库</p>
        <p className="mt-2 text-[#555]">请先导入模板视频，槽位字幕将显示在这里</p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col p-3 text-xs">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-medium text-[#face15]">槽位字幕</span>
        {onBatchRecognize ? (
          <button
            type="button"
            disabled={disabled || batchRecognizing}
            onClick={onBatchRecognize}
            className="rounded bg-[#2a3a55] px-2 py-1 text-[10px] text-[#93c5fd] hover:bg-[#334866] disabled:opacity-40"
          >
            {batchRecognizing ? '识别中…' : '批量 AI 识别'}
          </button>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
        {slots.map((slot, index) => (
          <div
            key={slot.id}
            className={`rounded border p-2 ${
              slot.id === selectedSlotId
                ? 'border-[#face15]/60 bg-[#2a2a1a]'
                : 'border-[#2e2e2e] bg-[#222]'
            }`}
          >
            <button
              type="button"
              onClick={() => onSelectSlot(slot.id)}
              className="mb-1 w-full text-left text-[10px] text-[#8b8b8b] hover:text-[#ccc]"
            >
              槽位 {index + 1} · {slot.name} · {slot.duration.toFixed(1)}s
            </button>
            <textarea
              value={slot.subtitleText || ''}
              disabled={disabled}
              onChange={(e) => onUpdateSubtitle(slot.id, e.target.value)}
              rows={2}
              placeholder="输入或 AI 识别字幕…"
              className="w-full resize-none rounded border border-[#3a3a3c] bg-[#141416] p-1.5 text-[11px] text-white placeholder:text-[#555] focus:border-[#face15] focus:outline-none disabled:opacity-50"
            />
          </div>
        ))}
      </div>
    </div>
  );
}
