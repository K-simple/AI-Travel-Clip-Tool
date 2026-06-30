'use client';

import PublishPanel from '@/components/PublishPanel';
import { toMediaUrl } from '@/lib/api';
import { ENABLE_PUBLISH_PANEL } from '@/lib/featureFlags';
import {
  capCutSetupSteps,
  REPLACEABLE_TEMPLATE_STEPS,
  type CapCutMateStatus,
} from '@/lib/capcutExport';

export type PreviewExportDrawerProps = {
  open: boolean;
  onClose: () => void;
  exportUrl?: string | null;
  exportResolution?: string;
  onExportResolutionChange?: (resolution: string) => void;
  addSubtitles?: boolean;
  onAddSubtitlesChange?: (value: boolean) => void;
  exportProgress?: number;
  exporting?: boolean;
  onExport?: () => void;
  onExportCapCut?: () => void;
  capCutDraftUrl?: string | null;
  capCutExporting?: boolean;
  capCutExportProgress?: number;
  capCutStatus?: string;
  capCutReplaceableMode?: boolean;
  onCapCutReplaceableModeChange?: (value: boolean) => void;
  capCutMateStatus?: CapCutMateStatus | null;
  onRefreshCapCutMate?: () => void;
  onOpenCapCutDraft?: () => void;
  canExport?: boolean;
};

