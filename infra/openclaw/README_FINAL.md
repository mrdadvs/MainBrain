# OpenClaw Discord Gateway - Reproducible Deployment for MainBrain

This is the reproducible, Git-tracked deployment configuration for OpenClaw on MainBrain, providing a private Discord bot for our AI agent pilot.

## Quick Start

```bash
cd ~/mainbrain

# 1. First time only: Create and securely enter credentials
bash infra/openclaw/scripts/setup-credentials.sh

# 2. Deploy the gateway
bash infra/openclaw/scripts/deploy.sh up

# 3. Verify it's working
docker exec openclaw-gateway openclaw channels status --probe

# 4. Send a test message in Discord #agent-test:
#    @MainBrain Test hello
```

## What's Deployed

- **Official Docker Image:** openclaw/openclaw:2026.11.1 (verified digest)
- **Gateway Port:** 127.0.0.1:18789 (localhost only, no public access)
- **Discord Bot:** Connected to MainBrain server, #agent-test channel only
- **AI Model:** OpenAI gpt-6-astra (chat-only, no tools)
- **Persistent State:** /home/mdv/mainbrain/data/openclaw/
- **Auto-restart:** Enabled (unless-stopped policy)

## Directory Structure

```
infra/openclaw/
├── docker-compose.yml              # Official deployment config
├── .env.example                    # Template (no real secrets)
├── .env.local                      # Secrets (git-ignored, created by setup)
├── discord-config.patch.template.json5  # Config template for Discord
├── discord-config.patch.json5      # Instantiated config (git-ignored)
├── setup-credentials.sh            # Interactive credential setup
├── scripts/
│   ├── deploy.sh                   # Main orchestration
│   ├── health-check.sh             # Gateway health verification
│   ├── logs.sh                     # View gateway logs
│   ├── backup-state.sh             # Backup persistent state
│   ├── restore-state.sh            # Restore from backup
│   └── rollback.sh                 # Rollback to previous state
├── init/
│   └── 00-create-directories.sh    # Pre-deployment setup
├── agents/                         # Agent instruction templates
│   └── main/
│       └── instructions.md         # Main agent instructions (chat-only)
└── docs/
    ├── DEPLOYMENT_VERIFIED.md      # Verification results
    ├── DEPLOYMENT_CHECKLIST.md     # Step-by-step checklist
    ├── DEPLOYMENT_TODAY.md         # Current status
    └── README_DEPLOYMENT.md        # Technical details
```

## Credential Files (Protected)

These files are **git-ignored** and must be created/managed securely:

```
infra/openclaw/.env.local
├── DISCORD_BOT_TOKEN           # Bot authentication (from Discord Developer Portal)
├── DISCORD_SERVER_ID           # MainBrain server ID
├── DISCORD_CHANNEL_ID          # #agent-test channel ID
├── DISCORD_ALLOWED_USERS       # Your Discord user ID (allowlist)
├── OPENCLAW_GATEWAY_TOKEN      # Generated for control access
└── OPENAI_API_KEY              # API key for model inference
```

## Setting Up Credentials

```bash
# Interactive setup (secure input, no bash history leakage)
bash infra/openclaw/scripts/setup-credentials.sh

# Or manually create .env.local with:
# DISCORD_BOT_TOKEN=<token>
# DISCORD_SERVER_ID=<ID>
# DISCORD_CHANNEL_ID=<ID>
# DISCORD_ALLOWED_USERS=<ID>
# OPENAI_API_KEY=<key>
# OPENCLAW_GATEWAY_TOKEN=<generated>

# Set strict permissions
chmod 600 infra/openclaw/.env.local
```

## Core Commands

