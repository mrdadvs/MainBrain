#!/usr/bin/env python3

import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import discord
from discord import app_commands


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} must be set")
    return value


def _parse_id_set(value: str, *, field_name: str) -> frozenset[str]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    if not values:
        raise SystemExit(f"{field_name} must contain at least one Discord ID")
    return frozenset(values)


@dataclass(frozen=True)
class BotConfig:
    discord_bot_token: str
    socket_path: Path
    auth_token: str
    request_timeout_seconds: float
    allowed_user_ids: frozenset[str]
    allowed_guild_ids: frozenset[str]
    allowed_channel_ids: frozenset[str]
    announce_channel_id: str

    @classmethod
    def from_env(cls) -> "BotConfig":
        allowed_user_ids = _parse_id_set(
            os.getenv("ENGINEER_RELEASE_APPROVER_ALLOWED_USER_IDS", "1568655444321243136"),
            field_name="ENGINEER_RELEASE_APPROVER_ALLOWED_USER_IDS",
        )
        allowed_guild_ids = _parse_id_set(
            os.getenv("ENGINEER_RELEASE_APPROVER_ALLOWED_GUILD_IDS", "1568656073898987651"),
            field_name="ENGINEER_RELEASE_APPROVER_ALLOWED_GUILD_IDS",
        )
        allowed_channel_ids = _parse_id_set(
            os.getenv("ENGINEER_RELEASE_APPROVER_ALLOWED_CHANNEL_IDS", "1570598910173646890"),
            field_name="ENGINEER_RELEASE_APPROVER_ALLOWED_CHANNEL_IDS",
        )
        announce_channel_id = os.getenv("ENGINEER_RELEASE_APPROVER_ANNOUNCE_CHANNEL_ID", "").strip()
        if not announce_channel_id:
            announce_channel_id = sorted(allowed_channel_ids)[0]
        return cls(
            discord_bot_token=_require_env("DISCORD_RELEASE_APPROVER_BOT_TOKEN"),
            socket_path=Path(
                os.getenv(
                    "ENGINEER_RELEASE_EXECUTOR_SOCKET_PATH",
                    "/home/mdv/mainbrain/data/engineer-release-executor/release-executor.sock",
                )
            ).resolve(),
            auth_token=_require_env("ENGINEER_RELEASE_EXECUTOR_DISCORD_AUTH_TOKEN"),
            request_timeout_seconds=float(os.getenv("ENGINEER_RELEASE_APPROVER_TIMEOUT_SECONDS", "15")),
            allowed_user_ids=allowed_user_ids,
            allowed_guild_ids=allowed_guild_ids,
            allowed_channel_ids=allowed_channel_ids,
            announce_channel_id=announce_channel_id,
        )


