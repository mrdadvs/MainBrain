# Librarian Agent - Registry & Configuration

**Agent Name**: Librarian  
**Agent ID**: `librarian`  
**Type**: Production MCP Agent  
**Status**: Active  
**Created**: 2026-11-08

---

## Agent Registration

### OpenClaw Configuration

The Librarian agent is registered in OpenClaw's `openclaw.json` configuration:

```json
{
  "agents": {
    "entries": {
      "librarian": {
        "model": "gpt-4-turbo",
        "tools": ["videodb-mcp"],
        "constraints": {
          "permissions": "read-only",
          "mcp_tools": [
            "search_transcripts",
            "list_videos",
            "get_video_details",
            "list_video_clips",
            "list_import_sources",
            "preview_import",
            "list_processing_jobs",
            "get_processing_job"
          ]
        }
      }
    }
  }
}
```

### Discord Binding

The Librarian agent is bound to Discord via multi-agent routing:

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "agents": {
        "librarian": {
          "guild": "LIBRARIAN_GUILD_ID",
          "channel": "LIBRARIAN_CHANNEL_ID",
          "require_mention": true,
          "allowed_users": ["DISCORD_USER_ID"],
          "enable_reactions": true
        }
      }
    }
  }
}
```

---

## Lifecycle

### Deployment

1. **Create workspace directory**:
   ```bash
   mkdir -p /home/mdv/mainbrain/data/openclaw/workspace/agents/librarian
   ```

2. **Register agent in OpenClaw**:
   ```bash
   # OpenClaw auto-discovers agent from:
   # - infra/openclaw/agents/librarian/SOUL.md
   # - infra/openclaw/agents/librarian/instructions.md
   # - openclaw.json agent entry
   ```

3. **Connect MCP server**:
   ```bash
   # MCP server must be running on host:
   python3 /home/mdv/mainbrain/apps/video_pipeline/mcp_server.py
   ```

4. **Start OpenClaw gateway**:
   ```bash
   docker compose -f infra/openclaw/docker-compose.yml up -d
   ```

### Session Initialization

When Librarian receives first Discord message:
1. OpenClaw creates new session: `/data/openclaw/workspace/agents/librarian/sessions/[session-id]/`
2. Loads `instructions.md` and `SOUL.md`
3. Connects to MCP server (stdio transport)
4. Initializes tools
5. Responds to user

### Session Persistence

Session files survive:
- ✅ Container restart (Docker volume mount)
- ✅ Agent process restart
- ❌ Explicit cleanup with `rm -rf data/openclaw/workspace/agents/librarian/`

### Shutdown

Stop Librarian gracefully:
```bash
# OpenClaw will flush session state
docker compose -f infra/openclaw/docker-compose.yml down

# Sessions persisted to disk:
ls -la data/openclaw/workspace/agents/librarian/sessions/
```

---

## Tool Bindings

### MCP Server Connection

**Transport**: stdio (standard input/output)  
**Protocol**: MCP v1.0  
**Address**: localhost (host machine)  
**Process**: Separate Python process

**Configuration in docker-compose.yml**:
```yaml
services:
  openclaw-gateway:
    environment:
      VIDEODB_MCP_COMMAND: "python3"
      VIDEODB_MCP_ARGS: "/home/mdv/mainbrain/apps/video_pipeline/mcp_server.py"
```

**How it works**:
1. OpenClaw gateway spawns MCP server process
2. Communicates via stdin/stdout (MCP protocol)
3. Librarian calls tools through gateway
4. Results returned as structured JSON
5. Librarian formats for Discord

### Available Tools

All tools are read-only and discoverable:

#### Search & Query

1. **`search_transcripts(query, limit)`**
   - Find videos by transcript keywords
   - Primary tool for user requests
   - Returns: filename, videoDB ID, timestamp, excerpt

2. **`list_videos(limit, offset)`**
   - List all videos with metadata
   - Useful for browsing
   - Returns: paginated video list

3. **`get_video_details(video_id)`**
   - Get full metadata for one video
   - Resolution, duration, transcript status, etc.
   - Returns: detailed video record

4. **`list_video_clips(video_id)`**
   - List clips extracted from a video
   - Help identify scenes
   - Returns: clip names, timestamps, descriptions

#### Administrative (Info-only)

5. **`list_import_sources()`**
   - Discover removable media
   - Librarian cannot import
   - Returns: device list

6. **`preview_import(source_id)`**
   - Preview import (read-only)
   - No files copied
   - Returns: files & sizes that would be imported

7. **`list_processing_jobs(status)`**
   - Check job queue status
   - Read-only informational
   - Returns: job list

8. **`get_processing_job(job_id)`**
   - Get job details
   - Read-only informational
   - Returns: detailed job record

### Tool Permissions

```
Librarian Agent Permissions
├── MCP Tools: ✅ ALL 8 tools available (read-only)
├── Database: ✅ Read-only sessions only
├── Filesystem: ❌ No file I/O (Docker-isolated)
├── Docker: ❌ No Docker socket access
├── Shell: ❌ No shell commands
├── NAS: ❌ No direct mount access
└── Discord: ✅ Send messages + reactions in #librarian only
```

---

## Security Model

### Permission Boundary

```
┌─────────────────────────────────────────────────────────┐
│ OpenClaw Gateway (Docker Container)                     │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌──────────────────────────────────────────────────┐   │
│  │ Librarian Agent                                  │   │
│  ├──────────────────────────────────────────────────┤   │
│  │ Allowed:                 Blocked:                │   │
│  │ • MCP tools (read)       • Database write        │   │
│  │ • Discord messages       • File system access    │   │
│  │ • Memory/history         • Shell commands        │   │
│  │ • AI model (GPT-4)       • Docker operations     │   │
│  │                          • NAS/mounted drives    │   │
│  └──────────────────────────────────────────────────┘   │
│           ↓ (stdio) ↓                                   │
│  ┌──────────────────────────────────────────────────┐   │
│  │ VideoDB MCP Server (stdio transport)             │   │
│  │ • Connection: Host machine (Python process)      │   │
│  │ • Access: VideoDB only (read-only)              │   │
│  │ • Tools: All 8 query/preview tools              │   │
│  └──────────────────────────────────────────────────┘   │
│                                                           │
└─────────────────────────────────────────────────────────┘
                          ↓
        Discord API (network, TLS)
