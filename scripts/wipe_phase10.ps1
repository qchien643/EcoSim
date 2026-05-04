# ============================================================
# EcoSim - Phase 10 Wipe Script
# Xóa toàn bộ data campaigns + simulations + meta.db + FalkorDB graphs
# Để bootstrap fresh với schema v3 (FalkorDB single source of truth)
# Usage: .\scripts\wipe_phase10.ps1 [-Force]
# ============================================================
param(
    [switch]$Force
)

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "  EcoSim Phase 10 — WIPE (DESTRUCTIVE)" -ForegroundColor Red
Write-Host "  ====================================" -ForegroundColor Red
Write-Host ""

# Pre-flight: count what's about to be deleted
$campaignCount = 0
if (Test-Path "data\campaigns") {
    $campaignCount = (Get-ChildItem "data\campaigns" -Directory -ErrorAction SilentlyContinue).Count
}
$simCount = 0
if (Test-Path "data\simulations") {
    $simCount = (Get-ChildItem "data\simulations" -Directory -ErrorAction SilentlyContinue).Count
}
$metaExists = Test-Path "data\meta.db"

$falkorRunning = $false
$graphCount = 0
$container = docker ps -q -f "name=ecosim-falkordb" 2>$null
if ($container) {
    $falkorRunning = $true
    $graphList = docker exec ecosim-falkordb redis-cli GRAPH.LIST 2>$null
    if ($graphList) {
        $graphCount = ($graphList -split "`n" | Where-Object { $_.Trim() -ne "" }).Count
    }
}

Write-Host "  Sẽ xóa:" -ForegroundColor Yellow
Write-Host "    • data/campaigns/         : $campaignCount campaign folder(s)"
Write-Host "    • data/simulations/        : $simCount sim folder(s)"
Write-Host "    • data/uploads/            : legacy folder"
Write-Host "    • data/meta.db             : $(if ($metaExists) { 'EXISTS' } else { 'not found' })"
Write-Host "    • FalkorDB GRAPH.LIST      : $graphCount graph(s) (FLUSHALL)"
Write-Host ""
Write-Host "  GIỮ:" -ForegroundColor Green
Write-Host "    • data/reference/          (parquet pool, name lists)"
Write-Host "    • data/samples/            (test fixtures)"
Write-Host "    • data/backups/            (backup history)"
Write-Host ""

if (-not $Force) {
    $confirm = Read-Host "  Tiếp tục? Gõ 'WIPE' để confirm"
    if ($confirm -ne "WIPE") {
        Write-Host "  Hủy. Không xóa gì." -ForegroundColor Cyan
        exit 0
    }
}

# 1. Stop services (giữ Docker để FLUSHALL)
Write-Host ""
Write-Host "  [1/3] Stop services..." -ForegroundColor Cyan
& "$PSScriptRoot\stop.ps1" -KeepDocker

# 2. FalkorDB FLUSHALL
if ($falkorRunning) {
    Write-Host ""
    Write-Host "  [2/3] FalkorDB FLUSHALL..." -ForegroundColor Cyan
    docker exec ecosim-falkordb redis-cli FLUSHALL | Out-Null
    Write-Host "    Done."
} else {
    Write-Host ""
    Write-Host "  [2/3] FalkorDB không chạy, skip FLUSHALL" -ForegroundColor DarkGray
}

# 3. Remove filesystem data
Write-Host ""
Write-Host "  [3/3] Remove data files..." -ForegroundColor Cyan

$campaignsDir = "data\campaigns"
if (Test-Path $campaignsDir) {
    Get-ChildItem $campaignsDir -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item -Recurse -Force $_.FullName -ErrorAction SilentlyContinue
    }
    Write-Host "    data/campaigns/* removed"
}

$simsDir = "data\simulations"
if (Test-Path $simsDir) {
    Get-ChildItem $simsDir -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item -Recurse -Force $_.FullName -ErrorAction SilentlyContinue
    }
    Write-Host "    data/simulations/* removed"
}

$uploadsDir = "data\uploads"
if (Test-Path $uploadsDir) {
    Get-ChildItem $uploadsDir -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item -Recurse -Force $_.FullName -ErrorAction SilentlyContinue
    }
    Write-Host "    data/uploads/* removed"
}

foreach ($f in @("data\meta.db", "data\meta.db-wal", "data\meta.db-shm")) {
    if (Test-Path $f) {
        Remove-Item -Force $f -ErrorAction SilentlyContinue
        Write-Host "    $f removed"
    }
}

Write-Host ""
Write-Host "  Wipe complete. Schema v3 sẽ tạo từ đầu khi service start." -ForegroundColor Green
Write-Host "  Run: .\scripts\start.ps1" -ForegroundColor Cyan
Write-Host ""
