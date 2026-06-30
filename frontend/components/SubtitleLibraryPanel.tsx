'use client';

import { useEffect, useState } from 'react';
import type { SubtitleClip, TemplateSlot } from '@/lib/timeline';
import type { SpokenCaptionSegment } from '@/lib/primarySubtitleClips';
import {
  labelSubtitleQuality,
  labelSubtitleSource,
  slotSubtitleWarning,
  subtitleQualityTone,
} from '@/lib/subtitleStatus';

export type { SpokenCaptionSegment };

const SPLIT_REASON_LABELS: Record<string, string> = {
  punctuation: '标点',
  pause: '停顿',
  semantic: '语义',
  max_duration: '时长',
  max_chars: '字数',
  merged_short: '合并',
  asr_segment: 'ASR',
  caption_sentence: '一句一槽',
  ocr_boundary_split: 'OCR拆分',
  ocr_boundary_merge: 'OCR合并',
};

const SOURCE_LABELS: Record<string, string> = {
  asr: 'ASR',
  ocr: 'OCR',
  asr_ocr_fused: '融合',
  asr_ocr_validated: 'ASR+OCR校验',
};

const VALIDATION_ACTION_LABELS: Record<string, string> = {
  validated: '已校验',
  keep: '已校验',
  ocr_split: 'OCR拆分',
  ocr_merge: 'OCR合并',
  mismatch: '不一致',
  asr_only: '仅ASR',
};

type SubtitleLibraryPanelProps = {
  slots: TemplateSlot[];
  selectedSlotId?: string;
  onSelectSlot: (slotId: string) => void;
  onUpdateSubtitle: (slotId: string, text: string) => void;
  onRecognizeAll?: () => void;
  onApplyCaptionSlots?: () => void;
  onApplyVisualSceneSlots?: () => void;
  applyingCaptionSlots?: boolean;
  onGenerateTts?: () => void;
  onAlignTimelineToTts?: () => void;
  generatingTts?: boolean;
  aligningTimeline?: boolean;
  voiceProfiles?: Array<{ voiceId?: string; displayName?: string }>;
  selectedVoiceId?: string;
  onVoiceChange?: (voiceId: string) => void;
  ttsSegments?: import('@/lib/timeline').TtsSegment[];
  onUpdateSubtitleClip?: (index: number, patch: Partial<SubtitleClip>) => void;
  onRecognizeSelected?: () => void;
  recognizingAll?: boolean;
  recognizingSelected?: boolean;
  recognizeProgress?: string;
  subtitleMode?: 'speech' | 'burned';
  onSubtitleModeChange?: (mode: 'speech' | 'burned') => void;
  spokenCaptions?: SpokenCaptionSegment[];
  subtitleClips?: SubtitleClip[];
  recognitionDebug?: Record<string, unknown> | null;
  disabled?: boolean;
};

function isDevEnv(): boolean {
  return process.env.NODE_ENV === 'development';
}

function clipDisplayText(clip: SubtitleClip): string {
  return String(clip.displayText || clip.text || '').replace(/\\n/g, '\n');
}

