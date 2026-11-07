#!/bin/bash
# OpenClaw Backup Script - Backup state, configuration, and runtime data

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DATA_DIR="${PROJECT_ROOT}/data/openclaw"
BACKUP_DIR="${DATA_DIR}/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/openclaw-backup-${TIMESTAMP}.tar.gz"

echo "======================================================================"
echo "OpenClaw State Backup"
echo "======================================================================"
echo "Backup directory: ${BACKUP_DIR}"
echo "Backup file: ${BACKUP_FILE}"
echo ""

# Ensure backup directory exists
mkdir -p "${BACKUP_DIR}"

# Stop the gateway (graceful shutdown)
echo "[*] Stopping gateway for consistent backup..."
docker compose -f "${SCRIPT_DIR}/docker-compose.yml" stop openclaw-gateway || true
sleep 2

# Create backup
echo "[*] Creating backup archive..."
cd "${DATA_DIR}"

tar --exclude='workspace/temp' \
    --exclude='*.log' \
    -czf "${BACKUP_FILE}" \
    state/ \
    workspace/ || {
    echo "ERROR: Backup failed"
    docker compose -f "${SCRIPT_DIR}/docker-compose.yml" start openclaw-gateway
    exit 1
}

echo "[✓] Backup created: $(du -h "${BACKUP_FILE}" | cut -f1)"

# Restart the gateway
echo "[*] Restarting gateway..."
docker compose -f "${SCRIPT_DIR}/docker-compose.yml" start openclaw-gateway

# Clean old backups (keep last 10)
echo "[*] Cleaning old backups (keeping 10 most recent)..."
ls -1t "${BACKUP_DIR}"/openclaw-backup-*.tar.gz 2>/dev/null | tail -n +11 | xargs -r rm -v

echo ""
echo "[✓] Backup complete!"
echo "Restore with: bash scripts/restore-state.sh ${BACKUP_FILE}"
echo ""
