# Agent Template Usage

This folder is the minimal starting point for a new agent.

## Files

- `AGENTS.md` - runtime behavior rules
- `SOUL.md` - identity/mission/constraints
- `agent.patch.template.json5` - OpenClaw config patch template

## How to use

0. Run from `~/mainbrain` (commands below assume this working directory).
1. Copy `AGENTS.md` + `SOUL.md` into:
   - `data/openclaw/workspace/<agent-id>/`
2. Replace placeholders (`<...>`).
3. Copy `agent.patch.template.json5` to a new patch file and replace placeholders.
4. Pull current config sections and merge them into your patch:

```bash
docker exec openclaw-gateway openclaw config get agents.entries --json
docker exec openclaw-gateway openclaw config get channels.discord.accounts --json
docker exec openclaw-gateway openclaw config get bindings --json
```

5. Preserve existing entries:
   - `agents.entries` and `channels.discord.accounts` are object-merges; do not remove existing keys.
   - `bindings` is array-replace; include all existing bindings plus your new one.
   - Keep fallback routes unless intentionally changing routing.

6. Validate and apply:

```bash
docker exec -i openclaw-gateway openclaw config patch --stdin --dry-run --json < /path/to/patch.json5
docker exec -i openclaw-gateway openclaw config patch --stdin < /path/to/patch.json5
```

7. Verify via Discord + `openclaw sessions tail --agent <agent-id>`.

## Placeholder key

- `<AGENT_ID>`: OpenClaw agent ID (e.g. `researcher`)
- `<AGENT_NAME>`: display name
- `<DISCORD_ACCOUNT_ID>`: account key under `channels.discord.accounts`
- `<DISCORD_GUILD_ID>`: Discord server ID
- `<DISCORD_ALLOWED_USER_ID>`: allowed user ID
- `<DISCORD_CHANNEL_ID>`: dedicated channel ID
- `<MODEL_ID>`: model (e.g. `openai/gpt-6-luna`)
- `<ALLOWED_TOOL_*>`: runtime tool names (e.g. `videodb__search_transcripts`)
