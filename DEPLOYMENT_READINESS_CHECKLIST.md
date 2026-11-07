# OpenClaw Deployment Readiness Checklist

**Status:** VALIDATION COMPLETE ✓  
**Date:** 2026-11-07  
**Next Action:** User provides Discord bot token, OpenAI key, Discord IDs

---

## Validation Phase - COMPLETE ✓

### Docker Image & Configuration
- [x] Docker image identified as official (openclaw/openclaw)
- [x] Image version pinned (2026.11.1)
- [x] Image digest verified with Docker Hub (sha256:db0e0809...)
- [x] docker-compose.yml validated against official standards
- [x] Gateway port corrected (8080 → 18789)
- [x] Environment variables standardized
- [x] Health check updated to official script
- [x] CLI service added (per official compose)
- [x] Security capabilities configured (cap_drop)

### Git Repository & Security
- [x] Repository initialized at ~/mainbrain/
- [x] .gitignore created with comprehensive exclusions
- [x] No API keys in Git history (verified grep scan)
- [x] No Discord tokens in Git history
- [x] No .env files with secrets committed
- [x] State directories properly excluded
- [x] Virtual environments properly excluded
- [x] All documentation committed to Git
- [x] Commit history clean and descriptive

### Permission & Access Control
- [x] Chat-only agent mode configured (AGENT_CHAT_ONLY=true)
- [x] Skills disabled (AGENT_DISABLE_SKILLS=true)
- [x] Non-privileged container execution
- [x] No Docker socket access
- [x] Localhost-only binding (127.0.0.1:18789)
- [x] No public inbound ports
- [x] No unrestricted filesystem access
- [x] Network isolation (custom bridge network)

### Documentation & Setup
- [x] README.md updated with correct image and port
- [x] SECURITY.md describes access model
- [x] HEALTH.md explains monitoring
- [x] ROLLBACK.md documents recovery
- [x] QUICKSTART.md provides rapid reference
- [x] DEPLOYMENT_SUMMARY.md explains architecture
- [x] VALIDATION_REPORT.md documents audit process
- [x] VALIDATION_COMPLETE.md summarizes results
- [x] SECURE_CREDENTIAL_PROVISIONING.md guides setup
- [x] All .env.example updated with official variables

### Deployment Scripts
- [x] deploy.sh created and reviewed
- [x] backup-state.sh created and reviewed
- [x] restore-state.sh created and reviewed
- [x] rollback.sh created and reviewed
- [x] health-check.sh created and reviewed
- [x] logs.sh created and reviewed
- [x] Script permissions verified (executable)
- [x] Script syntax validated

### Directory Structure
- [x] infra/openclaw/ created for deployment
- [x] data/openclaw/state/ created for persistent state
- [x] data/openclaw/workspace/ created for agent operations
- [x] data/openclaw/backups/ created for backup archives
- [x] infra/openclaw/agents/ created for agent instructions
- [x] infra/openclaw/scripts/ created for operational scripts
- [x] infra/openclaw/init/ created for initialization helpers
- [x] Directory structure git-tracked (.gitkeep files)

### Critical Issues Fixed
- [x] **CRITICAL:** Non-existent Docker image replaced
- [x] **CRITICAL:** Fake SHA256 hash corrected
- [x] **HIGH:** Gateway port 8080 → 18789
- [x] **HIGH:** Environment variables standardized
- [x] **MEDIUM:** CLI service added for completeness
- [x] **MEDIUM:** Documentation updated throughout

---

## Credential Provisioning Phase - PENDING USER ACTION

### Discord Setup (User Must Complete)
- [ ] Discord Developer Portal: Create bot token
  - Location: https://discord.com/developers/applications
  - App: "MainBrain Test"
  - Copy: Bot token (appears as long alphanumeric string)

- [ ] Collect Discord IDs
  - Right-click "MainBrain" server → Copy Server ID
  - Right-click "#agent-test" channel → Copy Channel ID
  - Right-click your username → Copy User ID

### OpenAI Setup (User Must Complete)
- [ ] Create OpenAI API key
  - Location: https://platform.openai.com/api-keys
  - Copy: Secret key (appears as sk-proj-...)
  - Verify: Account has billing enabled

