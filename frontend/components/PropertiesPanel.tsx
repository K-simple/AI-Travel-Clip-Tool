'use client';

import EffectsPanel from '@/components/EffectsPanel';
import { describeSubtitleSceneMatch, describeSubtitleStyle, parseSubtitleSegments, type SfxMarker } from '@/lib/slotEdit';
import { isTrackLocked, type TrackControls, type TrackKey } from '@/lib/trackControls';
import type { MatchStrategy } from '@/lib/matchStrategy';
import type { TemplateAiVision } from '@/lib/useTemplateProcessing';
import { DEFAULT_SLOT_EFFECTS, type SlotEffects } from '@/lib/slotEffects';
import {
  labelSubtitleQuality,
  labelSubtitleSource,
  slotSubtitleWarning,
  subtitleQualityTone,
} from '@/lib/subtitleStatus';

export type MatchWeights = {
  tags_weight: number;
  visual_weight: number;
  duration_tolerance: number;
};

type SelectedSlot = {
  id: string;
  name: string;
  duration: number;
  matchedAssetId?: string;
  useOriginalAudio: boolean;
  clipStart: number;
  subtitleText: string;
  subtitle_segments?: unknown[];
  match_score?: number;
  match_reason?: string;
  locked?: boolean;
  asset_filename?: string;
  shot_type?: string;
  scene_tags?: string[];
  ai_description?: string;
  ai_tags?: string[];
  ai_replace_hint?: string;
  ai_subject?: string;
  subtitle_visual_context?: string;
  subtitle_scene_match?: number;
  subtitle_scene_match_reason?: string;
  subtitle_effect_label?: string;
  subtitle_style?: import('@/lib/slotEdit').SubtitleStyle;
  subtitle_source?: string;
  subtitle_quality?: 'ok' | 'low' | 'empty';
  subtitle_status_reason?: string;
  speed?: number;
  opticalFlow?: boolean;
  keyframes?: SlotEffects['keyframes'];
  colorGrade?: SlotEffects['colorGrade'];
  mask?: SlotEffects['mask'];
  transitionOut?: SlotEffects['transitionOut'];
};

type AssetType = {
  id: string;
  title: string;
  duration: string;
};

type PropertiesPanelProps = {
  selectedSlot: SelectedSlot | null;
  trackControls: Record<TrackKey, TrackControls>;
  asset?: AssetType;
  assetDurationSeconds?: number;
  matchWeights: MatchWeights;
  matchStrategy: MatchStrategy;
  templateName: string;
  slotCount: number;
  templateAiVision?: TemplateAiVision;
  sfxMarkers?: SfxMarker[];
  templateMusicEnabled: boolean;
  matching: boolean;
  matchMessage: string;
  matchError: string;
  onMatchWeightsChange: (weights: MatchWeights) => void;
  onMatchStrategyChange: (strategy: MatchStrategy) => void;
  onUpdateSlot: (updates: Partial<SelectedSlot>) => void;
  onDeleteSlot?: (slotId: string) => void;
  onClearAsset?: (slotId: string) => void;
  onAutoMatch: () => void;
  onToggleTemplateMusic: () => void;
  onRecognizeSlotSubtitle?: () => void;
  recognizingSubtitle?: boolean;
  templateId?: string | null;
  onImportTemplate?: () => void;
  onMoveSlot?: (slotId: string, direction: -1 | 1) => void;
  slotOrderIndex?: number;
  slotOrderTotal?: number;
};

function ParamRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg px-1 py-2.5 text-xs even:bg-editor-panel-2/40">
      <span className="shrink-0 text-editor-muted">{label}</span>
      <span className="text-right font-medium text-editor-text">{value}</span>
    </div>
  );
}

