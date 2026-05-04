#!/usr/bin/env bash
# FalkorDB backup — bash version (Linux/macOS/Git Bash on Windows).
# See backup_falkordb.ps1 for PowerShell version.
#
# Usage:
#   ./scripts/backup_falkordb.sh           # default keep 7
#   KEEP=14 ./scripts/backup_falkordb.sh   # custom retention
#
# Cron daily 2am:
#   0 2 * * * cd /path/to/EcoSim && ./scripts/backup_falkordb.sh

set -euo pipefail

CONTAINER="${CONTAINER:-ecosim-falkordb}"
KEEP="${KEEP:-7}"
BACKUP_DIR="${BACKUP_DIR:-data/backups/falkordb}"

# Resolve repo root from script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

mkdir -p "$BACKUP_DIR"

# 1. BGSAVE
echo "Triggering BGSAVE on $CONTAINER..."
docker exec "$CONTAINER" redis-cli BGSAVE

# 2. Poll LASTSAVE
initial=$(docker exec "$CONTAINER" redis-cli LASTSAVE)
deadline=$(( $(date +%s) + 60 ))
while true; do
  sleep 0.5
  current=$(docker exec "$CONTAINER" redis-cli LASTSAVE)
  if [ "$current" != "$initial" ]; then break; fi
  if [ "$(date +%s)" -gt "$deadline" ]; then
    echo "WARN: BGSAVE timeout 60s — proceeding"
    break
  fi
done

# 3. Copy
ts=$(date +"%Y%m%d-%H%M%S")
out="$BACKUP_DIR/$ts.rdb"
echo "Copying dump.rdb → $out"
docker cp "$CONTAINER:/var/lib/falkordb/data/dump.rdb" "$out"

size_mb=$(du -m "$out" | cut -f1)
echo "Backup OK: ${size_mb} MB"

# 4. Rotate
count=$(ls -1 "$BACKUP_DIR"/*.rdb 2>/dev/null | wc -l)
if [ "$count" -gt "$KEEP" ]; then
  ls -1t "$BACKUP_DIR"/*.rdb | tail -n +$((KEEP + 1)) | while read -r f; do
    echo "Rotated out: $(basename "$f")"
    rm -f "$f"
  done
fi

echo "Done. Backups retained: $(( count > KEEP ? KEEP : count ))"
