# FalkorDB backup script — BGSAVE + copy dump.rdb ra data/backups/falkordb/.
# Cross-platform companion: scripts/backup_falkordb.sh (bash).
#
# Usage:
#   pwsh ./scripts/backup_falkordb.ps1               # default: keep 7 daily backups
#   pwsh ./scripts/backup_falkordb.ps1 -Keep 14      # custom retention
#
# Cron example (Task Scheduler trigger daily 2am):
#   pwsh -File E:\code\project\DUT_STARTUP\EcoSim\scripts\backup_falkordb.ps1
#
# Prereq: docker container `ecosim-falkordb` đang chạy.
# Output: data/backups/falkordb/<ISO_timestamp>.rdb

[CmdletBinding()]
param(
  [string]$Container = "ecosim-falkordb",
  [int]$Keep = 7,
  [string]$BackupDir = "data/backups/falkordb"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not (Test-Path $BackupDir)) {
  New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
  Write-Host "Created backup dir: $BackupDir"
}

# 1. Trigger BGSAVE (async, non-blocking)
Write-Host "Triggering BGSAVE on container $Container..."
$bgsave = docker exec $Container redis-cli BGSAVE
if ($LASTEXITCODE -ne 0) {
  Write-Error "BGSAVE failed: $bgsave"
  exit 1
}
Write-Host "  $bgsave"

# 2. Poll LASTSAVE until completion (timeout 60s)
$initial = docker exec $Container redis-cli LASTSAVE
$deadline = (Get-Date).AddSeconds(60)
do {
  Start-Sleep -Milliseconds 500
  $current = docker exec $Container redis-cli LASTSAVE
  if ($current -ne $initial) { break }
  if ((Get-Date) -gt $deadline) {
    Write-Warning "BGSAVE timeout sau 60s — proceeding (snapshot có thể chưa xong)"
    break
  }
} while ($true)

# 3. Copy dump.rdb ra backup dir
$timestamp = (Get-Date).ToString("yyyyMMdd-HHmmss")
$outPath = Join-Path $BackupDir "$timestamp.rdb"
Write-Host "Copying dump.rdb → $outPath"
docker cp "${Container}:/var/lib/falkordb/data/dump.rdb" $outPath
if ($LASTEXITCODE -ne 0) {
  Write-Error "docker cp failed"
  exit 1
}

$size = (Get-Item $outPath).Length / 1MB
Write-Host ("Backup OK: {0:N2} MB" -f $size)

# 4. Rotate — keep last N backups
$all = Get-ChildItem -Path $BackupDir -Filter "*.rdb" | Sort-Object Name -Descending
if ($all.Count -gt $Keep) {
  $toDelete = $all | Select-Object -Skip $Keep
  foreach ($f in $toDelete) {
    Remove-Item $f.FullName -Force
    Write-Host "Rotated out: $($f.Name)"
  }
}

Write-Host "Done. Backups retained: $([Math]::Min($all.Count, $Keep))"
