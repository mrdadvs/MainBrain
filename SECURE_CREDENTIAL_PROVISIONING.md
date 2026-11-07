# Secure Credential Provisioning Guide

**Status:** Validation complete, ready for credential setup  
**Next Step:** User provides Discord bot token, OpenAI key, and Discord IDs  
**Security Model:** Secrets protected locally, never committed to Git

---

## Overview

This guide walks you through securely provisioning the three required secrets on MainBrain:
1. **Discord Bot Token** — Controls bot authentication to Discord
2. **OpenAI API Key** — Enables AI responses
3. **Discord IDs** — Server ID, channel ID, user ID for allowlisting

All secrets are stored in `.env.local` (git-ignored) and loaded by Docker at runtime.

---

## Required Credentials

### 1. Discord Bot Token

**Where to Get It:**
1. Go to https://discord.com/developers/applications
2. Click your "MainBrain Test" application
3. Navigate to **Bot** tab
4. Click **Reset Token** (or view existing token)
5. Copy the token (appears as `ODk4M...` format)

**Security Notes:**
- This token gives the bot full permissions on your Discord server
- If compromised, regenerate it immediately (you have the reset button)
- Never paste it in chat, logs, or commit it to Git
- Store only in `.env.local` on MainBrain

### 2. OpenAI API Key

**Where to Get It:**
1. Go to https://platform.openai.com/api-keys
2. Click **Create new secret key**
3. Copy the key (appears as `sk-proj-...` format)
4. Optionally name it "MainBrain Test"

**Security Notes:**
- This key authenticates requests to OpenAI and is billed against your account
- If compromised, delete it immediately from the API keys page
- Never paste it in chat, logs, or commit it to Git
- Store only in `.env.local` on MainBrain

**Cost Consideration:**
- Pilot testing: ~$0.10-0.50 per conversation (with gpt-3.5-turbo or gpt-4-turbo)
- Monitor usage at https://platform.openai.com/account/billing/overview

### 3. Discord IDs (Server, Channel, User)

**Where to Get Them:**

#### Server ID (MainBrain Server)
1. In Discord, right-click your "MainBrain" server name
2. Select **Copy Server ID**
3. Paste somewhere temporary (appears as a long number like `1234567890123456789`)

#### Channel ID (#agent-test)
1. Right-click the `#agent-test` text channel
2. Select **Copy Channel ID**
3. Paste somewhere temporary

#### Your User ID
1. Right-click your username in Discord
2. Select **Copy User ID**
3. Paste somewhere temporary

