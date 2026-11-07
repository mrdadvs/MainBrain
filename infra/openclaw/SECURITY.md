# OpenClaw Security & Secret Management

**Version**: 1.0  
**Classification**: Internal Security Documentation  
**Last Updated**: 2026-11-07

---

## Table of Contents

1. [Secret Management](#secret-management)
2. [Container Security](#container-security)
3. [Network Isolation](#network-isolation)
4. [Permission Model](#permission-model)
5. [Audit & Logging](#audit--logging)
6. [Incident Response](#incident-response)

---

## Secret Management

### Overview

Secrets (API keys, tokens) are handled with strict separation from Git and version control.

```
Git Repository (Safe)              Local Filesystem (Protected)
├── .env.example  ────────┐       ├── .env.local (git-ignored)
│   (placeholders only)   │       │   (real secrets)
│                         └──────→│
├── docker-compose.yml             │
│   (references $ENVVARS)          ├── .env.discord (git-ignored)
│                                  └── .env.openai (git-ignored)
└── .gitignore
    (blocks *.local)
```

### Protected Secrets

**Never commit or expose**:
- Discord bot token (`DISCORD_BOT_TOKEN`)
- OpenAI API key (`OPENAI_API_KEY`)
- Gateway token (`OPENCLAW_GATEWAY_TOKEN`)
- Any credentials or auth tokens

**Locations**:
- `.env.local` (root OpenClaw directory)
- `data/openclaw/state/config/` (runtime secrets)

### Accessing Secrets During Deployment

**Safe method**:

```bash
cd infra/openclaw

# 1. Verify .env.local exists and is not world-readable
ls -la .env.local
# Should show: -rw------- 1 mdv mdv

# 2. Load secrets into environment (not exported to subshells)
source .env.local

# 3. Use in scripts (stays in memory, not logged)
echo "Using token: ${DISCORD_BOT_TOKEN:0:10}..."

# 4. Don't forward to other scripts or logs
# ✗ Bad: docker compose run -e DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN} ...
# ✓ Good: Pass via --env-file .env.local
```

### Rotating Secrets

**If a secret is compromised**:

1. **Discord Token**:
   - Go to https://discord.com/developers/applications
   - Your App → Bot → Regenerate Token
   - Update `.env.local`
   - Restart: `bash scripts/deploy.sh restart`

2. **OpenAI API Key**:
   - Go to https://platform.openai.com/api-keys
   - Delete old key
   - Create new key
   - Update `.env.local`
   - Restart: `bash scripts/deploy.sh restart`

3. **Gateway Token**:
   - Generate new: `openssl rand -hex 32`
   - Update `.env.local`
   - Restart: `bash scripts/deploy.sh restart`

### Secret Audit

**List files with secrets**:

```bash
# Should only show .env.local and git-ignored files
find . -type f \( -name ".env*" -o -name "*secret*" -o -name "*token*" \) \
  | grep -v ".git"
```

**Check for accidental commits**:

```bash
# Search Git history for API keys
git log --all -S "sk-proj-" --source --remotes -- 2>/dev/null || echo "Not a Git repo yet"

# Search staged changes
git diff --cached | grep -i "api.key\|secret\|token" || echo "No secrets in staging"
```

---

## Container Security

### Non-Root Execution

**Default**: Container runs as UID 1000 (non-root)

```bash
# Verify in container
docker exec openclaw-gateway id
# Output: uid=1000 gid=1000 groups=1000

# Check in docker-compose.yml
grep "user:" infra/openclaw/docker-compose.yml
```

**Why**: Prevents container escape exploitation and limits privilege escalation.

### No Privileged Mode

```yaml
# ✓ Correct: No privileged mode
openclaw-gateway:
  image: ...
  # No "privileged: true"
  # No "cap_add"

# ✗ Dangerous (DO NOT USE):
# privileged: true              # Not used
# cap_add:                       # Not used
#   - NET_ADMIN
#   - SYS_ADMIN
```

### No Docker Socket

```yaml
# ✓ Correct: No Docker socket mounted
volumes:
  - /home/mdv/mainbrain/data/openclaw/state:/home/node/.openclaw

# ✗ Dangerous (DO NOT USE):
# volumes:
#   - /var/run/docker.sock:/var/run/docker.sock
```

This prevents container from:
- Viewing other containers
- Stopping/starting services
- Escalating privileges

### Resource Limits (Optional but Recommended)

```yaml
deploy:
  resources:
    limits:
      cpus: '2'           # Max 2 CPU cores
      memory: 2G          # Max 2GB RAM
    reservations:
      cpus: '1'           # Reserve 1 core
      memory: 1G          # Reserve 1GB RAM
```

Currently commented out; uncomment if resource exhaustion is a concern.

---

## Network Isolation

### Inbound Network

```
OpenClaw Container
┌─────────────────────────────┐
│ Listening on:               │
│  127.0.0.1:8080 (gateway)   │ ← NOT accessible from network
│                             │    (only localhost)
│ No other listening ports    │
└─────────────────────────────┘
```

**Gateway URL**: `http://127.0.0.1:8080` (localhost only)

**Access from remote machine**:
```bash
# ✗ This will NOT work (intentional):
curl http://192.168.1.50:8080/health

# ✓ Only from MainBrain itself:
curl http://127.0.0.1:8080/health
```

### Outbound Network

```
Container → Allowed Outbound Connections

✓ Discord API
  - wss://gateway.discord.gg:443
  - https://api.discord.com:443

✓ OpenAI API
  - https://api.openai.com:443

✓ DNS (127.0.0.11:53)
  - For hostname resolution

✗ Host Filesystem (no access)
✗ NAS shares (no mounts)
✗ VideoDB/MCP (not configured)
✗ MainBrain worker queue (not configured)
```

### Docker Network

```bash
# Container runs on bridge network (isolated from host network)
docker network inspect openclaw-network

# No port mappings to host network interface
# (127.0.0.1:8080 binding doesn't expose to external IPs)
```

---

## Permission Model

### Filesystem Access

**Allowed (Mounted)**:

```
/home/node/.openclaw → /home/mdv/mainbrain/data/openclaw/state/
  ├── config/          (read/write)
  ├── cache/           (read/write)
  └── logs/            (write-only)

/home/node/.openclaw/workspace → /home/mdv/mainbrain/data/openclaw/workspace/
  ├── chat-history/    (read/write)
  └── temp/            (read/write, auto-cleaned)
```

**Blocked (Not Mounted)**:

```
✗ /etc                (host config)
✗ /root               (host home directory)
✗ /var                (host system state)
✗ /home/mdv           (except isolated data/openclaw/)
✗ /nas                (NAS shares)
✗ /media              (removable media)
✗ /var/run/docker.sock (Docker socket)
```

### Process Capabilities

```bash
# Verify container restrictions
docker exec openclaw-gateway grep Cap /proc/1/status
# Should show minimal capabilities

# ✓ Expected: Basic read/write capabilities only
# ✗ NOT expected: SYS_ADMIN, NET_ADMIN, CAP_SYS_MODULE
```

### Tool Access Restrictions

**Chat-Only Phase** (pilot):

```
✓ Discord messaging
✗ Bash/shell execution
✗ File operations (outside workspace)
✗ Database access
✗ External tool/skill plugins
✗ Worker queue access
✗ VideoDB/MCP access
```

**Enforcement**:

```env
AGENT_CHAT_ONLY=true        # Disable file tools
AGENT_DISABLE_SKILLS=true   # Disable plugins
```

**Future Phases**:
- Librarian: Read-only to `data/indexed/`
- Director: API calls to worker queue only
- Animator: Worker queue + output directory

---

## Audit & Logging

### Log Locations

```
Container logs:
$ docker compose logs openclaw-gateway

Persistent logs:
$ cat data/openclaw/state/logs/openclaw.log

Docker event logs:
$ docker events --filter "container=openclaw-gateway"
```

### Log Levels

```env
LOG_LEVEL=info          # Normal operation
LOG_LEVEL=debug         # Detailed (verbos, for troubleshooting)
LOG_LEVEL=error         # Errors only
```

**Note**: Never set LOG_LEVEL=debug in production (may log sensitive data).

### Security Events to Monitor

```bash
# Watch for:
grep -i "permission\|denied\|unauthorized\|failed" data/openclaw/state/logs/openclaw.log

# Alert on:
- "Permission denied" errors
- "Unauthorized" API responses
- Repeated failed connection attempts
- Unusual resource usage spikes
```

### Audit Trail

**Not currently enabled but can be added**:

```bash
# Sample audit log format:
[2026-11-07T16:22:50.123Z] user:123456789 action:message_sent channel:#agent-test
[2026-11-07T16:22:55.456Z] action:api_call service:openai status:success
[2026-11-07T16:22:56.789Z] action:api_call service:discord status:success
```

---

## Incident Response

### Suspected Compromise

**If you suspect the Discord token or API key was leaked**:

1. **Stop the gateway immediately**:
   ```bash
   docker compose stop openclaw-gateway
   ```

2. **Preserve logs**:
   ```bash
   docker compose logs openclaw-gateway > /tmp/incident-logs-$(date +%s).txt
   cp -r data/openclaw/state/logs /tmp/incident-logs-$(date +%s)/
   ```

3. **Rotate credentials**:
   ```bash
   # Discord token
   # Go to https://discord.com/developers/applications → Regenerate
   
   # OpenAI key
   # Go to https://platform.openai.com/api-keys → Delete and create new
   
   # Gateway token
   openssl rand -hex 32 > /tmp/new-gateway-token.txt
   ```

4. **Update .env.local with new secrets**

5. **Review logs for unusual activity**:
   ```bash
   grep -i "unusual\|extra\|unexpected" /tmp/incident-logs-*/openclaw.log
   ```

6. **Restart with new credentials**:
   ```bash
   bash scripts/deploy.sh up
   ```

7. **Monitor closely**:
   ```bash
   bash scripts/logs.sh follow    # Watch logs
   docker stats                   # Watch resource usage
   ```

### Unauthorized Access Attempt

**If logs show attempted access to restricted resources**:

```
Example:
[ERROR] Permission denied: Cannot access /etc/shadow
[ERROR] Tool execution failed: bash command not permitted
```

**Response**:
1. This is expected and shows permissions are working
2. Review logs to understand what was attempted
3. If attacker behavior detected, rotate credentials immediately
4. No container restart needed if denial successful

### Resource Exhaustion

**If container consumes excessive resources**:

```bash
# Monitor
docker stats openclaw-gateway

# If memory > 2GB or CPU > 80% sustained:
1. Kill any zombie processes: docker exec openclaw-gateway ps aux
2. Check log file size: du -sh data/openclaw/state/logs/
3. Rotate logs: rm data/openclaw/state/logs/*.old
4. Restart: bash scripts/deploy.sh restart
5. Monitor again: docker stats
```

---

## Checklist: Security Review

Before production use, verify:

- [ ] .env.local exists and is not world-readable (`-rw------- 1 mdv mdv`)
- [ ] No secrets in .gitignore files (check with `git diff`)
- [ ] Container runs non-root (UID 1000, no privileged mode)
- [ ] Docker socket is NOT mounted
- [ ] No access to /etc, /root, /var, or host filesystem
- [ ] Only localhost can access gateway (http://127.0.0.1:8080)
- [ ] Outbound restricted to Discord and OpenAI APIs
- [ ] AGENT_CHAT_ONLY=true (no shell/file access)
- [ ] AGENT_DISABLE_SKILLS=true (no plugins)
- [ ] Logs don't contain secrets (spot check with `grep -i "token\|key\|secret"`)
- [ ] Backup procedure tested
- [ ] Incident response plan understood

---

**Security Review Date**: ____________  
**Reviewer Name**: ____________________  
**Approval**: ☐ APPROVED / ☐ REQUIRES CHANGES

---

*Last updated: 2026-11-07*
