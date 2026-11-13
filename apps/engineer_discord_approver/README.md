# Engineer Discord Approver (Checkpoint 6C)

Host-side Discord slash-command bot that creates trusted release approvals through the existing release executor.

## Command

- `/approve_engineer_release integration_workspace_id:<id>`

Flow:

1. Bot sends `discord_prepare_approval` to release executor.
2. Executor validates trusted identity (user/guild/channel), release bindings, and required trusted test evidence.
3. Bot shows exact release details in an ephemeral preview with a **Confirm approval** button.
4. Confirm button sends `discord_confirm_approval`.
5. Executor revalidates details/evidence and creates a single-use expiring approval in the same private approvals DB.
6. Bot posts the generated `approval_id` back to the approved Engineer channel.

## Security

- Uses trusted Discord interaction metadata (`interaction.user.id`, `guild_id`, `channel_id`), not natural-language content.
- Uses a dedicated executor auth token (`ENGINEER_RELEASE_EXECUTOR_DISCORD_AUTH_TOKEN`).
- Does not mount or read the private executor DB directly.
- Replays cannot mint extra approvals: each interaction/intent is single-use and stateful.

## Host secret file

Both host services read privileged Discord approval secrets from:

- `/home/mdv/.config/mainbrain/engineer-release-approver.env`

This file is intentionally host-only and not used by OpenClaw containers.

