# OpenClaw Monitoring, Health Checks & Troubleshooting

**Version**: 1.0  
**Last Updated**: 2026-11-07

---

## Table of Contents

1. [Health Checks](#health-checks)
2. [Monitoring](#monitoring)
3. [Common Issues](#common-issues)
4. [Debugging](#debugging)
5. [Performance Tuning](#performance-tuning)

---

## Health Checks

### Quick Health Status

```bash
# One-liner check
bash scripts/health-check.sh

# Output: ✓ HEALTHY or warnings
```

### Manual Verification

```bash
# 1. Container running?
docker compose ps openclaw-gateway
# Should show: Up (healthy)

# 2. Gateway responsive?
curl -I http://127.0.0.1:18789/health
# Should return: HTTP 200

# 3. Logs clean?
docker compose logs --tail=20 openclaw-gateway | grep -i error
# Should show: (nothing or expected errors)

# 4. Disk space?
du -sh data/openclaw/
# Should be < 1GB (state is usually ~100-300MB)

# 5. Memory usage?
docker stats openclaw-gateway --no-stream
# Memory should be 200-500MB range
```

### Automated Health Monitoring

**For regular monitoring**, create a cron job:

```bash
# Edit crontab
crontab -e

# Add this line (checks every 10 minutes)
*/10 * * * * cd /home/mdv/mainbrain/infra/openclaw && bash scripts/health-check.sh >> health.log 2>&1 || echo "ALERT: OpenClaw health check failed" | mail -s "OpenClaw Alert" mdv@localhost
```

---

## Monitoring

### View Live Logs

```bash
# Follow logs in real-time (most recent first)
bash scripts/logs.sh

# Or manually:
docker compose logs -f --tail=50 openclaw-gateway
```

### Check Resource Usage

```bash
# CPU, Memory, Network stats
docker stats openclaw-gateway

# Example output:
# CONTAINER                CPU %               MEM USAGE / LIMIT
# openclaw-gateway         0.15%               356MiB / 2GiB
```

**Healthy ranges**:
- CPU: < 10% sustained (spikes to 30% okay)
- Memory: 200-500MB (< 1GB critical)
- Disk I/O: < 50MB/s sustained

### Disk Space Monitoring

```bash
# OpenClaw data size
du -sh /home/mdv/mainbrain/data/openclaw/

# Breakdown:
du -sh /home/mdv/mainbrain/data/openclaw/{state,workspace,backups}/*

# If state/ is > 500MB:
du -sh /home/mdv/mainbrain/data/openclaw/state/cache/
# Clear cache if needed: rm -rf data/openclaw/state/cache/*
```

### Container Event Logs

```bash
# Last 10 container events
docker events --filter "container=openclaw-gateway" --since 24h | tail -20

# Real-time events
docker events --filter "container=openclaw-gateway"
```

### Discord Bot Presence

Check Discord app:
1. Open MainBrain server
2. Look for "MainBrain Test" bot in members list
3. Should show status (online/idle/do not disturb)
4. Right-click → "View Profile" → Last active timestamp

---

## Common Issues

### Issue 1: Bot Not Responding to Messages

**Symptoms**:
- Send message but no reply
- Other bots in same channel work

**Diagnosis**:

```bash
# Step 1: Is container running?
docker ps | grep openclaw-gateway
# ✗ If not running: start with `bash scripts/deploy.sh up`

# Step 2: Check logs for Discord connection
docker compose logs --tail=100 openclaw-gateway | grep -i discord
# Look for: "Connected to Discord" or connection errors

# Step 3: Verify bot token
source infra/openclaw/.env.local
if [ -z "$DISCORD_BOT_TOKEN" ]; then echo "ERROR: DISCORD_BOT_TOKEN not set"; fi

# Step 4: Check bot permissions in Discord
# Right-click channel → Permissions → MainBrain Test bot
# Should have: Send Messages, Read Messages/View Channels, Read Message History
```

**Resolution**:

```bash
# Restart container
docker compose restart openclaw-gateway
sleep 10

# Verify
bash scripts/logs.sh tail 50  # Should show connection success
```

### Issue 2: Gateway Port Already in Use

**Symptoms**:
```
ERROR: Ports are not available: listen tcp 127.0.0.1:18789: bind: address already in use
```

**Diagnosis**:

```bash
# Find what's using port 18789
lsof -i :18789
# or
netstat -tuln | grep 18789
```

**Resolution**:

```bash
# If it's an old openclaw-gateway container:
docker compose down --remove-orphans

# If it's something else using the port:
# Kill the process (replace PID with actual process ID)
kill <PID>

# Retry deployment
bash scripts/deploy.sh up
```

### Issue 3: API Key Invalid / 401 Errors

**Symptoms**:
```
[ERROR] 401 Unauthorized: Invalid OpenAI API key
```

**Diagnosis**:

```bash
# 1. Check key format
source infra/openclaw/.env.local
echo "${OPENAI_API_KEY:0:10}..."  # Should start with "sk-proj-"

# 2. Verify key is active
# Go to https://platform.openai.com/api-keys
# Check key hasn't expired and has available quota

# 3. Test key with curl
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer ${OPENAI_API_KEY}" | head -c 100
# Should NOT return 401
```

**Resolution**:

```bash
# Generate new key at https://platform.openai.com/api-keys
# Update .env.local:
nano infra/openclaw/.env.local
# Change: OPENAI_API_KEY=sk-proj-...

# Restart
bash scripts/deploy.sh restart
```

### Issue 4: Discord Token Invalid

**Symptoms**:
```
[ERROR] Invalid token
[ERROR] Cannot connect to Discord Gateway
```

**Diagnosis**:

```bash
# Check token format
source infra/openclaw/.env.local
echo "${DISCORD_BOT_TOKEN:0:20}..."  # Should be a long string

# Verify in Discord developer portal
# https://discord.com/developers/applications → Your App → Bot
# Check if token shown there matches (might have been regenerated)
```

**Resolution**:

```bash
# Go to https://discord.com/developers/applications
# Select "MainBrain Test" → Bot tab
# Click "Regenerate" (IMPORTANT: saves the new token immediately)
# Copy new token
# Update .env.local:
nano infra/openclaw/.env.local
DISCORD_BOT_TOKEN=<paste new token>

# Restart
bash scripts/deploy.sh restart
```

### Issue 5: High Memory Usage

**Symptoms**:
```
Docker stats shows > 1GB memory usage
```

**Diagnosis**:

```bash
# Check actual memory
docker stats openclaw-gateway --no-stream | awk '{print $4}'

# Check process memory
docker exec openclaw-gateway ps aux | head -5

# Check log file size (logs can grow large)
du -sh data/openclaw/state/logs/
```

**Resolution**:

```bash
# Option 1: Clean old logs
rm data/openclaw/state/logs/*.log.*
docker compose restart openclaw-gateway

# Option 2: Clear cache
rm -rf data/openclaw/state/cache/*
docker compose restart openclaw-gateway

# Option 3: Full restart
bash scripts/deploy.sh restart

# Option 4: Rotate logs (backup first)
bash scripts/backup-state.sh
# Then clean:
rm data/openclaw/state/logs/*.log
docker compose restart openclaw-gateway
```

### Issue 6: Logs Show Connection Drops

**Symptoms**:
```
[WARN] Discord connection lost
[WARN] Reconnecting to Discord...
(happens multiple times)
```

**Diagnosis**:

```bash
# 1. Check internet connectivity
ping -c 3 8.8.8.8  # Google's DNS
curl -I https://api.discord.com  # Discord reachable?
curl -I https://api.openai.com   # OpenAI reachable?

# 2. Check container DNS
docker exec openclaw-gateway nslookup gateway.discord.gg

# 3. Check for firewall rules
sudo iptables -L -n | grep 443  # Should show ACCEPT
```

**Resolution**:

```bash
# If internet is fine, restart Docker daemon
sudo systemctl restart docker

# Restart container
bash scripts/deploy.sh restart

# Monitor reconnection
bash scripts/logs.sh tail 100 | grep -i "discord\|connect"
```

---

## Debugging

### Enable Debug Logging

```bash
# In .env.local, set:
LOG_LEVEL=debug

# Restart
bash scripts/deploy.sh restart

# Now logs will include detailed info
bash scripts/logs.sh tail 200
```

**WARNING**: Debug logs are verbose and may include sensitive data. Use only temporarily.

### Inspect Container Environment

```bash
# See all environment variables in container
docker exec openclaw-gateway env | sort

# Check what network connections it has
docker exec openclaw-gateway netstat -tuln | grep LISTEN

# Check mounted volumes
docker inspect openclaw-gateway | grep -A 20 "Mounts"
```

### Test Discord Connection

```bash
# From container, test Discord API
docker exec openclaw-gateway \
  curl -I https://api.discord.com/api/v10/users/@me \
    -H "Authorization: Bot ${DISCORD_BOT_TOKEN}"

# Should return 200 (unless token is invalid)
```

### Test OpenAI Connection

```bash
# From container, test OpenAI API
docker exec openclaw-gateway \
  curl https://api.openai.com/v1/models \
    -H "Authorization: Bearer ${OPENAI_API_KEY}" | head -c 200

# Should return JSON list of models
```

### Check File Permissions

```bash
# Verify files are readable by container (UID 1000)
ls -la data/openclaw/state/config/

# Should show: -rw-r--r-- (or -rw------- for sensitive files)

# Test read access from container
docker exec openclaw-gateway cat /home/node/.openclaw/config/models.json
# Should print JSON without errors
```

---

## Performance Tuning

### Increasing Responsiveness

If bot seems slow responding:

1. **Check resource limits** (if enabled):
   ```bash
   # In docker-compose.yml, verify limits are appropriate:
   #   cpus: '2'    # At least 2 cores
   #   memory: 2G   # At least 2GB
   ```

2. **Reduce log verbosity**:
   ```bash
   # In .env.local:
   LOG_LEVEL=warn  # Instead of info
   
   bash scripts/deploy.sh restart
   ```

3. **Monitor concurrent requests**:
   ```bash
   # If many messages at once, container may queue them
   # This is normal behavior
   docker stats --no-stream
   ```

### Reducing Memory Usage

If memory usage high:

1. **Disable debug logging**: `LOG_LEVEL=info`
2. **Clear cache**: `rm -rf data/openclaw/state/cache/*`
3. **Archive old logs**: `gzip data/openclaw/state/logs/*.log`
4. **Reduce workspace temp**: `rm -rf data/openclaw/workspace/temp/*`

### Optimizing Disk Usage

Regular maintenance:

```bash
# Weekly backup rotation (automated)
bash scripts/backup-state.sh  # Creates backup, deletes old ones

# Monthly cleanup
find data/openclaw/state/logs -name "*.log" -mtime +30 -delete
find data/openclaw/workspace -type f -mtime +7 -delete
```

---

## Monitoring Dashboard (Future)

### Example Prometheus Metrics

When monitoring is added, track:

```
openclaw_container_cpu_percent
openclaw_container_memory_bytes
openclaw_container_network_in_bytes
openclaw_container_network_out_bytes
openclaw_discord_messages_received_total
openclaw_discord_messages_sent_total
openclaw_api_calls_total{provider="openai"}
openclaw_api_calls_total{provider="discord"}
openclaw_api_call_errors_total
openclaw_uptime_seconds
```

---

## Checklist: Healthy System

Every morning:

- [ ] Container running: `docker ps | grep openclaw-gateway`
- [ ] Recent logs clean: `docker compose logs --tail=20 openclaw-gateway | grep -i error` (should be empty or expected)
- [ ] Disk usage normal: `du -sh data/openclaw/` (< 1GB)
- [ ] Memory healthy: `docker stats openclaw-gateway --no-stream` (< 500MB)
- [ ] Bot online: Check Discord server members list

Every week:

- [ ] Backup created: `ls -lt data/openclaw/backups/ | head -1` (should be recent)
- [ ] No growing log files: `du -sh data/openclaw/state/logs/`
- [ ] Slow responses?: Check logs for errors or timeouts

Every month:

- [ ] Review logs for patterns: `grep -i "error\|warn" data/openclaw/state/logs/*.log | head -20`
- [ ] Test restore: `bash scripts/restore-state.sh <backup>` (use oldest backup)
- [ ] Update documentation if any issues found

---

*Last updated: 2026-11-07*
