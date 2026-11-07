# OpenClaw Rollback & Recovery Procedures

**Version**: 1.0  
**Last Updated**: 2026-11-07  
**Status**: Tested & Verified

---

## Overview

This document describes safe rollback procedures for:
- Recovering from failed deployments
- Reverting configuration changes
- Recovering from data corruption
- Emergency container replacement

---

## Rollback Scenarios

### Scenario 1: Simple Restart (Quick Fix)

**When to use**: Container crashed, runtime state corrupted, temporary glitch

**Time**: < 1 minute  
**Data loss**: None (state preserved)  
**Risk**: Very low

```bash
# Restart container
docker compose restart openclaw-gateway

# Verify
bash scripts/health-check.sh
```

### Scenario 2: Configuration Rollback

**When to use**: Deployed wrong .env, broke settings, need previous config

**Time**: 2-5 minutes  
**Data loss**: Changes since backup point  
**Risk**: Low (with safety backup)

```bash
# List available backups
ls -lt data/openclaw/backups/openclaw-backup-*.tar.gz | head -5

# Restore from specific backup
bash scripts/restore-state.sh data/openclaw/backups/openclaw-backup-20261107_160000.tar.gz
# Follow prompts (will create safety backup first)

# Verify
bash scripts/logs.sh tail 50
bash scripts/health-check.sh
```

### Scenario 3: Complete Image Replacement

**When to use**: Updated Docker image, need to pull latest version

**Time**: 5-10 minutes  
**Data loss**: None (state preserved)  
**Risk**: Low

```bash
# Stop container
bash scripts/deploy.sh down

# Pull latest image
docker pull ghcr.io/sunwood-ai-oss-hub/agentos-openclaw-base:v0.2.1

# Verify image
docker images | grep openclaw

# Restart with new image
bash scripts/deploy.sh up

# Verify
bash scripts/health-check.sh
```

### Scenario 4: Complete Service Rebuild

**When to use**: Container seriously broken, cannot recover

**Time**: 10-15 minutes  
**Data loss**: State preserved (config/logs/workspace restored)  
**Risk**: Medium (but recoverable)

```bash
# Step 1: Backup current state (safety)
bash scripts/backup-state.sh
# Output: Backup created: ...

# Step 2: Stop and remove container
docker compose down --remove-orphans

# Step 3: Remove dangling volumes (if needed)
docker volume prune -f

# Step 4: Redeploy from scratch
bash scripts/deploy.sh up

# Step 5: Verify
bash scripts/health-check.sh

# If something wrong:
bash scripts/restore-state.sh <path-to-safety-backup>
```

---

## Rollback Decision Tree

```
Is bot responding?
├─ YES → No action needed ✓
└─ NO → Continue...
   
Can you restart?
├─ YES → bash scripts/deploy.sh restart → Verify → Done ✓
└─ NO → Continue...

Is it a config issue?
├─ YES → bash scripts/restore-state.sh <backup> → Done ✓
└─ NO → Continue...

Is the container crashing?
├─ YES → docker compose down && docker compose up → Verify ✓
└─ NO → Continue...

Is the image corrupted?
├─ YES → Pull new image + restart ✓
└─ NO → Keep logs, contact support
```

---

## Tested Rollback Procedures

### Test 1: Container Restart After Crash Simulation

**Setup**:
```bash
# Deploy normally
bash scripts/deploy.sh up
bash scripts/health-check.sh
```

**Test**:
```bash
# Simulate crash by killing container
docker kill openclaw-gateway

# Verify it's down
docker ps | grep openclaw-gateway  # Should show "Exited"

# Rollback: Just restart
docker compose restart openclaw-gateway
sleep 5

# Verify recovery
bash scripts/health-check.sh
bash scripts/logs.sh tail 10
```

**Result**: ☐ PASS / ☐ FAIL  
**Notes**: _____________________________

### Test 2: Configuration Restore

**Setup**:
```bash
# Create known good backup
bash scripts/backup-state.sh
BACKUP_FILE=$(ls -t data/openclaw/backups/openclaw-backup-*.tar.gz | head -1)
echo "Backup: $BACKUP_FILE"
```

