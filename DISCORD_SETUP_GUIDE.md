# Job 3: Discord Multi-Agent Routing Setup

**Objective**: Enable separate Discord identities for MainBrain Test and Librarian agents through OpenClaw multi-agent routing.

**Status**: Configuration templates ready, awaiting Discord bot setup.

---

## Quick Summary

- **MainBrain Test**: Existing chat-only agent in `#agent-test` channel
- **Librarian**: New agent in `#librarian` channel with VideoDB search access
- **Protocol**: Both use same Discord bot application, routed by channel
- **Security**: Mention-required, user allowlist, read-only access

---

## Step 1: Create Discord Application (If Needed)

If you already have the MainBrain Test bot configured, you may reuse it. Otherwise:

### 1a. Go to Discord Developer Portal
```
https://discord.com/developers/applications
```

### 1b. Create New Application
- Click "New Application"
- Name: `MainBrain` (or `MainBrain Librarian` for separate app)
- Accept terms and Create

### 1c. Generate Bot User
- Go to "Bot" → "Add Bot"
- Copy token (you'll need this for `DISCORD_BOT_TOKEN`)
- Enable "Message Content Intent" (required to read message text)

### 1d. Set Permissions
Go to OAuth2 → URL Generator:
- Scopes: `bot`
- Permissions:
  - `Send Messages`
  - `Read Messages/View Channels`
  - `Read Message History`

- Copy generated URL and use it to invite bot to your server

---

## Step 2: Set Up Discord Server Channels

Create two channels in your existing MainBrain server:

### Channel 1: #agent-test
- For MainBrain Test agent (chat-only, existing)
- Topic: "Validation of OpenClaw infrastructure"
- Visibility: Private to your user

### Channel 2: #librarian
- For Librarian agent (VideoDB search)
- Topic: "Search GoPro footage and transcripts"
- Visibility: Private to your user

---

## Step 3: Configure OpenClaw

### 3a. Update Environment Variables

In `/home/mdv/mainbrain/infra/openclaw/.env.local`:

```bash
# Discord bot configuration
DISCORD_BOT_TOKEN=your_bot_token_here

# Your Discord user ID (get from Developer Mode: Right-click user → Copy User ID)
YOUR_USER_ID=123456789012345678

# AI provider (OpenAI, or alternative)
OPENAI_API_KEY=your_openai_key_here
OPENAI_BASE_URL=https://api.openai.com/v1

# OpenClaw gateway token (generate with `openssl rand -hex 32`)
OPENCLAW_GATEWAY_TOKEN=your_gateway_token_here

# Timezone
OPENCLAW_TZ=America/Los_Angeles
```

### 3b. Update Configuration File

Edit `/home/mdv/mainbrain/infra/openclaw/openclaw.json`:

Replace these placeholders with actual values:

1. **Channel IDs**: Get from Discord (Developer Mode → Right-click channel → Copy Channel ID)
   ```json
   "bindings": {
     "discord": {
       "channel_id": "YOUR_CHANNEL_ID_HERE"
     }
   }
   ```

2. **User IDs**: Your Discord user ID
   ```json
   "allowed_user_ids": ["YOUR_USER_ID"]
   ```

3. **Discord Token**: Will be loaded from `DISCORD_BOT_TOKEN` env var
   ```json
   "bot_token": "${DISCORD_BOT_TOKEN}"
   ```

### 3c. Verify MCP Configuration

In `openclaw.json`, the MCP server is configured as:

```json
{
  "id": "videodb-mcp",
  "type": "stdio",
  "command": "python3",
  "args": ["/home/mdv/mainbrain/apps/video_pipeline/mcp_server.py"],
  "envfile": "/home/mdv/mainbrain/apps/video_pipeline/.env.mcp",
  "auto_start": true
}
```

This will:
- Auto-start MCP server when OpenClaw gateway starts
- Pass `videodb_reader` credentials from `.env.mcp`
- Make all 8 tools available to Librarian only

---

## Step 4: Start OpenClaw with Librarian

```bash
cd /home/mdv/mainbrain/infra/openclaw

# Start the gateway (includes MCP server auto-start)
docker compose up -d openclaw-gateway

# Monitor gateway startup
docker compose logs -f openclaw-gateway

# Check MCP server initialization
docker compose logs openclaw-gateway | grep -i "mcp\|videodb"
```

### Expected Output

```
openclaw-gateway | INFO: MCP server "videodb-mcp" started (PID ...)
openclaw-gateway | INFO: Librarian agent loaded with 8 tools
openclaw-gateway | INFO: MainBrain Test agent loaded (chat-only)
openclaw-gateway | INFO: Discord gateway connected
openclaw-gateway | INFO: Gateway listening on port 18789
```

---

## Step 5: Test Discord Integration

### 5a. Test MainBrain Test (Should still work)

In `#agent-test` channel:
```
@MainBrain Test Hello! Are you working?
```

**Expected**: MainBrain Test responds with a greeting.

### 5b. Test Librarian (New agent)

In `#librarian` channel:
```
@Librarian Find the GoPro video where I mention an IP address. Give me the filename, VideoDB ID, and timestamp.
```

**Expected Output**:
```
Librarian responds:
Found 1 video matching "IP address":

Video #64: GX011154.MP4
Timestamp: 2.29s - 6.53s
Text: "Computers everywhere, funny IP address..."

Details:
- Duration: 6.24 seconds
- Resolution: 3840x2160
- FPS: 29.97
```

### 5c. Verify Security

Send message from different Discord user (if available):
```
@Librarian List all videos
```

**Expected**: Rejected with "Unauthorized user" or similar (based on allow list)

---

## Step 6: Verify Configuration Persists

Restart the gateway:
```bash
docker compose restart openclaw-gateway
docker compose logs openclaw-gateway | grep -i "librarian\|test"
```

**Expected**:
- Both agents load again
- MCP server reconnects
- No errors in logs

---

## Troubleshooting

### MCP Server Won't Start

Check if Python MCP server is running on host:
```bash
cd /home/mdv/mainbrain/apps/video_pipeline
python3 mcp_server.py
```

Should print:
```
2026-11-08 14:22:47 - __main__ - INFO - Starting MainBrain VideoDB MCP Server
2026-11-08 14:22:47 - __main__ - INFO - MCP server ready, listening on stdio
```

If error, check:
1. Python dependencies: `pip install -r requirements.txt`
2. Database connection: `psql -h localhost -U videodb_reader -d mainbrain -c "SELECT 1"`
3. .env.mcp file: `cat apps/video_pipeline/.env.mcp | head -3`

### Discord Bot Not Responding

1. Verify token is correct in `.env.local`:
   ```bash
   grep DISCORD_BOT_TOKEN infra/openclaw/.env.local
   ```

2. Check bot has correct permissions in server:
   - Right-click bot role in server
   - Ensure "Send Messages" and "Read Message History" are enabled

3. Check if bot is mentioned correctly:
   ```
   @MainBrain Test hello  ✅ Correct
   @mainbrain test hello  ❌ Case sensitive
   MainBrain Test hello   ❌ Requires mention
   ```

4. Check OpenClaw logs:
   ```bash
   docker compose logs openclaw-gateway | grep -i discord
   ```

### Librarian Returns Empty Results

Test MCP directly:
```bash
cd /home/mdv/mainbrain/apps/video_pipeline
python3 << 'EOF'
from dotenv import load_dotenv
load_dotenv('.env.mcp')
from db import SessionLocal
from models import TranscriptSegment
session = SessionLocal()
results = session.query(TranscriptSegment).filter(
    TranscriptSegment.text.ilike("%IP address%")
).all()
print(f"Found {len(results)} results")
for r in results:
    print(f"  Video #{r.video_id}: {r.text[:50]}")
EOF
```

If no results, check:
1. Transcript data exists: `psql -h localhost -U videodb_reader -d mainbrain -c "SELECT COUNT(*) FROM transcript_segments;"`
2. Query syntax: Try simpler search terms
3. Video data exists: `psql -h localhost -U videodb_reader -d mainbrain -c "SELECT COUNT(*) FROM videos;"`

### Librarian Can't Access Tools

Check `openclaw.json`:
1. Librarian agent has `"tools"` array with 8 MCP tool bindings
2. MCP server ID `videodb-mcp` is defined in `mcp_servers` section
3. Tool names match exactly: `search_transcripts`, `list_videos`, etc.

Restart gateway:
```bash
docker compose restart openclaw-gateway
sleep 5
docker compose logs openclaw-gateway | grep -i librarian
```

---

## Security Checklist

- ✅ Discord token stored in `.env.local` (git-ignored)
- ✅ User allowlist restricts to your Discord ID only
- ✅ Librarian mention-required (prevents accidental public use)
- ✅ MCP server read-only (no write access via database role)
- ✅ Each agent has isolated tool permissions
- ✅ MainBrain Test agent remains chat-only (no tools)
- ✅ No secrets in openclaw.json (uses env var substitution)
- ✅ No Docker socket or shell access granted

---

## Next Steps

1. Get Discord bot token and update `.env.local`
2. Get Discord channel IDs and user ID
3. Update `openclaw.json` with actual IDs
4. Start OpenClaw: `docker compose up -d openclaw-gateway`
5. Test Discord: `@Librarian Find the IP address video`
6. Commit configuration to Git

---

**Date**: 2026-11-08  
**Status**: Template Ready — Awaiting Discord Setup