class ReleaseExecutorClient:
    def __init__(self, config: BotConfig):
        self._config = config

    def call(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        envelope = {
            "auth_token": self._config.auth_token,
            "action": action,
            "payload": payload,
        }
        request_bytes = (json.dumps(envelope, separators=(",", ":")) + "\n").encode("utf-8")
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.settimeout(self._config.request_timeout_seconds)
            client.connect(str(self._config.socket_path))
            client.sendall(request_bytes)
            response = bytearray()
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                response.extend(chunk)
                if b"\n" in chunk:
                    break
        finally:
            client.close()
        if not response:
            raise RuntimeError("release executor returned an empty response")
        line = bytes(response).split(b"\n", 1)[0]
        decoded = json.loads(line.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise RuntimeError("release executor response must be an object")
        return decoded


class ConfirmApprovalView(discord.ui.View):
    def __init__(
        self,
        *,
        bot_config: BotConfig,
        executor_client: ReleaseExecutorClient,
        intent_id: str,
        authorized_user_id: str,
        workspace_id: str,
    ) -> None:
        super().__init__(timeout=900)
        self._bot_config = bot_config
        self._executor_client = executor_client
        self._intent_id = intent_id
        self._authorized_user_id = authorized_user_id
        self._workspace_id = workspace_id

    async def _announce_approval(self, interaction: discord.Interaction, response: dict[str, Any]) -> None:
        channel = interaction.client.get_channel(int(self._bot_config.announce_channel_id))
        if channel is None or not isinstance(channel, discord.abc.Messageable):
            return
        approval = response.get("approval", {})
        if not isinstance(approval, dict):
            return
        approval_id = str(approval.get("approval_id", "")).strip()
        commit_sha = str(approval.get("integration_commit_sha", "")).strip()
        remote_name = str(approval.get("remote_name", "")).strip()
        target_branch = str(approval.get("target_branch", "")).strip()
        if not approval_id:
            return
        short_sha = commit_sha[:12] if len(commit_sha) >= 12 else commit_sha
        await channel.send(
            (
                "✅ **Engineer release approved**\n"
                f"- approval_id: `{approval_id}`\n"
                f"- integration_workspace_id: `{self._workspace_id}`\n"
                f"- integration_commit_sha: `{short_sha}`\n"
                f"- destination: `{remote_name}:{target_branch}`\n"
                "Engineer may now execute `execute_release` with this approval ID."
            )
        )

    @discord.ui.button(label="Confirm approval", style=discord.ButtonStyle.danger, custom_id="confirm_release_approval")
    async def confirm_approval(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        actor_id = str(interaction.user.id)
        guild_id = str(interaction.guild_id or "")
        channel_id = str(interaction.channel_id or "")
        if actor_id != self._authorized_user_id:
            await interaction.response.send_message(
                "Only the user who initiated this approval preview can confirm it.",
                ephemeral=True,
            )
            return
        payload = {
            "interaction_id": str(interaction.id),
            "discord_user_id": actor_id,
            "discord_guild_id": guild_id,
            "discord_channel_id": channel_id,
            "intent_id": self._intent_id,
        }
        try:
            response = self._executor_client.call("discord_confirm_approval", payload)
        except Exception as exc:
            await interaction.response.send_message(f"Approval confirmation failed: {exc}", ephemeral=True)
            return

        if not bool(response.get("ok")):
            error = str(response.get("error", "unknown executor error"))
            await interaction.response.send_message(f"Approval confirmation rejected: {error}", ephemeral=True)
            return

        approval = response.get("approval", {})
        approval_id = str(approval.get("approval_id", "")).strip()
        expires_at = str(approval.get("expires_at", "")).strip()
        await interaction.response.edit_message(
            content=(
                "✅ Approval created.\n"
                f"- approval_id: `{approval_id}`\n"
                f"- expires_at: `{expires_at}`\n"
                "Shared to the Engineer channel."
            ),
            view=None,
        )
        await self._announce_approval(interaction, response)


def _is_allowed_context(interaction: discord.Interaction, config: BotConfig) -> tuple[bool, str]:
    user_id = str(interaction.user.id)
    guild_id = str(interaction.guild_id or "")
    channel_id = str(interaction.channel_id or "")
    if user_id not in config.allowed_user_ids:
        return False, "You are not allowed to approve releases in this environment."
    if guild_id not in config.allowed_guild_ids:
        return False, "This guild is not approved for release authorization."
    if channel_id not in config.allowed_channel_ids:
        return False, "This channel is not approved for release authorization."
    return True, ""


def _render_preview_message(preview: dict[str, Any]) -> str:
    details = preview.get("release_details", {})
    tests = preview.get("trusted_test_results", [])
    if not isinstance(details, dict):
        details = {}
    if not isinstance(tests, list):
        tests = []
    checks = []
    for item in tests:
        if not isinstance(item, dict):
            continue
        checks.append(
            f"- `{item.get('check_id','?')}`@`{item.get('check_config_version','?')}` -> "
            f"{item.get('result_state','missing')}"
        )
    checks_text = "\n".join(checks) if checks else "- (no checks returned)"
    return (
        "Review and confirm this exact release authorization:\n"
        f"- repository: `{details.get('repository_id','')}`\n"
        f"- integration_workspace_id: `{details.get('integration_workspace_id','')}`\n"
        f"- integration_commit_sha: `{details.get('integration_commit_sha','')}`\n"
        f"- destination: `{details.get('remote_name','')}:{details.get('target_branch','')}`\n"
        f"- expected_remote_head: `{details.get('expected_remote_head_sha','')}`\n"
        f"- deployment_profile: `{details.get('deployment_profile_id','')}`\n"
        f"- allowed_services: `{', '.join(details.get('allowed_services', []))}`\n"
        f"- intent_expires_at: `{preview.get('intent_expires_at','')}`\n"
        f"- approval_expires_at: `{preview.get('approval_expires_at','')}`\n"
        "- trusted_test_results:\n"
        f"{checks_text}\n"
        "Click **Confirm approval** to mint a single-use approval ID."
    )


def main() -> None:
    config = BotConfig.from_env()
    executor_client = ReleaseExecutorClient(config)

    intents = discord.Intents.none()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    @tree.command(name="approve_engineer_release", description="Preview and confirm an Engineer sandbox release approval.")
    @app_commands.describe(integration_workspace_id="Integration workspace ID to authorize for execute_release")
    async def approve_engineer_release(interaction: discord.Interaction, integration_workspace_id: str) -> None:
        allowed, reason = _is_allowed_context(interaction, config)
        if not allowed:
            await interaction.response.send_message(reason, ephemeral=True)
            return

        payload = {
            "interaction_id": str(interaction.id),
            "discord_user_id": str(interaction.user.id),
            "discord_guild_id": str(interaction.guild_id or ""),
            "discord_channel_id": str(interaction.channel_id or ""),
            "integration_workspace_id": integration_workspace_id.strip(),
        }
        try:
            preview = executor_client.call("discord_prepare_approval", payload)
        except Exception as exc:
            await interaction.response.send_message(f"Approval preview failed: {exc}", ephemeral=True)
            return
        if not bool(preview.get("ok")):
            await interaction.response.send_message(
                f"Approval preview rejected: {preview.get('error', 'unknown error')}",
                ephemeral=True,
            )
            return

        intent_id = str(preview.get("intent_id", "")).strip()
        if not intent_id:
            await interaction.response.send_message("Approval preview failed: missing intent ID.", ephemeral=True)
            return
        view = ConfirmApprovalView(
            bot_config=config,
            executor_client=executor_client,
            intent_id=intent_id,
            authorized_user_id=str(interaction.user.id),
            workspace_id=integration_workspace_id.strip(),
        )
        await interaction.response.send_message(_render_preview_message(preview), ephemeral=True, view=view)

    @client.event
    async def on_ready() -> None:
        guild_ids = sorted(config.allowed_guild_ids)
        for guild_id in guild_ids:
            guild = discord.Object(id=int(guild_id))
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
        print(f"engineer-discord-approver ready as {client.user}", flush=True)

    client.run(config.discord_bot_token)


if __name__ == "__main__":
    main()
