# ============================================================
# EcoSim - Start All Services
#
# Usage:
#   .\start.ps1                              # bật full stack
#   .\start.ps1 -SkipDocker                  # bỏ qua FalkorDB
#   .\start.ps1 -Only sim                    # chỉ 1 service
#   .\start.ps1 -NoPreflight                 # bỏ qua check uv/venv/Docker
#
# Mỗi service chạy trong 1 cửa sổ cmd riêng (tiêu đề "EcoSim - ..."), dễ
# nhận diện ở taskbar. Dùng .\stop.ps1 để tắt.
# ============================================================
param(
    [switch]$SkipDocker,
    [ValidateSet("falkordb","core","sim","gateway","frontend","")]
    [string]$Only = "",
    [switch]$NoPreflight,
    [int]$DockerWaitSec = 90
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

# Build a cmd.exe /c argument string. Avoids PS 5.1 parser quirks với
# escape-quotes trong long strings.
function New-CmdArgs($title, $command) {
    return "/c title $title && $command"
}

# Ensure Docker daemon is ready. Auto-launch Docker Desktop and wait up to
# $DockerWaitSec seconds. Returns $true if ready, $false otherwise.
function Ensure-DockerReady {
    docker info 2>$null 1>$null
    if ($LASTEXITCODE -eq 0) { return $true }

    Write-Host "       Docker daemon not responding - attempting to start Docker Desktop..." -ForegroundColor Yellow
    $ddPath = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $ddPath)) {
        Write-Host "       Docker Desktop.exe not found at $ddPath" -ForegroundColor Red
        Write-Host "       Cài Docker Desktop hoặc start daemon thủ công rồi rerun." -ForegroundColor Red
        return $false
    }
    Start-Process -FilePath $ddPath -WindowStyle Minimized

    $elapsed = 0
    while ($elapsed -lt $DockerWaitSec) {
        Start-Sleep -Seconds 3
        $elapsed += 3
        docker info 2>$null 1>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "       Docker daemon ready (after ${elapsed}s)." -ForegroundColor Green
            return $true
        }
        Write-Host "       Waiting for Docker daemon... ${elapsed}/${DockerWaitSec}s" -ForegroundColor DarkGray
    }
    Write-Host "       Docker daemon still not responding after ${DockerWaitSec}s." -ForegroundColor Red
    Write-Host "       Mở Docker Desktop thủ công + chờ icon thành 'Engine running' rồi rerun." -ForegroundColor Red
    return $false
}

# ============================================================
# Pre-flight checks — verify tooling + venvs trước khi spawn windows.
# Bỏ qua bằng -NoPreflight.
# ============================================================
if (-not $NoPreflight) {
    $problems = @()

    # uv (cần cho cả Core lẫn Sim nếu chưa có venv)
    $needsUv = $false
    if ((Should-Run "core") -and -not (Test-Path "$ROOT\apps\core\.venv\Scripts\python.exe")) {
        $needsUv = $true
        $problems += "Core .venv chưa có. Chạy: cd apps/core && uv sync"
    }
    if ((Should-Run "sim") -and -not (Test-Path "$ROOT\apps\simulation\.venv\Scripts\python.exe")) {
        $needsUv = $true
        $problems += "Sim .venv chưa có. Chạy: cd apps/simulation && uv sync --python 3.11"
    }
    if ($needsUv -and -not (Get-Command uv -ErrorAction SilentlyContinue)) {
        $problems += "uv chưa cài. Chạy: powershell -ExecutionPolicy ByPass -c ""irm https://astral.sh/uv/install.ps1 | iex"""
    }

    # node_modules cho frontend (tự handle ở step 5 — chỉ warn)
    if ((Should-Run "frontend") -and -not (Test-Path "$ROOT\apps\frontend\node_modules")) {
        Write-Host "  Note: apps/frontend/node_modules chưa có - sẽ tự chạy 'npm install' khi cần." -ForegroundColor DarkGray
    }

    if ($problems.Count -gt 0) {
        Write-Host "  Pre-flight failed:" -ForegroundColor Red
        foreach ($p in $problems) {
            Write-Host "    - $p" -ForegroundColor Red
        }
        Write-Host ""
        Write-Host "  Rerun .\start.ps1 sau khi fix. (Bỏ qua check: .\start.ps1 -NoPreflight)" -ForegroundColor DarkGray
        Write-Host ""
        exit 1
    }
}

# ============================================================
# 1. FalkorDB (Docker)
# ============================================================
if ((Should-Run "falkordb") -and -not $SkipDocker) {
    Write-Host "[1/5] FalkorDB (Docker, port 6379)" -ForegroundColor Green

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host "       docker CLI không có trong PATH. Cài Docker Desktop trước." -ForegroundColor Red
    } else {
        if (-not (Ensure-DockerReady)) {
            Write-Host "       Skipping FalkorDB. Stack chạy được nhưng KG endpoints sẽ fail." -ForegroundColor Yellow
        } else {
            $container = docker ps -q -f "name=ecosim-falkordb" 2>$null
            if ($container) {
                Write-Host "       Already running." -ForegroundColor Yellow
            } else {
                docker compose -f "$ROOT\docker-compose.yml" up -d falkordb 2>$null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "       Started." -ForegroundColor Green
                } else {
                    Write-Host "       'docker compose up -d falkordb' failed - check 'docker compose logs falkordb'." -ForegroundColor Red
                }
            }
        }
    }
    Write-Host ""
}

