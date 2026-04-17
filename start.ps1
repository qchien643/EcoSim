# ============================================================
# EcoSim - Start All Services
# Usage: .\start.ps1 [-SkipDocker] [-Only <service>]
#
# Each service runs in a named window for easy identification.
# Use .\stop.ps1 to stop all services.
# ============================================================
param(
    [switch]$SkipDocker,
    [ValidateSet("falkordb","core","sim","gateway","frontend","")]
    [string]$Only = ""
)

$ErrorActionPreference = "Continue"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "  EcoSim - Service Launcher" -ForegroundColor Cyan
Write-Host "  =========================" -ForegroundColor Cyan
Write-Host ""

function Should-Run($name) {
    return ($Only -eq "" -or $Only -eq $name)
}

# -- 1. FalkorDB (Docker) --
if ((Should-Run "falkordb") -and -not $SkipDocker) {
    Write-Host "[1/5] FalkorDB (Docker, port 6379)" -ForegroundColor Green

    $container = docker ps -q -f "name=ecosim-falkordb" 2>$null
    if ($container) {
        Write-Host "       Already running." -ForegroundColor Yellow
    } else {
        docker-compose -f "$ROOT\docker-compose.yml" up -d falkordb 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "       Started." -ForegroundColor Green
        } else {
            Write-Host "       Failed! Is Docker running?" -ForegroundColor Red
        }
    }
    Write-Host ""
}

# -- 2. Core Service (Flask, port 5001) --
if (Should-Run "core") {
    Write-Host "[2/5] Core Service (Flask, port 5001)" -ForegroundColor Green

    Start-Process cmd.exe -ArgumentList "/c title EcoSim - Core Service (5001) && `"$ROOT\venv\Scripts\python.exe`" `"$ROOT\backend\run.py`"" -WorkingDirectory "$ROOT\backend"
    Write-Host "       Started." -ForegroundColor Green
    Write-Host ""
}

# -- 3. Simulation Service (FastAPI, port 5002) --
if (Should-Run "sim") {
    Write-Host "[3/5] Simulation Service (FastAPI, port 5002)" -ForegroundColor Green

    Start-Process cmd.exe -ArgumentList "/c title EcoSim - Simulation Service (5002) && `"$ROOT\oasis\.venv\Scripts\python.exe`" -m uvicorn sim_service:app --host 0.0.0.0 --port 5002" -WorkingDirectory "$ROOT\oasis"
    Write-Host "       Started." -ForegroundColor Green
    Write-Host ""
}

# -- 4. API Gateway (Flask, port 5000) --
if (Should-Run "gateway") {
    Write-Host "[4/5] API Gateway (Flask, port 5000)" -ForegroundColor Green

    Start-Process cmd.exe -ArgumentList "/c title EcoSim - API Gateway (5000) && `"$ROOT\venv\Scripts\python.exe`" `"$ROOT\gateway\gateway.py`"" -WorkingDirectory "$ROOT\gateway"
    Write-Host "       Started." -ForegroundColor Green
    Write-Host ""
}

# -- 5. Frontend (Vite, port 5173) --
if (Should-Run "frontend") {
    Write-Host "[5/5] Frontend (Vite dev server, port 5173)" -ForegroundColor Green

    Start-Process cmd.exe -ArgumentList "/c title EcoSim - Frontend (5173) && cd /d `"$ROOT\frontend`" && npm run dev" -WorkingDirectory "$ROOT\frontend"
    Write-Host "       Started." -ForegroundColor Green
    Write-Host ""
}

# -- Summary --
Write-Host "  -------------------------------------------" -ForegroundColor DarkGray
Write-Host "  Services:" -ForegroundColor Cyan
Write-Host "    FalkorDB       : http://localhost:6379"
Write-Host "    Core Service   : http://localhost:5001"
Write-Host "    Simulation     : http://localhost:5002"
Write-Host "    API Gateway    : http://localhost:5000"
Write-Host "    Frontend       : http://localhost:5173"
Write-Host ""
Write-Host "  Windows: Look for 'EcoSim - ...' in taskbar" -ForegroundColor DarkGray
Write-Host "  Tip: .\stop.ps1 to stop all" -ForegroundColor DarkGray
Write-Host ""
