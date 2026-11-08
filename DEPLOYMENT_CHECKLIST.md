# ✅ OpenClaw Discord Deployment Checklist

Use this checklist as you deploy. Check off each item as you complete it.

---

## Pre-Deployment (5 min)

Before you start, verify you have all three credentials ready (don't paste them here):

- [ ] Discord Bot Token (from Discord Developer Portal)
- [ ] OpenAI API Key (from OpenAI platform)
- [ ] Your Discord User ID (right-click username → Copy ID)
- [ ] MainBrain Server ID (right-click server → Copy ID)
- [ ] #agent-test Channel ID (right-click channel → Copy ID)

---

## Step 1: SSH & Navigate (1 min)

```bash
ssh mainbrain
cd ~/mainbrain
```

- [ ] SSH connection successful
- [ ] In ~/mainbrain directory

---

## Step 2: Setup Credentials (3 min)

```bash
bash infra/openclaw/setup-credentials.sh
```

When prompted:
- [ ] Entered Discord Bot Token (silent)
- [ ] Entered OpenAI API Key (silent)
- [ ] Entered Discord User ID
- [ ] Entered MainBrain Server ID
- [ ] Entered #agent-test Channel ID
- [ ] Script reported "✓ All credentials saved"
- [ ] Script reported ".env.local is git-ignored"

Verify:
```bash
test -f infra/openclaw/.env.local && echo "✓ .env.local exists" || echo "✗ MISSING"
test ! -z "$(grep DISCORD_BOT_TOKEN infra/openclaw/.env.local)" && echo "✓ Credentials loaded" || echo "✗ EMPTY"
```

- [ ] .env.local file exists
- [ ] Credentials are loaded (first check passed)

---

## Step 3: Deploy Container (2 min)

```bash
bash infra/openclaw/scripts/deploy.sh up
```

Expected output:
```
[*] Validating credentials...
[✓] All credentials validated
[✓] Starting container...
[+] Running 1/1
  ✔ openclaw-gateway  Running
```

- [ ] All credential checks passed
- [ ] Container started successfully
- [ ] No error messages in output

---

## Step 4: Verify Bot Is Online (1 min)

In Discord, go to #agent-test channel.

- [ ] MainBrain Test bot appears in member list
- [ ] Bot status shows as "Online"

If not online after 30 seconds:
```bash
bash infra/openclaw/scripts/logs.sh | tail -20
```

Look for:
```
Connected to Discord!
Agent initialized
```

- [ ] Bot connected to Discord (check logs)
- [ ] No error messages in logs

---

## Step 5: Test First Message (2 min)

In #agent-test channel, send:
```
@MainBrain Test What is 2 + 2?
```

- [ ] Message sent successfully
- [ ] Bot started typing (three dots appear)
- [ ] Bot replied within 5–10 seconds
- [ ] Response is correct (mentions "4" or similar)

If no reply after 10 seconds, check logs:
```bash
bash infra/openclaw/scripts/logs.sh
```

---

## Step 6: Test Second Message (2 min)

Send a different message:
```
@MainBrain Test Tell me a joke.
```

- [ ] Message sent successfully
- [ ] Bot started typing
- [ ] Bot replied within 5–10 seconds
- [ ] Response is different from first reply (distinct content)
- [ ] Response seems reasonable (joke or humor)

---

## Step 7: Test Container Restart (3 min)

Stop and restart the container:
```bash
docker compose -f infra/openclaw/docker-compose.yml down
docker compose -f infra/openclaw/docker-compose.yml up -d
```

Wait 10 seconds for startup.

- [ ] Container stopped cleanly
- [ ] Container restarted
- [ ] Bot appears online again in Discord

Send a message:
```
@MainBrain Test Hi, I restarted you!
```

- [ ] Bot responds
- [ ] Configuration persisted (no re-entry needed)
- [ ] Service available after restart

---

## Step 8: Record Success in Git (1 min)

```bash
cd ~/mainbrain
git log --oneline -3
git status
```

You should see:
- Recent commits for docker-compose.yml fix and deployment guide
- `.env.local` should NOT appear in git status
- No uncommitted changes related to OpenClaw (other files may be untracked)

- [ ] Recent commits visible
- [ ] .env.local NOT in Git
- [ ] No secrets leaked to Git

---

## Success Criteria Met ✅

If all items above are checked:

✅ **OpenClaw Discord deployment is working**
✅ **Bot reliably responds to mentions**
✅ **Configuration persists across restarts**
✅ **Secrets are protected (not in Git)**
✅ **Chat-only restrictions enforced**

---

## Troubleshooting Quick Reference

| Issue | Check | Solution |
|-------|-------|----------|
| Bot doesn't appear online | Logs: `bash infra/openclaw/scripts/logs.sh` | Verify Discord token is correct |
| Bot is online but doesn't reply | Make sure you mentioned bot with `@MainBrain Test` | Only responds to mentions in #agent-test |
| Container won't start | Check port: `lsof -i :18789` | Port 18789 in use; check for stray container |
| "credential validation failed" | Check .env.local: `grep DISCORD infra/openclaw/.env.local` | One or more credentials missing/empty |
| Logs show auth error | Verify token first 30 chars: `grep DISCORD_BOT_TOKEN infra/openclaw/.env.local \| head -c 30` | Token may have expired; regenerate from Discord |

---

## After Deployment ✅

Once all items are checked and the bot is working:

1. **Don't add more agents yet** – One test agent is enough for now
2. **Don't connect VideoDB or NAS** – Chat-only for this pilot
3. **Don't add GPU workers** – Single machine deployment only
4. **Keep Buzz running** – Leave all existing MainBrain services untouched

Next steps (after verification):
- [ ] Document any deviations from this checklist
- [ ] Test from your phone (cellular data, VPN off) to verify no local-network restrictions
- [ ] Schedule next phase: Add Librarian agent (separate agent, different tools)

---

## End of Checklist

**Total time**: ~20 minutes
**Success**: Bot responds to 2+ Discord messages + survives restart
**Scope**: Test agent, chat-only, #agent-test channel, single machine
