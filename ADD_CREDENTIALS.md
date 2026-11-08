# 🔐 Adding Your Real Credentials to .env.local

**IMPORTANT**: Never commit .env.local to Git. It's already in .gitignore.

## Option 1: Manual Edit (Fastest for Testing)

On MainBrain, create/edit `.env.local` directly:

```bash
cat > ~/mainbrain/infra/openclaw/.env.local << 'EOF'
# Copy this entire block, replace placeholders with YOUR real values

# ============================================================================
# Docker Image Configuration (leave as-is)
# ============================================================================
OPENCLAW_IMAGE=openclaw/openclaw:2026.11.1
OPENCLAW_CONFIG_DIR=/home/mdv/mainbrain/data/openclaw/state
OPENCLAW_WORKSPACE_DIR=/home/mdv/mainbrain/data/openclaw/workspace
OPENCLAW_AUTH_PROFILE_SECRET_DIR=/home/mdv/mainbrain/data/openclaw/secrets

# Generate this with: openssl rand -hex 32
OPENCLAW_GATEWAY_TOKEN=YOUR_GENERATED_GATEWAY_TOKEN_HERE_64_HEX_CHARACTERS

OPENCLAW_GATEWAY_PORT=18789
OPENCLAW_TZ=UTC

# ============================================================================
# DISCORD - Replace with YOUR actual values
# ============================================================================
# Your bot token from Discord Developer Portal
DISCORD_BOT_TOKEN=YOUR_ACTUAL_DISCORD_BOT_TOKEN_HERE

# Your MainBrain server ID
DISCORD_SERVER_ID=YOUR_MAINBRAIN_SERVER_ID_HERE

# Your #agent-test channel ID
DISCORD_CHANNEL_ID=YOUR_AGENT_TEST_CHANNEL_ID_HERE

# Your Discord user ID (so only you can trigger the bot)
DISCORD_ALLOWED_USERS=YOUR_DISCORD_USER_ID_HERE

# Require the bot to be mentioned (recommended for safety)
DISCORD_REQUIRE_MENTION=true

# ============================================================================
# OPENAI - Replace with YOUR actual key
# ============================================================================
# Your OpenAI API key from https://platform.openai.com/api-keys
OPENAI_API_KEY=YOUR_ACTUAL_OPENAI_API_KEY_HERE

OPENAI_BASE_URL=https://api.openai.com/v1

# ============================================================================
# Agent Behavior (leave as-is for pilot testing)
# ============================================================================
AGENT_CHAT_ONLY=true
AGENT_DISABLE_SKILLS=true
LOG_LEVEL=info

# ============================================================================
# Backup Configuration
# ============================================================================
BACKUP_INTERVAL_HOURS=24
MAX_BACKUPS=10
DEBUG_MODE=false
EOF

chmod 600 ~/mainbrain/infra/openclaw/.env.local
echo "✓ .env.local created with mode 600"
```

## How to Get Each Value

### 1. DISCORD_BOT_TOKEN
- Go to https://discord.com/developers/applications
- Select "MainBrain Test" application
- Click "Bot" in left sidebar
- Click "Reset Token" (if needed) or copy existing token
- Paste into `DISCORD_BOT_TOKEN=` (starts with "MTA..." or similar)

### 2. DISCORD_SERVER_ID
- In Discord, right-click on "MainBrain" server name
- Select "Copy Server ID"
- Paste into `DISCORD_SERVER_ID=`

### 3. DISCORD_CHANNEL_ID
- In Discord, right-click on "#agent-test" channel
- Select "Copy Channel ID"
- Paste into `DISCORD_CHANNEL_ID=`

### 4. DISCORD_ALLOWED_USERS (your user ID)
- In Discord, right-click your username
- Select "Copy User ID"
- Paste into `DISCORD_ALLOWED_USERS=`

### 5. OPENAI_API_KEY
- Go to https://platform.openai.com/api-keys
- Click "Create new secret key"
- Copy the key (starts with "sk-proj-" or "sk-")
- Paste into `OPENAI_API_KEY=`

### 6. OPENCLAW_GATEWAY_TOKEN (generate locally)
- Run this on MainBrain:
  ```bash
  openssl rand -hex 32
  ```
- Copy the output (64 hex characters)
- Paste into `OPENCLAW_GATEWAY_TOKEN=`

## Verify Before Deploying

After editing `.env.local`:

```bash
# 1. Check file was created with correct permissions
ls -la ~/mainbrain/infra/openclaw/.env.local
# Should show: -rw------- (600)

# 2. Verify it's git-ignored
cd ~/mainbrain
git status | grep .env.local
# Should show nothing (file is ignored)

# 3. Test the configuration
cd ~/mainbrain
source infra/openclaw/.env.local
bash infra/openclaw/scripts/deploy.sh config
# Should output: [✓] Configuration valid

# 4. Deploy
bash infra/openclaw/scripts/deploy.sh up
```

## ⚠️ Security Checklist

Before deploying:
- [ ] .env.local is NOT in Git (verify with `git status`)
- [ ] .env.local has permissions 600 (user-readable only)
- [ ] All tokens are real (not placeholder text)
- [ ] DISCORD_BOT_TOKEN starts with real Discord token
- [ ] OPENAI_API_KEY starts with "sk-proj-" or "sk-"
- [ ] DISCORD_SERVER_ID and CHANNEL_ID are numeric
- [ ] OPENCLAW_GATEWAY_TOKEN is 64 hex characters

## If You Make Mistakes

If you put wrong values in .env.local:

1. Edit the file again:
   ```bash
   nano ~/mainbrain/infra/openclaw/.env.local
   ```

2. Stop the container:
   ```bash
   docker compose -f ~/mainbrain/infra/openclaw/docker-compose.yml down
   ```

3. Update .env.local with correct values

4. Deploy again:
   ```bash
   bash ~/mainbrain/infra/openclaw/scripts/deploy.sh up
   ```

## Testing

Once deployed:

```bash
# 1. Check container is running
docker compose -f ~/mainbrain/infra/openclaw/docker-compose.yml ps

# 2. View logs
bash ~/mainbrain/infra/openclaw/scripts/logs.sh

# 3. In Discord #agent-test, send:
@MainBrain Test What is 2 + 2?

# Bot should reply within 5-10 seconds
```

That's it! 🚀
