# 🚀 OpenClaw Discord Deployment – TODAY

**Status**: ✅ All infrastructure, validation, and tooling are complete.

This guide walks you through the **single deployable step** to get your Discord bot live.

---

## What's Ready

✅ Official OpenClaw image validated (v2026.11.1, digest verified)
✅ docker-compose.yml certified against official OpenClaw documentation
✅ Chat-only permissions enforced (no shell, filesystem, or skill execution)
✅ Localhost-only gateway binding (127.0.0.1:18789)
✅ Persistent state directory mounted
✅ Health-check scripts prepared
✅ Rollback procedures documented and tested
✅ All deployment secrets excluded from Git

---

## Prerequisites

Before starting, gather these **three pieces of information**:

1. **Discord Bot Token** – from your "MainBrain Test" application
   - Go to https://discord.com/developers/applications
   - Select "MainBrain Test"
   - Copy token from "TOKEN" section
   
2. **OpenAI API Key** – your dedicated key
   - Go to https://platform.openai.com/account/api-keys
   - Generate or copy existing key

3. **Discord Server/User IDs**
   - Your user ID: Right-click your name in Discord → "Copy User ID"
   - MainBrain server ID: Right-click server name → "Copy Server ID"
   - #agent-test channel ID: Right-click channel → "Copy Channel ID"

**Important**: Never paste these into chat. We'll use a local, interactive script.

---

## Step 1: SSH Into MainBrain

```bash
ssh mainbrain
cd ~/mainbrain
```

---

## Step 2: Set Up Credentials Securely

Run the interactive credential setup script. **Tokens will not echo to your screen.**

```bash
bash infra/openclaw/setup-credentials.sh
```

This script will:
- Prompt for each credential without echoing (silent input)
- Validate they're non-empty
- Save them to `.env.local` (permissions 600, git-ignored)
- Verify the file is git-ignored
- Show a checksum so you can verify nothing was corrupted

**Example interaction:**
```
Enter Discord Bot Token (silent): 
Enter OpenAI API Key (silent): 
Enter your Discord user ID: 
Enter MainBrain server ID: 
Enter #agent-test channel ID: 

✓ All credentials saved to .env.local
✓ File is git-ignored
✓ Checksum: abc1234...
```

---

## Step 3: Deploy OpenClaw

```bash
bash infra/openclaw/scripts/deploy.sh up
```

This script will:
1. Validate `.env.local` contains all required non-placeholder credentials
2. Export them to the environment
3. Run `docker compose up -d` to start the OpenClaw gateway
4. Wait 10 seconds for startup
5. Show you the logs

**Expected output:**
```
[*] Validating credentials in .env.local...
[✓] DISCORD_BOT_TOKEN is set
[✓] OPENAI_API_KEY is set
[✓] DISCORD_USER_ID is set
[✓] DISCORD_SERVER_ID is set
[✓] DISCORD_CHANNEL_ID is set
[✓] Starting OpenClaw container...
[+] Running 1/1
  ✔ openclaw-gateway  Running
[*] Waiting for startup...
[✓] Gateway is ready
[*] Recent logs:
```

---

## Step 4: Verify Bot Is Online

In Discord, go to #agent-test channel. You should see **MainBrain Test** bot listed as online.

If not online after 30 seconds:
```bash
bash infra/openclaw/scripts/logs.sh
```

Look for connection messages:
```
Connected to Discord!
Agent initialized
Listening for mentions...
```

---

## Step 5: Test First Message

In #agent-test channel, send:

```
@MainBrain Test What is 2 + 2?
```

**Expected**: Bot replies with "4" or similar within 5–10 seconds.

---

## Step 6: Test Second Message

Send a different message:

```
@MainBrain Test Tell me a joke.
```

**Expected**: Bot replies with a joke or humorous response within 5–10 seconds.

---

## Step 7: Test Container Persistence

Restart the OpenClaw container:

```bash
docker compose -f infra/openclaw/docker-compose.yml down
docker compose -f infra/openclaw/docker-compose.yml up -d
```

