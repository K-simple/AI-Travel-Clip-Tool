# Build AI Travel Cut portable package (Windows)
# Usage: powershell -ExecutionPolicy Bypass -File scripts/build-portable.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root "dist\AITravelCut-Portable"
$app = Join-Path $dist "app"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "=== $msg ===" -ForegroundColor Cyan
}

Write-Step "Clean output"
if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
New-Item -ItemType Directory -Path $app -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $dist "data") -Force | Out-Null

Write-Step "Build frontend (Next.js standalone)"
Push-Location (Join-Path $root "frontend")
$env:NEXT_PUBLIC_API_BASE = "http://127.0.0.1:8000"
npm run build
if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
Pop-Location

$standaloneSrc = Join-Path $root "frontend\.next\standalone"
$staticSrc = Join-Path $root "frontend\.next\static"
$publicSrc = Join-Path $root "frontend\public"
$frontendDst = Join-Path $app "frontend"

if (-not (Test-Path (Join-Path $standaloneSrc "server.js"))) {
    throw "Missing frontend/.next/standalone/server.js - check next.config output standalone"
}

Write-Step "Copy frontend standalone"
Copy-Item $standaloneSrc $frontendDst -Recurse
New-Item -ItemType Directory -Path (Join-Path $frontendDst ".next") -Force | Out-Null
Copy-Item $staticSrc (Join-Path $frontendDst ".next\static") -Recurse -Force
if (Test-Path $publicSrc) {
    Copy-Item $publicSrc (Join-Path $frontendDst "public") -Recurse -Force
}

Write-Step "Copy backend"
$backendDst = Join-Path $app "backend"
$backendSrc = Join-Path $root "backend"
robocopy $backendSrc $backendDst /E /XD venv __pycache__ .pytest_cache storage temp /XF *.pyc ai_travel_cut.db /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy backend failed: $LASTEXITCODE" }

Write-Step "Copy Python venv"
$venvSrc = Join-Path $backendSrc "venv"
$venvDst = Join-Path $backendDst "venv"
if (-not (Test-Path $venvSrc)) {
    throw "Missing backend\venv - create venv and pip install -r requirements.txt first"
}
robocopy $venvSrc $venvDst /E /XD __pycache__ /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy venv failed: $LASTEXITCODE" }

Write-Step "Copy portable Node"
$nodeDst = Join-Path $app "node"
New-Item -ItemType Directory -Path $nodeDst -Force | Out-Null
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCmd) {
    Copy-Item $nodeCmd.Source (Join-Path $nodeDst "node.exe") -Force
    Write-Host "Copied node: $($nodeCmd.Source)" -ForegroundColor Green
} else {
    Write-Host "WARN: node not found - put node.exe in app\node\" -ForegroundColor Yellow
}

Write-Step "Copy ffmpeg"
$ffmpegDst = Join-Path $app "ffmpeg"
New-Item -ItemType Directory -Path $ffmpegDst -Force | Out-Null
$ffmpegCandidates = @(
    "C:\ffmpeg\bin\ffmpeg.exe",
    "C:\Program Files\ffmpeg\bin\ffmpeg.exe"
)
$ffmpegCopied = $false
foreach ($candidate in $ffmpegCandidates) {
    if (Test-Path $candidate) {
        $binDir = Split-Path $candidate -Parent
        Copy-Item (Join-Path $binDir "ffmpeg.exe") $ffmpegDst -Force -ErrorAction SilentlyContinue
        Copy-Item (Join-Path $binDir "ffprobe.exe") $ffmpegDst -Force -ErrorAction SilentlyContinue
        Write-Host "Copied ffmpeg from $binDir" -ForegroundColor Green
        $ffmpegCopied = $true
        break
    }
}
$ffmpegInPath = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpegCopied -and $ffmpegInPath) {
    $binDir = Split-Path $ffmpegInPath.Source -Parent
    Copy-Item (Join-Path $binDir "ffmpeg.exe") $ffmpegDst -Force -ErrorAction SilentlyContinue
    Copy-Item (Join-Path $binDir "ffprobe.exe") $ffmpegDst -Force -ErrorAction SilentlyContinue
    Write-Host "Copied ffmpeg from PATH: $binDir" -ForegroundColor Green
    $ffmpegCopied = $true
}
if (-not $ffmpegCopied) {
    Write-Host "WARN: ffmpeg not found - copy ffmpeg.exe to app\ffmpeg\" -ForegroundColor Yellow
}

Write-Step "Write backend/.env"
$envFile = Join-Path $backendDst ".env"
if (-not (Test-Path $envFile)) {
    $envLines = @(
        "PROCESSING_PRESET=budget",
        "CORS_ORIGINS=http://127.0.0.1:3000,http://localhost:3000"
    )
    Set-Content -Path $envFile -Value $envLines -Encoding UTF8
}

Write-Step "Build launcher exe (PyInstaller)"
$py = Join-Path $backendSrc "venv\Scripts\python.exe"
& $py -m pip install pyinstaller -q
& $py -m PyInstaller (Join-Path $root "scripts\AITravelCut.spec") --distpath $dist --workpath (Join-Path $root "dist\build") --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Step "Write start.bat fallback"
$batPath = Join-Path $dist "start.bat"
$batLines = @(
    "@echo off",
    "cd /d `"%~dp0`"",
    "AITravelCut.exe",
    "pause"
)
Set-Content -Path $batPath -Value $batLines -Encoding Default

Write-Step "Done"
Write-Host ""
Write-Host "Output: $dist" -ForegroundColor Green
Write-Host "Run: $dist\AITravelCut.exe" -ForegroundColor Green
Write-Host "Zip the whole AITravelCut-Portable folder to share." -ForegroundColor Yellow
