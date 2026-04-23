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
$ROOT = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

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

    Start-Process cmd.exe -ArgumentList "/c title EcoSim - Core Service (5001) && `"$ROOT\venv\Scripts\python.exe`" `"$ROOT\apps\core\run.py`"" -WorkingDirectory "$ROOT\apps\core"
    Write-Host "       Started." -ForegroundColor Green
    Write-Host ""
}

# -- 3. Simulation Service (FastAPI, port 5002) --
if (Should-Run "sim") {
    Write-Host "[3/5] Simulation Service (FastAPI, port 5002)" -ForegroundColor Green

    Start-Process cmd.exe -ArgumentList "/c title EcoSim - Simulation Service (5002) && `"$ROOT\apps\simulation\.venv\Scripts\python.exe`" -m uvicorn sim_service:app --host 0.0.0.0 --port 5002" -WorkingDirectory "$ROOT\apps\simulation"
    Write-Host "       Started." -ForegroundColor Green
    Write-Host ""
}

# -- 4. API Gateway (Caddy, port 5000) --
if (Should-Run "gateway") {
    Write-Host "[4/5] API Gateway (Caddy, port 5000)" -ForegroundColor Green

    # Local dev: upstream pointer về localhost thay vì container hostname
    $env:CORE_UPSTREAM = "localhost:5001"
    $env:SIM_UPSTREAM  = "localhost:5002"

    $caddyCmd = Get-Command caddy.exe -ErrorAction SilentlyContinue
    if ($caddyCmd) {
        Start-Process cmd.exe -ArgumentList "/c title EcoSim - API Gateway (Caddy, 5000) && set CORE_UPSTREAM=localhost:5001 && set SIM_UPSTREAM=localhost:5002 && caddy run --config `"$ROOT\apps\gateway\Caddyfile`" --adapter caddyfile" -WorkingDirectory "$ROOT\apps\gateway"
        Write-Host "       Started (Caddy)." -ForegroundColor Green
    } else {
        Write-Host "       Caddy not in PATH; falling back to legacy Python gateway (gateway.py.bak)" -ForegroundColor Yellow
        $legacy = "$ROOT\apps\gateway\gateway.py.bak"
        if (Test-Path $legacy) {
            Start-Process cmd.exe -ArgumentList "/c title EcoSim - API Gateway (legacy Python, 5000) && `"$ROOT\venv\Scripts\python.exe`" `"$legacy`"" -WorkingDirectory "$ROOT\apps\gateway"
            Write-Host "       Started (legacy)." -ForegroundColor Green
        } else {
            Write-Host "       Neither caddy.exe nor gateway.py.bak found — gateway not started." -ForegroundColor Red
        }
    }
    Write-Host ""
}

# -- 5. Frontend (Vite, port 5173) --
if (Should-Run "frontend") {
    Write-Host "[5/5] Frontend (Vite dev server, port 5173)" -ForegroundColor Green

    Start-Process cmd.exe -ArgumentList "/c title EcoSim - Frontend (5173) && cd /d `"$ROOT\apps\frontend`" && npm run dev" -WorkingDirectory "$ROOT\apps\frontend"
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
