# ============================================================
# EcoSim - Stop All Services
# Usage: .\stop.ps1 [-KeepDocker] [-Only <service>]
# ============================================================
param(
    [switch]$KeepDocker,
    [ValidateSet("falkordb","core","sim","gateway","frontend","")]
    [string]$Only = ""
)

$ErrorActionPreference = "Continue"
$killed = 0

Write-Host ""
Write-Host "  EcoSim - Stopping Services" -ForegroundColor Red
Write-Host "  ==========================" -ForegroundColor Red
Write-Host ""

# Helper: kill process and all children
function Kill-Tree {
    param([int]$ProcessId)
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Kill-Tree -ProcessId $child.ProcessId
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

# Track killed PIDs to avoid double-kill
$killedPids = [System.Collections.Generic.HashSet[int]]::new()

# -- 1. Kill by port --
$ports = @(
    @{ Port = 5000; Name = "API Gateway";        Filter = "gateway" },
    @{ Port = 5001; Name = "Core Service";        Filter = "core" },
    @{ Port = 5002; Name = "Simulation Service";  Filter = "sim" },
    @{ Port = 5173; Name = "Frontend";            Filter = "frontend" }
)

foreach ($entry in $ports) {
    if ($Only -ne "" -and $Only -ne $entry.Filter) { continue }

    $connections = Get-NetTCPConnection -LocalPort $entry.Port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $connections) {
        $procId = $conn.OwningProcess
        if ($killedPids.Contains($procId)) { continue }

        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "  [PORT $($entry.Port)] Killing $($proc.ProcessName) (PID $procId) - $($entry.Name)" -ForegroundColor Yellow
            Kill-Tree -ProcessId $procId
            [void]$killedPids.Add($procId)
            $killed++
        }
    }
}

# -- 2. Kill by window title --
$titles = @(
    @{ Pattern = "EcoSim - Core Service";       Filter = "core" },
    @{ Pattern = "EcoSim - Simulation Service";  Filter = "sim" },
    @{ Pattern = "EcoSim - API Gateway";         Filter = "gateway" },
    @{ Pattern = "EcoSim - Frontend";            Filter = "frontend" }
)

foreach ($entry in $titles) {
    if ($Only -ne "" -and $Only -ne $entry.Filter) { continue }

    $procs = Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.MainWindowTitle -like "*$($entry.Pattern)*"
    }
    foreach ($proc in $procs) {
        if ($killedPids.Contains($proc.Id)) { continue }

        Write-Host "  [WINDOW] Killing $($proc.ProcessName) (PID $($proc.Id)) - '$($proc.MainWindowTitle)'" -ForegroundColor Yellow
        Kill-Tree -ProcessId $proc.Id
        [void]$killedPids.Add($proc.Id)
        $killed++
    }
}

# -- 3. Kill orphan python from EcoSim. Patterns are SCOPED to the
#    requested service so `-Only gateway` doesn't nuke Core / Sim too.
#    -Only "" (all)   => match every EcoSim python process
#    -Only "core"     => only `run.py`
#    -Only "sim"      => only `sim_service` / `run_simulation`
#    -Only "gateway"  => only legacy `gateway.py`
$pyPatterns = @()
if ($Only -eq "" -or $Only -eq "core")    { $pyPatterns += "run\.py" }
if ($Only -eq "" -or $Only -eq "sim")     { $pyPatterns += "sim_service"; $pyPatterns += "run_simulation" }
if ($Only -eq "" -or $Only -eq "gateway") { $pyPatterns += "gateway\.py" }

if ($pyPatterns.Count -gt 0) {
    $combined = ($pyPatterns -join "|")
    $pyProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $pyProcs) {
        if ($killedPids.Contains([int]$p.ProcessId)) { continue }
        $cmd = $p.CommandLine
        if ($cmd -and $cmd -match $combined) {
            Write-Host "  [ORPHAN] Killing python.exe (PID $($p.ProcessId)) - matched /$combined/" -ForegroundColor Yellow
            Kill-Tree -ProcessId $p.ProcessId
            [void]$killedPids.Add([int]$p.ProcessId)
            $killed++
        }
    }
}

if ($Only -eq "" -or $Only -eq "gateway") {
    $caddyProcs = Get-CimInstance Win32_Process -Filter "Name='caddy.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $caddyProcs) {
        if ($killedPids.Contains([int]$p.ProcessId)) { continue }
        $cmd = $p.CommandLine
        if ($cmd -and $cmd -match "Caddyfile") {
            Write-Host "  [ORPHAN] Killing caddy.exe (PID $($p.ProcessId)) - Gateway" -ForegroundColor Yellow
            Kill-Tree -ProcessId $p.ProcessId
            [void]$killedPids.Add([int]$p.ProcessId)
            $killed++
        }
    }
}

if ($Only -eq "" -or $Only -eq "frontend") {
    # Next.js dev spawns several node workers (compiler, server, esbuild).
    # Match any node/esbuild whose CommandLine references the EcoSim frontend dir
    # OR which is the standalone next/server.js process.
    $jsProcNames = @("node.exe", "esbuild.exe")
    foreach ($name in $jsProcNames) {
        $procs = Get-CimInstance Win32_Process -Filter "Name='$name'" -ErrorAction SilentlyContinue
        foreach ($p in $procs) {
            if ($killedPids.Contains([int]$p.ProcessId)) { continue }
            $cmd = $p.CommandLine
            if ($cmd -and ($cmd -match "EcoSim[\\/]apps[\\/]frontend" -or
                            $cmd -match "next/dist/bin/next" -or
                            $cmd -match "\.next[\\/]standalone[\\/]server\.js")) {
                Write-Host "  [ORPHAN] Killing $name (PID $($p.ProcessId)) - Frontend" -ForegroundColor Yellow
                Kill-Tree -ProcessId $p.ProcessId
                [void]$killedPids.Add([int]$p.ProcessId)
                $killed++
            }
        }
    }
}

# -- 4. FalkorDB (Docker) --
if (-not $KeepDocker -and ($Only -eq "" -or $Only -eq "falkordb")) {
    $container = docker ps -q -f "name=ecosim-falkordb" 2>$null
    if ($container) {
        Write-Host "  [DOCKER] Stopping FalkorDB" -ForegroundColor Yellow
        docker stop ecosim-falkordb 2>$null | Out-Null
        $killed++
    }
}

# -- Summary --
Write-Host ""
if ($killed -eq 0) {
    Write-Host "  No EcoSim services were running." -ForegroundColor DarkGray
} else {
    Write-Host "  Stopped $killed service(s)." -ForegroundColor Green
}
Write-Host ""
