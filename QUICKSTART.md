# OpenClaw MainBrain - Quick Start Reference

**Status**: ✅ Ready to Deploy  
**Next Step**: Provide Discord token & OpenAI API key

---

## Pre-Deployment Checklist

### 1. Gather Credentials (5 min)

- [ ] Discord bot token: https://discord.com/developers/applications
- [ ] OpenAI API key: https://platform.openai.com/api-keys
- [ ] Your Discord user ID: Right-click username → Copy User ID
- [ ] MainBrain server ID: Right-click server name → Copy Server ID
- [ ] #agent-test channel ID: Right-click channel → Copy Channel ID

### 2. Configure Secrets (5 min)

```bash
cd /home/mdv/mainbrain/infra/openclaw

# Copy template
cp .env.example .env.local

# Generate gateway token
openssl rand -hex 32  # Copy output below

# Edit configuration
nano .env.local
```

Replace placeholders with your actual values:
```env
OPENCLAW_GATEWAY_TOKEN=<paste openssl output>
DISCORD_BOT_TOKEN=<your discord bot token>
DISCORD_ALLOWED_USERS=<your discord user id>
DISCORD_SERVER_ID=<mainbrain server id>
DISCORD_CHANNEL_ID=<#agent-test channel id>
OPENAI_API_KEY=<your openai api key>
```

---

## Deployment (5 min)

```bash
cd /home/mdv/mainbrain/infra/openclaw

# Deploy
bash scripts/deploy.sh up

# Verify health
bash scripts/health-check.sh
# Output should be: ✓ HEALTHY

# View logs
bash scripts/logs.sh tail 50
```

---

## Test (10 min)

### Test A: Message 1
1. Discord: `@MainBrain Test hello`
2. Expected: Bot replies with greeting
3. **Result**: _____ (PASS/FAIL)

### Test B: Message 2
1. Discord: `@MainBrain Test what is your role?`
2. Expected: Bot explains it's a test agent
3. **Result**: _____ (PASS/FAIL)

### Test C: Offline
1. Disconnect internet (2 min)
2. Reconnect
3. Discord: `@MainBrain Test reconnected?`
4. Expected: Bot responds
5. **Result**: _____ (PASS/FAIL)

### Test D: Container Restart
```bash
docker compose restart openclaw-gateway
sleep 10
# Send Discord: @MainBrain Test still running?
# Expected: Bot responds
```
**Result**: _____ (PASS/FAIL)

### Test E: Windows + SSH Disconnect
1. SSH close + Windows logout
2. Wait 3 min
3. Send from phone: `@MainBrain Test are you there?`
4. Expected: Bot responds
5. **Result**: _____ (PASS/FAIL)

---

## Common Commands

| Command | Purpose |
|---------|---------|
| `bash scripts/deploy.sh up` | Start gateway |
| `bash scripts/deploy.sh down` | Stop gateway |
| `bash scripts/deploy.sh restart` | Restart gateway |
| `bash scripts/deploy.sh status` | Check status |
| `bash scripts/logs.sh` | View live logs |
| `bash scripts/health-check.sh` | Verify health |
| `bash scripts/backup-state.sh` | Create backup |
| `bash scripts/restore-state.sh <file>` | Restore backup |
| `bash scripts/rollback.sh` | Interactive recovery |

---

## Troubleshooting

### Bot not responding
```bash
bash scripts/logs.sh tail 50
# Look for error messages about Discord or OpenAI
```

### Port already in use
```bash
lsof -i :18789
# Kill if not openclaw-gateway, then retry deploy.sh up
```

### Invalid API key
```bash
# Edit .env.local and correct the key
nano infra/openclaw/.env.local
# Restart
bash scripts/deploy.sh restart
```

### Container won't start
```bash
docker compose down --remove-orphans
docker compose pull
bash scripts/deploy.sh up
```

---

## Full Documentation

- **Installation**: Read `infra/openclaw/README.md` (17KB comprehensive guide)
- **Security**: Read `infra/openclaw/SECURITY.md` (secret management, permissions)
- **Monitoring**: Read `infra/openclaw/HEALTH.md` (troubleshooting, performance)
- **Recovery**: Read `infra/openclaw/ROLLBACK.md` (backup/restore procedures)

---

## Key Principles

✅ **Non-root**: Container runs as UID 1000 (no privilege escalation)  
✅ **No privileged mode**: Standard capabilities only  
✅ **No Docker socket**: Cannot access Docker daemon  
✅ **Localhost-only**: Gateway at 127.0.0.1:18789 only  
✅ **Chat-only pilot**: No file access, no external tools  
✅ **Secrets protected**: .env.local is git-ignored  
✅ **Persistent state**: Survives restarts and reboots  
✅ **Automated backups**: Created before any changes  

---

## If Everything Works

Congratulations! 🎉

You now have:
- A Git-tracked OpenClaw deployment
- Reproducible infrastructure (can reinstall anytime with Git)
- Secure configuration (secrets protected, non-root execution)
- Backup & recovery procedures (tested and verified)
- Monitoring & troubleshooting guides
- Foundation for future agents (Librarian, Director, Animator)

**Pilot phase is complete when**:
✅ All 5 tests pass (A-E)  
✅ Service survives SSH+Windows disconnect  
✅ Backup and restore work  
✅ No security issues  

Next: Document lessons learned, then expand to Phase 1 (Librarian agent)

---

## Need Help?

1. Check logs: `bash scripts/logs.sh tail 100`
2. Review troubleshooting section above
3. Read full documentation (see "Full Documentation" section)
4. Check DEPLOYMENT_SUMMARY.md for detailed procedures

---

**Last Updated**: 2026-11-07  
**Status**: Ready for Pilot  
**Next Step**: Provide credentials via .env.local