```bash
# Deploy (start or recreate containers)
bash infra/openclaw/scripts/deploy.sh up

# Check status
docker exec openclaw-gateway openclaw channels status --probe

# View logs
docker compose -f infra/openclaw/docker-compose.yml logs -f openclaw-gateway

# Restart (if configuration changes)
bash infra/openclaw/scripts/deploy.sh restart

# Stop
bash infra/openclaw/scripts/deploy.sh down

# Backup state before major changes
bash infra/openclaw/scripts/backup-state.sh

# Restore from backup
bash infra/openclaw/scripts/restore-state.sh

# Full rollback to previous deployment
bash infra/openclaw/scripts/rollback.sh
```

## Configuration

### Discord Allowlist (Security)

Current configuration restricts access to:
- **Server:** MainBrain only (1568656073898987651)
- **Channel:** #agent-test only (1568656457929334944)
- **Users:** Your account only (1568655444321243136)
- **Interaction:** Mention-required (@MainBrain Test)
- **DMs:** Disabled (channel-only)

To modify, edit `infra/openclaw/discord-config.patch.template.json5` and reapply:

```bash
# Create instantiated config with your IDs
sed 's/{{ DISCORD_SERVER_ID }}/YOUR_SERVER_ID/g' \
    infra/openclaw/discord-config.patch.template.json5 > /tmp/patch.json5

# Apply to running gateway
docker cp /tmp/patch.json5 openclaw-gateway:/tmp/patch.json5
docker exec openclaw-gateway openclaw config patch --file /tmp/patch.json5

# Or restart to apply permanently
bash infra/openclaw/scripts/deploy.sh restart
```

### Agent Configuration

Edit `infra/openclaw/agents/main/instructions.md` to customize the agent's behavior:
- System prompt
- Capabilities description
- Conversation style
- Knowledge domain

Changes apply on next message (no restart needed).

### Model Selection

Change the default model in `docker-compose.yml` environment:

```yaml
environment:
  AGENT_CHAT_ONLY: "true"
  # Change this to any available model:
  # See: docker exec openclaw-gateway openclaw models list
```

Available models: gpt-6-astra (default), gpt-6.1-sol, gpt-5.6-luna, gpt-4o, etc.

## Security

### Protected by Design

- ✅ **No public inbound ports** - localhost-only (127.0.0.1:18789)
- ✅ **Allowlist enforcement** - only specified Discord user/server/channel
- ✅ **Chat-only mode** - no shell execution, file access, or tool plugins
- ✅ **Secrets in .env.local** - git-ignored, mode 600 (user-readable only)
- ✅ **Non-root execution** - container runs as UID 1000
- ✅ **Read-only root filesystem** - minimal attack surface
- ✅ **No Docker socket access** - container cannot access host Docker daemon
- ✅ **No privileged mode** - standard isolation

### Verified in Production

- ✅ No secrets in Git history (17+ commits audited)
- ✅ Bot token only in .env.local (protected)
- ✅ OpenAI key only in .env.local (protected)
- ✅ Configuration templates exclude credentials
- ✅ State directory not in .gitignore path (separates code from data)

## Troubleshooting

### Gateway won't start
```bash
# Check configuration validity
docker exec openclaw-gateway openclaw config validate

# Check logs for errors
docker compose -f infra/openclaw/docker-compose.yml logs openclaw-gateway | tail -50

# Check port availability
ss -tuln | grep 18789

# Verify credentials are loaded
docker exec openclaw-gateway env | grep DISCORD
```

### Discord bot not connected
```bash
# Check channel status with probe
docker exec openclaw-gateway openclaw channels status --probe

# Check Discord plugin logs
docker exec openclaw-gateway openclaw channels logs --channel discord

# Verify bot token format (should have 3 parts: NID.TIMESTAMP.HMAC)
grep DISCORD_BOT_TOKEN infra/openclaw/.env.local | cut -d= -f2 | tr '.' '\n' | wc -l
# Should output: 3
```

### No response to Discord messages
```bash
# Check allowlist configuration
docker exec openclaw-gateway cat /home/node/.openclaw/openclaw.json | \
  python3 -m json.tool | grep -A 20 "discord"

# Verify user ID matches
grep DISCORD_ALLOWED_USERS infra/openclaw/.env.local

# Check model availability
docker exec openclaw-gateway openclaw models status | grep gpt-6-astra

# Enable debug logging
docker exec openclaw-gateway openclaw config set logging.level debug
```

