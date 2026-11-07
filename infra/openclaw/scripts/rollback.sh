#!/bin/bash
# OpenClaw Rollback Script - Safe container and configuration rollback

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "======================================================================"
echo "OpenClaw Container Rollback"
echo "======================================================================"
echo ""

# List recent containers
echo "[*] Recent OpenClaw containers:"
docker ps -a --filter "name=openclaw-gateway" --format "table {{.ID}}\t{{.Status}}\t{{.CreatedAt}}" | head -10

echo ""
echo "Current container:"
CURRENT_ID=$(docker compose -f "${SCRIPT_DIR}/docker-compose.yml" ps -q openclaw-gateway 2>/dev/null || echo "none")
echo "  ${CURRENT_ID}"

echo ""
echo "[*] Rollback options:"
echo "  1. Restart current container (cleans runtime state)"
echo "  2. Restore configuration from backup"
echo "  3. Both (1 + 2)"
echo ""

read -p "Select option (1-3): " -r CHOICE

case "${CHOICE}" in
    1)
        echo ""
        echo "[*] Restarting container..."
        docker compose -f "${SCRIPT_DIR}/docker-compose.yml" restart openclaw-gateway
        sleep 3
        bash "${SCRIPT_DIR}/scripts/health-check.sh" || echo "Health check inconclusive"
        echo "[✓] Container restarted"
        ;;
    
    2)
        echo ""
        echo "[*] Available backups:"
        ls -1t /home/mdv/mainbrain/data/openclaw/backups/openclaw-backup-*.tar.gz 2>/dev/null | head -5 || echo "  (no backups found)"
        echo ""
        read -p "Enter backup file path: " -r BACKUP_FILE
        if [ -f "${BACKUP_FILE}" ]; then
            bash "${SCRIPT_DIR}/scripts/restore-state.sh" "${BACKUP_FILE}"
        else
            echo "ERROR: Backup file not found"
            exit 1
        fi
        ;;
    
    3)
        echo ""
        read -p "Enter backup file path: " -r BACKUP_FILE
        if [ -f "${BACKUP_FILE}" ]; then
            echo ""
            echo "[*] Restoring configuration..."
            bash "${SCRIPT_DIR}/scripts/restore-state.sh" "${BACKUP_FILE}"
            echo ""
            echo "[*] Restarting container..."
            docker compose -f "${SCRIPT_DIR}/docker-compose.yml" restart openclaw-gateway
            sleep 3
            bash "${SCRIPT_DIR}/scripts/health-check.sh" || echo "Health check inconclusive"
            echo "[✓] Rollback complete"
        else
            echo "ERROR: Backup file not found"
            exit 1
        fi
        ;;
    
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

echo ""
echo "Next steps:"
echo "  - Monitor: bash ${SCRIPT_DIR}/scripts/logs.sh"
echo "  - Check status: bash ${SCRIPT_DIR}/scripts/deploy.sh status"
echo ""
