'use client';

import { useEffect, useRef, useState } from 'react';

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
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const item = (label: string, action: () => void, disabled?: boolean) => (
    <button
      type="button"
      disabled={disabled}
      onClick={() => {
        action();
        setOpen(false);
      }}
      className="block w-full px-3 py-2 text-left text-xs text-[#ccc] hover:bg-[#333] disabled:cursor-not-allowed disabled:text-[#555]"
    >
      {label}
    </button>
  );

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="rounded px-2 py-1 text-sm text-[#8b8b8b] hover:bg-[#2a2a2a] hover:text-white"
      >
        菜单
      </button>
      {open ? (
        <div className="absolute left-0 top-full z-50 mt-1 min-w-[168px] overflow-hidden rounded-md border border-[#3a3a3c] bg-[#1e1e1e] py-1 shadow-xl">
          <div className="border-b border-[#2e2e2e] px-3 py-2 text-[10px] text-[#666]">{projectTitle}</div>
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
          <div className="border-t border-[#2e2e2e] px-3 py-2 text-[10px] leading-relaxed text-[#555]">
            快捷键：Space 播放 · S 分割 · W 删除槽位 · Q 波纹清除
          </div>
        </div>
      ) : null}
    </div>
  );
}
