'use client';

import { useEffect, useState } from 'react';
import type { OnboardingStep, OnboardingStepId } from '@/lib/onboardingSteps';

const DISMISS_KEY = 'ai-travel-cut-onboarding-dismissed';

type OnboardingGuideProps = {
  steps: OnboardingStep[];
  currentStep: OnboardingStepId;
  progressPercent: number;
  allDone: boolean;
  onStepAction?: (stepId: OnboardingStepId) => void;
};

export default function OnboardingGuide({
  steps,
  currentStep,
  progressPercent,
  allDone,
  onStepAction,
}: OnboardingGuideProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    try {
      setDismissed(localStorage.getItem(DISMISS_KEY) === '1');
    } catch {
      setDismissed(false);
    }
  }, []);

  const handleDismiss = () => {
    setDismissed(true);
    try {
      localStorage.setItem(DISMISS_KEY, '1');
    } catch {
      /* ignore */
    }
  };

  if (dismissed && allDone) return null;

  return (
    <div className="shrink-0 border-b border-[#2e2e2e] bg-[#181818] px-4 py-2">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-white">新手引导</span>
          {!allDone ? (
            <span className="text-[10px] text-[#888]">
              当前：{steps.find((s) => s.id === currentStep)?.title.replace(/^\d+\.\s*/, '')}
            </span>
          ) : (
            <span className="text-[10px] text-[#4ade80]">全部完成，可以导出了</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-[#666]">匹配进度 {progressPercent}%</span>
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            className="text-[10px] text-[#888] hover:text-white"
          >
            {collapsed ? '展开' : '收起'}
          </button>
          {allDone ? (
            <button
              type="button"
              onClick={handleDismiss}
              className="text-[10px] text-[#888] hover:text-white"
            >
              不再显示
            </button>
          ) : null}
        </div>
      </div>

      {!collapsed ? (
        <div className="flex flex-wrap gap-2">
          {steps.map((step, index) => {
            const stepNum = index + 1;
            const stateClass = step.done
              ? 'border-[#2d4a2d] bg-[#1a2e1a] text-[#4ade80]'
              : step.active
                ? 'border-[#face15]/50 bg-[#2a2818] text-white'
                : step.locked
                  ? 'border-[#2a2a2a] bg-[#1a1a1a] text-[#555] cursor-not-allowed'
                  : 'border-[#333] bg-[#222] text-[#aaa] hover:border-[#444]';

            return (
              <button
                key={step.id}
                type="button"
                disabled={step.locked && !step.done}
                onClick={() => onStepAction?.(step.id)}
                className={`flex min-w-[140px] flex-1 flex-col rounded-md border px-3 py-2 text-left transition-colors ${stateClass}`}
                title={step.description}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
                      step.done
                        ? 'bg-[#4ade80] text-black'
                        : step.active
                          ? 'bg-[#face15] text-black'
                          : 'bg-[#333] text-[#888]'
                    }`}
                  >
                    {step.done ? '✓' : stepNum}
                  </span>
                  <span className="text-xs font-medium">{step.title.replace(/^\d+\.\s*/, '')}</span>
                </div>
                <p className="mt-1 pl-7 text-[10px] leading-snug opacity-80">{step.description}</p>
              </button>
            );
          })}
        </div>
      ) : null}

      {!allDone && !collapsed ? (
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-[#2a2a2a]">
          <div
            className="h-full bg-[#face15] transition-all duration-500"
            style={{ width: `${Math.max(4, progressPercent)}%` }}
          />
        </div>
      ) : null}
    </div>
  );
}