**Security Notes:**
- These IDs are not secrets (they're visible on Discord)
- They restrict bot access to only your server, channel, and user ID
- These are allowlist controls for security

---

## Setup on MainBrain

### Step 1: SSH into MainBrain

```bash
# From your laptop/phone
ssh mdv@mainbrain

# You should be in /home/mdv/mainbrain
cd /home/mdv/mainbrain
```

### Step 2: Create `.env.local` with Your Secrets

```bash
# Copy the template
cp infra/openclaw/.env.example infra/openclaw/.env.local

# Edit with your real secrets (use nano, vim, or your editor)
nano infra/openclaw/.env.local
```

### Step 3: Replace Placeholders

Inside `.env.local`, replace these placeholders with your actual values:

```env
# Line ~8: Replace with your Discord bot token
DISCORD_BOT_TOKEN=your_actual_discord_bot_token_here

# Line ~18-20: Replace with your Discord IDs
DISCORD_SERVER_ID=your_server_id_number
DISCORD_CHANNEL_ID=your_channel_id_number
DISCORD_ALLOWED_USERS=your_user_id_number

# Line ~28: Replace with your OpenAI API key
OPENAI_API_KEY=sk-proj-your_actual_openai_key_here

# Line ~32: Generate a random gateway token (or leave the placeholder)
OPENCLAW_GATEWAY_TOKEN=placeholder_generate_with_openssl_rand_hex_32
```

**To Generate a Random Gateway Token:**
```bash
openssl rand -hex 32
# Output: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6a7b8c9
# Copy this into OPENCLAW_GATEWAY_TOKEN=
```

### Step 4: Verify `.env.local` is Protected

```bash
# Confirm .env.local is in .gitignore
grep ".env.local" /home/mdv/mainbrain/.gitignore
# Should show: .env.local ✓

# Verify Git won't track it
cd /home/mdv/mainbrain
git status
# Should NOT show infra/openclaw/.env.local

# Verify file permissions (read-only to you, not world-readable)
ls -la infra/openclaw/.env.local
# Should show: -rw-r--r-- (or more restrictive)
```

### Step 5: Test Configuration

```bash
# Verify Docker can read the .env file
cd /home/mdv/mainbrain/infra/openclaw
docker compose config --quiet 2>&1 | head -3
# Should output valid YAML with no errors (only ignore version deprecation warning)
```

---

## Deploy and Test

### Step 1: Create Required Directories

```bash
cd /home/mdv/mainbrain/infra/openclaw
bash init/00-create-directories.sh
# Creates data/openclaw/{state,workspace,backups}
```

### Step 2: Deploy Gateway

```bash
bash scripts/deploy.sh up
# Pulls image, creates network, starts containers
# Wait for "✓ Gateway health check passed" message
```

### Step 3: Verify Gateway is Running

```bash
# Check container status
docker ps | grep openclaw
# Should show: openclaw-gateway, HEALTHY status

# Check gateway is accessible locally
curl -I http://127.0.0.1:18789/health
# Should show: HTTP 200

# View logs
bash scripts/logs.sh
# Should show no errors, "Gateway started" message
```

### Step 4: Test Discord Bot (First Message)

**On your Discord server (#agent-test channel):**

```
@MainBrain Test What is 2+2?
```

**Expected Response:**
- Bot replies with something like: "2 + 2 = 4"
- Reply appears within 5-10 seconds
- Message comes from your bot account ("MainBrain Test")

**If no response:**
1. Check bot has "Message Content Intent" enabled (Discord Developer Portal → Bot → toggle on)
2. Check bot has Send Messages permission on #agent-test channel
3. View gateway logs: `bash scripts/logs.sh`
4. Verify DISCORD_BOT_TOKEN in .env.local is correct (copy-paste carefully)

### Step 5: Test Discord Bot (Second Message)

**Send a different message:**

```
@MainBrain Test Tell me a short joke.
```

**Expected Response:**
- Bot replies with a joke
- Different content than first message (not cached)
- Reply appears within 5-10 seconds

**If this works, gateway is functioning correctly.**

---

## Container Restart Test

### Step 1: Verify Current State

```bash
# Send a test message and note the bot's reply
# In Discord: @MainBrain Test Say "hello world"
# Bot should reply: "hello world"
```

### Step 2: Restart Container

```bash
cd /home/mdv/mainbrain/infra/openclaw

# Stop containers
docker compose stop

# Wait 5 seconds
sleep 5

# Start containers again
docker compose up -d

# Wait for health check to pass
sleep 10
bash scripts/health-check.sh
```

### Step 3: Verify Configuration Persisted

```bash
# Send same test message again
# In Discord: @MainBrain Test Say "hello world"

# Expected: Bot still replies with "hello world"
# Configuration is preserved after container restart ✓
```

---

## SSH Disconnection Test

### Prerequisites
- Container running and tested (previous steps complete)
- Phone with Discord app and cellular data (not WiFi on MainBrain)

### Step 1: Start Long-Running Test

```bash
# On MainBrain over SSH:
cd /home/mdv/mainbrain/infra/openclaw
bash scripts/logs.sh --follow
# Leaves logs running to observe messages
```

### Step 2: Disconnect SSH

On your phone:
1. Open Discord app (with cellular data, VPN off)
2. Go to MainBrain server, #agent-test channel
3. Send: `@MainBrain Test Say "testing after disconnect"`
4. Expected: Bot replies within 5-10 seconds

### Step 3: Verify with SSH Closed

Without re-opening SSH, verify:
- Bot replied to the message
- Reply appeared in #agent-test
- Timestamp shows it was sent after SSH disconnection

This confirms the gateway service survives SSH session closure.

---

## Backup and Rollback Verification

### Backup Test

```bash
cd /home/mdv/mainbrain/infra/openclaw

# Create a backup
bash scripts/backup-state.sh

# Verify backup created
ls -lh data/openclaw/backups/
# Should show: openclaw-state-2026-11-07-17-30-00.tar.gz (example)
```

### Restore Test

```bash
# Create a test file in workspace
echo "test content" > data/openclaw/workspace/test.txt

# Verify it exists
ls -la data/openclaw/workspace/test.txt

# Stop gateway
docker compose stop openclaw-gateway

# Restore from backup
bash scripts/restore-state.sh
# Select the most recent backup from the menu

# Start gateway
docker compose up -d openclaw-gateway

# Verify restore (test.txt should be gone if restored from before)
ls data/openclaw/workspace/test.txt 2>&1
# Should show: "No such file or directory" ✓
```

---

## Rollback Procedure

If you need to rollback to a previous version:

```bash
cd /home/mdv/mainbrain/infra/openclaw

# Interactive rollback menu
bash scripts/rollback.sh
# Follow on-screen prompts to select previous backup and version
```

---

## Troubleshooting

### Bot Doesn't Reply

**Checklist:**
1. ✓ Gateway health check passes: `bash scripts/health-check.sh`
2. ✓ Discord bot token is correct in `.env.local`
3. ✓ Bot has "Message Content Intent" enabled (Discord Developer Portal)
4. ✓ Bot has "Send Messages" permission on #agent-test channel
5. ✓ You're using the correct format: `@MainBrain Test <message>`
6. ✓ OpenAI API key is correct in `.env.local`
7. ✓ OpenAI account has available credits

**Debug Steps:**
```bash
# View full gateway logs
bash scripts/logs.sh | tail -50

# Look for error messages about:
# - Discord authentication
# - OpenAI API errors
# - Permission issues

# Test gateway directly (localhost only)
curl http://127.0.0.1:18789/api/v1/status
# Should return JSON with gateway status
```

### Container Won't Start

```bash
# Check error messages
docker compose up openclaw-gateway 2>&1 | tail -20

# Common causes:
# - Wrong .env.local location (must be in infra/openclaw/)
# - Missing environment variables
# - Port 18789 already in use
```

**Port Check:**
```bash
# See if something else is using port 18789
lsof -i :18789
# If shown, stop that service first
```

### State Not Persisting

```bash
# Verify volumes are mounted
docker inspect openclaw-gateway --format='{{json .Mounts}}' | jq .

# Should show three mounts:
# 1. OPENCLAW_STATE_DIR → /home/node/.openclaw
# 2. OPENCLAW_WORKSPACE_DIR → /home/node/.openclaw/workspace
# 3. Auth profile secrets → /home/node/.config/openclaw

# Verify directory permissions
ls -la data/openclaw/state/
# Should be readable/writable by current user
```

---

## Security Checklist Before Production

Before treating this as production-ready:

- [ ] `.env.local` exists in `infra/openclaw/` (not in root)
- [ ] `.env.local` is in `.gitignore` (verify: `git status`)
- [ ] Discord bot token is fresh (not leaked anywhere)
- [ ] OpenAI API key has spending limits set (check billing page)
- [ ] Gateway token is randomly generated (not placeholder)
- [ ] Discord server ID, channel ID, user ID are correct allowlist
- [ ] Container runs as non-root user
- [ ] No Docker socket or privileged access
- [ ] Gateway only accessible on localhost (127.0.0.1:18789)
- [ ] Backup and restore scripts tested and working
- [ ] Container survives restart and SSH disconnection

---

## Next Steps

1. **Credential Provisioning:** Follow this guide to supply Discord token, OpenAI key, and IDs
2. **Deployment:** Run `bash scripts/deploy.sh up`
3. **Testing:** Verify two Discord replies, container restart, and SSH disconnection
4. **Backup/Restore:** Execute and verify backup and restore procedures
5. **Documentation:** Once validated, credentials remain in `.env.local` only

**Success Criteria:**
- ✓ Discord bot replies to two distinct messages
- ✓ Container restart preserves configuration
- ✓ Service available after SSH disconnection
- ✓ Backup and restore procedures work

Once all tests pass, the pilot deployment is complete and ready for future expansion.

---

## Important Reminders

- **Never paste secrets into chat or tickets** — Keep them local only
- **Never commit `.env.local` to Git** — It's git-ignored for safety
- **Regenerate Discord token if it leaks** — Use Discord Developer Portal reset button
- **Monitor OpenAI billing** — Set spending alerts at https://platform.openai.com/account/billing/limits
- **Keep MainBrain SSH secure** — Only you should have access to MainBrain
- **Backup before testing** — Always create a backup before major changes

---

**Status:** Ready for credential provisioning  
**Success Threshold:** Two distinct Discord replies + container persistence tests  
**Estimated Time:** 15 minutes for setup, 5-10 minutes for testing
