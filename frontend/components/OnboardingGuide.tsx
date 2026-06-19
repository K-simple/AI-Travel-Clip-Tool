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
  exportBusy?: { label: string; progress: number } | null;
};

export default function OnboardingGuide({
  steps,
  currentStep,
  progressPercent,
  allDone,
  onStepAction,
  exportBusy = null,
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

  const barProgress = exportBusy ? exportBusy.progress : progressPercent;
  const progressLabel = exportBusy ? exportBusy.label : `完成度 ${progressPercent}%`;

  return (
    <div className="shrink-0 border-b border-editor-border bg-editor-panel/70 px-3 py-2.5 backdrop-blur-sm sm:px-5">
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <span className="text-xs font-semibold text-editor-text">快速上手</span>
          {!allDone ? (
            <span className="rounded-full bg-editor-elevated px-2 py-0.5 text-[10px] text-editor-muted">
              {steps.find((s) => s.id === currentStep)?.title.replace(/^\d+\.\s*/, '')}
            </span>
          ) : (
            <span className="text-[10px] font-medium text-editor-success">全部完成，可以导出了</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-editor-subtle">{progressLabel}</span>
          <button type="button" onClick={() => setCollapsed((v) => !v)} className="ui-btn-ghost">
            {collapsed ? '展开' : '收起'}
          </button>
          {allDone ? (
            <button type="button" onClick={handleDismiss} className="ui-btn-ghost">
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
              ? 'border-emerald-500/25 bg-emerald-500/10 text-editor-success'
              : step.active
                ? 'border-editor-accent/40 bg-editor-accent-muted text-editor-text shadow-glow'
                : step.locked
                  ? 'cursor-not-allowed border-editor-border bg-editor-panel-2 text-editor-subtle opacity-60'
                  : 'border-editor-border bg-editor-panel-2 text-editor-muted hover:border-editor-border hover:bg-editor-elevated';

            return (
              <button
                key={step.id}
                type="button"
                disabled={step.locked && !step.done}
                onClick={() => onStepAction?.(step.id)}
                className={`flex min-w-[148px] flex-1 flex-col rounded-xl border px-3 py-2.5 text-left transition-all duration-150 ${stateClass}`}
                title={step.description}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
                      step.done
                        ? 'bg-editor-success text-[#0f1012]'
                        : step.active
                          ? 'bg-editor-accent text-[#141414]'
                          : 'bg-editor-elevated text-editor-muted'
                    }`}
                  >
                    {step.done ? '✓' : stepNum}
                  </span>
                  <span className="text-xs font-medium">{step.title.replace(/^\d+\.\s*/, '')}</span>
                </div>
                <p className="mt-1.5 pl-7 text-[10px] leading-snug opacity-85">{step.description}</p>
              </button>
            );
          })}
        </div>
      ) : null}

      {!allDone && !collapsed ? (
        <div className="ui-progress-track mt-2.5">
          {exportBusy && exportBusy.progress <= 0 ? (
            <div className="status-indeterminate-bar ui-progress-fill w-2/5" />
          ) : (
            <div className="ui-progress-fill" style={{ width: `${Math.max(4, barProgress)}%` }} />
          )}
        </div>
      ) : null}
    </div>
  );
}
