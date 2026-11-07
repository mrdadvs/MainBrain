#!/bin/bash
# OpenClaw Initialization Script - Create Required Directories and Permissions
# Run this once before first deployment

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DATA_DIR="${PROJECT_ROOT}/data/openclaw"

echo "======================================================================"
echo "OpenClaw Directory Initialization"
echo "======================================================================"
echo "Project root: ${PROJECT_ROOT}"
echo "Data directory: ${DATA_DIR}"
echo ""

# Create required directories
echo "[*] Creating persistent state directories..."
mkdir -p "${DATA_DIR}/state"/{config,cache,logs}
mkdir -p "${DATA_DIR}/workspace"
mkdir -p "${DATA_DIR}/backups"

# Set appropriate permissions (user:group = 1000:1000 for container)
echo "[*] Setting directory permissions..."
chown -R 1000:1000 "${DATA_DIR}" 2>/dev/null || echo "    Note: Could not change ownership (might need sudo)"
chmod -R u+rwX,g+rX,o-rwx "${DATA_DIR}"

# Create initial empty config if not exists
if [ ! -f "${DATA_DIR}/state/config/models.json" ]; then
    echo "[*] Creating initial models.json configuration..."
    cat > "${DATA_DIR}/state/config/models.json" << 'MODELS_EOF'
{
  "mode": "replace",
  "data": {
    "models": [
      {
        "id": "openai-gpt4",
        "name": "GPT-4 Turbo",
        "provider": "openai",
        "model": "gpt-4-turbo",
        "enabled": true,
        "temperature": 0.7,
        "max_tokens": 2048
      },
      {
        "id": "openai-gpt35",
        "name": "GPT-3.5 Turbo",
        "provider": "openai",
        "model": "gpt-3.5-turbo",
        "enabled": true,
        "temperature": 0.7,
        "max_tokens": 4096
      }
    ]
  }
}
MODELS_EOF
    chmod 644 "${DATA_DIR}/state/config/models.json"
fi

# Create initial Discord configuration if not exists
if [ ! -f "${DATA_DIR}/state/config/discord.json" ]; then
    echo "[*] Creating initial Discord configuration..."
    cat > "${DATA_DIR}/state/config/discord.json" << 'DISCORD_EOF'
{
  "mode": "replace",
  "data": {
    "discord": {
      "intents": [
        "GUILDS",
        "GUILD_MESSAGES",
        "MESSAGE_CONTENT",
        "DIRECT_MESSAGES"
      ],
      "mention_required": true,
      "chat_only": true
    }
  }
}
DISCORD_EOF
    chmod 644 "${DATA_DIR}/state/config/discord.json"
fi

# Create logs directory with proper permissions
touch "${DATA_DIR}/state/logs/.keep"
chmod 755 "${DATA_DIR}/state/logs"

echo ""
echo "[✓] Directory initialization complete!"
echo ""
echo "Next steps:"
echo "  1. Copy .env.example to .env.local: cp .env.example .env.local"
echo "  2. Edit .env.local with your Discord bot token and OpenAI API key"
echo "  3. Generate a gateway token: openssl rand -hex 32"
echo "  4. Run: bash scripts/deploy.sh"
echo ""
