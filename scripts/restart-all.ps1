# 完全重启 backend(8000) + frontend(3000) + CapCut Mate(30000)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot

function Stop-PortListener {
    param([int]$Port)
    for ($attempt = 0; $attempt -lt 5; $attempt++) {
        $pids = @(
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess -Unique
        )
        if (-not $pids -or $pids.Count -eq 0) { return }
        foreach ($procId in $pids) {
            if ($procId -gt 0) {
                Write-Host "Stopping port $Port PID $procId" -ForegroundColor DarkYellow
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                Start-Sleep -Milliseconds 300
            }
        }
        Start-Sleep -Seconds 1
    }
}

Write-Host "=== Stopping all services ===" -ForegroundColor Cyan
Stop-PortListener -Port 8000
Stop-PortListener -Port 3000
Stop-PortListener -Port 30000
Start-Sleep -Seconds 3

$still = @(
    Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
    Get-NetTCPConnection -LocalPort 30000 -State Listen -ErrorAction SilentlyContinue
)
if ($still) {
    Write-Host "Warning: some ports still in use, retrying..." -ForegroundColor Yellow
    Stop-PortListener -Port 8000
    Stop-PortListener -Port 3000
    Stop-PortListener -Port 30000
    Start-Sleep -Seconds 2
}

$backendPy = Join-Path $root "backend\venv\Scripts\python.exe"
$matePy = Join-Path $root "capcut-mate\venv\Scripts\python.exe"

if (-not (Test-Path $backendPy)) {
    Write-Host "Backend venv not found: $backendPy" -ForegroundColor Red
    exit 1
}

Write-Host "=== Starting backend http://127.0.0.1:8000 ===" -ForegroundColor Green
Start-Process -FilePath $backendPy `
    -ArgumentList "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory (Join-Path $root "backend") `
    -WindowStyle Normal

Write-Host "=== Starting frontend http://localhost:3000 ===" -ForegroundColor Green
Start-Process -FilePath "npm" `
    -ArgumentList "run", "dev" `
    -WorkingDirectory (Join-Path $root "frontend") `
    -WindowStyle Normal

if (Test-Path $matePy) {
    $jianyingDraft = Join-Path $env:LOCALAPPDATA "JianyingPro\User Data\Projects\com.lveditor.draft"
    $env:DRAFT_URL = "http://127.0.0.1:30000/openapi/capcut-mate/v1/get_draft"
    $env:DOWNLOAD_URL = "http://127.0.0.1:30000/"
    if (Test-Path $jianyingDraft) { $env:DRAFT_SAVE_PATH = $jianyingDraft }
    Write-Host "=== Starting CapCut Mate http://127.0.0.1:30000 ===" -ForegroundColor Green
    Start-Process -FilePath $matePy `
        -ArgumentList "main.py" `
        -WorkingDirectory (Join-Path $root "capcut-mate") `
        -WindowStyle Normal
} else {
    Write-Host "CapCut Mate venv not found" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done." -ForegroundColor Cyan
Write-Host "  Frontend:    http://localhost:3000"
Write-Host "  Backend:     http://127.0.0.1:8000"
Write-Host "  CapCut Mate: http://127.0.0.1:30000"
Write-Host "  CapCut status: http://127.0.0.1:8000/api/export/capcut-status"
