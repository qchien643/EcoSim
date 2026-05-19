# ============================================================
# EcoSim - Restart Services
#
# Usage:
#   .\restart.ps1                            # restart full stack
#   .\restart.ps1 -Only sim                  # restart 1 service
#   .\restart.ps1 -KeepDocker                # restart Python/Node, không đụng FalkorDB
#   .\restart.ps1 -SkipDocker                # restart Python/Node, FalkorDB không bị tắt cũng không bật lại
#   .\restart.ps1 -NoPreflight               # bỏ qua check uv/venv/Docker khi start lại
#
# Stop trước rồi start. Cờ -KeepDocker forward sang stop.ps1 (giữ container),
# -SkipDocker forward sang start.ps1 (không khởi lại FalkorDB).
# ============================================================
param(
    [ValidateSet("falkordb","core","sim","gateway","frontend","")]
    [string]$Only = "",
    [switch]$KeepDocker,
    [switch]$SkipDocker,
    [switch]$NoPreflight,
    [int]$DockerWaitSec = 90
)

$ErrorActionPreference = "Continue"
$SCRIPTS = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "  EcoSim - Restart" -ForegroundColor Magenta
Write-Host "  ================" -ForegroundColor Magenta
Write-Host ""

# -- Stop phase --
$stopArgs = @{}
if ($Only -ne "") { $stopArgs["Only"] = $Only }
if ($KeepDocker)  { $stopArgs["KeepDocker"] = $true }
# -SkipDocker (start-side) cũng tránh tắt Docker trong stop, để FalkorDB vẫn chạy.
if ($SkipDocker)  { $stopArgs["KeepDocker"] = $true }

& "$SCRIPTS\stop.ps1" @stopArgs

# Cho OS giải phóng port + cửa sổ cmd đóng hoàn toàn trước khi spawn lại.
# 2s đủ với hầu hết trường hợp; nâng lên nếu thấy "port still in use".
Start-Sleep -Seconds 2

# -- Start phase --
$startArgs = @{}
if ($Only -ne "")    { $startArgs["Only"] = $Only }
if ($SkipDocker)     { $startArgs["SkipDocker"] = $true }
if ($NoPreflight)    { $startArgs["NoPreflight"] = $true }
if ($DockerWaitSec)  { $startArgs["DockerWaitSec"] = $DockerWaitSec }

& "$SCRIPTS\start.ps1" @startArgs
