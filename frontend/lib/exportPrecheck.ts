import type { TemplateSlot } from '@/lib/timeline';

type AssetLike = {
  id: string;
  title: string;
  processingStatus?: 'processing' | 'ready' | 'failed';
};

type TemplateProcessingLike = {
  status: string;
  progress: number;
  enhanceStatus?: string;
};

export type ExportPrecheckResult = {
  canProceed: boolean;
  blockers: string[];
  warnings: string[];
  unmatchedSlots: TemplateSlot[];
  unmatchedCount: number;
};

export function isSlotFilled(slot: TemplateSlot): boolean {
  return !!(slot.matchedAssetId || slot.asset_file_path);
}

export function buildExportPrecheck(
  slots: TemplateSlot[],
  assets: AssetLike[],
  templateProcessing: TemplateProcessingLike,
  options?: { matching?: boolean; exporting?: boolean; capcutReplaceable?: boolean }
): ExportPrecheckResult {
  const blockers: string[] = [];
  const warnings: string[] = [];

  if (!slots.length) {
    blockers.push('时间线还没有槽位，请先导入并完成模板解析');
  }

  if (templateProcessing.status === 'processing') {
    blockers.push(`模板还在切分中（${templateProcessing.progress}%），请稍候再导出`);
  } else if (templateProcessing.status === 'failed') {
    blockers.push('模板处理失败，请重新上传模板视频');
  } else if (templateProcessing.enhanceStatus === 'processing') {
    warnings.push('AI 镜头修正仍在后台进行，导出将使用当前槽位切分结果');
  }

  const processingAssets = assets.filter((a) => a.processingStatus === 'processing');
  if (processingAssets.length) {
    const names = processingAssets
      .slice(0, 3)
      .map((a) => a.title)
      .join('、');
    const suffix = processingAssets.length > 3 ? ` 等 ${processingAssets.length} 个` : '';
    blockers.push(`素材仍在分析中：${names}${suffix}，请等待完成后再导出`);
  }

  const failedAssets = assets.filter((a) => a.processingStatus === 'failed');
  if (failedAssets.length) {
    warnings.push(`${failedAssets.length} 个素材分析失败，相关槽位可能无法正常导出`);
  }

  if (options?.matching) {
    blockers.push('AI 正在匹配素材，请等待完成后再导出');
  }

  if (options?.exporting) {
    blockers.push('已有导出任务进行中，请等待完成');
  }

  const unmatchedSlots = slots.filter((slot) => !isSlotFilled(slot));
  if (unmatchedSlots.length) {
    const preview = unmatchedSlots
      .slice(0, 4)
      .map((s) => s.ai_description || s.name)
      .join('、');
    const ellipsis = unmatchedSlots.length > 4 ? '…' : '';
    if (options?.capcutReplaceable) {
      warnings.push(
        `可替换模板模式将导出 ${slots.length} 个槽位的模板占位片段（未匹配 ${unmatchedSlots.length} 个），请在剪映中逐段替换素材`
      );
    } else {
      warnings.push(
        `${unmatchedSlots.length} 个槽位尚未匹配素材（${preview}${ellipsis}），导出时这些片段将使用模板原画面或留空`
      );
    }
  }

  return {
    canProceed: blockers.length === 0,
    blockers,
    warnings,
    unmatchedSlots,
    unmatchedCount: unmatchedSlots.length,
  };
}

export function formatExportPrecheckDialog(result: ExportPrecheckResult): string {
  const lines: string[] = [];
  if (result.blockers.length) {
    lines.push('无法导出：');
    result.blockers.forEach((b) => lines.push(`• ${b}`));
  }
  if (result.warnings.length) {
    if (lines.length) lines.push('');
    lines.push(result.blockers.length ? '提示：' : '导出前请注意：');
    result.warnings.forEach((w) => lines.push(`• ${w}`));
  }
  return lines.join('\n');
}
