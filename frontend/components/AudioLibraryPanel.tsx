'use client';

import type { TemplateSlot } from '@/lib/timeline';

type AudioLibraryPanelProps = {
  slots: TemplateSlot[];
  templateMusicEnabled: boolean;
  templateAudioUrl?: string;
  onToggleTemplateMusic: () => void;
  onToggleSlotOriginalAudio: (slotId: string) => void;
  selectedSlotId?: string;
  onSelectSlot: (slotId: string) => void;
};

export default function AudioLibraryPanel({
  slots,
  templateMusicEnabled,
  templateAudioUrl,
  onToggleTemplateMusic,
  onToggleSlotOriginalAudio,
  selectedSlotId,
  onSelectSlot,
}: AudioLibraryPanelProps) {
  return (
    <div className="flex h-full flex-col p-3 text-xs">
      <div className="mb-3 rounded border border-[#2e2e2e] bg-[#222] p-2">
        <div className="mb-2 font-medium text-[#face15]">模板 BGM</div>
        <button
          type="button"
          onClick={onToggleTemplateMusic}
          className="w-full rounded bg-[#2a2a2a] py-1.5 text-[#ccc] hover:bg-[#333]"
        >
          模板音乐：{templateMusicEnabled ? '开启' : '关闭'}
        </button>
        {templateAudioUrl ? (
          <p className="mt-2 truncate text-[10px] text-[#666]">音频轨已就绪</p>
        ) : (
          <p className="mt-2 text-[10px] text-[#666]">上传模板后自动提取 BGM</p>
        )}
      </div>

      <div className="mb-1 font-medium text-[#8b8b8b]">槽位原声</div>
      {!slots.length ? (
        <p className="text-[10px] text-[#555]">导入模板后可按槽位开关素材原声</p>
      ) : (
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
          {slots.map((slot, index) => (
            <div
              key={slot.id}
              className={`flex items-center justify-between rounded border px-2 py-1.5 ${
                slot.id === selectedSlotId
                  ? 'border-[#face15]/50 bg-[#2a2a1a]'
                  : 'border-[#2e2e2e] bg-[#222]'
              }`}
            >
              <button
                type="button"
                onClick={() => onSelectSlot(slot.id)}
                className="min-w-0 flex-1 truncate text-left text-[11px] text-[#ccc] hover:text-white"
              >
                {index + 1}. {slot.name}
                {slot.matchedAssetId ? '' : ' · 未匹配'}
              </button>
              <button
                type="button"
                disabled={!slot.matchedAssetId}
                onClick={() => onToggleSlotOriginalAudio(slot.id)}
                className={`ml-2 shrink-0 rounded px-2 py-0.5 text-[10px] ${
                  slot.useOriginalAudio
                    ? 'bg-[#1a3a55] text-[#93c5fd]'
                    : 'bg-[#333] text-[#888]'
                } disabled:opacity-40`}
              >
                原声 {slot.useOriginalAudio ? '开' : '关'}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
