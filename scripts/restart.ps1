# ============================================================
# EcoSim - Restart All Services (or a specific one)
# Usage: .\restart.ps1 [-Only <service>]
# ============================================================
param(
    [ValidateSet("falkordb","core","sim","gateway","frontend","")]
    [string]$Only = ""
)

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "  EcoSim - Restarting Services" -ForegroundColor Magenta
Write-Host "  =============================" -ForegroundColor Magenta
Write-Host ""

# Stop only the targeted service(s)
if ($Only) {
    & "$ROOT\stop.ps1" -Only $Only -KeepDocker
} else {
    & "$ROOT\stop.ps1"
}

# Wait for ports to free up
Write-Host "  Waiting for ports to release..." -ForegroundColor DarkGray
Start-Sleep -Seconds 2

# Start
if ($Only) {
    & "$ROOT\start.ps1" -Only $Only
} else {
    & "$ROOT\start.ps1"
}
