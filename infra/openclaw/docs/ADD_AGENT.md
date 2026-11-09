# Add a New OpenClaw Agent (Checklist)

Use this checklist exactly; keep changes minimal and validated.

## Execution context

- Run commands from `~/mainbrain`.
- Commands below use repo-relative paths and `docker exec`; no directory change is required.
- Only if you run `docker compose` directly, run it from `~/mainbrain/infra/openclaw`.

## 0) Preflight + mandatory backup/rollback plan

```bash
cd ~/mainbrain
docker exec openclaw-gateway openclaw --version
docker exec openclaw-gateway openclaw config file
docker exec openclaw-gateway openclaw config get bindings --json
```

- Confirm you are editing the live runtime config (`/home/node/.openclaw/openclaw.json` inside container).
- Do **not** edit `data/openclaw/state/openclaw.json` manually.

Create a mandatory pre-change backup:

```bash
cd ~/mainbrain
TS="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p data/backups/openclaw
cp data/openclaw/state/openclaw.json "data/backups/openclaw/openclaw.${TS}.json"
echo "Backup: data/backups/openclaw/openclaw.${TS}.json"
```

Rollback procedure (if anything regresses):

```bash
cd ~/mainbrain
# replace <TIMESTAMP> with the backup timestamp you created
cp "data/backups/openclaw/openclaw.<TIMESTAMP>.json" data/openclaw/state/openclaw.json
docker exec openclaw-gateway openclaw config validate
docker exec openclaw-gateway openclaw channels status --json --probe
```

## Source of truth (important)

- Git-tracked authoring templates:
  - `infra/openclaw/docs/AGENT_TEMPLATE/`
- Runtime instructions actually used by OpenClaw:
  - `data/openclaw/workspace/<agent-id>/AGENTS.md`
  - `data/openclaw/workspace/<agent-id>/SOUL.md`
- Live config source of truth:
  - `data/openclaw/state/openclaw.json` (managed via `openclaw config patch`)

Deployment model: edit templates in git, copy/update runtime workspace files, patch live config, then validate with real runs.

## 1) Create agent workspace and runtime instructions

```bash
cd ~/mainbrain
AGENT_ID="<agent-id>"
mkdir -p "data/openclaw/workspace/${AGENT_ID}"
cp infra/openclaw/docs/AGENT_TEMPLATE/AGENTS.md "data/openclaw/workspace/${AGENT_ID}/AGENTS.md"
cp infra/openclaw/docs/AGENT_TEMPLATE/SOUL.md "data/openclaw/workspace/${AGENT_ID}/SOUL.md"
```

Edit placeholders in those two files.

## STOP checkpoint A

STOP after this checkpoint and confirm:
- runtime workspace files are prepared
- config patch draft is prepared
- no live config has been changed yet

## 2) Register the agent in OpenClaw config

Use a patch derived from:
- `infra/openclaw/docs/AGENT_TEMPLATE/agent.patch.template.json5`

Set:
- agent ID/name/description
- workspace path (`/home/node/.openclaw/workspace/<agent-id>`)
- model (explicit)
- `tools.allow` list (least privilege)

## 3) Configure MCP/tool access

- Ensure required MCP server exists under `mcp.servers`.
- Ensure agent allowlist uses runtime tool names (`serverprefix__tool` style).
  - Example: `videodb__search_transcripts`

Inspect current MCP config:

```bash
cd ~/mainbrain
docker exec openclaw-gateway openclaw mcp show videodb --json
docker exec openclaw-gateway openclaw config get agents.entries.${AGENT_ID}.tools --json
```

## 4) Create Discord app/bot for this agent

In Discord Developer Portal:

1. Create application and bot.
2. Installation mode:
   - Enable **Guild Install**
   - Keep **User Install** off unless explicitly needed
3. Privileged gateway intents:
   - Enable **Message Content Intent**
   - Keep Presence / Server Members off unless required
4. Bot permissions (minimum for this deployment pattern):
   - View Channels
   - Send Messages
   - Send Messages in Threads
   - Read Message History
   - Add Reactions (optional but recommended)
   - Use Application Commands
