# MainBrain OpenClaw Troubleshooting (Verified Fixes)

Focused on issues we actually hit and the working resolution.

## 1) `.env.local` vs running container environment

**Symptom**
Config dry-run fails with missing env secret refs (for new Discord account token).

**Cause**
`openclaw-gateway` only sees environment injected at container start (compose env/`env_file`), not host-only edits in `.env.local` unless wired and restarted.

**Verified fix**
Use OpenClaw secret store for additional bot tokens:

```bash
docker exec -i openclaw-gateway \
  openclaw secrets store set DISCORD_<AGENT_KEY>_BOT_TOKEN \
  --kind secret --value-file -
```

Then reference token as:

```json5
token: { source: "store", provider: "default", id: "DISCORD_<AGENT_KEY>_BOT_TOKEN" }
```

---

## 2) Wrong config file edited

**Symptom**
Edits in repo template do not change live behavior.

**Cause**
Live gateway reads mounted runtime config, not template file.

**Verified fix**

```bash
docker exec openclaw-gateway openclaw config file
# /home/node/.openclaw/openclaw.json
```

Host path is `data/openclaw/state/openclaw.json` via bind mount.

---

## 3) MCP transport mismatch (stdio vs HTTP)

**Symptom**
Custom HTTP wrapper path was unreliable; tool usage unstable.

**Cause**
Non-minimal custom transport layer added failure surface.

**Verified fix**
Use official MCP Streamable HTTP transport in `mcp_server_http.py`, reusing existing `mcp_server.py` tool handlers, with:
- health endpoint
- DB check at startup
- `mcp.servers.videodb.transport = "streamable-http"`
- URL `http://videodb-mcp:9001/mcp`

---

## 4) Docker networking / DB hostname

**Symptom**
MCP container cannot reach PostgreSQL.

**Cause**
Network path or hostname mismatch.

**Verified fix**
- Keep gateway on `openclaw_openclaw-network`.
- Attach `videodb-mcp` to both:
  - `openclaw_openclaw-network` (for gateway -> MCP)
  - `postgres_default` (for MCP -> DB)
- Use DB host reachable on `postgres_default` (`mainbrain-postgres`).

---

## 5) Tools registered but not actually called

**Symptom**
Agent replies in text without invoking MCP tool.

**Cause**
Tool catalog presence alone is insufficient; model may still choose no tool.

**Verified checks**
- Confirm per-agent allowlist in config.
- Confirm runtime trace includes actual `tool.call`.

```bash
docker exec openclaw-gateway openclaw sessions tail --agent <agent-id> --tail 80
```

Look for:
- `tool.call ... <expected_tool>`
- `tool.result ... ok`

---

## 6) Tool permissions and runaway subagents

**Symptom**
Agent loops/delegates unexpectedly (session explosion).

**Cause**
Over-broad tool surface (e.g. `sessions_spawn`/generic messaging tools) for a narrowly scoped agent.

**Verified fix**
- Restrict tools to required MCP tools only.
- Remove unrelated control/delegation tools for that agent.
- Keep explicit account binding for deterministic routing.

---

## 7) Provider rate limits during churn

**Symptom**
Slow/failing runs, repeated retries, unstable behavior.

**Cause**
High run churn from recursive/delegated behavior.

**Verified fix**
- Cancel only active runaway parent/children.
- Re-test with one clean session and strict timeout.
- Do not run parallel retries during diagnosis.

---

## 8) Model behavior differences

**Symptom**
`gpt-4o-mini` returned text without tool call in this workload.

**Verified result**
- Same agent/tool config with `openai/gpt-6-luna` successfully called `videodb__search_transcripts` and returned expected VideoDB result.

**Operational guidance**
- Treat model selection as part of tool reliability testing.
- Validate with real `tool.call` trace, not only final text.

---

## 9) Discord allowlists / mention gating / account routing

**Symptom**
Bot connected but not responding in intended channel or responding in wrong scope.

**Cause**
Missing/incorrect guild channel allowlist, mention policy, or account->agent binding.

**Verified fix**
- For each account under `channels.discord.accounts.<id>`:
  - `groupPolicy: "allowlist"`
  - `guilds.<guildId>.channels.<channelId>.enabled: true`
  - `users` allowlist (if required)
  - `requireMention: true`
- Add binding:
  - `match.channel = "discord"`
  - `match.accountId = "<account-id>"`
  - `agentId = "<agent-id>"`
- Validate:

```bash
docker exec openclaw-gateway openclaw channels status --json --probe
docker exec openclaw-gateway openclaw config get bindings --json
```
