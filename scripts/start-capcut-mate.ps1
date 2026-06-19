# 启动项目内置 CapCut Mate（剪映小助手），默认 http://localhost:30000
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$mateDir = Join-Path $root "capcut-mate"
$python = Join-Path $mateDir "venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
  Write-Host "CapCut Mate 未安装。请先运行:" -ForegroundColor Yellow
  Write-Host "  cd capcut-mate"
  Write-Host "  python -m venv venv"
  Write-Host "  .\venv\Scripts\pip install -e `".[windows]`""
  exit 1
}

Set-Location $mateDir

$jianyingDraft = Join-Path $env:LOCALAPPDATA "JianyingPro\User Data\Projects\com.lveditor.draft"
$env:DRAFT_URL = "http://127.0.0.1:30000/openapi/capcut-mate/v1/get_draft"
$env:DOWNLOAD_URL = "http://127.0.0.1:30000/"
if (Test-Path $jianyingDraft) {
  $env:DRAFT_SAVE_PATH = $jianyingDraft
  Write-Host "Jianying draft path: $jianyingDraft" -ForegroundColor DarkGray
} else {
  Write-Host "Jianying draft folder not found; set DRAFT_SAVE_PATH in capcut-mate if needed." -ForegroundColor Yellow
}

Write-Host "Starting CapCut Mate on http://localhost:30000 ..." -ForegroundColor Cyan
& $python main.py