5. Invite bot to existing MainBrain Discord server.
6. Create dedicated channel for this agent.

## 5) Record token securely (no plaintext in git)

Verified for OpenClaw `2026.11.1`:

```bash
docker exec openclaw-gateway openclaw secrets store set --help
```

Secure token input (no token in shell history):

```bash
cd ~/mainbrain
read -rsp "Discord bot token: " DISCORD_TOKEN; echo
printf '%s' "$DISCORD_TOKEN" | docker exec -i openclaw-gateway \
  openclaw secrets store set DISCORD_<AGENT_KEY>_BOT_TOKEN \
  --kind secret --value-file -
unset DISCORD_TOKEN
```

Verification without revealing credentials:

```bash
docker exec openclaw-gateway openclaw secrets store list --json
docker exec openclaw-gateway openclaw config get channels.discord.accounts.<discord-account-id>.token --json
```

Notes:
- `secrets store list` shows metadata only (name/kind/timestamps).
- Secret values are write-only (`openclaw secrets store get` does not reveal secret-kind values).

## 6) Configure `channels.discord.accounts` and bindings

Patch must include:
- `channels.discord.accounts.<discord-account-id>`
- allowlist (`guilds -> users/channels`)
- `requireMention: true`
- `dmPolicy: "disabled"` (if using channel-only bot)
- binding:
  - `{ agentId: "<agent-id>", match: { channel: "discord", accountId: "<discord-account-id>" } }`

Keep fallback binding for existing agents.

## 7) Dry-run, then apply

```bash
cd ~/mainbrain
# dry-run first (required)
docker exec -i openclaw-gateway openclaw config patch --stdin --dry-run --json < /path/to/patch.json5

# apply only if dry-run passes
docker exec -i openclaw-gateway openclaw config patch --stdin < /path/to/patch.json5
```

Before dry-run, confirm your patch preserves existing objects/arrays:

```bash
cd ~/mainbrain
docker exec openclaw-gateway openclaw config get agents.entries --json
docker exec openclaw-gateway openclaw config get channels.discord.accounts --json
docker exec openclaw-gateway openclaw config get bindings --json
```

`agents.entries` and `channels.discord.accounts` are object-merges; `bindings` is array-replace (must include existing entries).

## STOP checkpoint B

STOP after this checkpoint and confirm:
- Discord bot account exists and token is stored
- config patch is applied
- routing/bindings are correct
- no tests run yet

## 8) Validate effective config

```bash
cd ~/mainbrain
docker exec openclaw-gateway openclaw config get agents.entries.<agent-id> --json
docker exec openclaw-gateway openclaw config get channels.discord.accounts.<discord-account-id> --json
docker exec openclaw-gateway openclaw config get bindings --json
docker exec openclaw-gateway openclaw channels status --json --probe
docker exec openclaw-gateway openclaw agents list --json --bindings
```

## 9) Test real Discord behavior + tool call trace

1. In the new Discord channel, mention the new bot with a real task.
2. Verify session and tool invocation:

```bash
cd ~/mainbrain
docker exec openclaw-gateway openclaw sessions --agent <agent-id> --active 30 --limit 5
docker exec openclaw-gateway openclaw sessions tail --agent <agent-id> --tail 80
```

Expected trace includes:
- `context.compiled` with tool count
- `tool.call` for expected tool(s)
- `tool.result ... ok`
- `session.ended ... success`

## 10) Regression-check existing agents

1. Send one message to each existing bot/channel.
2. Confirm each still routes to the intended agent:

```bash
cd ~/mainbrain
docker exec openclaw-gateway openclaw sessions --all-agents --active 30 --limit 20
docker exec openclaw-gateway openclaw channels status --json --probe
```

If regression appears, revert with a small corrective patch (do not broad-refactor config).

## STOP checkpoint C

STOP after this checkpoint and confirm:
- end-to-end Discord test passed for the new agent
- expected tool calls are present in session trace
- existing agents still function in their own channels/accounts