### Credential Provisioning (User Must Complete on MainBrain)
- [ ] SSH into MainBrain: `ssh mdv@mainbrain`
- [ ] Copy template: `cp infra/openclaw/.env.example infra/openclaw/.env.local`
- [ ] Edit with editor: `nano infra/openclaw/.env.local`
- [ ] Replace DISCORD_BOT_TOKEN placeholder
- [ ] Replace OPENAI_API_KEY placeholder
- [ ] Replace DISCORD_SERVER_ID placeholder
- [ ] Replace DISCORD_CHANNEL_ID placeholder
- [ ] Replace DISCORD_ALLOWED_USERS placeholder
- [ ] (Optional) Generate gateway token: `openssl rand -hex 32`
- [ ] Verify permissions: `.env.local` not world-readable
- [ ] Verify git-ignored: `git status` should not show `.env.local`

---

## Deployment Phase - READY (Pending Credentials)

### Pre-Deployment Checks (User Must Execute)
- [ ] `.env.local` file exists in `infra/openclaw/`
- [ ] All credentials filled in (no placeholders)
- [ ] `.env.local` not in `git status` output
- [ ] Directory structure created: `bash infra/openclaw/init/00-create-directories.sh`

### Deployment (User Must Execute)
```bash
cd /home/mdv/mainbrain/infra/openclaw
bash scripts/deploy.sh up
# Wait for: "✓ Gateway health check passed"
```

- [ ] Docker image pulled successfully
- [ ] Containers created (openclaw-gateway, openclaw-cli)
- [ ] Network bridge created (openclaw-network)
- [ ] Volumes mounted correctly
- [ ] Health check passes within 30 seconds

---

## Testing Phase - VERIFICATION REQUIRED

### Test A: Discord Message Reply
- [ ] Send message: `@MainBrain Test What is 2+2?`
- [ ] Expected: Bot replies with "2 + 2 = 4" (or similar) within 5-10 seconds
- [ ] Verify: Reply comes from "MainBrain Test" bot account

**If No Response:**
- [ ] Check bot has "Message Content Intent" enabled
- [ ] Check bot has "Send Messages" permission on #agent-test
- [ ] View logs: `bash scripts/logs.sh`
- [ ] Verify Discord token in `.env.local` is correct

### Test B: Second Distinct Message
- [ ] Send message: `@MainBrain Test Tell me a joke`
- [ ] Expected: Bot replies with a joke (different from first message) within 5-10 seconds
- [ ] Verify: Response is distinct and contextually appropriate

**If No Response:**
- [ ] Same troubleshooting as Test A

### Test C: Container Restart Persistence
- [ ] Run: `docker compose stop openclaw-gateway`
- [ ] Wait: 5 seconds
- [ ] Run: `docker compose up -d openclaw-gateway`
- [ ] Wait: 10 seconds for health check
- [ ] Send message: `@MainBrain Test Say "hello world"`
- [ ] Expected: Bot replies "hello world" after restart
- [ ] Verify: Configuration survived container replacement

### Test D: SSH Disconnection Resilience
- [ ] On phone: Open Discord app (cellular data, no VPN)
- [ ] Close SSH session on MainBrain
- [ ] Send message: `@MainBrain Test Test after disconnect`
- [ ] Expected: Bot replies despite SSH being closed
- [ ] Verify: Service remains available without SSH session

### Test E: Backup Functionality
- [ ] Run: `bash scripts/backup-state.sh`
- [ ] Verify: Archive created in `data/openclaw/backups/`
- [ ] Check: Archive has timestamp and `.tar.gz` extension
- [ ] Verify: File size reasonable (> 1KB, < 100MB for pilot)

### Test F: Restore Functionality
- [ ] Run: `docker compose stop openclaw-gateway`
- [ ] Run: `bash scripts/restore-state.sh`
- [ ] Select: Most recent backup from menu
- [ ] Run: `docker compose up -d openclaw-gateway`
- [ ] Verify: Gateway starts and health check passes
- [ ] Test: Send Discord message and get reply

---

## Success Criteria - ALL REQUIRED

For pilot deployment to be considered successful, ALL of these must pass:

✓ **Test A:** Discord message receives correct reply  
✓ **Test B:** Second distinct message receives correct reply  
✓ **Test C:** Messaging works from phone on cellular (VPN off)  
✓ **Test D:** Container restarts without losing configuration  
✓ **Test E:** Service remains available after SSH closes  
✓ **Test F:** Backup and restore procedures work  