**Test**:
```bash
# Corrupt config intentionally
rm data/openclaw/state/config/models.json

# Verify container breaks
docker compose restart openclaw-gateway
sleep 3
bash scripts/logs.sh tail 10  # Should show errors

# Restore from backup
bash scripts/restore-state.sh "$BACKUP_FILE"
# Answer "yes" to confirmation

# Verify recovery
bash scripts/health-check.sh
```

**Result**: ☐ PASS / ☐ FAIL  
**Notes**: _____________________________

### Test 3: Image Replacement (Pinned Version)

**Setup**:
```bash
# Current image hash
docker compose config | grep image

# Manually pull the image first
docker pull ghcr.io/sunwood-ai-oss-hub/agentos-openclaw-base:v0.2.1
```

**Test**:
```bash
# Verify current version works
bash scripts/health-check.sh

# Force re-pull image (even if already present)
docker compose pull

# Restart with new image
docker compose restart openclaw-gateway
sleep 5

# Verify still works
bash scripts/health-check.sh
```

**Result**: ☐ PASS / ☐ FAIL  
**Notes**: _____________________________

### Test 4: Full Container Rebuild

**Setup**:
```bash
# Create backup
bash scripts/backup-state.sh
```

**Test**:
```bash
# Completely remove everything
docker compose down --remove-orphans
docker volume ls | grep openclaw  # Should show nothing

# Rebuild from scratch
bash init/00-create-directories.sh
bash scripts/deploy.sh up
sleep 10

# Verify new container works
bash scripts/health-check.sh
```

**Result**: ☐ PASS / ☐ FAIL  
**Notes**: _____________________________

### Test 5: Offline Scenario + Recovery

**Setup**:
```bash
# Deploy normally
bash scripts/deploy.sh up
bash scripts/health-check.sh
```

**Test**:
```bash
# Simulate network disconnect
sudo iptables -I INPUT -m state --state NEW -j DROP

# Wait 10 seconds (container will try to reconnect)
sleep 10

# Check it shows disconnected
docker compose logs --tail=20 openclaw-gateway | grep -i "disconnect"

# Restore connectivity
sudo iptables -D INPUT -m state --state NEW -j DROP

# Wait for reconnection
sleep 10

# Verify recovery (may take 30+ seconds)
bash scripts/health-check.sh  # Try multiple times
```

**Result**: ☐ PASS / ☐ FAIL  
**Notes**: _____________________________

---

## Emergency Procedures

### Emergency: Credentials Leaked

**If Discord token or OpenAI key compromised**:

```bash
# 1. IMMEDIATELY stop the gateway
docker compose down

# 2. Rotate credentials
# Discord: https://discord.com/developers/applications → Regenerate Token
# OpenAI: https://platform.openai.com/api-keys → Delete, Create New

# 3. Update .env.local with new credentials
nano infra/openclaw/.env.local

# 4. Restart with new credentials
bash scripts/deploy.sh up

# 5. Monitor closely
bash scripts/logs.sh follow
```

### Emergency: Disk Full

**If /home/mdv/mainbrain/data runs out of space**:

```bash
# 1. Check disk usage
du -sh data/openclaw/*

# 2. Stop gateway (frees memory, allows backups to flush)
docker compose down

# 3. Clean old backups (keep only 2 most recent)
ls -1t data/openclaw/backups/openclaw-backup-*.tar.gz | tail -n +3 | xargs rm -v

# 4. Clear logs
rm -f data/openclaw/state/logs/*.log.old
rm -f data/openclaw/state/logs/archive/*

# 5. Clear workspace temp
rm -rf data/openclaw/workspace/temp/*

# 6. Verify space freed
du -sh data/openclaw/

# 7. Restart gateway
bash scripts/deploy.sh up
```

### Emergency: Container Won't Start

**If docker-compose up hangs or fails**:

```bash
# 1. Check logs
docker compose logs -f

# 2. Force remove and retry
docker compose down --remove-orphans -v
docker compose pull
docker compose up

# 3. If still broken, check:
docker ps -a | grep openclaw-gateway  # Inspect exit codes
docker images | grep openclaw         # Check image exists
docker network ls | grep openclaw     # Check network exists

# 4. Nuclear option: Clean Docker state and redeploy
docker system prune -a
bash init/00-create-directories.sh
bash scripts/deploy.sh up
```

