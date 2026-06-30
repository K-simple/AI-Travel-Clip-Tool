'use client';

import { useEffect, useMemo, useState } from 'react';
import type { TemplateSlot } from '@/lib/timeline';
import {
  EFFECT_CATEGORY_ORDER,
  applyEffectPresetToSlots,
  fetchEffectsLibrary,
  type EffectCategory,
  type EffectPreset,
} from '@/lib/effectsLibrary';

type EffectsLibraryPanelProps = {
  slots: TemplateSlot[];
  selectedSlotId?: string;
  onSelectSlot: (slotId: string) => void;
  onApplyPreset: (slots: TemplateSlot[]) => void;
  onAnalyzeTemplateEffects?: () => void;
  analyzingEffects?: boolean;
  disabled?: boolean;
};

export default function EffectsLibraryPanel({
  slots,
  selectedSlotId,
  onSelectSlot,
  onApplyPreset,
  onAnalyzeTemplateEffects,
  analyzingEffects = false,
  disabled = false,
}: EffectsLibraryPanelProps) {
  const [categories, setCategories] = useState<EffectCategory[]>([]);
  const [activeCategory, setActiveCategory] = useState<string>('subtitle_in');
  const [loading, setLoading] = useState(true);
  const [applyTarget, setApplyTarget] = useState<'selected' | 'all'>('selected');

  useEffect(() => {
    void (async () => {
      setLoading(true);
      const data = await fetchEffectsLibrary();
      const cats = data?.categories || [];
      setCategories(cats);
      const first = EFFECT_CATEGORY_ORDER.find((id) => cats.some((c) => c.id === id)) || cats[0]?.id;
      if (first) setActiveCategory(first);
      setLoading(false);
    })();
  }, []);

  const sortedCategories = useMemo(() => {
    const order = EFFECT_CATEGORY_ORDER as readonly string[];
    return [...categories].sort((a, b) => {
      const ia = order.indexOf(a.id);
      const ib = order.indexOf(b.id);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
  }, [categories]);

  const activePresets = useMemo(
    () => sortedCategories.find((c) => c.id === activeCategory)?.presets || [],
    [sortedCategories, activeCategory]
  );

  const selectedIndex = slots.findIndex((s) => s.id === selectedSlotId);
  const selectedSlot = selectedIndex >= 0 ? slots[selectedIndex] : null;
  const aiSuggestedIds = new Set(selectedSlot?.ai_effect_understanding?.catalog_preset_ids || []);
  const aiUnderstanding = selectedSlot?.ai_effect_understanding;

  const handleApply = (preset: EffectPreset) => {
    if (disabled) return;
    if (applyTarget === 'selected' && !selectedSlotId) return;
    const updated = applyEffectPresetToSlots(slots, preset, applyTarget, selectedSlotId);
    onApplyPreset(updated);
  };

  if (!slots.length) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-6 text-center text-xs text-editor-subtle">
        <p className="font-medium text-editor-muted">特效库</p>
        <p className="mt-2">导入模板并识别字幕后，在此手动为槽位应用花字/动效（AI 推荐需您点应用）</p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden p-3 text-xs">
      <div className="mb-2 shrink-0 rounded-xl border border-editor-border bg-editor-panel-2 p-3">
        <div className="mb-1 text-sm font-semibold text-editor-text">特效库</div>
        <p className="mb-3 text-[10px] leading-relaxed text-editor-subtle">
          模板上传后 AI 自动分析每槽位的调色、动效与字幕动画；也可手动选择预设，导出剪映草稿时烧录进画面。
        </p>
        <div className="mb-2 flex gap-2">
          <button
            type="button"
            className={`ui-btn flex-1 py-1.5 text-[10px] ${applyTarget === 'selected' ? 'ring-1 ring-[#face15]' : ''}`}
            onClick={() => setApplyTarget('selected')}
          >
            当前槽位
          </button>
          <button
            type="button"
            className={`ui-btn flex-1 py-1.5 text-[10px] ${applyTarget === 'all' ? 'ring-1 ring-[#face15]' : ''}`}
            onClick={() => setApplyTarget('all')}
          >
            全部槽位
          </button>
        </div>
        {onAnalyzeTemplateEffects ? (
          <button
            type="button"
            disabled={disabled || analyzingEffects}
            onClick={onAnalyzeTemplateEffects}
            className="ui-btn-primary mt-2 w-full py-2 text-xs"
          >
            {analyzingEffects ? 'AI 分析特效中…' : '重新 AI 分析模板特效'}
          </button>
        ) : null}
      </div>

      {selectedSlot ? (
        <div className="mb-2 shrink-0 rounded-lg border border-editor-border bg-editor-panel px-2 py-1.5 text-[10px] text-editor-subtle">
          当前：槽位 {selectedIndex + 1}
          {(selectedSlot.template_effect_label || selectedSlot.subtitle_effect_label) ? (
            <span className="ml-1 text-editor-muted">
              · AI: {selectedSlot.subtitle_effect_label || selectedSlot.template_effect_label}
            </span>
          ) : null}
          {aiUnderstanding?.summary ? (
            <p className="mt-1 leading-relaxed text-[#93c5fd]/90">{aiUnderstanding.summary}</p>
          ) : null}
          {aiUnderstanding?.preset_labels?.length ? (
            <p className="mt-1 leading-relaxed text-[#face15]/90">
              推荐预设：{aiUnderstanding.preset_labels.join(' · ')}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="mb-2 flex shrink-0 flex-wrap gap-1">
        {sortedCategories.map((cat) => (
          <button
            key={cat.id}
            type="button"
            onClick={() => setActiveCategory(cat.id)}
            className={`rounded-md px-2 py-1 text-[10px] ${
              activeCategory === cat.id
                ? 'bg-[#face15]/20 text-[#face15]'
                : 'bg-editor-panel text-editor-subtle hover:text-editor-text'
            }`}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="py-8 text-center text-editor-subtle">加载特效库…</div>
      ) : (
        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
          {activePresets.map((preset) => (
            <button
              key={preset.id}
              type="button"
              disabled={disabled || (applyTarget === 'selected' && !selectedSlotId)}
              onClick={() => handleApply(preset)}
              className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left transition disabled:opacity-40 ${
                aiSuggestedIds.has(preset.id)
                  ? 'border-[#face15]/50 bg-[#face15]/10 hover:border-[#face15]/70'
                  : 'border-editor-border bg-editor-panel hover:border-[#face15]/40 hover:bg-editor-panel-2'
              }`}
            >
              <span className="text-xs text-editor-text">
                {preset.name}
                {aiSuggestedIds.has(preset.id) ? (
                  <span className="ml-1 text-[10px] text-[#face15]">AI 推荐</span>
                ) : null}
              </span>
              <span className="text-[10px] text-editor-subtle">应用</span>
            </button>
          ))}
          {!activePresets.length ? (
            <div className="py-6 text-center text-editor-subtle">该分类暂无预设</div>
          ) : null}
        </div>
      )}

      <div className="mt-2 shrink-0 space-y-1 border-t border-editor-border pt-2">
        <div className="text-[10px] font-medium text-editor-muted">槽位 AI 特效标签</div>
        {slots.slice(0, 8).map((slot, index) => (
          <button
            key={slot.id}
            type="button"
            onClick={() => onSelectSlot(slot.id)}
            className={`block w-full truncate rounded px-1 py-0.5 text-left text-[10px] ${
              slot.id === selectedSlotId ? 'bg-[#face15]/15 text-[#face15]' : 'text-editor-subtle hover:text-editor-text'
            }`}
          >
            槽位 {index + 1}
            {(slot.subtitle_effect_label || slot.template_effect_label)
              ? ` · ${slot.subtitle_effect_label || slot.template_effect_label}`
              : slot.ai_effect_understanding?.preset_labels?.length
                ? ` · ${slot.ai_effect_understanding.preset_labels.slice(0, 2).join(' · ')}`
                : ''}
          </button>
        ))}
      </div>
    </div>
  );
}
