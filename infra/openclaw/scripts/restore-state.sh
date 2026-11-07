#!/bin/bash
# OpenClaw Restore Script - Restore state from backup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DATA_DIR="${PROJECT_ROOT}/data/openclaw"
BACKUP_FILE="${1}"

if [ -z "${BACKUP_FILE}" ]; then
    echo "Usage: $0 <backup-file>"
    echo ""
    echo "Example:"
    echo "  $0 ${DATA_DIR}/backups/openclaw-backup-20261107_162250.tar.gz"
    echo ""
    echo "Available backups:"
    ls -lh "${DATA_DIR}/backups"/openclaw-backup-*.tar.gz 2>/dev/null || echo "  (none found)"
    echo ""
    exit 1
fi

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "ERROR: Backup file not found: ${BACKUP_FILE}"
    exit 1
fi

echo "======================================================================"
echo "OpenClaw State Restore"
echo "======================================================================"
echo "Backup file: ${BACKUP_FILE}"
echo "File size: $(du -h "${BACKUP_FILE}" | cut -f1)"
echo ""

# Confirm restore
read -p "WARNING: This will overwrite current state. Continue? (yes/no) " -r
if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo "[*] Stopping gateway for state restore..."
docker compose -f "${SCRIPT_DIR}/docker-compose.yml" stop openclaw-gateway || true
sleep 2

echo "[*] Backing up current state before restore..."
SAFETY_BACKUP="${DATA_DIR}/backups/openclaw-safety-backup-$(date +%Y%m%d_%H%M%S).tar.gz"
tar -czf "${SAFETY_BACKUP}" -C "${DATA_DIR}" state workspace 2>/dev/null || true
echo "   Safety backup: ${SAFETY_BACKUP}"

echo "[*] Restoring from backup..."
cd "${DATA_DIR}"
tar -xzf "${BACKUP_FILE}" || {
    echo "ERROR: Restore failed - safety backup available at: ${SAFETY_BACKUP}"
    docker compose -f "${SCRIPT_DIR}/docker-compose.yml" start openclaw-gateway
    exit 1
}

echo "[✓] State restored"

echo "[*] Restarting gateway..."
docker compose -f "${SCRIPT_DIR}/docker-compose.yml" start openclaw-gateway

echo ""
echo "[✓] Restore complete!"
echo ""
