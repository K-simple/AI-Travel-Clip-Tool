# 启动/重启 AI Travel Cut 前后端（backend:8000 + frontend:3000）
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Stop-PortListener {
    param([int]$Port)
    for ($attempt = 0; $attempt -lt 3; $attempt++) {
        $pids = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
        if (-not $pids) { return }
        foreach ($procId in $pids) {
            if ($procId -gt 0) {
                Write-Host "Stopping port $Port PID $procId" -ForegroundColor DarkYellow
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            }
        }
        Start-Sleep -Seconds 1
    }
}

Write-Host "Stopping old backend/frontend/CapCut Mate listeners..." -ForegroundColor Cyan
Stop-PortListener -Port 8000
Stop-PortListener -Port 3000
Stop-PortListener -Port 30000
Start-Sleep -Seconds 2

$backendPy = Join-Path $root "backend\venv\Scripts\python.exe"
if (-not (Test-Path $backendPy)) {
    Write-Host "Backend venv not found: $backendPy" -ForegroundColor Red
    exit 1
}

Write-Host "Starting backend http://127.0.0.1:8000 ..." -ForegroundColor Green
Start-Process -FilePath $backendPy `
    -ArgumentList "-m", "uvicorn", "main:app", "--reload", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory (Join-Path $root "backend") `
    -WindowStyle Normal

Write-Host "Starting frontend http://localhost:3000 ..." -ForegroundColor Green
Start-Process -FilePath "npm" `
    -ArgumentList "run", "dev" `
    -WorkingDirectory (Join-Path $root "frontend") `
    -WindowStyle Normal

Write-Host "Done. Frontend http://localhost:3000 | Backend http://127.0.0.1:8000" -ForegroundColor Cyan

$matePy = Join-Path $root "capcut-mate\venv\Scripts\python.exe"
if (Test-Path $matePy) {
    $jianyingDraft = Join-Path $env:LOCALAPPDATA "JianyingPro\User Data\Projects\com.lveditor.draft"
    $env:DRAFT_URL = "http://127.0.0.1:30000/openapi/capcut-mate/v1/get_draft"
    $env:DOWNLOAD_URL = "http://127.0.0.1:30000/"
    if (Test-Path $jianyingDraft) { $env:DRAFT_SAVE_PATH = $jianyingDraft }
    Write-Host "Starting CapCut Mate http://127.0.0.1:30000 ..." -ForegroundColor Green
    Start-Process -FilePath $matePy `
        -ArgumentList "main.py" `
        -WorkingDirectory (Join-Path $root "capcut-mate") `
        -WindowStyle Normal
} else {
    Write-Host "CapCut Mate not installed. Run: .\scripts\start-capcut-mate.ps1" -ForegroundColor Yellow
}