**Status:** Ready for user to execute tests (awaiting credentials)

---

## Post-Deployment Phase - FUTURE

### Not Yet Implemented (Future Phases)
- [ ] VideoDB integration (stdio MCP server)
- [ ] NAS mount and permissions
- [ ] Processing job queue access
- [ ] Additional agents (Librarian, Director, Animator)
- [ ] Separate tool permissions per agent
- [ ] GPU worker registration (second computer)
- [ ] Production hardening (TLS, reverse proxy)
- [ ] Monitoring and alerting setup
- [ ] Log aggregation and analysis

---

## Security Checklist - BEFORE PRODUCTION

Before treating this as production-ready:

- [ ] `.env.local` exists in `infra/openclaw/` only
- [ ] `.env.local` contains real credentials (not placeholders)
- [ ] `.env.local` is in `.gitignore` and not committed
- [ ] Discord bot token is fresh (not leaked)
- [ ] OpenAI API key is fresh (not leaked)
- [ ] OpenAI account has spending limits set
- [ ] Gateway token is randomly generated
- [ ] Discord allowlist contains only your user ID
- [ ] Container runs as non-root user
- [ ] No Docker socket access
- [ ] No privileged mode or capabilities
- [ ] Gateway only accessible on 127.0.0.1:18789
- [ ] All backup/restore scripts tested
- [ ] Service survives restart and SSH disconnection
- [ ] Documentation is synchronized with configuration

---

## Git Commit Summary

| Commit | Message | Status |
|--------|---------|--------|
| 7535552 | Add secure credential provisioning guide | ✓ |
| 3abf358 | Add comprehensive validation completion summary | ✓ |
| f85808e | Update documentation with corrected Docker image/port | ✓ |
| 6e47150 | Fix critical Docker configuration issues | ✓ MAIN FIX |
| 8ae8e65 | Add quick start reference card | ✓ |
| b046c74 | Add comprehensive deployment summary | ✓ |
| c1ffd6e | Initialize reproducible OpenClaw deployment | ✓ |

**Total Changes:** 7 commits, 19 tracked files, 4000+ lines of configuration and documentation

---

## Key Files Reference

**Configuration Files:**
- `infra/openclaw/docker-compose.yml` — Docker Compose definition (CORRECTED)
- `infra/openclaw/.env.example` — Environment template (UPDATED)
- `.gitignore` — Git ignore rules (VERIFIED)

**Deployment Scripts:**
- `infra/openclaw/scripts/deploy.sh` — Main deployment
- `infra/openclaw/scripts/backup-state.sh` — Create backups
- `infra/openclaw/scripts/restore-state.sh` — Restore from backup
- `infra/openclaw/scripts/rollback.sh` — Rollback menu
- `infra/openclaw/scripts/health-check.sh` — Verify health
- `infra/openclaw/scripts/logs.sh` — View logs

**Documentation:**
- `VALIDATION_COMPLETE.md` — Validation results (this phase)
- `VALIDATION_REPORT.md` — Detailed audit trail
- `SECURE_CREDENTIAL_PROVISIONING.md` — Credential setup guide (next phase)
- `infra/openclaw/README.md` — Installation guide
- `infra/openclaw/SECURITY.md` — Security model
- `infra/openclaw/ROLLBACK.md` — Recovery procedures

---

## Next Action

1. **Read:** `SECURE_CREDENTIAL_PROVISIONING.md`
2. **Collect:** Discord bot token and OpenAI API key
3. **Create:** `.env.local` with credentials
4. **Deploy:** Run `bash infra/openclaw/scripts/deploy.sh up`
5. **Test:** Verify all six test criteria pass
6. **Report:** Confirm tests completed and success criteria met

---

**Status Summary:**
- Validation Phase: ✓ COMPLETE
- Credential Provisioning: ⏳ PENDING USER ACTION
- Deployment: ⏳ READY (awaiting credentials)
- Testing: ⏳ READY (awaiting deployment)
- Post-Deployment: ⏳ FUTURE (not yet started)

**Overall:** 🟢 READY FOR CREDENTIAL PROVISIONING AND DEPLOYMENT