```

### Container Isolation

- **User**: UID 1000 (non-root)
- **Volumes**: Read-only for config, read-write for workspace
- **Network**: Discord + MCP server only (no external access)
- **Capabilities**: NET_RAW, NET_ADMIN dropped

### MCP Server Trust Boundary

- MCP server is run by OpenClaw (managed subprocess)
- Inherits same security context as gateway container
- Cannot be accessed by other agents or external processes
- Only Librarian can call its tools (configured in openclaw.json)

---

## Distinct from MainBrain Test

### MainBrain Test (discord-test agent)

```
✅ Discord messaging only
✅ Chat-only mode (AGENT_CHAT_ONLY=true)
❌ No external tools
❌ No MCP server access
❌ No database access
Channel: #agent-test
```

### Librarian (librarian agent)

```
✅ Discord messaging
✅ MCP tools enabled (AGENT_DISABLE_SKILLS=false)
✅ VideoDB read-only access
✅ 8 search/query tools
❌ No file modifications
❌ No shell commands
Channel: #librarian
```

### Isolation

Each agent has:
- Separate session workspace
- Separate Discord bindings
- Separate tool permissions
- Separate configuration

Modifications to one agent **do not affect** the other.

---

## Debugging

### Check Agent Status

```bash
# List registered agents
docker exec -it openclaw-gateway \
  node dist/index.js agent list

# Get Librarian status
docker exec -it openclaw-gateway \
  node dist/index.js agent status librarian

# View session history
ls -la data/openclaw/workspace/agents/librarian/sessions/
```

### View MCP Tool Discovery

```bash
# List available tools
docker compose logs openclaw-gateway 2>&1 | grep -i "tool\|mcp"

# Test MCP connection
docker exec -it openclaw-gateway \
  curl http://localhost:9001/tools

# Check MCP server process
ps aux | grep mcp_server.py
```

### Check Discord Binding

```bash
# Verify agent is listening to Discord channel
docker compose logs openclaw-gateway 2>&1 | grep -i "discord\|librarian"

# Verify mention requirement is enabled
grep -A 10 "librarian" data/openclaw/state/openclaw.json
```

### Enable Debug Logging

```bash
# In .env.local:
LOG_LEVEL=debug
OPENCLAW_DEBUG=1

# Restart:
docker compose restart openclaw-gateway

# View debug logs:
docker compose logs -f openclaw-gateway
```

---

## Configuration Files

### infra/openclaw/agents/librarian/SOUL.md
Agent identity, mission, constraints, and behaviors.

### infra/openclaw/agents/librarian/instructions.md
Detailed operating procedures for all MCP tools and workflows.

### infra/openclaw/agents/librarian/AGENTS.md
This file — registry, deployment, security, and debugging.

### infra/openclaw/docker-compose.yml
Service definition with environment variables and volume mounts.

### data/openclaw/state/openclaw.json
Active configuration (generated/managed by OpenClaw runtime).

### .env.local
Runtime secrets (Discord token, OpenAI key, etc.). Git-ignored.

---

## Related Documentation

- **Identity & Behavior**: [SOUL.md](./SOUL.md)
- **Operating Procedures**: [instructions.md](./instructions.md)
- **Deployment Guide**: [../../README.md](../../README.md)
- **Health Checks**: [../../HEALTH.md](../../HEALTH.md)
- **Discord Integration**: [../../discord-config.patch.json5](../../discord-config.patch.json5)
- **MCP Server**: [../../../apps/video_pipeline/MCP_SERVER_README.md](../../../apps/video_pipeline/MCP_SERVER_README.md)

---

**Version**: 1.0  
**Last Updated**: 2026-11-08  
**Status**: Production
