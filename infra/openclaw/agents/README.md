# OpenClaw Agent Permissions and Restrictions

## Overview

This document defines security boundaries and permissions for OpenClaw agents running in MainBrain. Each agent has explicit tool restrictions to prevent unintended actions.

## Permission Model

Permissions follow a **whitelist** approach: only explicitly authorized tools are available to agents.

```
┌─────────────────────────────────────────────────────┐
│  Agent Instance (confined by explicit permissions)  │
├─────────────────────────────────────────────────────┤
│                                                       │
│  Allowed Tools:                Blocked Tools:       │
│  ✓ Discord messaging           ✗ Docker socket      │
│  ✓ Basic utilities             ✗ Host shell (bash)  │
│  ✓ Memory (chat history)       ✗ Filesystem write   │
│  ✓ Configured AI models        ✗ VideoDB/MCP       │
│                                ✗ Worker queue       │
│                                ✗ Database access    │
│                                                       │
│  Container: runs as non-root   Resources: limited   │
│  Network: outbound only        Storage: isolated    │
└─────────────────────────────────────────────────────┘
```

## Pilot Phase - Discord Test Agent

### Allowed Operations

- **Chat only**: Respond to Discord messages (text)
- **Message formatting**: Markdown, embeds, reactions
- **Memory**: Chat history within current conversation
- **Mentions**: Respond only when explicitly mentioned (if DISCORD_REQUIRE_MENTION=true)

### Blocked Operations

- File operations (no local filesystem access)
- External tools or skills (disabled: AGENT_DISABLE_SKILLS=true)
- MCP server access (VideoDB, stdio servers)
- Worker queue submission
- Database queries
- Shell commands
- Docker operations
- Network requests (except Discord API)

### Configuration

**Environment Variables** (set in .env.local):

```bash
AGENT_CHAT_ONLY=true
AGENT_DISABLE_SKILLS=true
DISCORD_REQUIRE_MENTION=true
DISCORD_ALLOWED_USERS=<your_discord_user_id>
DISCORD_SERVER_ID=<your_server_id>
LOG_LEVEL=info
```

**Permission Enforcement**:

- Container runs as UID 1000 (non-root)
- No Docker socket mounted
- No access to `/host` or `/nas` directories
- Network restricted to Discord API outbound
- Process resource limits applied (if enabled)

## Future Phase 1 - Librarian Agent

### Purpose

Index and search MainBrain's digital assets (transcripts, notes, research).

### Planned Operations

- Read-only access to indexed data
- Full-text search
- Referenced material retrieval
- Chat with context from knowledge base

### Security Boundary

- Read-only filesystem access to `data/indexed/`
- No write permissions
- No access to raw source files
- Limited to 2 GB memory, 1 CPU for searches

## Future Phase 2 - Director Agent

### Purpose

Orchestrate video processing jobs (analysis, editing, effects).

### Planned Operations

- Submit jobs to MainBrain worker queue
- Monitor job status
- Retrieve processed results
- Suggest video improvements

### Security Boundary

- Worker queue API calls only (no shell access)
- No direct file I/O
- Limited job complexity
- Resource quotas per agent

## Future Phase 3 - Animator Agent

### Purpose

Create and modify animations, graphics, effects.

### Planned Operations

- Submit animation jobs to worker queue
- Monitor rendering progress
- Store results in designated output directory
- Return animation previews to Discord

### Security Boundary

- Worker queue API calls only
- No access to video processing pipeline
- Output files isolated to `data/animations/agent-created/`
- Time-limited rendering (no infinite loops)

---

## Implementation Checklist

### For Any New Agent

- [ ] Define explicit tool whitelist
- [ ] Disable all skills by default
- [ ] Restrict filesystem access (mount single directory if needed)
- [ ] Enable non-root user (UID 1000)
- [ ] Set resource limits (CPU, memory)
- [ ] Document external dependencies
- [ ] Create read-only fixture data for testing
- [ ] Audit logs for unauthorized access attempts

### Review Procedure

1. Agent instructions reviewed by maintainer
2. Tool permissions validated against threat model
3. Resource limits tested under load
4. Filesystem access verified as least-privilege
5. External service calls logged and auditable

---

## Troubleshooting Permission Issues

### Agent Cannot Write to Directory

Check:
- Volume mount path in docker-compose.yml
- Directory ownership (chown to UID 1000)
- Directory permissions (chmod 750)

### Tool Not Available

Check:
- Tool is in agent instructions (if using skills)
- Tool permission not blocked in AGENT_* settings
- Agent skill plugins enabled in models.json

### Too Many Permissions

Remove from:
- docker-compose.yml volume mounts
- models.json external_tools
- Environment variables passed to container

---

## Audit and Monitoring

### Log Locations

- Container logs: `docker compose logs openclaw-gateway`
- State directory: `/home/mdv/mainbrain/data/openclaw/state/logs/`

### Security Events to Monitor

- Unexpected tool access attempts
- Failed permission checks
- Unusual resource usage spikes
- Network connection attempts outside Discord API

### Incident Response

If unauthorized access detected:

1. Stop container: `docker compose stop openclaw-gateway`
2. Snapshot state: `bash scripts/backup-state.sh`
3. Review logs: `docker compose logs --tail=1000 openclaw-gateway`
4. Rollback if needed: `bash scripts/rollback.sh`
5. Update permissions and redeploy

---

*Last updated: 2026-11-07*
*Revision: 1.0 (Pilot Phase)*