# ============================================================
# 2. Core Service (Flask :5001)
# ============================================================
if (Should-Run "core") {
    Write-Host "[2/5] Core Service (Flask, port 5001)" -ForegroundColor Green

    $corePy = "$ROOT\apps\core\.venv\Scripts\python.exe"
    if (-not (Test-Path $corePy)) {
        Write-Host "       Core .venv missing. Chạy: cd apps/core && uv sync" -ForegroundColor Red
    } else {
        $cmdArgs = New-CmdArgs "EcoSim - Core Service (5001)" "`"$corePy`" run.py"
        Start-Process cmd.exe -ArgumentList $cmdArgs -WorkingDirectory "$ROOT\apps\core"
        Write-Host "       Started." -ForegroundColor Green
    }
    Write-Host ""
}

# ============================================================
# 3. Simulation Service (FastAPI :5002)
# ============================================================
if (Should-Run "sim") {
    Write-Host "[3/5] Simulation Service (FastAPI, port 5002)" -ForegroundColor Green

    $simPy = "$ROOT\apps\simulation\.venv\Scripts\python.exe"
    if (-not (Test-Path $simPy)) {
        Write-Host "       Sim .venv missing. Chạy: cd apps/simulation && uv sync --python 3.11" -ForegroundColor Red
    } else {
        $cmdArgs = New-CmdArgs "EcoSim - Simulation Service (5002)" "`"$simPy`" -m uvicorn sim_service:app --host 0.0.0.0 --port 5002"
        Start-Process cmd.exe -ArgumentList $cmdArgs -WorkingDirectory "$ROOT\apps\simulation"
        Write-Host "       Started." -ForegroundColor Green
    }
    Write-Host ""
}

# ============================================================
# 4. API Gateway (Caddy :5000, fallback to legacy Flask proxy)
# ============================================================
if (Should-Run "gateway") {
    Write-Host "[4/5] API Gateway (Caddy, port 5000)" -ForegroundColor Green

    $env:CORE_UPSTREAM = "localhost:5001"
    $env:SIM_UPSTREAM  = "localhost:5002"

    $caddyCmd = Get-Command caddy.exe -ErrorAction SilentlyContinue
    if ($caddyCmd) {
        $gwInner = "set CORE_UPSTREAM=localhost:5001 && set SIM_UPSTREAM=localhost:5002 && caddy run --config Caddyfile --adapter caddyfile"
        $cmdArgs = New-CmdArgs "EcoSim - API Gateway (Caddy, 5000)" $gwInner
        Start-Process cmd.exe -ArgumentList $cmdArgs -WorkingDirectory "$ROOT\apps\gateway"
        Write-Host "       Started (Caddy)." -ForegroundColor Green
    } else {
        Write-Host "       caddy.exe không có trong PATH - fallback gateway.py.bak (Flask proxy)" -ForegroundColor Yellow
        $legacy = "$ROOT\apps\gateway\gateway.py.bak"
        if (Test-Path $legacy) {
            # Reuse Core venv vì gateway.py.bak chỉ cần flask + httpx.
            $legacyPy = "$ROOT\apps\core\.venv\Scripts\python.exe"
            if (-not (Test-Path $legacyPy)) {
                Write-Host "       Core .venv missing - cần cho fallback gateway. Chạy: cd apps/core && uv sync" -ForegroundColor Red
            } else {
                $cmdArgs = New-CmdArgs "EcoSim - API Gateway (legacy Python, 5000)" "`"$legacyPy`" gateway.py.bak"
                Start-Process cmd.exe -ArgumentList $cmdArgs -WorkingDirectory "$ROOT\apps\gateway"
                Write-Host "       Started (legacy)." -ForegroundColor Green
            }
        } else {
            Write-Host "       Cả caddy.exe lẫn gateway.py.bak đều không có - gateway KHÔNG start." -ForegroundColor Red
        }
    }
    Write-Host ""
}

# ============================================================
# 5. Frontend (Next.js 16 :5173)
# ============================================================
if (Should-Run "frontend") {
    Write-Host "[5/5] Frontend (Next.js dev server, port 5173)" -ForegroundColor Green

    $fePath = "$ROOT\apps\frontend"

    if (-not (Test-Path "$fePath\node_modules")) {
        Write-Host "       node_modules missing - running 'npm install' first..." -ForegroundColor Yellow
        Push-Location $fePath
        npm install --no-audit --no-fund
        Pop-Location
    }

    $cmdArgs = New-CmdArgs "EcoSim - Frontend (Next.js, 5173)" "npm run dev"
    Start-Process cmd.exe -ArgumentList $cmdArgs -WorkingDirectory $fePath
    Write-Host "       Started." -ForegroundColor Green
    Write-Host ""
}

# ============================================================
# Summary
# ============================================================
Write-Host "  -------------------------------------------" -ForegroundColor DarkGray
Write-Host "  Services:" -ForegroundColor Cyan
Write-Host "    FalkorDB       : redis://localhost:6379 (Browser: http://localhost:3000)"
Write-Host "    Core Service   : http://localhost:5001"
Write-Host "    Simulation     : http://localhost:5002"
Write-Host "    API Gateway    : http://localhost:5000"
Write-Host "    Frontend (UI)  : http://localhost:5173"
Write-Host ""
Write-Host "  Verify:  curl http://localhost:5000/api/health" -ForegroundColor DarkGray
Write-Host "  Stop:    .\scripts\stop.ps1" -ForegroundColor DarkGray
Write-Host "  Restart: .\scripts\restart.ps1" -ForegroundColor DarkGray
Write-Host ""