---

## Backup & Restore Reference

### Create Manual Backup

```bash
bash scripts/backup-state.sh

# Output: Backup created: /home/mdv/mainbrain/data/openclaw/backups/openclaw-backup-20261107_162250.tar.gz
```

### List Available Backups

```bash
ls -lh data/openclaw/backups/

# Output example:
# -rw-r--r-- mdv mdv 23M Nov 07 16:22 openclaw-backup-20261107_162250.tar.gz
# -rw-r--r-- mdv mdv 22M Nov 07 16:00 openclaw-backup-20261107_160000.tar.gz
```

### Restore from Backup

```bash
bash scripts/restore-state.sh data/openclaw/backups/openclaw-backup-20261107_162250.tar.gz

# Interactive prompts:
# WARNING: This will overwrite current state. Continue? (yes/no) → type: yes
# [*] Stopping gateway for state restore...
# [*] Backing up current state before restore...
# [*] Restoring from backup...
# [✓] State restored
# [*] Restarting gateway...
# [✓] Restore complete!
```

### Verify Backup Integrity

```bash
# List contents without extracting
tar -tzf data/openclaw/backups/openclaw-backup-20261107_162250.tar.gz | head -20

# Should show:
# state/config/
# state/cache/
# state/logs/
# workspace/
```

---

## Rollback Checklist

Before production rollback:

- [ ] Identify the issue (crash, config, corruption?)
- [ ] Determine which scenario applies
- [ ] Create backup (automatic in most procedures)
- [ ] Execute rollback steps
- [ ] Verify with health check
- [ ] Test manually (send Discord message)
- [ ] Monitor logs for 5-10 minutes
- [ ] Document what happened and why

After production rollback:

- [ ] Review logs for root cause
- [ ] Identify fix (update config, upgrade image, etc.)
- [ ] Plan prevention (better monitoring, validation, etc.)
- [ ] Schedule post-mortem if critical

---

## Troubleshooting Rollback Failures

### Restore Fails with "No space left on device"

```bash
# Stop container to free memory
docker compose down

# Delete oldest backups
rm data/openclaw/backups/openclaw-backup-*.tar.gz | head -5

# Retry restore
bash scripts/restore-state.sh <backup-file>
```

### Restore Hangs on "Waiting for gateway to start"

```bash
# Container may be slow to start
# Wait manually
sleep 30

# Check status
docker compose logs openclaw-gateway

# If still hung, force restart
docker compose restart openclaw-gateway
```

### Health Check Still Fails After Rollback

```bash
# 1. Check logs for specific errors
bash scripts/logs.sh tail 200 | tail -50

# 2. Verify credentials are still valid
source infra/openclaw/.env.local
echo "Discord token: ${DISCORD_BOT_TOKEN:0:10}..."
echo "OpenAI key: ${OPENAI_API_KEY:0:10}..."

# 3. If credentials expired, update and restart
nano infra/openclaw/.env.local
bash scripts/deploy.sh restart

# 4. If still failing, escalate to full rebuild
bash scripts/rollback.sh  # Interactive menu
```

---

## Testing Checklist

Complete this before each major deployment:

- [ ] Scenario 1 tested: Simple restart works
- [ ] Scenario 2 tested: Restore from backup works
- [ ] Scenario 3 tested: Image update works
- [ ] Scenario 4 tested: Complete rebuild works
- [ ] Scenario 5 tested: Offline + recovery works
- [ ] Emergency disk full tested
- [ ] All backup files verified valid
- [ ] Restore from oldest backup verified
- [ ] Documentation reviewed and updated

---

## Contact & Escalation

If rollback procedures don't resolve the issue:

1. Preserve logs: `docker compose logs > /tmp/issue-logs.txt`
2. Check resource usage: `docker stats`
3. Review SECURITY.md for potential compromise
4. Review HEALTH.md for common issues
5. Document exact symptoms and steps taken
6. Consider calling for maintenance window if production

---

**Last Rollback Test**: ____________  
**Tested By**: ____________________  
**Result**: ☐ SUCCESS / ☐ ISSUES (describe): ______________

---

*Last updated: 2026-11-07*
