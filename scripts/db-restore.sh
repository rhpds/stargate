#!/bin/bash
# Database restore script
# Usage: ./scripts/db-restore.sh backups/stargate-20260511-120000.sql.gz

set -euo pipefail

if [ $# -eq 0 ]; then
    echo "Usage: $0 <backup-file.sql.gz>"
    echo "Available backups:"
    ls -lt "$(dirname "$0")/../backups"/stargate-*.sql.gz 2>/dev/null || echo "  (none)"
    exit 1
fi

BACKUP_FILE="$1"
if [ ! -f "$BACKUP_FILE" ]; then
    echo "Error: $BACKUP_FILE not found"
    exit 1
fi

echo "WARNING: This will replace all data in the stargate database."
echo "Restoring from: $BACKUP_FILE"
read -p "Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

gunzip -c "$BACKUP_FILE" | podman exec -i stargate-platform_postgres_1 \
    psql -U stargate -d stargate

echo "Restore complete."
