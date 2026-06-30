import type { TemplateSlot } from '@/lib/timeline';
import { isSlotFilled } from '@/lib/exportPrecheck';

/** 与产品业务一致：模板 → 识别字幕/音频 → 手动配对换画面 → 改字幕配特效 → 导出 */
export type OnboardingStepId = 'template' | 'subtitle' | 'match' | 'polish' | 'export';

export type OnboardingStep = {
  id: OnboardingStepId;
  title: string;
  description: string;
  done: boolean;
  active: boolean;
  locked: boolean;
};

export type OnboardingState = {
  steps: OnboardingStep[];
  currentStep: OnboardingStepId;
  progressPercent: number;
  allDone: boolean;
};

export function computeOnboardingState(input: {
  hasTemplate: boolean;
  templateReady: boolean;
  assetCount: number;
  slots: TemplateSlot[];
  matchedCount: number;
  subtitleRecognizedCount?: number;
  polishTouched?: boolean;
}): OnboardingState {
  const {
    hasTemplate,
    templateReady,
    assetCount,
    slots,
    matchedCount,
    subtitleRecognizedCount = slots.filter((s) => s.subtitleText.trim()).length,
    polishTouched = slots.some((s) => (s.applied_effect_presets?.length ?? 0) > 0),
  } = input;

  const totalSlots = slots.length;
  const hasAssets = assetCount > 0;
  const subtitleDone =
    totalSlots > 0 &&
    (subtitleRecognizedCount >= Math.max(1, Math.ceil(totalSlots * 0.5)) ||
      subtitleRecognizedCount >= totalSlots);
  const matchDone =
    totalSlots > 0 &&
    (matchedCount >= totalSlots || matchedCount >= Math.ceil(totalSlots * 0.8));
  const exportReady = templateReady && totalSlots > 0 && matchedCount > 0;

  const stepDone: Record<OnboardingStepId, boolean> = {
    template: hasTemplate && templateReady && totalSlots > 0,
    subtitle: subtitleDone,
    match: matchDone,
    polish: polishTouched || (matchDone && subtitleDone),
    export: exportReady && matchDone,
  };

  let current: OnboardingStepId = 'template';
  if (stepDone.template && !stepDone.subtitle) current = 'subtitle';
  else if (stepDone.template && stepDone.subtitle && !stepDone.match) current = 'match';
  else if (stepDone.template && stepDone.subtitle && stepDone.match && !stepDone.polish) current = 'polish';
  else if (stepDone.template && stepDone.match) current = 'export';

  const steps: OnboardingStep[] = [
    {
      id: 'template',
      title: '1. 导入模板',
      description: '先导入参考短视频，系统切分镜头槽位',
      done: stepDone.template,
      active: current === 'template',
      locked: false,
    },
    {
      id: 'subtitle',
      title: '2. 识别字幕与音频',
      description: '批量识别模板字幕与人声，作为后续修改底稿',
      done: stepDone.subtitle,
      active: current === 'subtitle',
      locked: !stepDone.template,
    },
    {
      id: 'match',
      title: '3. 配对换画面',
      description: 'AI 理解模板每镜画面，从素材库挑选语义相近片段填入',
      done: stepDone.match,
      active: current === 'match',
      locked: !stepDone.template || !stepDone.subtitle || !hasAssets,
    },
    {
      id: 'polish',
      title: '4. 改字幕配特效',
      description: '自行修改字幕文案，在特效库为槽位应用花字/动效',
      done: stepDone.polish,
      active: current === 'polish',
      locked: !stepDone.template || matchedCount === 0,
    },
    {
      id: 'export',
      title: '5. 预览导出',
      description: '预览成片，导出 MP4 或剪映草稿',
      done: stepDone.export,
      active: current === 'export',
      locked: !stepDone.template || matchedCount === 0,
    },
  ];

  const doneCount = steps.filter((s) => s.done).length;
  const filledCount = slots.filter(isSlotFilled).length;

  return {
    steps,
    currentStep: current,
    progressPercent: totalSlots
      ? Math.round((filledCount / totalSlots) * 100)
      : Math.round((doneCount / steps.length) * 100),
    allDone: stepDone.export,
  };
}