Wait 10 seconds, then send another message in #agent-test:

```
@MainBrain Test Hi again!
```

**Expected**: Bot still replies. All configuration persisted.

---

## Step 8: Record Success

Once both Discord messages work and restart succeeds, record the deployment in Git:

```bash
cd ~/mainbrain
git log --oneline | head -5
```

The latest commit should be your docker-compose.yml fix. Your `.env.local` file is **not** and **will not be** in Git.

---

## Troubleshooting

### Bot doesn't appear online

**Check 1**: Credentials are correct and loaded
```bash
grep DISCORD_BOT_TOKEN infra/openclaw/.env.local | head -c 50
```
Should show your token (first 50 chars).

**Check 2**: Container is running
```bash
docker ps | grep openclaw
```

**Check 3**: View full logs
```bash
bash infra/openclaw/scripts/logs.sh | tail -50
```

### Bot is online but doesn't reply

**Check 1**: Make sure you're mentioning the bot
```
@MainBrain Test (not @mainbrain or plain text)
```

**Check 2**: Bot only responds in #agent-test channel
```
(not in DMs or other channels)
```

**Check 3**: Check Discord server/user IDs are correct
```bash
grep DISCORD_SERVER_ID infra/openclaw/.env.local
grep DISCORD_CHANNEL_ID infra/openclaw/.env.local
grep DISCORD_USER_ID infra/openclaw/.env.local
```

**Check 4**: OpenAI key is valid and has quota
```bash
grep OPENAI_API_KEY infra/openclaw/.env.local | head -c 30
```

### Container crashes on startup

**View detailed error**:
```bash
docker compose -f infra/openclaw/docker-compose.yml logs -f
```

Common causes:
- Missing or invalid `OPENAI_API_KEY`
- Missing or invalid `DISCORD_BOT_TOKEN`
- Port 18789 already in use: `lsof -i :18789`

---

## Rollback (If Needed)

Stop the container without destroying state:

```bash
docker compose -f infra/openclaw/docker-compose.yml down
```

Restore from backup:

```bash
bash infra/openclaw/scripts/restore-state.sh
```

---

## Files & Scripts Location

```
infra/openclaw/
├── docker-compose.yml          ← Deployment config (validated)
├── .env.example                ← Template (no secrets)
├── .env.local                  ← YOUR CREDENTIALS (git-ignored, local only)
├── setup-credentials.sh        ← Interactive credential entry
└── scripts/
    ├── deploy.sh               ← Main deployment orchestrator
    ├── health-check.sh         ← Check container status
    ├── logs.sh                 ← View container logs
    ├── backup-state.sh         ← Backup persistent state
    ├── restore-state.sh        ← Restore from backup
    └── rollback.sh             ← Complete rollback procedure
```

---

## Next Steps (After Verification)

Once Discord messaging works reliably:

1. ✅ Stop and commit results
2. 🔄 Then: Add Librarian agent (separate agent, different instructions)
3. 🔄 Then: Connect VideoDB stdio MCP server
4. 🔄 Then: Add GPU worker machine
5. 🔄 Then: Add job queue integration

For now: **One test agent, chat-only, Discord verified.**

---

## Questions?

Review these docs:

- **How to understand the setup**: [infra/openclaw/README.md](/home/mdv/mainbrain/infra/openclaw/README.md)
- **Security model**: [infra/openclaw/SECURITY.md](/home/mdv/mainbrain/infra/openclaw/SECURITY.md)
- **Detailed deployment steps**: [infra/openclaw/FIRST_DISCORD_TEST_GUIDE.md](/home/mdv/mainbrain/infra/openclaw/FIRST_DISCORD_TEST_GUIDE.md)
- **Validation results**: [infra/openclaw/VALIDATION_REPORT.md](/home/mdv/mainbrain/infra/openclaw/VALIDATION_REPORT.md)

---

**Status**: 🟢 Ready to deploy.

**Next action**: SSH to MainBrain, run `bash infra/openclaw/setup-credentials.sh`, then `bash infra/openclaw/scripts/deploy.sh up`.
