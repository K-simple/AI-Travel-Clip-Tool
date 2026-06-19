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
    <header className="relative z-50 flex min-h-[52px] shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-editor-border bg-editor-panel/95 px-3 py-2 backdrop-blur-md sm:px-5">
      <div className="flex min-w-0 flex-1 items-center gap-2.5 sm:gap-3">
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
        <div className="hidden h-5 w-px bg-editor-border sm:block" />
        <div className="min-w-0">
          <h1
            className="truncate text-sm font-semibold tracking-tight text-editor-text sm:max-w-[240px]"
            title={projectTitle}
          >
            {projectTitle}
          </h1>
          {projectId ? (
            <p className="hidden truncate text-[10px] text-editor-subtle md:block">
              {autosaveLabel || `项目 ${projectId.slice(0, 8)}…`}
            </p>
          ) : null}
        </div>
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

      <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
        <button
          type="button"
          onClick={triggerTemplatePick}
          className="ui-btn hidden md:inline-flex"
        >
          导入模板
        </button>
        <button
          type="button"
          disabled={saving || !projectId}
          onClick={onSaveProject}
          className="ui-btn hidden sm:inline-flex"
          title={!projectId ? '请先导入模板' : undefined}
        >
          {saving ? '保存中…' : '保存'}
        </button>
        <button
          type="button"
          disabled={loadingProject}
          onClick={onLoadProject}
          className="ui-btn hidden sm:inline-flex"
        >
          载入
        </button>
        <button
          type="button"
          disabled={exporting || !canExport}
          onClick={onExport}
          title={exportHint}
          className="ui-btn-primary min-w-[72px]"
        >
          {exporting ? '导出中…' : '导出成片'}
        </button>
      </div>
    </header>
  );
}