function WeightSlider({
  label,
  value,
  min,
  max,
  step,
  formatValue,
  onChange,
  disabled = false,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  formatValue: (v: number) => string;
  onChange: (v: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className={`py-2 ${disabled ? 'opacity-50' : ''}`}>
      <div className="mb-1.5 flex items-center justify-between text-xs">
        <span className="text-[#aaa]">{label}</span>
        <span className="font-medium text-[#face15]">{formatValue(value)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="editor-slider w-full disabled:cursor-not-allowed"
      />
    </div>
  );
}

function normalizeMatchWeights(weights: MatchWeights, changedKey: keyof MatchWeights, value: number): MatchWeights {
  const next = { ...weights, [changedKey]: value };
  if (changedKey === 'duration_tolerance') return next;
  const total = next.tags_weight + next.visual_weight;
  if (total > 1) {
    const scale = 1 / total;
    next.tags_weight *= scale;
    next.visual_weight *= scale;
  }
  return next;
}

export default function PropertiesPanel({
  selectedSlot,
  trackControls,
  asset,
  assetDurationSeconds,
  matchWeights,
  matchStrategy,
  templateName,
  slotCount,
  templateAiVision,
  sfxMarkers = [],
  templateMusicEnabled,
  matching,
  matchMessage,
  matchError,
  onMatchWeightsChange,
  onMatchStrategyChange,
  onUpdateSlot,
  onDeleteSlot,
  onClearAsset,
  onAutoMatch,
  onToggleTemplateMusic,
  onRecognizeSlotSubtitle,
  recognizingSubtitle = false,
  templateId,
  onImportTemplate,
  onMoveSlot,
  slotOrderIndex = -1,
  slotOrderTotal = 0,
}: PropertiesPanelProps) {
  const hasTemplate = !!templateId && slotCount > 0;
  const subtitleStyleHint = selectedSlot
    ? describeSubtitleStyle(
        selectedSlot.subtitle_style ||
          parseSubtitleSegments(selectedSlot.subtitle_segments)[0]?.style
      )
    : '';
  const subtitleSceneHint = selectedSlot
    ? describeSubtitleSceneMatch(
        selectedSlot.subtitle_scene_match,
        selectedSlot.subtitle_scene_match_reason,
        selectedSlot.subtitle_visual_context
      )
    : '';
  const durationWeight = Math.max(0, 1 - matchWeights.tags_weight - matchWeights.visual_weight);
  const clipMax = Math.max(selectedSlot?.duration ?? 0, assetDurationSeconds ?? 30);
  const videoLocked = isTrackLocked(trackControls, 'video');
  const subtitleLocked = isTrackLocked(trackControls, 'subtitle');
  const audioVoiceLocked = isTrackLocked(trackControls, 'audioVoice');
  const slotSubtitleMetaWarning = selectedSlot ? slotSubtitleWarning(selectedSlot) : '';
  const slotQualityTone = subtitleQualityTone(selectedSlot?.subtitle_quality);
  const qualityBadgeClass =
    slotQualityTone === 'ok'
      ? 'border-[#2d4a2d] bg-[#1a2e1a] text-[#4ade80]'
      : slotQualityTone === 'warn'
        ? 'border-[#4a4020] bg-[#2a2410] text-[#face15]'
        : 'border-[#4a2828] bg-[#2a1818] text-[#f87171]';

  const updateWeight = (key: keyof MatchWeights, value: number) => {
    onMatchWeightsChange(normalizeMatchWeights(matchWeights, key, value));
  };

  return (
    <aside className="ui-panel flex h-full max-h-[min(20vh,200px)] min-h-0 w-full min-w-0 flex-col overflow-hidden lg:max-h-none">
      <div className="ui-panel-header shrink-0">
        <h2 className="ui-panel-title">草稿参数</h2>
        <p className="ui-panel-subtitle">{templateName || '尚未选择模板'}</p>
      </div>

      <div className="panel-scroll flex-1 overflow-y-auto px-4 py-2">
        {!hasTemplate ? (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-editor-border bg-editor-panel-2/50 px-4 py-10 text-center">
            <p className="text-sm font-medium text-editor-muted">尚未导入模板</p>
            <p className="mt-2 max-w-[220px] text-xs leading-relaxed text-editor-subtle">
              从左侧「导入」拖入模板视频，或点击顶部「导入模板」开始剪辑
            </p>
            {onImportTemplate ? (
              <button type="button" onClick={onImportTemplate} className="ui-btn-primary mt-5">
                导入模板视频
              </button>
            ) : null}
          </div>
        ) : (
          <>
        <ParamRow label="模板名称" value={templateName} />
        <ParamRow label="槽位数量" value={`${slotCount} 个`} />
        {sfxMarkers.length > 0 ? (
          <ParamRow label="音效点位" value={`${sfxMarkers.length} 个（音频轨橙色标记）`} />
        ) : null}
        <ParamRow label="比例" value="9:16" />
        <ParamRow label="分辨率" value="1080×1920" />
        <ParamRow label="模板音乐" value={templateMusicEnabled ? '已开启' : '已关闭'} />
        {templateAiVision?.summary ? (
          <div className="mt-3 rounded-md border border-[#3a3520] bg-[#1a1810] p-2.5">
            <div className="mb-1.5 text-xs font-medium text-[#face15]">AI 模板理解</div>
            <p className="text-[11px] leading-relaxed text-[#ddd]">{templateAiVision.summary}</p>
            {templateAiVision.style || templateAiVision.pacing ? (
              <p className="mt-1 text-[10px] text-[#888]">
                {[templateAiVision.style, templateAiVision.pacing, templateAiVision.mood]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
            ) : null}
            {templateAiVision.replace_guide ? (
              <p className="mt-1.5 text-[10px] leading-relaxed text-[#aaa]">
                替换建议：{templateAiVision.replace_guide}
              </p>
            ) : null}
          </div>
        ) : null}
          </>
        )}

        {hasTemplate && selectedSlot ? (
          <>
            <div className="mt-3 rounded-md border border-[#333] bg-[#141414] p-3">
              <div className="mb-2 text-xs font-medium text-white">槽位操作</div>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={videoLocked}
                  onClick={() => onClearAsset?.(selectedSlot.id)}
                  className="flex-1 rounded-md bg-[#face15] py-2 text-xs font-semibold text-black hover:bg-[#ffe066] disabled:cursor-not-allowed disabled:opacity-40"
                  title="清空当前素材，从左侧拖入新素材替换"
                >
                  {asset ? '换素材' : '拖入素材'}
                </button>
                <button
                  type="button"
                  disabled={videoLocked}
                  onClick={() => onUpdateSlot({ locked: !selectedSlot.locked })}
                  className={`flex-1 rounded-md py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-40 ${
                    selectedSlot.locked
                      ? 'bg-[#2d4a2d] text-[#4ade80] ring-1 ring-[#4ade80]/40'
                      : 'bg-[#2a2a2a] text-[#ccc] hover:bg-[#333]'
                  }`}
                  title="锁定后 AI 自动匹配不会覆盖此槽位"
                >
                  {selectedSlot.locked ? '已锁定' : '锁定槽位'}
                </button>
              </div>
              <p className="mt-2 text-[10px] leading-relaxed text-[#666]">
                {asset
                  ? '点击「换素材」后，从左侧素材库拖一个新视频到时间轴对应槽位'
                  : 'AI 理解模板画面后从素材库挑选相近片段；也可手动拖拽替换'}
              </p>
            </div>

            <div className="mt-3 border-t border-[#2e2e2e] pt-2">
              <div className="mb-1 text-xs font-medium text-[#face15]">当前槽位</div>
              <ParamRow label="槽位名称" value={selectedSlot.ai_description || selectedSlot.name} />
              <ParamRow label="时长" value={`${selectedSlot.duration}s`} />
              <ParamRow label="已匹配" value={asset?.title || '未匹配'} />
              <ParamRow label="镜头类型" value={selectedSlot.shot_type || '未知'} />
              {selectedSlot.ai_description ? (
                <ParamRow label="AI 画面描述" value={selectedSlot.ai_description} />
              ) : null}
              {selectedSlot.ai_replace_hint ? (
                <ParamRow label="替换建议" value={selectedSlot.ai_replace_hint} />
              ) : null}
              {selectedSlot.ai_subject ? (
                <ParamRow label="画面主体" value={selectedSlot.ai_subject} />
              ) : null}
              {selectedSlot.match_score !== undefined ? (
                <ParamRow label="匹配分" value={`${Math.round(selectedSlot.match_score * 100)}%`} />
              ) : null}
              {selectedSlot.match_reason ? (
                <ParamRow label="匹配原因" value={selectedSlot.match_reason} />
              ) : null}
              {selectedSlot.ai_tags?.length ? (
                <ParamRow label="AI 关键词" value={selectedSlot.ai_tags.join(' · ')} />
              ) : null}
              {selectedSlot.scene_tags?.length ? (
                <ParamRow label="匹配标签" value={selectedSlot.scene_tags.join(' · ')} />
              ) : null}
              {selectedSlot.subtitle_source || selectedSlot.subtitle_quality ? (
                <div className="flex items-start justify-between gap-3 rounded-lg px-1 py-2.5 text-xs even:bg-editor-panel-2/40">
                  <span className="shrink-0 text-editor-muted">字幕来源</span>
                  <div className="text-right">
                    <span className="font-medium text-editor-text">
                      {labelSubtitleSource(selectedSlot.subtitle_source)}
                    </span>
                    {selectedSlot.subtitle_quality ? (
                      <span
                        className={`ml-2 inline-flex rounded border px-1.5 py-0.5 text-[10px] ${qualityBadgeClass}`}
                      >
                        {labelSubtitleQuality(selectedSlot.subtitle_quality)}
                      </span>
                    ) : null}
                  </div>
                </div>
              ) : null}
              {slotSubtitleMetaWarning ? (
                <p className="rounded border border-[#4a2828] bg-[#2a1818] px-2 py-1.5 text-[10px] leading-relaxed text-[#f87171]">
                  {slotSubtitleMetaWarning}
                </p>
              ) : null}
            </div>

            <div className="mt-3 border-t border-[#2e2e2e] pt-2">
              <div className="mb-1 text-xs font-medium text-white">槽位编辑</div>
              {videoLocked || subtitleLocked || audioVoiceLocked ? (
                <p className="mb-2 text-[10px] text-[#face15]/80">
                  {[
                    videoLocked ? '视频轨已锁定' : '',
                    subtitleLocked ? '字幕轨已锁定' : '',
                    audioVoiceLocked ? '原声轨已锁定' : '',
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
              ) : null}
              <WeightSlider
                label="裁剪起点"
                value={selectedSlot.clipStart}
                min={0}
                max={clipMax}
                step={0.5}
                formatValue={(v) => `${v.toFixed(1)}s`}
                onChange={(v) => onUpdateSlot({ clipStart: v })}
                disabled={videoLocked}
              />
              <textarea
                value={selectedSlot.subtitleText}
                onChange={(e) => onUpdateSlot({ subtitleText: e.target.value })}
                rows={3}
                placeholder="字幕文本（可手动修改）"
                disabled={subtitleLocked}
                className="mt-2 w-full resize-none rounded border border-[#3a3a3a] bg-[#141414] p-2 text-xs text-white placeholder:text-[#555] focus:border-[#face15] focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
              />
              <div className="mt-2 flex flex-col gap-1.5">
                {onRecognizeSlotSubtitle ? (
                  <button
                    type="button"
                    disabled={subtitleLocked || recognizingSubtitle || !templateId}
                    onClick={onRecognizeSlotSubtitle}
                    className="w-full rounded bg-[#2a3a55] py-1.5 text-xs text-[#93c5fd] hover:bg-[#334866] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {recognizingSubtitle ? '识别中…' : '识别当前槽位字幕'}
                  </button>
                ) : null}
              </div>
              <p className="mt-1 text-[10px] leading-relaxed text-[#666]">
                批量识别请用左侧「字幕」标签页；识别结果仅供参考，换画面后请自行校对
              </p>
              {subtitleStyleHint ? (
                <p className="mt-2 rounded border border-[#3a3a3a] bg-[#141414] px-2 py-1.5 text-[10px] leading-relaxed text-[#face15]/90">
                  花字样式：{selectedSlot.subtitle_effect_label || subtitleStyleHint}
                </p>
              ) : null}
              {subtitleSceneHint ? (
                <p className="mt-2 rounded border border-[#3a3a3a] bg-[#141414] px-2 py-1.5 text-[10px] leading-relaxed text-[#93c5fd]/90">
                  字幕与画面：{subtitleSceneHint}
                </p>
              ) : null}
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  disabled={videoLocked || slotOrderIndex <= 0}
                  onClick={() => onMoveSlot?.(selectedSlot.id, -1)}
                  className="flex-1 rounded bg-[#2a2a2a] py-1.5 text-xs text-[#ccc] hover:bg-[#333] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  ↑ 前移
                </button>
                <button
                  type="button"
                  disabled={videoLocked || slotOrderIndex < 0 || slotOrderIndex >= slotOrderTotal - 1}
                  onClick={() => onMoveSlot?.(selectedSlot.id, 1)}
                  className="flex-1 rounded bg-[#2a2a2a] py-1.5 text-xs text-[#ccc] hover:bg-[#333] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  ↓ 后移
                </button>
              </div>
              <p className="mt-1 text-[10px] text-[#555]">
                或在时间轴片段右上角 ⋮⋮ 拖拽排序（{slotOrderIndex >= 0 ? `${slotOrderIndex + 1}/${slotOrderTotal}` : ''}）
              </p>
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  disabled={audioVoiceLocked}
                  onClick={() => onUpdateSlot({ useOriginalAudio: !selectedSlot.useOriginalAudio })}
                  className="flex-1 rounded bg-[#2a2a2a] py-1.5 text-xs text-[#ccc] hover:bg-[#333] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  原声 {selectedSlot.useOriginalAudio ? '开' : '关'}
                </button>
              </div>
              <button
                type="button"
                disabled={videoLocked}
                onClick={() => onDeleteSlot?.(selectedSlot.id)}
                className="mt-2 w-full rounded bg-[#3a2020] py-1.5 text-xs text-[#f87171] hover:bg-[#4a2828] disabled:cursor-not-allowed disabled:opacity-40"
              >
                删除槽位 (W)
              </button>
              <EffectsPanel
                slotId={selectedSlot.id}
                disabled={videoLocked}
                effects={{
                  speed: selectedSlot.speed ?? DEFAULT_SLOT_EFFECTS.speed,
                  opticalFlow: selectedSlot.opticalFlow,
                  keyframes: selectedSlot.keyframes,
                  colorGrade: selectedSlot.colorGrade,
                  mask: selectedSlot.mask,
                  transitionOut: selectedSlot.transitionOut,
                }}
                onChange={(effects) =>
                  onUpdateSlot({
                    speed: effects.speed,
                    opticalFlow: effects.opticalFlow,
                    keyframes: effects.keyframes,
                    colorGrade: effects.colorGrade,
                    mask: effects.mask,
                    transitionOut: effects.transitionOut,
                  })
                }
              />
            </div>
          </>
        ) : null}

        {hasTemplate ? (
          <>
            <div className="mt-4 border-t border-[#2e2e2e] pt-3">
              <div className="mb-2 text-xs font-medium text-white">生成策略 (PRD)</div>
              {(
                [
                  ['strict_mode', '严格模式（时长不变）'],
                  ['allow_cross_slot', '允许跨槽位素材'],
                  ['prefer_4k', '优先高画质'],
                  ['color_match_template', '色调匹配模板'],
                  ['transition_inherit', '继承转场'],
                  ['use_vector_match', '向量语义匹配'],
                ] as const
              ).map(([key, label]) => (
                <label key={key} className="mt-1 flex items-center gap-2 text-xs text-[#aaa]">
                  <input
                    type="checkbox"
                    checked={!!matchStrategy[key]}
                    onChange={(e) => onMatchStrategyChange({ ...matchStrategy, [key]: e.target.checked })}
                    className="accent-[#face15]"
                  />
                  {label}
                </label>
              ))}
              <WeightSlider
                label="向量权重"
                value={matchStrategy.vector_weight}
                min={0}
                max={0.6}
                step={0.05}
                formatValue={(v) => `${Math.round(v * 100)}%`}
                onChange={(v) => onMatchStrategyChange({ ...matchStrategy, vector_weight: v })}
                disabled={!matchStrategy.use_vector_match}
              />
              <label className="mt-2 flex flex-col gap-1 text-xs text-[#aaa]">
                素材去重策略
                <select
                  value={matchStrategy.dedup_policy}
                  onChange={(e) =>
                    onMatchStrategyChange({
                      ...matchStrategy,
                      dedup_policy: e.target.value as 'global' | 'none',
                    })
                  }
                  className="rounded border border-[#3a3a3c] bg-[#141416] px-2 py-1 text-xs text-[#e5e5e5]"
                >
                  <option value="global">全局去重（推荐）</option>
                  <option value="none">允许重复使用</option>
                </select>
              </label>
            </div>

            <div className="mt-4 border-t border-[#2e2e2e] pt-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-medium text-white">匹配权重设置</span>
                <span className="text-[10px] text-[#8b8b8b]">时长 {Math.round(durationWeight * 100)}%</span>
              </div>
              <WeightSlider
                label="标签权重"
                value={matchWeights.tags_weight}
                min={0}
                max={1}
                step={0.05}
                formatValue={(v) => `${Math.round(v * 100)}%`}
                onChange={(v) => updateWeight('tags_weight', v)}
              />
              <WeightSlider
                label="视觉权重"
                value={matchWeights.visual_weight}
                min={0}
                max={1}
                step={0.05}
                formatValue={(v) => `${Math.round(v * 100)}%`}
                onChange={(v) => updateWeight('visual_weight', v)}
              />
              <WeightSlider
                label="时长容忍度"
                value={matchWeights.duration_tolerance}
                min={1}
                max={5}
                step={0.5}
                formatValue={(v) => `${v.toFixed(1)}×`}
                onChange={(v) => updateWeight('duration_tolerance', v)}
              />
            </div>

            {matchMessage ? <p className="mt-2 text-[10px] text-[#4ade80]">{matchMessage}</p> : null}
            {matchError ? <p className="mt-2 text-[10px] text-[#f87171]">{matchError}</p> : null}
          </>
        ) : null}
      </div>

      <div className="space-y-2 border-t border-[#2e2e2e] p-4">
        {!hasTemplate && onImportTemplate ? (
          <button
            type="button"
            onClick={onImportTemplate}
            className="w-full rounded-md bg-[#face15] py-2.5 text-sm font-semibold text-black hover:bg-[#ffe066]"
          >
            导入模板开始
          </button>
        ) : null}
        <button
          type="button"
          onClick={onToggleTemplateMusic}
          disabled={!hasTemplate}
          className="w-full rounded-md bg-[#2a2a2a] py-2 text-xs text-[#ccc] hover:bg-[#333] disabled:cursor-not-allowed disabled:opacity-40"
        >
          模板音乐：{templateMusicEnabled ? '开启' : '关闭'}
        </button>
        <button
          type="button"
          onClick={onAutoMatch}
          disabled={matching || !hasTemplate}
          className="w-full rounded-md bg-[#face15] py-2.5 text-sm font-semibold text-black hover:bg-[#ffe066] disabled:bg-[#665c20] disabled:text-[#999]"
        >
          {matching ? '智能匹配中…' : 'AI 智能匹配素材'}
        </button>
      </div>
    </aside>
  );
}
