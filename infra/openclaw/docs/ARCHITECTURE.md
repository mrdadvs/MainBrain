# MainBrain OpenClaw Architecture (Working Reference)

Validated against running stack on OpenClaw `2026.11.1`.

## 1) Runtime containers (actual)

| Container | Image | Purpose | Networks |
|---|---|---|---|
| `openclaw-gateway` | `openclaw/openclaw:2026.11.1` | Live OpenClaw gateway + agents | `openclaw_openclaw-network` |
| `videodb-mcp` | `mainbrain-videodb-mcp:checkpoint3` | VideoDB MCP Streamable HTTP server | `openclaw_openclaw-network`, `postgres_default` |
| `mainbrain-postgres` | `postgres:16` | VideoDB PostgreSQL | `postgres_default` |
| `openclaw-openclaw-cli-1` | `openclaw/openclaw:2026.11.1` | Optional CLI sidecar | shared with gateway service |

Notes:
- MCP is private to Docker (`videodb-mcp` exposes `9001` internally, no host/LAN publish).
- Gateway is host-local only (`127.0.0.1:18789`).

## 2) Persistent paths and live config

`openclaw-gateway` bind mounts (actual):

| Host path | Container path | Use |
|---|---|---|
| `data/openclaw/state` | `/home/node/.openclaw` | live OpenClaw state + active `openclaw.json` |
| `data/openclaw/workspace` | `/home/node/.openclaw/workspace` | per-agent runtime workspaces (`AGENTS.md`, `SOUL.md`) |
| `data/openclaw/secrets` | `/home/node/.config/openclaw` | OpenClaw auth/secrets profile data |

Active config file inside container:

```bash
docker exec openclaw-gateway openclaw config file
# /home/node/.openclaw/openclaw.json
```

Host file for that path:
- `data/openclaw/state/openclaw.json`

## 3) Discord account -> agent routing (working pattern)

Live behavior uses:
- `channels.discord.defaultAccount = "default"`
- `channels.discord.accounts.<accountId>` for additional bot accounts
- top-level `bindings[]` for account-to-agent routing

Current routing pattern:
- `accountId: "librarian"` -> `agentId: "librarian"`
- `accountId: "*"` -> `agentId: "main"` fallback

Important:
- `bindings` is an array; patching it replaces the whole array. Preserve existing entries when adding a new one.

## 4) MCP tool exposure path

1. MCP server defined at `mcp.servers.videodb` with:
   - `transport: "streamable-http"`
   - `url: "http://videodb-mcp:9001/mcp"`
   - `toolFilter.include`: base tool names (no prefix), e.g. `search_transcripts`
2. At runtime, OpenClaw exposes those to agents as prefixed tools:
   - `videodb__search_transcripts`, `videodb__list_videos`, etc.
3. Per-agent allow/deny is enforced in `agents.entries.<id>.tools`.

## 5) Git-tracked templates vs live runtime config

Git-tracked (authoring/templates):
- `infra/openclaw/docker-compose.yml`
- `infra/openclaw/openclaw.json` (legacy/template reference, not active runtime file)
- `infra/openclaw/discord-config.patch.template.json5`
- `infra/openclaw/agents/` (reference instruction content)
- `infra/openclaw/docs/`

Live runtime state (mounted and mutable):
- `data/openclaw/state/openclaw.json` (authoritative live config)
- `data/openclaw/workspace/<agent-id>/` (runtime instructions and session context)

Deployment rule:
1. Update git-tracked templates/reference files.
2. Copy/update runtime instruction files under `data/openclaw/workspace/<agent-id>/`.
3. Apply config changes via `openclaw config patch`.
4. Verify with live `config get` + session/tool traces.

## 6) Verified operator commands

```bash
# Version
docker exec openclaw-gateway openclaw --version

# Inspect effective Discord + bindings
docker exec openclaw-gateway openclaw config get channels.discord --json
docker exec openclaw-gateway openclaw config get bindings --json

# Validate/apply patch
docker exec -i openclaw-gateway openclaw config patch --stdin --dry-run --json < patch.json5
docker exec -i openclaw-gateway openclaw config patch --stdin < patch.json5

# Connectivity
docker exec openclaw-gateway openclaw channels status --json --probe
docker exec openclaw-gateway openclaw agents list --json --bindings
```
