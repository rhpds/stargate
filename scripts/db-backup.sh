#!/bin/bash
# Database backup script — run via cron or manually
# Usage: ./scripts/db-backup.sh
#
# Dumps the stargate database from the Podman postgres container
# to backups/ directory with timestamp. Keeps last 7 days.

set -euo pipefail

BACKUP_DIR="$(dirname "$0")/../backups"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="$BACKUP_DIR/stargate-${TIMESTAMP}.sql.gz"

echo "Backing up stargate database..."
podman exec stargate-platform_postgres_1 \
    pg_dump -U stargate -d stargate --clean --if-exists \
    | gzip > "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Backup complete: $BACKUP_FILE ($SIZE)"

# Prune backups older than 7 days
find "$BACKUP_DIR" -name "stargate-*.sql.gz" -mtime +7 -delete 2>/dev/null || true
REMAINING=$(ls -1 "$BACKUP_DIR"/stargate-*.sql.gz 2>/dev/null | wc -l | tr -d ' ')
echo "Backups retained: $REMAINING"