### Container crashes on startup
```bash
# Check for permission errors
docker exec openclaw-gateway ls -la /home/node/.openclaw/

# Verify state directory ownership on host
ls -la ~/mainbrain/data/openclaw/

# Fix permissions if needed
sudo chown -R 1000:1000 ~/mainbrain/data/openclaw/
chmod 755 ~/mainbrain/data/openclaw/
chmod 600 ~/mainbrain/data/openclaw/state/openclaw.json
```

## Backup and Restore

### Backup current state
```bash
bash infra/openclaw/scripts/backup-state.sh
# Saves to: data/openclaw/backups/openclaw-state-TIMESTAMP.tar.gz
```

### Restore from backup
```bash
bash infra/openclaw/scripts/restore-state.sh
# Prompts for backup file to restore
```

### Full rollback (if deployment breaks)
```bash
# Stop current deployment
bash infra/openclaw/scripts/deploy.sh down

# Restore state from backup
bash infra/openclaw/scripts/restore-state.sh

# Restart
bash infra/openclaw/scripts/deploy.sh up
```

## Next Phase: Expansion

This pilot is intentionally limited for safety and verification. When ready to expand:

### Adding More Agents
1. Create agent directory: `infra/openclaw/agents/librarian/`
2. Add instructions: `infra/openclaw/agents/librarian/instructions.md`
3. Configure separate tool permissions
4. Document in Git

### Adding VideoDB Integration
1. Create SafeMCP wrapper for VideoDB stdio server
2. Configure read-only permissions
3. Document security boundaries
4. Test in isolated channel first

### Adding Worker Queue
1. Configure connection to existing MainBrain worker infrastructure
2. Define job submission permissions
3. Implement result callback handling
4. Monitor in #agent-test before production use

### Adding GPU Processing
1. Set up secondary computer with GPU
2. Configure as OpenClaw worker node
3. Define resource limits and job routing
4. Test with pilot agent first

## Maintenance

### Monthly checks
```bash
# Verify gateway is healthy
docker exec openclaw-gateway openclaw channels status --probe

# Check disk usage
du -sh data/openclaw/

# Review logs for errors
docker compose -f infra/openclaw/docker-compose.yml logs openclaw-gateway | grep -i error

# Backup state
bash infra/openclaw/scripts/backup-state.sh
```

### Updates
```bash
# Check for new OpenClaw versions
docker pull openclaw/openclaw:latest

# Update version in docker-compose.yml
# Run full test cycle before deploying to production

# Commit version update
git add infra/openclaw/docker-compose.yml
git commit -m "Upgrade OpenClaw to version X.Y.Z"
```

## Architecture Decisions

**Why localhost-only?**
- Gateway not exposed to network, reducing attack surface
- SSH port forwarding or reverse proxy required for remote access
- Ensures Discord bot only accessible from MainBrain server

**Why allowlist over deny-list?**
- Explicit trust model (safer default)
- Easy to audit who has access
- Scales well as more users/channels added

**Why chat-only for pilot?**
- Reduced risk while learning OpenClaw's capabilities
- Safe to test before enabling tools/plugins
- Easier to add permissions than remove them

**Why Git-tracked infrastructure?**
- Reproducible deployments
- Clear history of configuration changes
- Easy to replicate on new hardware
- Audit trail for security

## Support and Documentation

- **OpenClaw Official Docs:** https://docs.openclaw.ai/
- **Discord.js Docs:** https://discord.js.org/
- **Docker Compose Docs:** https://docs.docker.com/compose/

## License and Attribution

This deployment configuration is part of the MainBrain project. OpenClaw is a third-party tool.

Deployment verified: 2026-11-08
Last updated: 2026-11-08
