'use client';

import type { TemplateSlot } from '@/lib/timeline';

type SubtitleLibraryPanelProps = {
  slots: TemplateSlot[];
  selectedSlotId?: string;
  onSelectSlot: (slotId: string) => void;
  onUpdateSubtitle: (slotId: string, text: string) => void;
  onBatchRecognize?: () => void;
  onRecognizeSelected?: () => void;
  batchRecognizing?: boolean;
  recognizingSelected?: boolean;
  disabled?: boolean;
};

export default function SubtitleLibraryPanel({
  slots,
  selectedSlotId,
  onSelectSlot,
  onUpdateSubtitle,
  onBatchRecognize,
  onRecognizeSelected,
  batchRecognizing = false,
  recognizingSelected = false,
  disabled = false,
}: SubtitleLibraryPanelProps) {
  const selectedIndex = slots.findIndex((s) => s.id === selectedSlotId);

  if (!slots.length) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-6 text-center text-xs text-editor-subtle">
        <p className="font-medium text-editor-muted">智能字幕识别</p>
        <p className="mt-2">请先导入模板视频，识别结果会写入各槽位字幕轨</p>
      </div>
    );
  }

  return (
    <div className="panel-scroll flex h-full flex-col p-3 text-xs">
      <div className="mb-3 shrink-0 rounded-xl border border-editor-border bg-editor-panel-2 p-3">
        <div className="mb-1 text-sm font-semibold text-editor-text">智能字幕识别</div>
        <p className="mb-3 text-[10px] leading-relaxed text-editor-subtle">
          先分离人声与 BGM，再从人声音轨转写；若结果过长、重复或明显不可信，自动改用画面烧录字幕 OCR。识别后可手动修改。
        </p>
        <div className="flex flex-col gap-2">
          {onBatchRecognize ? (
            <button
              type="button"
              disabled={disabled || batchRecognizing}
              onClick={onBatchRecognize}
              className="ui-btn-primary w-full py-2 text-xs"
            >
              {batchRecognizing ? '批量识别中…' : '批量识别全部槽位'}
            </button>
          ) : null}
          {onRecognizeSelected ? (
            <button
              type="button"
              disabled={disabled || recognizingSelected || selectedIndex < 0}
              onClick={onRecognizeSelected}
              className="ui-btn w-full py-2 text-xs"
            >
              {recognizingSelected
                ? '识别当前槽位中…'
                : selectedIndex >= 0
                  ? `识别当前槽位（槽位 ${selectedIndex + 1}）`
                  : '请先在时间轴选择槽位'}
            </button>
          ) : null}
        </div>
      </div>

      <div className="mb-2 shrink-0 text-[11px] font-medium text-editor-muted">槽位字幕（可手动改）</div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
        {slots.map((slot, index) => (
          <div
            key={slot.id}
            className={`rounded-lg border p-2 ${
              slot.id === selectedSlotId
                ? 'border-editor-accent/50 bg-editor-accent-muted'
                : 'border-editor-border bg-editor-panel-2'
            }`}
          >
            <button
              type="button"
              onClick={() => onSelectSlot(slot.id)}
              className="mb-1 w-full text-left text-[10px] text-editor-subtle hover:text-editor-text"
            >
              槽位 {index + 1} · {slot.name} · {slot.duration.toFixed(1)}s
            </button>
            <textarea
              value={slot.subtitleText || ''}
              disabled={disabled}
              onChange={(e) => onUpdateSubtitle(slot.id, e.target.value)}
              rows={2}
              placeholder="识别后显示在这里，也可手动输入…"
              className="ui-input resize-none py-1.5 text-[11px]"
            />
          </div>
        ))}
      </div>
    </div>
  );
}
