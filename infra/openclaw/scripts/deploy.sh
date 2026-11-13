#!/bin/bash
# OpenClaw Deployment Script - Deploy/Update the gateway
# Usage: bash scripts/deploy.sh [up|down|restart|logs|status]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMMAND="${1:-up}"

echo "======================================================================"
echo "OpenClaw Deployment Manager"
echo "======================================================================"
echo "Project root: ${PROJECT_ROOT}"
echo "Command: ${COMMAND}"
echo ""

# Check for .env.local
if [ ! -f "${SCRIPT_DIR}/.env.local" ]; then
    echo "ERROR: .env.local not found!"
    echo ""
    echo "Please create .env.local with your secrets:"
    echo "  1. cp ${SCRIPT_DIR}/.env.example ${SCRIPT_DIR}/.env.local"
    echo "  2. Edit .env.local with your Discord token and OpenAI key"
    echo "  3. Run this script again"
    echo ""
    exit 1
fi

# Check for required secrets in .env.local
echo "[*] Validating configuration..."
source "${SCRIPT_DIR}/.env.local" 2>/dev/null || true

if [ -z "${DISCORD_BOT_TOKEN}" ] || [ "${DISCORD_BOT_TOKEN}" = "placeholder_discord_bot_token" ]; then
    echo "ERROR: DISCORD_BOT_TOKEN not set in .env.local"
    exit 1
fi

if [ -z "${OPENAI_API_KEY}" ] || [ "${OPENAI_API_KEY}" = "placeholder_openai_api_key" ]; then
    echo "ERROR: OPENAI_API_KEY not set in .env.local"
    exit 1
fi

if [ -z "${OPENCLAW_GATEWAY_TOKEN}" ] || [ "${OPENCLAW_GATEWAY_TOKEN}" = "placeholder_generate_with_openssl_rand_hex_32" ]; then
    echo "ERROR: OPENCLAW_GATEWAY_TOKEN not set in .env.local"
    echo "Generate one: openssl rand -hex 32"
    exit 1
fi

echo "[✓] Configuration valid"
echo ""

# Export environment for docker-compose
export COMPOSE_PROJECT_NAME=openclaw
export COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

cd "${SCRIPT_DIR}"

case "${COMMAND}" in
    up)
        echo "[*] Starting OpenClaw gateway..."
        docker compose --env-file "${SCRIPT_DIR}/.env.local" up -d --pull always
        echo ""
        echo "[*] Waiting for gateway to start..."
        sleep 5
        bash "${SCRIPT_DIR}/scripts/health-check.sh" || true
        echo "[✓] Deployment complete!"
        echo ""
        echo "Gateway available at: http://127.0.0.1:8080"
        echo "View logs: bash ${SCRIPT_DIR}/scripts/logs.sh"
        ;;
    
    down)
        echo "[*] Stopping OpenClaw gateway..."
        docker compose --env-file "${SCRIPT_DIR}/.env.local" down --remove-orphans
        echo "[✓] Gateway stopped"
        ;;
    
    restart)
        echo "[*] Restarting OpenClaw gateway..."
        docker compose --env-file "${SCRIPT_DIR}/.env.local" restart
        echo "[*] Waiting for gateway to restart..."
        sleep 5
        bash "${SCRIPT_DIR}/scripts/health-check.sh" || true
        echo "[✓] Gateway restarted"
        ;;
    
    logs)
        echo "[*] OpenClaw gateway logs (last 100 lines):"
        echo "======================================================================"
        docker compose logs --tail=100 -f openclaw-gateway || true
        ;;
    
    status)
        echo "[*] OpenClaw gateway status:"
        echo "======================================================================"
        docker compose ps
        echo ""
        bash "${SCRIPT_DIR}/scripts/health-check.sh" || echo "WARNING: Health check failed"
        ;;
    
    *)
        echo "Usage: $0 {up|down|restart|logs|status}"
        echo ""
        echo "Commands:"
        echo "  up       - Start the OpenClaw gateway (default)"
        echo "  down     - Stop the OpenClaw gateway"
        echo "  restart  - Restart the OpenClaw gateway"
        echo "  logs     - View gateway logs (live)"
        echo "  status   - Show gateway status"
        echo ""
        exit 1
        ;;
esac
