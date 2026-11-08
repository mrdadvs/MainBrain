# OpenClaw Discord Gateway - Verified Deployment

**Status: ✅ READY FOR TESTING**

## Deployment Confirmed

- **Image:** `openclaw/openclaw:2026.11.1@sha256:db0e0809fbd0df375445e9eea8daf2a278ac7ac3a263fa6bfce8fb344ad3ad77`
- **Gateway URL:** `http://127.0.0.1:18789`
- **Gateway Status:** ✅ Healthy and responding
- **Discord Bot:** ✅ Connected and authenticated as @MainBrain Test
- **Configuration:** ✅ Applied via official `openclaw config patch` command
- **Persistent State:** `/home/mdv/mainbrain/data/openclaw/`

## Verified Configuration

Discord channel is configured with:
- **Policy:** Allowlist (only specified server/user/channel)
- **Server:** MainBrain (1568656073898987651)
- **Channel:** #agent-test (1568656457929334944)
- **User:** Single Discord user allowed (1568655444321243136)
- **Interaction Mode:** Mention-required (chat-only)
- **Bot Token:** Loaded from environment variable (DISCORD_BOT_TOKEN)
- **DM Policy:** Disabled (channel-only)

## Configuration Method

Configuration applied using official OpenClaw documentation approach:

1. Created template: `infra/openclaw/discord-config.patch.template.json5`
2. Instantiated with actual IDs from `infra/openclaw/.env.local` (credentials file)
3. Applied using: `docker exec openclaw-gateway openclaw config patch --file /tmp/discord-config.patch.json5`
4. Validated with `--dry-run` before applying
5. Applied without requiring gateway restart

## Verification Steps Completed

```bash
# 1. Confirm gateway is responding
curl http://127.0.0.1:18789/health
# Response: {"ok": true, "status": "live"}

# 2. Confirm Discord is connected
docker exec openclaw-gateway openclaw channels status
# Response: Discord default: enabled, configured, running, connected, 
#           bot:@MainBrain Test, transport:just now

# 3. Confirm in logs
docker compose -f infra/openclaw/docker-compose.yml logs openclaw-gateway | grep -i discord
# Shows: Discord bot initialized, Message Content Intent configured, 
#        client awaiting gateway readiness
```

## Next: Test Actual Discord Messages

Send test messages in Discord #agent-test channel:
- Message 1: `@MainBrain Test hello`
- Message 2: `@MainBrain Test what is your name?`

Both should receive replies from the gateway.

## Docker-Tracked Configuration

All infrastructure is Git-tracked in `infra/openclaw/`:
- ✅ docker-compose.yml - Official OpenClaw image with correct ports/bind
- ✅ scripts/deploy.sh - Orchestration with env-file loading
- ✅ discord-config.patch.template.json5 - Reproducible Discord config template
- ✅ .env.example - Template for required credentials
- ✅ .gitignore - Excludes secrets, state, and instantiated configs

Secrets remain protected:
- ✅ DISCORD_BOT_TOKEN in .env.local (mode 600, git-ignored)
- ✅ OPENAI_API_KEY in .env.local (mode 600, git-ignored)
- ✅ OPENCLAW_GATEWAY_TOKEN in .env.local (mode 600, git-ignored)

## Known Limitations (By Design)

For this pilot phase:
- Only chat messages supported (no tools, file access, or system execution)
- Only specified Discord user can interact
- Only #agent-test channel monitored
- DMs disabled
- No skills or plugins beyond built-in chat capabilities
- VideoDB, NAS, and other MainBrain services not connected

Expansion to additional agents, tools, and services will be added in future phases with explicit security review.

## Troubleshooting

If Discord doesn't receive replies:

1. Verify container is healthy:
   ```bash
   docker ps | grep openclaw-gateway
   # Should show: (healthy)
   ```

2. Check Discord connection logs:
   ```bash
   docker compose -f infra/openclaw/docker-compose.yml logs openclaw-gateway | tail -50
   ```

3. Verify configuration was applied:
   ```bash
   docker exec openclaw-gateway cat /home/node/.openclaw/openclaw.json | \
     python3 -m json.tool | grep -A 30 "discord"
   ```

4. Check that bot token and Discord IDs are correct in .env.local:
   ```bash
   grep DISCORD infra/openclaw/.env.local
   ```

5. Restart if needed:
   ```bash
   bash infra/openclaw/scripts/deploy.sh restart
   ```

## Rollback

If issues arise, rollback to a known state:

```bash
cd /home/mdv/mainbrain

# Stop current deployment
bash infra/openclaw/scripts/deploy.sh down

# Restore previous OpenClaw state (if backup exists)
bash infra/openclaw/scripts/restore-state.sh

# Restart
bash infra/openclaw/scripts/deploy.sh up
```

## Next Phase

Once Discord messaging is verified:
1. Configure proper logging and monitoring
2. Add agent instructions and model selection
3. Prepare for multi-agent setup (Librarian, Director, Animator)
4. Document tool restrictions and security boundaries
5. Plan VideoDB and NAS integration (separate phase)
