'use client';

import { useEffect, useState } from 'react';
import { apiHeaders, apiUrl } from '@/lib/api';
import {
  DEFAULT_SLOT_EFFECTS,
  type SlotEffects,
  type TransitionOut,
} from '@/lib/slotEffects';

type TransitionPreset = { id: string; name: string; ffmpeg: string; duration: number };

type EffectsPanelProps = {
  effects: SlotEffects;
  onChange: (effects: SlotEffects) => void;
  disabled?: boolean;
  slotId?: string;
};

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  onChange,
  disabled,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-[#8b8b8b]">
      <span className="flex justify-between">
        <span>{label}</span>
        <span className="text-[#e5e5e5]">{value.toFixed(2)}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-[#face15]"
      />
    </label>
  );
}

export default function EffectsPanel({ effects, onChange, disabled, slotId }: EffectsPanelProps) {
  const [transitions, setTransitions] = useState<TransitionPreset[]>([]);
  const [previewVf, setPreviewVf] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const merged = { ...DEFAULT_SLOT_EFFECTS, ...effects };
  const grade = merged.colorGrade ?? DEFAULT_SLOT_EFFECTS.colorGrade!;
  const mask = merged.mask ?? DEFAULT_SLOT_EFFECTS.mask!;

  useEffect(() => {
    void (async () => {
      try {
        const resp = await fetch(apiUrl('/api/effects/transitions'), { headers: apiHeaders() });
        const data = await resp.json();
        if (resp.ok && Array.isArray(data.presets)) {
          setTransitions(data.presets.slice(0, 120));
        }
      } catch {
        /* ignore */
      }
    })();
  }, []);

  const patch = (partial: Partial<SlotEffects>) => onChange({ ...merged, ...partial });

  const setTransition = (id: string) => {
    const preset = transitions.find((p) => p.id === id);
    const next: TransitionOut = {
      type: id,
      duration: preset?.duration ?? 0.3,
    };
    patch({ transitionOut: next });
  };

  const previewFilterChain = async () => {
    setPreviewLoading(true);
    setPreviewVf('');
    try {
      const clip = {
        speed: merged.speed ?? 1,
        optical_flow: merged.opticalFlow ?? false,
        color_grade: merged.colorGrade,
        mask: merged.mask,
        keyframes: merged.keyframes ?? [],
        transition_out: merged.transitionOut,
      };
      const resp = await fetch(apiUrl('/api/effects/preview-filter'), {
        method: 'POST',
        headers: { ...apiHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ clip, width: 1080, height: 1920 }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || '预览失败');
      setPreviewVf(String(data.vf || ''));
    } catch (err) {
      setPreviewVf(err instanceof Error ? err.message : '预览失败');
    } finally {
      setPreviewLoading(false);
    }
  };

  return (
    <div className="space-y-3 border-t border-[#2e2e2e] pt-3">
      <div className="text-xs font-medium text-[#face15]">专业特效</div>

      <SliderRow
        label="变速"
        value={merged.speed ?? 1}
        min={0.25}
        max={4}
        step={0.05}
        disabled={disabled}
        onChange={(speed) => patch({ speed })}
      />

      <label className="flex items-center gap-2 text-xs text-[#c5c5c5]">
        <input
          type="checkbox"
          checked={!!merged.opticalFlow}
          disabled={disabled}
          onChange={(e) => patch({ opticalFlow: e.target.checked })}
        />
        光流变速（minterpolate）
      </label>

      <div className="text-[11px] text-[#8b8b8b]">调色</div>
      <SliderRow
        label="亮度"
        value={grade.brightness ?? 0}
        min={-0.5}
        max={0.5}
        step={0.02}
        disabled={disabled}
        onChange={(brightness) => patch({ colorGrade: { ...grade, brightness } })}
      />
      <SliderRow
        label="对比度"
        value={grade.contrast ?? 1}
        min={0.5}
        max={2}
        step={0.05}
        disabled={disabled}
        onChange={(contrast) => patch({ colorGrade: { ...grade, contrast } })}
      />
      <SliderRow
        label="饱和度"
        value={grade.saturation ?? 1}
        min={0}
        max={2}
        step={0.05}
        disabled={disabled}
        onChange={(saturation) => patch({ colorGrade: { ...grade, saturation } })}
      />

      <div className="text-[11px] text-[#8b8b8b]">蒙版</div>
      <label className="flex items-center gap-2 text-xs text-[#c5c5c5]">
        <input
          type="checkbox"
          checked={!!mask.enabled}
          disabled={disabled}
          onChange={(e) => patch({ mask: { ...mask, enabled: e.target.checked } })}
        />
        启用矩形蒙版
      </label>

      <div className="text-[11px] text-[#8b8b8b]">转场（{transitions.length}+）</div>
      <select
        className="w-full rounded border border-[#3a3a3c] bg-[#1c1c1e] px-2 py-1.5 text-xs text-[#e5e5e5]"
        disabled={disabled}
        value={merged.transitionOut?.type ?? 'fade_3'}
        onChange={(e) => setTransition(e.target.value)}
      >
        {transitions.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>

      <button
        type="button"
        disabled={disabled || previewLoading}
        onClick={() => void previewFilterChain()}
        className="mt-2 w-full rounded bg-[#2a3a55] py-1.5 text-xs text-[#93c5fd] hover:bg-[#334866] disabled:cursor-not-allowed disabled:opacity-40"
      >
        {previewLoading ? '编译滤镜链…' : '预览 FFmpeg 滤镜链'}
      </button>
      {previewVf ? (
        <pre className="mt-2 max-h-24 overflow-auto rounded border border-[#333] bg-[#0d0d0d] p-2 text-[9px] leading-relaxed text-[#8b8b8b]">
          {previewVf}
        </pre>
      ) : null}
      {slotId ? (
        <p className="text-[10px] text-[#555]">预览区已同步近似调色效果</p>
      ) : null}
    </div>
  );
}
