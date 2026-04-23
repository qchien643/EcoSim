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

# ── 1. Kill by port ──
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

# ── 2. Kill by window title ──
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

# ── 3. Kill orphan python/node from EcoSim ──
if ($Only -eq "" -or $Only -eq "sim" -or $Only -eq "core" -or $Only -eq "gateway") {
    $pyProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $pyProcs) {
        if ($killedPids.Contains([int]$p.ProcessId)) { continue }
        $cmd = $p.CommandLine
        if ($cmd -and ($cmd -match "sim_service" -or $cmd -match "run\.py" -or $cmd -match "gateway\.py" -or $cmd -match "run_simulation")) {
            Write-Host "  [ORPHAN] Killing python.exe (PID $($p.ProcessId))" -ForegroundColor Yellow
            Kill-Tree -ProcessId $p.ProcessId
            [void]$killedPids.Add([int]$p.ProcessId)
            $killed++
        }
    }
}

if ($Only -eq "" -or $Only -eq "frontend") {
    $nodeProcs = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $nodeProcs) {
        if ($killedPids.Contains([int]$p.ProcessId)) { continue }
        $cmd = $p.CommandLine
        if ($cmd -and $cmd -match "EcoSim.*frontend") {
            Write-Host "  [ORPHAN] Killing node.exe (PID $($p.ProcessId)) - Frontend" -ForegroundColor Yellow
            Kill-Tree -ProcessId $p.ProcessId
            [void]$killedPids.Add([int]$p.ProcessId)
            $killed++
        }
    }
}

# ── 4. FalkorDB (Docker) ──
if (-not $KeepDocker -and ($Only -eq "" -or $Only -eq "falkordb")) {
    $container = docker ps -q -f "name=ecosim-falkordb" 2>$null
    if ($container) {
        Write-Host "  [DOCKER] Stopping FalkorDB" -ForegroundColor Yellow
        docker stop ecosim-falkordb 2>$null | Out-Null
        $killed++
    }
}

# ── Summary ──
Write-Host ""
if ($killed -eq 0) {
    Write-Host "  No EcoSim services were running." -ForegroundColor DarkGray
} else {
    Write-Host "  Stopped $killed service(s)." -ForegroundColor Green
}
Write-Host ""
