import type { TemplateSlot } from '@/lib/timeline';
import { isSlotFilled } from '@/lib/exportPrecheck';

export type OnboardingStepId = 'template' | 'assets' | 'match' | 'export';

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
}): OnboardingState {
  const { hasTemplate, templateReady, assetCount, slots, matchedCount } = input;
  const totalSlots = slots.length;
  const matchDone = totalSlots > 0 && matchedCount >= totalSlots;
  const hasAssets = assetCount > 0;
  const exportReady = templateReady && totalSlots > 0 && matchedCount > 0;

  const stepDone: Record<OnboardingStepId, boolean> = {
    template: hasTemplate && templateReady && totalSlots > 0,
    assets: hasAssets,
    match: matchDone || (matchedCount > 0 && matchedCount >= Math.ceil(totalSlots * 0.8)),
    export: exportReady && matchDone,
  };

  let current: OnboardingStepId = 'template';
  if (stepDone.template) current = 'assets';
  if (stepDone.template && stepDone.assets) current = 'match';
  if (stepDone.template && stepDone.assets && (stepDone.match || matchedCount > 0)) current = 'export';

  const steps: OnboardingStep[] = [
    {
      id: 'template',
      title: '1. 上传模板',
      description: '导入参考短视频，系统自动切分槽位',
      done: stepDone.template,
      active: current === 'template',
      locked: false,
    },
    {
      id: 'assets',
      title: '2. 上传素材',
      description: '上传你的旅行视频，等待 AI 分析完成',
      done: stepDone.assets,
      active: current === 'assets',
      locked: !stepDone.template,
    },
    {
      id: 'match',
      title: '3. AI 匹配',
      description: '一键匹配或手动拖拽素材到槽位',
      done: stepDone.match,
      active: current === 'match',
      locked: !stepDone.template || !hasAssets,
    },
    {
      id: 'export',
      title: '4. 预览导出',
      description: '预览成片并导出 MP4 或剪映草稿',
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
