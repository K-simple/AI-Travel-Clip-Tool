'use client';

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

type EditorMenuProps = {
  projectTitle: string;
  hasProject: boolean;
  canExport: boolean;
  onSave: () => void;
  onLoad: () => void;
  onExport: () => void;
  onExportCapCut?: () => void;
  onImportTemplate: () => void;
  onRename?: () => void;
  saving?: boolean;
  exporting?: boolean;
  capCutExporting?: boolean;
};

export default function EditorMenu({
  projectTitle,
  hasProject,
  canExport,
  onSave,
  onLoad,
  onExport,
  onExportCapCut,
  onImportTemplate,
  onRename,
  saving,
  exporting,
  capCutExporting,
}: EditorMenuProps) {
  const [open, setOpen] = useState(false);
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 });
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const updateMenuPos = () => {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (!rect) return;
    setMenuPos({ top: rect.bottom + 6, left: rect.left });
  };

  useEffect(() => {
    if (!open) return;
    updateMenuPos();
    const close = (e: MouseEvent) => {
      const target = e.target as Node;
      if (ref.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onLayout = () => updateMenuPos();
    document.addEventListener('mousedown', close);
    window.addEventListener('resize', onLayout);
    window.addEventListener('scroll', onLayout, true);
    return () => {
      document.removeEventListener('mousedown', close);
      window.removeEventListener('resize', onLayout);
      window.removeEventListener('scroll', onLayout, true);
    };
  }, [open]);

  const item = (label: string, action: () => void, disabled?: boolean) => (
    <button
      type="button"
      disabled={disabled}
      onClick={() => {
        action();
        setOpen(false);
      }}
      className="block w-full px-3 py-2 text-left text-xs text-editor-muted transition-colors hover:bg-editor-elevated hover:text-editor-text disabled:cursor-not-allowed disabled:text-editor-subtle"
    >
      {label}
    </button>
  );

  return (
    <div ref={ref} className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => {
          setOpen((v) => {
            const next = !v;
            if (next) {
              requestAnimationFrame(() => updateMenuPos());
            }
            return next;
          });
        }}
        className="ui-btn-ghost px-2.5 py-1.5 text-sm"
      >
        菜单
      </button>
      {open && typeof document !== 'undefined'
        ? createPortal(
            <div
              ref={menuRef}
              className="fixed z-[200] min-w-[180px] overflow-hidden rounded-xl border border-editor-border bg-editor-panel py-1 shadow-panel"
              style={{ top: menuPos.top, left: menuPos.left }}
            >
              <div className="border-b border-editor-border px-3 py-2 text-[10px] text-editor-subtle">
                {projectTitle}
              </div>
              {item('导入模板视频…', onImportTemplate)}
              {item('载入项目…', onLoad)}
              {onRename ? item('重命名项目…', onRename, !hasProject) : null}
              {item(saving ? '保存中…' : '保存项目', onSave, !hasProject || saving)}
              {item(exporting ? '导出中…' : '导出成片', onExport, !canExport || exporting)}
              {onExportCapCut
                ? item(
                    capCutExporting ? '生成剪映草稿…' : '导出剪映草稿',
                    onExportCapCut,
                    !canExport || exporting || capCutExporting
                  )
                : null}
              <div className="border-t border-editor-border px-3 py-2 text-[10px] leading-relaxed text-editor-subtle">
                快捷键：Space 播放 · S 分割 · W 删除槽位 · Q 波纹清除
              </div>
            </div>,
            document.body
          )
        : null}
    </div>
  );
}
