# OpenClaw MainBrain Deployment Guide

**Status**: Ready for pilot deployment  
**Version**: 1.0 (Pilot: Single Discord test agent)  
**Pinned Image**: ghcr.io/sunwood-ai-oss-hub/agentos-openclaw-base:v0.2.1  
**Last Updated**: 2026-11-07

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture](#architecture)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Deployment](#deployment)
6. [Testing](#testing)
7. [Maintenance](#maintenance)
8. [Troubleshooting](#troubleshooting)
9. [Future Expansion](#future-expansion)

---

## Quick Start

### Prerequisites

- Docker Engine 20.10+ and Docker Compose v2+
- Linux host (MainBrain)
- Discord Server with bot created (see [Discord Setup](#discord-setup))
- OpenAI API key (see [API Keys](#api-keys))
- ~2GB free disk space for state directory
- Network access to Discord and OpenAI APIs

### Installation (5 minutes)

```bash
cd /home/mdv/mainbrain/infra/openclaw

# 1. Initialize directories and config
bash init/00-create-directories.sh

# 2. Create secrets configuration
cp .env.example .env.local
# Edit .env.local with your Discord token and OpenAI key
# nano .env.local

# 3. Deploy
bash scripts/deploy.sh up

# 4. Verify
bash scripts/health-check.sh
```

### Test (2 messages)

Send in Discord #agent-test:
- Message 1: `@MainBrain Test hello` → Bot replies
- Message 2: `@MainBrain Test what is your role?` → Bot explains

**If both succeed, you're ready for the full test suite.**

---

## Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│  MainBrain Server (192.168.1.50)                                 │
├──────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Docker Container: openclaw-gateway                         │ │
│  ├─────────────────────────────────────────────────────────────┤ │
│  │                                                               │ │
│  │  ┌──────────────────────────────────────────────────────┐  │ │
│  │  │  OpenClaw Node.js Application                        │  │ │
│  │  │  - Discord bot client                                │  │ │
│  │  │  - Message handling                                  │  │ │
│  │  │  - AI model interaction                              │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  │           ▲                        ▼                         │ │
│  │        Configuration          Persistent State              │ │
│  │     (/home/node/.openclaw)   (/home/node/.openclaw)         │ │
│  │                                                               │ │
│  └─────────────────────────────────────────────────────────────┘ │
│           ▲                                    ▼                  │
│           │                                    │                  │
│     .env.local (secrets)         data/openclaw/state              │
│     Discord Bot Token            - config/                        │
│     OpenAI API Key               - workspace/                     │
│                                  - logs/                          │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  Networking (Local Access Only)                              │ │
│  ├──────────────────────────────────────────────────────────────┤ │
│  │                                                                │ │
│  │  Gateway Dashboard: http://127.0.0.1:8080                    │ │
│  │  (localhost only - no external access)                        │ │
│  │                                                                │ │
│  │  Outbound:                                                    │ │
│  │  ✓ Discord API (wss://gateway.discord.gg)                    │ │
│  │  ✓ OpenAI API (api.openai.com)                               │ │
│  │                                                                │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                    │
└──────────────────────────────────────────────────────────────────┘
```

### Data Persistence

All runtime state survives container replacement and reboot:

```
/home/mdv/mainbrain/data/openclaw/
├── state/                      # Configuration and cache
│   ├── config/                 # OpenClaw config (models.json, etc.)
│   ├── cache/                  # Application cache
│   └── logs/                   # Application logs
├── workspace/                  # Agent workspace
│   └── [chat history, temp files]
└── backups/                    # Automatic backups
    └── openclaw-backup-*.tar.gz
```

**Key Design**: Directories are **mounted as volumes**, not individual files. This allows seamless updates and configuration changes.

---

## Installation

### Step 1: Prerequisites Check

```bash
# Docker and Compose installed?
docker --version
docker compose version

# Internet connectivity
curl -I https://api.discord.com

# Disk space available?
df -h /home/mdv/mainbrain/data/
```

### Step 2: Discord Setup

Create a Discord server and bot:

1. Go to https://discord.com/developers/applications
2. Click "New Application" → Name: "MainBrain Test"
3. Left sidebar → "Bot" → "Add Bot"
4. Copy bot token (keep secret)
5. Permissions:
   - ✓ Send Messages
   - ✓ Read Messages/View Channels
   - ✓ Read Message History
6. Scopes: `bot`
7. OAuth2 URL (with permissions):
   ```
   https://discord.com/api/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=3072&scope=bot
   ```
   Follow link to invite bot to your MainBrain server
8. Create channel: `#agent-test`
9. Give bot permission to post there

**Note**: You'll provide the bot token securely when configuring .env.local

### Step 3: Prepare OpenClaw

```bash
cd /home/mdv/mainbrain/infra/openclaw

# Initialize directories (creates persistent state structure)
bash init/00-create-directories.sh

# Check output:
# ✓ [✓] Directory initialization complete!
```

### Step 4: Configure Secrets

```bash
# Create local secrets file (excluded from Git)
cp .env.example .env.local

# Generate a gateway token (run this command):
openssl rand -hex 32
# Output example: 7a3f9c2b1e5d8a4f6c9e2b1a8d3f5c7e9a2b4d6f8c1a3e5d7f9b1c3e5f7a9b

# Edit configuration with your actual secrets
nano infra/openclaw/.env.local
```

**In .env.local, replace these placeholders**:

```bash
# Paste the gateway token output above
OPENCLAW_GATEWAY_TOKEN=7a3f9c2b1e5d8a4f6c9e2b1a8d3f5c7e9a2b4d6f8c1a3e5d7f9b1c3e5f7a9b

# From Discord developer portal
DISCORD_BOT_TOKEN=MzYzNTA4MzM4NTM3NjM0MzA0.D...

# Your Discord user ID (right-click your username in Discord → Copy User ID)
DISCORD_ALLOWED_USERS=YOUR_NUMERIC_ID_HERE

# Your Discord server ID (right-click server name → Copy Server ID)
DISCORD_SERVER_ID=YOUR_SERVER_ID_HERE

# Your Discord channel ID (right-click #agent-test → Copy Channel ID)
DISCORD_CHANNEL_ID=YOUR_CHANNEL_ID_HERE

# From https://platform.openai.com/api-keys
OPENAI_API_KEY=sk-proj-...
```

**Security**: `.env.local` is in `.gitignore` - it will never be committed to Git.

---

## Configuration

### Environment Variables (Reference)

See `.env.example` for complete list. Key variables:

| Variable | Purpose | Required | Example |
|----------|---------|----------|---------|
| `OPENCLAW_GATEWAY_TOKEN` | Gateway security token | Yes | Random hex 32 |
| `DISCORD_BOT_TOKEN` | Discord bot authentication | Yes | MzYzNTA4... |
| `OPENAI_API_KEY` | OpenAI API access | Yes | sk-proj-... |
| `DISCORD_ALLOWED_USERS` | User ID allowlist | Yes | 123456789 |
| `DISCORD_SERVER_ID` | Server ID whitelist | Yes | 987654321 |
| `DISCORD_CHANNEL_ID` | Channel ID | Yes | 111111111 |
| `DISCORD_REQUIRE_MENTION` | Require @mention | No | true |
| `AGENT_CHAT_ONLY` | Disable file operations | No | true |
| `AGENT_DISABLE_SKILLS` | Disable plugins | No | true |
| `LOG_LEVEL` | Logging verbosity | No | info |

### Model Configuration

Models are configured in `data/openclaw/state/config/models.json` (created automatically).

To add models after deployment:

```json
{
  "models": [
    {
      "id": "openai-gpt4",
      "name": "GPT-4 Turbo",
      "provider": "openai",
      "model": "gpt-4-turbo",
      "enabled": true,
      "temperature": 0.7
    },
    {
      "id": "openai-gpt35",
      "name": "GPT-3.5 Turbo",
      "provider": "openai",
      "model": "gpt-3.5-turbo",
      "enabled": false
    }
  ]
}
```

---

## Deployment

### Deploy to Production

```bash
cd /home/mdv/mainbrain/infra/openclaw

# Start the gateway (pulls latest image, creates container)
bash scripts/deploy.sh up

# Monitor startup (watch logs in real-time)
bash scripts/logs.sh follow
# Press Ctrl+C to stop watching

# Verify health
bash scripts/health-check.sh
```

### Expected Output

```
[*] Starting OpenClaw gateway...
...
[✓] Deployment complete!

Gateway available at: http://127.0.0.1:8080
```

### Check Status Anytime

```bash
bash scripts/deploy.sh status
```

### Stop (if needed)

```bash
bash scripts/deploy.sh down
```

---

## Testing

### Test 1: Verify Container Running

```bash
docker ps | grep openclaw-gateway
# Should show: openclaw-gateway ... Up (healthy)
```

### Test 2: Verify Gateway Port

```bash
curl -I http://127.0.0.1:8080/health
# Should return: HTTP 200
```

### Test 3: Send Discord Messages

1. Open Discord → MainBrain server → #agent-test channel
2. Send: `@MainBrain Test hello`
3. **Expected**: Bot replies with greeting (within 10 seconds)

**Message 1 Test Passed**: _____ (YES/NO)

4. Send: `@MainBrain Test what is your purpose?`
5. **Expected**: Bot describes its test role

**Message 2 Test Passed**: _____ (YES/NO)

### Test 4: Offline Resilience

1. Close Discord desktop app / put phone in airplane mode
2. Wait 3 minutes
3. Reconnect (desktop app open / airplane mode off)
4. Send: `@MainBrain Test reconnected?`
5. **Expected**: Bot responds normally

**Offline Resilience Passed**: _____ (YES/NO)

### Test 5: Container Restart

```bash
# Restart container
docker compose -f infra/openclaw/docker-compose.yml restart openclaw-gateway

# Wait 10 seconds
sleep 10

# Send Discord message: @MainBrain Test still running after restart?
# Expected: Bot responds
```

**Restart Resilience Passed**: _____ (YES/NO)

### Test 6: Windows Disconnect + SSH Close

1. Ensure gateway is running: `bash scripts/deploy.sh status`
2. Log out of Windows (or lock screen)
3. SSH to MainBrain: `ssh mdv@192.168.1.50`
4. Close SSH connection: `exit`
5. Send Discord message from phone (3+ minutes later)
6. **Expected**: Bot still responds even though Windows is logged out and SSH closed

**Long-term Resilience Passed**: _____ (YES/NO)

---

## Maintenance

### Regular Tasks

#### Daily
- Monitor: `docker stats openclaw-gateway --no-stream` (check memory/CPU)
- Logs: `bash scripts/logs.sh tail 50` (check for errors)

#### Weekly
- Backup state: `bash scripts/backup-state.sh`
- Check disk: `du -sh data/openclaw/`

#### Monthly
- Review logs for errors/warnings
- Update Docker images: `docker pull ghcr.io/sunwood-ai-oss-hub/agentos-openclaw-base:v0.2.1`
- Test restore: `bash scripts/restore-state.sh <backup-file>`

### Backup & Restore

**Automatic backups** are created before every state change.

**Manual backup**:

```bash
bash scripts/backup-state.sh
# Output: Backup created: /home/mdv/mainbrain/data/openclaw/backups/openclaw-backup-20261107_162250.tar.gz
```

**Restore**:

```bash
bash scripts/restore-state.sh /home/mdv/mainbrain/data/openclaw/backups/openclaw-backup-20261107_162250.tar.gz
# Follow prompts (you'll be asked to confirm before overwriting)
```

### Rollback Procedure (Tested)

If something breaks:

```bash
# Option 1: Just restart container (cleans runtime state)
docker compose restart openclaw-gateway

# Option 2: Restore from backup
bash scripts/rollback.sh
# Follow menu (choose option 2 to restore from backup)

# Option 3: Both
bash scripts/rollback.sh
# Choose option 3
```

**Important**: The rollback script will:
1. Create a safety backup first
2. Restore your chosen backup
3. Restart the container
4. Verify health check

---

## Troubleshooting

### Bot Not Responding

**Issue**: Send message but bot doesn't reply

**Diagnostic**:
```bash
# 1. Check container running
docker ps | grep openclaw-gateway

# 2. Check logs
bash scripts/logs.sh tail 50

# 3. Check Discord intents
# Discord app may require message content intent enabled
# https://discord.com/developers/applications → Your App → Bot → MESSAGE CONTENT INTENT

# 4. Check bot has permissions in channel
# Discord server → #agent-test → Right-click → Permissions → MainBrain Test bot
# Should have: Send Messages, Read Messages
```

**Solution**:
1. Ensure bot is in the channel
2. Ensure @mention requirement is met (DISCORD_REQUIRE_MENTION setting)
3. Restart container: `docker compose restart openclaw-gateway`

### Gateway Port Conflict

**Issue**: Error "Address already in use"

**Diagnostic**:
```bash
netstat -tuln | grep 8080
# Should NOT show 127.0.0.1:8080 in use
```

**Solution**:
```bash
# Find process using port 8080
lsof -i :8080

# Kill it if it's not openclaw-gateway (note the PID)
kill <PID>

# Retry deployment
bash scripts/deploy.sh up
```

### High Memory Usage

**Issue**: Container memory keeps growing

**Diagnostic**:
```bash
docker stats openclaw-gateway --no-stream
# Memory > 1GB is concerning
```

**Solution**:
1. Check log file size: `du -sh data/openclaw/state/logs/`
2. Clear old logs: `rm -f data/openclaw/state/logs/*.log.old`
3. Restart: `docker compose restart openclaw-gateway`
4. Monitor: `docker stats openclaw-gateway`

### API Key Invalid

**Issue**: Logs show "Unauthorized" or "Invalid API key"

**Diagnostic**:
```bash
# Check key is set
grep "OPENAI_API_KEY" infra/openclaw/.env.local
# Should NOT show "placeholder_openai_api_key"
```

**Solution**:
1. Verify key at https://platform.openai.com/api-keys (has quota?)
2. Update .env.local with new key
3. Restart: `bash scripts/deploy.sh restart`

### DNS Resolution Fails

**Issue**: Logs show "Failed to resolve host"

**Diagnostic**:
```bash
# Check internet from container
docker exec openclaw-gateway cat /etc/resolv.conf

# Test DNS
docker exec openclaw-gateway nslookup api.openai.com
```

**Solution**:
1. Check host internet: `curl https://api.openai.com`
2. Check Docker daemon: `docker info | grep -i "error"`
3. Restart Docker: `sudo systemctl restart docker`

---

## Future Expansion

### Phase 1: Librarian Agent

**Purpose**: Index and search MainBrain's knowledge base

**When Ready**:
- Discord test agent stable for 2+ weeks
- Knowledge base indexed
- Read-only access proven safe

**Implementation**:
1. Create `agents/librarian/instructions.md`
2. Add Librarian container to docker-compose.yml
3. Mount `data/indexed/` as read-only
4. Add search commands to agent

**Example**: 
```
User: @Librarian search for "video effects"
Librarian: Found 12 references to "video effects" in your indexed content...
```

### Phase 2: Director Agent

**Purpose**: Submit and monitor video processing jobs

**When Ready**:
- Librarian agent proven stable
- Worker queue API authenticated
- Job submission rate limits set

**Implementation**:
1. Connect to MainBrain worker queue API
2. Validate job parameters
3. Return job IDs for status tracking
4. Retrieve results when complete

**Example**:
```
User: @Director analyze this video for scene changes
Director: Submitted job #5821. Check status: @Director status 5821
```

### Phase 3: Animator Agent

**Purpose**: Create and modify animations

**When Ready**:
- Director agent proven stable
- Rendering infrastructure scaling tested
- Output validation in place

**Implementation**:
1. Extend worker queue to animation tasks
2. Store results in `data/animations/`
3. Generate thumbnails for Discord preview
4. Rate-limit rendering to prevent resource exhaustion

---

## Deployment Checklist

Before considering the installation complete:

- [ ] Docker and Docker Compose installed
- [ ] Discord server and bot created
- [ ] OpenAI API key acquired
- [ ] Directories initialized: `bash init/00-create-directories.sh`
- [ ] Secrets configured: `.env.local` with actual tokens
- [ ] Gateway deployed: `bash scripts/deploy.sh up`
- [ ] Health check passing: `bash scripts/health-check.sh`
- [ ] Test message 1 works: Bot replies to `@MainBrain Test hello`
- [ ] Test message 2 works: Bot replies to second distinct message
- [ ] Offline resilience tested: Phone on cellular data, VPN off
- [ ] Container restart tested: Bot works after restart
- [ ] SSH disconnect tested: Bot available after closing SSH
- [ ] Backup tested: `bash scripts/backup-state.sh` creates archive
- [ ] Restore tested: `bash scripts/restore-state.sh <backup>` works
- [ ] Rollback procedure documented and reviewed

**Final Status**: Ready for production ✓

---

## Support & Documentation

- **Agent Permissions**: See [agents/README.md](agents/README.md)
- **Security & Secrets**: See [SECURITY.md](SECURITY.md)
- **Monitoring & Debugging**: See [HEALTH.md](HEALTH.md)
- **Rollback Procedures**: See [ROLLBACK.md](ROLLBACK.md)

---

**Version History**:
- v1.0 (2026-11-07): Initial Pilot Deployment
- Future: v1.1 (Librarian phase), v1.2 (Director phase), etc.