export default function PreviewExportDrawer({
  open,
  onClose,
  exportUrl,
  exportResolution = '1080x1920',
  onExportResolutionChange,
  addSubtitles = true,
  onAddSubtitlesChange,
  exportProgress = 0,
  exporting = false,
  onExport,
  onExportCapCut,
  capCutDraftUrl = null,
  capCutExporting = false,
  capCutExportProgress = 0,
  capCutStatus = '',
  capCutReplaceableMode = false,
  onCapCutReplaceableModeChange,
  capCutMateStatus,
  onRefreshCapCutMate,
  onOpenCapCutDraft,
  canExport = false,
}: PreviewExportDrawerProps) {
  if (!open) return null;

  const finalExportUrl = exportUrl ? toMediaUrl(exportUrl) : '';

  return (
    <>
      <div className="absolute inset-y-0 right-0 z-20 flex w-[min(280px,85%)] flex-col border-l border-[#2a2a2c] bg-[#1e1e20] shadow-2xl">
        <div className="flex items-center justify-between border-b border-[#2a2a2c] px-3 py-2">
          <span className="text-xs font-medium text-[#e5e5ea]">导出与发布</span>
          <button type="button" onClick={onClose} className="text-[#8e8e93] hover:text-white">
            ✕
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          <label className="mb-3 flex items-center gap-2 text-[11px] text-[#8b8b8b]">
            <input
              type="checkbox"
              checked={addSubtitles}
              onChange={(e) => onAddSubtitlesChange?.(e.target.checked)}
              className="accent-[#face15]"
            />
            导出时烧录字幕
          </label>
          <label className="mb-3 flex flex-col gap-1 text-[11px] text-[#8b8b8b]">
            导出分辨率
            <select
              value={exportResolution}
              onChange={(e) => onExportResolutionChange?.(e.target.value)}
              className="rounded border border-[#3a3a3c] bg-[#141416] px-2 py-1.5 text-xs text-[#e5e5e5]"
            >
              <option value="1080x1920">1080×1920</option>
              <option value="2160x3840">4K 竖屏</option>
              <option value="3840x2160">4K 横屏</option>
            </select>
          </label>
          {finalExportUrl ? (
            <a
              href={finalExportUrl}
              target="_blank"
              rel="noreferrer"
              className="mb-3 block rounded bg-[#2a2a2c] py-2 text-center text-xs text-[#face15] hover:bg-[#333]"
            >
              下载导出视频 →
            </a>
          ) : null}
          {onExport ? (
            <button
              type="button"
              disabled={!canExport || exporting}
              onClick={onExport}
              className="mb-3 w-full rounded bg-[#face15] py-2 text-xs font-semibold text-black hover:bg-[#ffe066] disabled:cursor-not-allowed disabled:bg-[#665c20] disabled:text-[#999]"
            >
              {exporting ? `导出中… ${exportProgress > 0 ? `${exportProgress}%` : ''}` : '开始导出'}
            </button>
          ) : null}
          {onExportCapCut ? (
            <>
              {onCapCutReplaceableModeChange ? (
                <label className="mb-2 flex cursor-pointer items-start gap-2 rounded border border-[#3a3a3c] bg-[#1a1a1c] px-2 py-2 text-[10px] leading-relaxed text-[#b0b0b0]">
                  <input
                    type="checkbox"
                    checked={capCutReplaceableMode}
                    onChange={(e) => onCapCutReplaceableModeChange(e.target.checked)}
                    className="mt-0.5 shrink-0"
                  />
                  <span>
                    <span className="font-medium text-[#e5e5e5]">可替换模板</span>
                    <span className="block text-[#8b8b8b]">
                      导出模板占位片段与槽位标签，在剪映中逐段「替换素材」套用你的成片
                    </span>
                  </span>
                </label>
              ) : null}
              <button
                type="button"
                disabled={!canExport || capCutExporting || exporting || capCutMateStatus?.ready === false}
                onClick={onExportCapCut}
                className="mb-2 w-full rounded border border-[#face15]/40 bg-[#2a2a2c] py-2 text-xs font-medium text-[#face15] hover:bg-[#333] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {capCutExporting
                  ? `生成剪映草稿… ${capCutExportProgress > 0 ? `${capCutExportProgress}%` : ''}`
                  : capCutReplaceableMode
                    ? '导出可替换模板草稿'
                    : '导出剪映草稿（成片）'}
              </button>
              {capCutExporting ? (
                <div className="mb-3 h-1.5 overflow-hidden rounded bg-[#1a3a1a]">
                  <div
                    className={`h-full transition-all ${capCutExportProgress <= 0 ? 'w-1/3 animate-pulse bg-[#face15]/60' : 'bg-[#4ade80]'}`}
                    style={
                      capCutExportProgress > 0
                        ? { width: `${Math.max(5, capCutExportProgress)}%` }
                        : undefined
                    }
                  />
                </div>
              ) : null}
              {capCutMateStatus && !capCutMateStatus.ready ? (
                <div className="mb-3 rounded border border-[#5c3a20] bg-[#2a1f14] px-2 py-2 text-[10px] leading-relaxed text-[#fbbf24]">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <p className="font-medium">剪映小助手未就绪</p>
                    {onRefreshCapCutMate ? (
                      <button
                        type="button"
                        onClick={onRefreshCapCutMate}
                        className="shrink-0 rounded bg-[#3a2a14] px-2 py-0.5 text-[9px] text-[#face15] hover:bg-[#4a3518]"
                      >
                        重新检测
                      </button>
                    ) : null}
                  </div>
                  <ul className="list-inside list-disc space-y-0.5 text-[#d4a574]">
                    {capCutSetupSteps(capCutMateStatus).map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ul>
                </div>
              ) : capCutMateStatus?.ready ? (
                <p className="mb-3 text-[10px] text-[#4ade80]">剪映小助手已连接</p>
              ) : null}
            </>
          ) : null}
          {capCutStatus ? (
            <p
              className={`mb-3 text-[10px] leading-relaxed ${
                capCutDraftUrl
                  ? 'rounded border border-[#2d4a2d] bg-[#142014] px-2 py-2 text-[#4ade80]'
                  : capCutExporting
                    ? 'text-[#face15]'
                    : 'rounded border border-[#4a2020] bg-[#2a1414] px-2 py-2 text-[#f87171]'
              }`}
            >
              {capCutStatus}
            </p>
          ) : null}
          {capCutDraftUrl ? (
            <div className="mb-3 space-y-2">
              <button
                type="button"
                onClick={onOpenCapCutDraft}
                className="w-full rounded bg-[#face15] py-2 text-xs font-semibold text-black hover:bg-[#ffe066]"
              >
                在剪映中打开草稿
              </button>
              <button
                type="button"
                onClick={onOpenCapCutDraft}
                className="w-full rounded border border-[#444] bg-[#2a2a2c] py-2 text-[10px] text-[#ccc] hover:bg-[#333]"
              >
                重新安装到剪映
              </button>
              <p className="text-[10px] leading-relaxed text-[#6e6e72]">
                点击后将草稿安装到剪映目录；请打开剪映 PC 版在草稿列表中查看，不要手动新建空白项目。
              </p>
              {capCutReplaceableMode ? (
                <div className="rounded border border-[#5c4a20] bg-[#2a2414] px-2 py-2 text-[10px] leading-relaxed text-[#d4a574]">
                  <p className="mb-1 font-medium text-[#face15]">剪映内替换素材</p>
                  <ol className="list-inside list-decimal space-y-0.5">
                    {REPLACEABLE_TEMPLATE_STEPS.map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ol>
                </div>
              ) : null}
            </div>
          ) : null}
          {exporting && exportProgress > 0 ? (
            <div className="mb-3 h-1 overflow-hidden rounded bg-[#1a3a1a]">
              <div
                className="h-full bg-[#4ade80] transition-all"
                style={{ width: `${exportProgress}%` }}
              />
            </div>
          ) : null}
          {ENABLE_PUBLISH_PANEL ? <PublishPanel exportUrl={exportUrl} /> : null}
        </div>
      </div>
      <button
        type="button"
        className="absolute inset-0 z-10 bg-black/40"
        aria-label="关闭菜单"
        onClick={onClose}
      />
    </>
  );
}