export default function SubtitleLibraryPanel({
  slots,
  selectedSlotId,
  onSelectSlot,
  onUpdateSubtitle,
  onRecognizeAll,
  onApplyCaptionSlots,
  onApplyVisualSceneSlots,
  applyingCaptionSlots = false,
  onGenerateTts,
  onAlignTimelineToTts,
  generatingTts = false,
  aligningTimeline = false,
  voiceProfiles = [],
  selectedVoiceId = 'real_blog_female',
  onVoiceChange,
  ttsSegments = [],
  onUpdateSubtitleClip,
  onRecognizeSelected,
  recognizingAll = false,
  recognizingSelected = false,
  recognizeProgress = '',
  subtitleMode = 'speech',
  onSubtitleModeChange,
  spokenCaptions = [],
  subtitleClips = [],
  recognitionDebug = null,
  disabled = false,
}: SubtitleLibraryPanelProps) {
  const selectedIndex = slots.findIndex((s) => s.id === selectedSlotId);
  const primaryClips = subtitleClips;
  const hasClips = subtitleMode === 'speech' && primaryClips.length > 0;

  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    if (hasClips) setAdvancedOpen(false);
  }, [hasClips]);

  if (!slots.length) {
    return (
      <div className="flex h-full min-h-0 flex-col items-center justify-center p-6 text-center text-xs text-editor-subtle">
        <p className="font-medium text-editor-muted">字幕</p>
        <p className="mt-2 max-w-[220px] leading-relaxed">
          上传模板后时间轴为整段原片；请先「识别字幕」，再选择分割方式
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden text-xs">
      {/* 顶部操作区：固定高度，不挤压字幕列表 */}
      <div className="shrink-0 space-y-2 border-b border-editor-border bg-editor-panel/95 p-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-editor-text">字幕</div>
            <p className="mt-0.5 text-[10px] leading-relaxed text-editor-subtle">
              {hasClips
                ? `已识别 ${primaryClips.length} 句，可直接编辑下方文本`
                : '识别字幕后在此编辑，确认后再 AI 分割画面'}
            </p>
          </div>
          {hasClips ? (
            <span className="shrink-0 rounded-full bg-editor-accent-muted px-2 py-0.5 text-[10px] font-medium text-editor-accent">
              {primaryClips.length} 句
            </span>
          ) : null}
        </div>

        {onSubtitleModeChange ? (
          <div className="flex gap-1.5">
            <button
              type="button"
              disabled={disabled || recognizingAll}
              onClick={() => onSubtitleModeChange('speech')}
              className={`flex-1 rounded-lg border py-1 text-[10px] ${
                subtitleMode === 'speech'
                  ? 'border-editor-accent bg-editor-accent-muted text-editor-accent'
                  : 'border-editor-border text-editor-muted'
              }`}
            >
              口播
            </button>
            <button
              type="button"
              disabled={disabled || recognizingAll}
              onClick={() => onSubtitleModeChange('burned')}
              className={`flex-1 rounded-lg border py-1 text-[10px] ${
                subtitleMode === 'burned'
                  ? 'border-editor-accent bg-editor-accent-muted text-editor-accent'
                  : 'border-editor-border text-editor-muted'
              }`}
            >
              烧录
            </button>
          </div>
        ) : null}

        {recognizeProgress ? (
          <p className="text-[10px] text-editor-accent">{recognizeProgress}</p>
        ) : null}

        <div className="grid grid-cols-2 gap-1.5">
          {onRecognizeAll ? (
            <button
              type="button"
              disabled={disabled || recognizingAll || recognizingSelected}
              onClick={onRecognizeAll}
              className="ui-btn-primary col-span-2 py-2 text-xs"
            >
              {recognizingAll ? '识别中…' : hasClips ? '重新识别字幕' : '识别字幕'}
            </button>
          ) : null}
          {onApplyVisualSceneSlots ? (
            <button
              type="button"
              disabled={
                disabled ||
                applyingCaptionSlots ||
                recognizingAll ||
                recognizingSelected
              }
              onClick={onApplyVisualSceneSlots}
              className="ui-btn col-span-2 border-editor-border py-2 text-xs text-editor-text"
            >
              {applyingCaptionSlots ? '切分中…' : '按原视频画面切分'}
            </button>
          ) : null}
          {onApplyCaptionSlots ? (
            <button
              type="button"
              disabled={
                disabled ||
                applyingCaptionSlots ||
                recognizingAll ||
                recognizingSelected ||
                primaryClips.length === 0
              }
              onClick={onApplyCaptionSlots}
              className="ui-btn col-span-2 border-editor-accent/40 py-2 text-xs text-editor-accent"
            >
              {applyingCaptionSlots ? '分割中…' : '按字幕一句一画面'}
            </button>
          ) : null}
        </div>

        <button
          type="button"
          onClick={() => setAdvancedOpen((v) => !v)}
          className="flex w-full items-center justify-between rounded-lg border border-editor-border/60 bg-editor-panel-2 px-2 py-1.5 text-[10px] text-editor-muted hover:text-editor-text"
        >
          <span>TTS 与高级步骤</span>
          <span className="text-editor-subtle">{advancedOpen ? '▲' : '▼'}</span>
        </button>

        {advancedOpen ? (
          <div className="space-y-1.5 rounded-lg border border-editor-border/60 bg-editor-panel-2 p-2">
            <p className="text-[10px] leading-relaxed text-editor-subtle">
              3 选音色 → 4 生成 AI 人声 → 5 按人声对齐 → 6 按画面或字幕切分
            </p>
            {voiceProfiles.length > 0 && onVoiceChange ? (
              <label className="flex flex-col gap-1 text-[10px] text-editor-subtle">
                AI 音色
                <select
                  value={selectedVoiceId}
                  disabled={disabled || generatingTts}
                  onChange={(e) => onVoiceChange(e.target.value)}
                  className="rounded-lg border border-editor-border bg-editor-panel px-2 py-1.5 text-xs text-editor-text"
                >
                  {voiceProfiles.map((v) => (
                    <option key={v.voiceId} value={v.voiceId}>
                      {v.displayName || v.voiceId}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {onGenerateTts ? (
              <button
                type="button"
                disabled={disabled || generatingTts || recognizingAll || primaryClips.length === 0}
                onClick={onGenerateTts}
                className="ui-btn w-full py-1.5 text-[10px]"
              >
                {generatingTts ? '生成中…' : '生成 AI 人声'}
              </button>
            ) : null}
            {onAlignTimelineToTts ? (
              <button
                type="button"
                disabled={disabled || aligningTimeline || generatingTts || ttsSegments.length === 0}
                onClick={onAlignTimelineToTts}
                className="ui-btn w-full py-1.5 text-[10px]"
              >
                {aligningTimeline ? '对齐中…' : '按人声对齐时间轴'}
              </button>
            ) : null}
            {onRecognizeSelected ? (
              <button
                type="button"
                disabled={disabled || recognizingSelected || recognizingAll || selectedIndex < 0}
                onClick={onRecognizeSelected}
                className="ui-btn w-full py-1.5 text-[10px]"
              >
                {recognizingSelected
                  ? '识别中…'
                  : selectedIndex >= 0
                    ? `识别当前槽位（${selectedIndex + 1}）`
                    : '请先在时间轴选择槽位'}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      {/* 主内容：字幕列表占满剩余高度 */}
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {subtitleMode === 'speech' ? (
          hasClips ? (
            <div className="space-y-2">
              <div className="sticky top-0 z-[1] -mx-1 mb-1 bg-editor-panel/95 px-1 py-1 text-[11px] font-medium text-editor-muted backdrop-blur-sm">
                校验字幕列表 · ASR 主文本 + OCR 边界校验 · 点击编辑
              </div>
              {primaryClips.map((clip, i) => {
                const reason = String(clip.splitReason || 'asr_segment');
                const reasonLabel = SPLIT_REASON_LABELS[reason] || reason;
                const sourceKey = String(clip.source || 'asr');
                const sourceLabel = SOURCE_LABELS[sourceKey] || sourceKey;
                const vAction = String(clip.validationDebug?.validationAction || clip.validationStatus || '');
                const vLabel = VALIDATION_ACTION_LABELS[vAction] || (clip.validationStatus === 'validated' ? '已校验' : '');
                const dur =
                  clip.duration ??
                  (clip.end != null && clip.start != null
                    ? Number(clip.end) - Number(clip.start)
                    : undefined);
                return (
                  <div
                    key={clip.id || `cap-${i}`}
                    className={`rounded-lg border p-2 ${
                      clip.quality?.needsReview
                        ? 'border-[#face15]/50 bg-[#face15]/5'
                        : 'border-editor-border/60 bg-editor-panel-2'
                    }`}
                  >
                    <div className="mb-1.5 flex flex-wrap items-center gap-x-1 gap-y-0.5 text-[10px] text-editor-subtle">
                      <span className="font-medium text-editor-muted">#{i + 1}</span>
                      <span>
                        {Number(clip.start ?? 0).toFixed(1)}s – {Number(clip.end ?? 0).toFixed(1)}s
                      </span>
                      {dur != null ? <span>· {dur.toFixed(1)}s</span> : null}
                      <span className="text-editor-accent/90">{sourceLabel}</span>
                      {reasonLabel ? <span>· {reasonLabel}</span> : null}
                      {vLabel ? (
                        <span className={clip.quality?.needsReview ? 'text-[#face15]' : 'text-[#4ade80]'}>
                          {vLabel}
                        </span>
                      ) : null}
                      {clip.quality?.needsReview ? (
                        <span className="text-[#face15]">建议检查</span>
                      ) : null}
                    </div>
                    {clip.validationDebug?.ocrText &&
                    clip.validationDebug?.asrText &&
                    clip.validationDebug.asrText !== clip.validationDebug.ocrText &&
                    isDevEnv() ? (
                      <div className="mb-1.5 rounded border border-editor-border/40 bg-editor-panel/60 px-2 py-1 text-[9px] leading-relaxed text-editor-subtle">
                        <div>OCR: {String(clip.validationDebug.ocrText).slice(0, 48)}</div>
                        {clip.validationDebug.similarity != null ? (
                          <div>相似度: {Number(clip.validationDebug.similarity).toFixed(2)}</div>
                        ) : null}
                      </div>
                    ) : null}
                    {onUpdateSubtitleClip ? (
                      <textarea
                        className="ui-input min-h-[52px] w-full resize-y py-2 text-[12px] leading-relaxed"
                        rows={2}
                        defaultValue={clipDisplayText(clip)}
                        disabled={disabled}
                        placeholder="字幕内容…"
                        onBlur={(e) =>
                          onUpdateSubtitleClip(i, {
                            text: e.target.value,
                            displayText: e.target.value,
                          })
                        }
                      />
                    ) : (
                      <div className="whitespace-pre-wrap text-[12px] leading-relaxed text-editor-text">
                        {clipDisplayText(clip)}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="flex h-full min-h-[120px] flex-col items-center justify-center rounded-xl border border-dashed border-editor-border/70 bg-editor-panel-2/50 px-4 py-8 text-center">
              <p className="text-[11px] font-medium text-editor-muted">尚无字幕</p>
              <p className="mt-2 max-w-[240px] text-[10px] leading-relaxed text-editor-subtle">
                点击上方「识别字幕」，识别完成后本区域会显示每一句，可直接修改文本
              </p>
            </div>
          )
        ) : (
          <>
            <div className="sticky top-0 z-[1] mb-2 bg-editor-panel/95 py-1 text-[11px] font-medium text-editor-muted backdrop-blur-sm">
              槽位字幕（烧录模式）
            </div>
            <div className="space-y-2">
              {slots.map((slot, index) => {
                const warning = slotSubtitleWarning(slot);
                const tone = subtitleQualityTone(slot.subtitle_quality);
                const badgeClass =
                  tone === 'ok'
                    ? 'text-[#4ade80]'
                    : tone === 'warn'
                      ? 'text-[#face15]'
                      : 'text-[#f87171]';
                return (
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
                      {slot.subtitle_quality ? (
                        <span className={`ml-1 ${badgeClass}`}>
                          · {labelSubtitleQuality(slot.subtitle_quality)}
                        </span>
                      ) : null}
                      {slot.subtitle_source ? (
                        <span className="ml-1">· {labelSubtitleSource(slot.subtitle_source)}</span>
                      ) : null}
                    </button>
                    {warning ? (
                      <p className="mb-1 text-[10px] leading-relaxed text-[#f87171]">{warning}</p>
                    ) : null}
                    <textarea
                      value={slot.subtitleText || ''}
                      disabled={disabled}
                      onChange={(e) => onUpdateSubtitle(slot.id, e.target.value)}
                      rows={2}
                      placeholder="识别后显示在这里，也可手动输入…"
                      className="ui-input min-h-[52px] resize-y py-2 text-[12px]"
                    />
                  </div>
                );
              })}
            </div>
          </>
        )}

        {isDevEnv() && recognitionDebug ? (
          <details className="mt-3 rounded-lg border border-dashed border-editor-border/70 bg-editor-panel-2 p-2 text-[10px] text-editor-subtle">
            <summary className="cursor-pointer text-editor-muted">调试信息</summary>
            <pre className="mt-2 max-h-24 overflow-auto whitespace-pre-wrap break-all">
              {JSON.stringify(recognitionDebug, null, 2)}
            </pre>
          </details>
        ) : null}
      </div>
    </div>
  );
}
