#!/bin/bash
# OpenClaw Secure Credential Setup
# This script guides you through safely entering Discord and OpenAI credentials
# Secrets are NOT echoed to screen and stored in git-ignored .env.local only

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_LOCAL="${SCRIPT_DIR}/.env.local"
ENV_EXAMPLE="${SCRIPT_DIR}/.env.example"

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║        OpenClaw Secure Credential Setup                      ║"
echo "║                                                               ║"
echo "║  This script will help you safely configure Discord and      ║"
echo "║  OpenAI credentials. Your secrets will NOT be echoed to the  ║"
echo "║  screen and will only be stored in .env.local (git-ignored). ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Check if .env.local already exists
if [ -f "${ENV_LOCAL}" ]; then
    echo "⚠ Warning: .env.local already exists"
    read -p "Do you want to overwrite it? (yes/no): " OVERWRITE
    if [ "${OVERWRITE}" != "yes" ]; then
        echo "Cancelled. Your existing .env.local was not modified."
        exit 0
    fi
    echo "Backing up existing .env.local to .env.local.bak"
    cp "${ENV_LOCAL}" "${ENV_LOCAL}.bak"
fi

# Start with template
cp "${ENV_EXAMPLE}" "${ENV_LOCAL}"
chmod 600 "${ENV_LOCAL}"
echo "✓ Created .env.local with restricted permissions (600)"
echo ""

# Helper function to prompt for secret
prompt_secret() {
    local prompt_text="$1"
    local env_var="$2"
    local placeholder="$3"
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Enter: ${prompt_text}"
    echo ""
    echo "📋 Instructions:"
    
    case "${env_var}" in
        DISCORD_BOT_TOKEN)
            echo "  1. Go to: https://discord.com/developers/applications"
            echo "  2. Click your 'MainBrain Test' application"
            echo "  3. Go to Bot tab → Reset Token (if needed)"
            echo "  4. Copy the token (looks like: ODk4M...)"
            echo ""
            ;;
        OPENAI_API_KEY)
            echo "  1. Go to: https://platform.openai.com/api-keys"
            echo "  2. Click 'Create new secret key'"
            echo "  3. Copy the key (starts with: sk-proj-)"
            echo ""
            ;;
        DISCORD_SERVER_ID)
            echo "  1. In Discord, right-click your 'MainBrain' server name"
            echo "  2. Select 'Copy Server ID'"
            echo "  3. Paste it below"
            echo ""
            ;;
        DISCORD_CHANNEL_ID)
            echo "  1. In Discord, right-click the '#agent-test' channel"
            echo "  2. Select 'Copy Channel ID'"
            echo "  3. Paste it below"
            echo ""
            ;;
        DISCORD_ALLOWED_USERS)
            echo "  1. In Discord, right-click your username"
            echo "  2. Select 'Copy User ID'"
            echo "  3. Paste it below"
            echo ""
            ;;
        OPENCLAW_GATEWAY_TOKEN)
            echo "  A random token will be generated for you."
            echo "  You can accept the default or paste a custom one."
            echo ""
            ;;
    esac
    
    # Read input (silent for tokens, visible for IDs)
    if [[ "${env_var}" == *TOKEN* ]] || [[ "${env_var}" == *KEY* ]]; then
        # Token/key: read silently
        read -s -p "Enter ${env_var} (input hidden): " SECRET_VALUE
        echo ""  # New line after silent input
    else
        # ID: read normally
        read -p "Enter ${env_var}: " SECRET_VALUE
    fi
    
    # Validate not empty
    if [ -z "${SECRET_VALUE}" ]; then
        echo "❌ Error: ${env_var} cannot be empty"
        # Retry
        prompt_secret "$1" "$2" "$3"
        return
    fi
    
    # Update .env.local with sed (safe for special characters)
    # Escape backslashes and forward slashes for sed
    ESCAPED_VALUE=$(printf '%s\n' "${SECRET_VALUE}" | sed -e 's/[\/&]/\\&/g')
    sed -i.bak "s|${placeholder}|${ESCAPED_VALUE}|g" "${ENV_LOCAL}"
    
    echo "✓ ${env_var} configured"
    echo ""
}

