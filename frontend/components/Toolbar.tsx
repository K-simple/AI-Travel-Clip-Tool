'use client';

import { useRef } from 'react';
import EditorMenu from '@/components/EditorMenu';

type ToolbarProps = {
  projectTitle: string;
  projectId: string | null;
  onSaveProject: () => void;
  onLoadProject: () => void;
  onExport: () => void;
  onExportCapCut?: () => void;
  onTemplateUpload: (file: File) => void;
  onRenameProject?: () => void;
  saving: boolean;
  loadingProject: boolean;
  exporting: boolean;
  capCutExporting?: boolean;
  canExport: boolean;
  exportHint?: string;
  autosaveLabel?: string;
};

export default function Toolbar({
  projectTitle,
  projectId,
  onSaveProject,
  onLoadProject,
  onExport,
  onExportCapCut,
  onTemplateUpload,
  onRenameProject,
  saving,
  loadingProject,
  exporting,
  capCutExporting = false,
  canExport,
  exportHint,
  autosaveLabel,
}: ToolbarProps) {
  const templateInputRef = useRef<HTMLInputElement>(null);

  const triggerTemplatePick = () => templateInputRef.current?.click();

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-[#2e2e2e] bg-[#1a1a1a] px-4">
      <div className="flex items-center gap-3">
        <EditorMenu
          projectTitle={projectTitle}
          hasProject={!!projectId}
          canExport={canExport}
          onSave={onSaveProject}
          onLoad={onLoadProject}
          onExport={onExport}
          onExportCapCut={onExportCapCut}
          onImportTemplate={triggerTemplatePick}
          onRename={onRenameProject}
          saving={saving}
          exporting={exporting}
          capCutExporting={capCutExporting}
        />
        <div className="h-4 w-px bg-[#3a3a3a]" />
        <h1 className="max-w-[220px] truncate text-sm font-medium text-white" title={projectTitle}>
          {projectTitle}
        </h1>
        {projectId ? (
          <span className="hidden text-xs text-[#666] md:inline">ID: {projectId.slice(0, 8)}…</span>
        ) : null}
        {autosaveLabel ? (
          <span className="hidden text-[10px] text-[#555] lg:inline">{autosaveLabel}</span>
        ) : null}
      </div>

      <input
        ref={templateInputRef}
        type="file"
        accept="video/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onTemplateUpload(file);
          e.target.value = '';
        }}
      />

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={triggerTemplatePick}
          className="rounded-md bg-[#2a2a2a] px-3 py-1.5 text-xs text-[#ccc] hover:bg-[#333]"
        >
          导入模板
        </button>
        <button
          type="button"
          disabled={saving || !projectId}
          onClick={onSaveProject}
          className="rounded-md bg-[#2a2a2a] px-3 py-1.5 text-xs text-[#ccc] hover:bg-[#333] disabled:cursor-not-allowed disabled:opacity-50"
          title={!projectId ? '请先导入模板' : undefined}
        >
          {saving ? '保存中…' : '保存'}
        </button>
        <button
          type="button"
          disabled={loadingProject}
          onClick={onLoadProject}
          className="rounded-md bg-[#2a2a2a] px-3 py-1.5 text-xs text-[#ccc] hover:bg-[#333]"
        >
          载入
        </button>
        <button
          type="button"
          disabled={exporting || !canExport}
          onClick={onExport}
          title={exportHint}
          className="rounded-md bg-[#face15] px-4 py-1.5 text-xs font-semibold text-black hover:bg-[#ffe066] disabled:cursor-not-allowed disabled:bg-[#665c20] disabled:text-[#999]"
        >
          {exporting ? '导出中…' : '导出'}
        </button>
      </div>
    </header>
  );
}
