# Discord Test Agent Instructions

**Agent Role**: Pilot Discord Chat Agent for MainBrain  
**Phase**: Testing & Validation  
**Permissions**: Chat-only (no file operations, no external tools)

## Operational Guidelines

### Core Behavior

1. **Respond to Discord messages** in configured channel when mentioned
2. **Use configured AI model** (OpenAI GPT-4/3.5) for all responses
3. **Stay conversational**: Keep responses concise, friendly, helpful
4. **Acknowledge limitations**: Explain when you cannot perform an action due to permissions

### Required Configuration

Before deploying this agent, ensure .env.local contains:

```bash
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_ALLOWED_USERS=YOUR_DISCORD_USER_ID
DISCORD_SERVER_ID=YOUR_SERVER_ID
DISCORD_CHANNEL_ID=#agent-test
DISCORD_REQUIRE_MENTION=true
OPENAI_API_KEY=your_openai_key_here
AGENT_CHAT_ONLY=true
AGENT_DISABLE_SKILLS=true
```

### Allowed Actions

- ✅ Read Discord messages in #agent-test channel
- ✅ Reply with text messages
- ✅ Use Discord formatting (bold, italics, code blocks)
- ✅ React to messages (emoji reactions)
- ✅ Send embeds (structured messages)
- ✅ Maintain conversation history within session
- ✅ Reference previous messages in channel

### Blocked Actions

- ❌ Execute shell commands (no bash, PowerShell, etc.)
- ❌ Access the host filesystem
- ❌ Read files from disk
- ❌ Write files to disk
- ❌ Access NAS shares or mounted drives
- ❌ Submit jobs to worker queue
- ❌ Query databases
- ❌ Use external tools or skills
- ❌ Connect to VideoDB or other MCP servers
- ❌ Modify configuration files
- ❌ Restart containers or services
- ❌ Access other Discord servers or channels

## Testing Checklist

### Manual Verification

- [ ] Deploy with: `bash infra/openclaw/init/00-create-directories.sh`
- [ ] Start gateway: `bash infra/openclaw/scripts/deploy.sh up`
- [ ] Health check: `bash infra/openclaw/scripts/health-check.sh`
- [ ] View logs: `bash infra/openclaw/scripts/logs.sh`

### Test Case 1: Basic Message

**Steps**:
1. Send message in Discord: `@MainBrain Test Hello`
2. Expect: Bot replies with greeting/acknowledgment

**Result**: _____ (PASS/FAIL)  
**Notes**: _______

### Test Case 2: Follow-up Conversation

**Steps**:
1. Send: `@MainBrain Test What is your role?`
2. Expect: Bot explains it is a test agent for MainBrain

**Result**: _____ (PASS/FAIL)  
**Notes**: _______

### Test Case 3: Blocked Permission

**Steps**:
1. Send: `@MainBrain Test run ls -la`
2. Expect: Bot refuses and explains it cannot execute commands

**Result**: _____ (PASS/FAIL)  
**Notes**: _______

### Test Case 4: Offline Resilience

**Steps**:
1. Close Discord window / put phone in airplane mode
2. Wait 2-5 minutes
3. Reconnect
4. Send: `@MainBrain Test still online?`
5. Expect: Bot replies

**Result**: _____ (PASS/FAIL)  
**Notes**: _______

### Test Case 5: Container Restart

**Steps**:
1. Run: `docker compose -f infra/openclaw/docker-compose.yml restart openclaw-gateway`
2. Wait for container to start
3. Send message in Discord
4. Expect: Bot responds normally after restart

**Result**: _____ (PASS/FAIL)  
**Notes**: _______

## Troubleshooting

### Bot Not Responding

1. **Check it's running**: `docker ps | grep openclaw-gateway`
2. **Check logs**: `bash infra/openclaw/scripts/logs.sh tail 50`
3. **Verify .env.local**: `grep DISCORD_BOT_TOKEN infra/openclaw/.env.local`
4. **Test channel**: Make sure bot is in the #agent-test channel
5. **Mention required**: Check if @mention is required (DISCORD_REQUIRE_MENTION setting)

### Permission Denied Errors

This agent intentionally blocks file operations. If a response says "permission denied":
- This is correct behavior for chat-only mode
- File access will be added in future phases with Librarian/Director agents

### Bot Goes Offline

If bot becomes unresponsive:
1. Check Discord connection: `docker compose logs openclaw-gateway 2>&1 | grep -i "discord\|connection" | tail -20`
2. Restart: `bash infra/openclaw/scripts/deploy.sh restart`
3. Verify health: `bash infra/openclaw/scripts/health-check.sh`

### High Memory Usage

If container memory increases:
1. Check for memory leaks: `docker stats openclaw-gateway --no-stream`
2. Restart container: `docker compose restart openclaw-gateway`
3. Check for large chat history: `du -sh data/openclaw/state/`

## Example Conversations

### Successful Interaction

```
User: @MainBrain Test hello
Bot: Hello! I'm the MainBrain Discord test agent. How can I help?

User: @MainBrain Test what can you do?
Bot: I can:
- Chat and answer questions
- Remember our conversation history
- Use GPT-4 to provide thoughtful responses

I cannot:
- Access files on this computer
- Run commands or scripts
- Connect to databases
- Submit jobs to the video pipeline

User: @MainBrain Test thanks!
Bot: You're welcome! Feel free to ask me anything.
```

### Expected Failure

```
User: @MainBrain Test run: cat /etc/passwd
Bot: I can't execute shell commands - my permissions are restricted to chat only.
This is a security feature to prevent accidental damage to the system.
For access to system tools, you'll need to use other interfaces or agents with appropriate permissions.
```

---

## Related Documentation

- **Deployment**: See [README.md](../README.md) for installation steps
- **Security**: See [SECURITY.md](../SECURITY.md) for permission model details
- **Troubleshooting**: See [HEALTH.md](../HEALTH.md) for monitoring and debugging
- **Agent Permissions**: See [agents/README.md](./README.md) for permission architecture

---

*Next Phase*: After successful testing, the Librarian agent will be deployed with read-only access to indexed content.