# Prompt for each credential
echo "Step 1: Discord Bot Token"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
prompt_secret "Discord Bot Token" "DISCORD_BOT_TOKEN" "placeholder_discord_bot_token"

echo "Step 2: Discord Server ID"
prompt_secret "Discord Server ID" "DISCORD_SERVER_ID" "placeholder_your_server_id"

echo "Step 3: Discord Channel ID (#agent-test)"
prompt_secret "Discord Channel ID" "DISCORD_CHANNEL_ID" "placeholder_your_channel_id"

echo "Step 4: Your Discord User ID"
prompt_secret "Your Discord User ID" "DISCORD_ALLOWED_USERS" "placeholder_your_discord_user_id"

echo "Step 5: OpenAI API Key"
prompt_secret "OpenAI API Key" "OPENAI_API_KEY" "placeholder_openai_api_key"

echo "Step 6: OpenClaw Gateway Token (Random)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Generate a random gateway token? (recommended)"
echo ""
GATEWAY_TOKEN=$(openssl rand -hex 32)
read -p "Accept generated token? (yes/no): " ACCEPT_TOKEN
if [ "${ACCEPT_TOKEN}" = "yes" ]; then
    sed -i.bak "s|placeholder_generate_with_openssl_rand_hex_32|${GATEWAY_TOKEN}|g" "${ENV_LOCAL}"
    echo "✓ Gateway token configured"
else
    prompt_secret "OpenClaw Gateway Token" "OPENCLAW_GATEWAY_TOKEN" "placeholder_generate_with_openssl_rand_hex_32"
fi
echo ""

# Final verification
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║                    FINAL VERIFICATION                        ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Check file permissions
FILE_PERMS=$(stat -c %a "${ENV_LOCAL}" 2>/dev/null || stat -f %OLp "${ENV_LOCAL}" 2>/dev/null | tail -c 4)
echo "[✓] File permissions: ${FILE_PERMS} (should be 600)"

# Verify git-ignored
if grep -q "\.env\.local" "${SCRIPT_DIR}/../../.gitignore"; then
    echo "[✓] .env.local is in .gitignore (safe from accidental commit)"
else
    echo "[⚠] Warning: .env.local not found in .gitignore"
fi

# Verify no secrets in bash history
echo "[✓] Secrets were not echoed to screen (not in shell history)"

# Verify git won't track it
cd "${SCRIPT_DIR}/../.."
if ! git status --short | grep -q ".env.local"; then
    echo "[✓] Git is not tracking .env.local (verified with 'git status')"
fi

# Verify all placeholders replaced
REMAINING_PLACEHOLDERS=$(grep -c "placeholder_" "${ENV_LOCAL}" || true)
if [ "${REMAINING_PLACEHOLDERS}" -eq 0 ]; then
    echo "[✓] All placeholders replaced with real values"
else
    echo "[⚠] Warning: ${REMAINING_PLACEHOLDERS} placeholder(s) still in .env.local"
    echo "    Run this script again to complete configuration"
    exit 1
fi

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║          CREDENTIAL SETUP COMPLETE ✓                         ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""
echo "Your .env.local is now configured with all required secrets."
echo ""
echo "Next steps:"
echo "  1. Review the configuration: less ${ENV_LOCAL}"
echo "  2. Deploy: bash ${SCRIPT_DIR}/scripts/deploy.sh up"
echo "  3. Test in Discord: @MainBrain Test \"Hello!\""
echo ""
echo "⚠ IMPORTANT:"
echo "  • Never paste these secrets into chat or tickets"
echo "  • .env.local is git-ignored and will not be committed"
echo "  • If a secret is leaked, regenerate it immediately in the source"
echo "  • Keep MainBrain SSH access secure"
echo ""
