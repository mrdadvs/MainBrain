#!/usr/bin/env python3

import argparse
import getpass
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from server import (
    APPROVAL_STATES,
    ExecutorConfig,
    ReleaseStateStore,
    parse_expires_at,
)


def _json_print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _new_cli_approval_id() -> str:
    return f"approval-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:10]}"


def _parse_services(value: str) -> list[str]:
    parts = [item.strip() for item in value.split(",")]
    parsed = [item for item in parts if item]
    if not parsed:
        raise ValueError("at least one service must be provided")
    return parsed


def _confirm_or_raise(approval_id: str, preview: dict[str, Any], confirm_value: str | None) -> None:
    phrase = f"APPROVE {approval_id}"
    _json_print(
        {
            "confirmation_required": True,
            "confirm_phrase": phrase,
            "approval_preview": preview,
        }
    )
    provided = confirm_value
    if provided is None:
        provided = input(f"Type '{phrase}' to confirm approval creation: ").strip()
    if provided != phrase:
        raise SystemExit("approval creation cancelled: confirmation phrase did not match")


def cmd_approve(args: argparse.Namespace) -> None:
    config = ExecutorConfig.from_cli_args(args)
    store = ReleaseStateStore(config)

    details = {
        "repository_id": args.repository_id,
        "integration_workspace_id": args.integration_workspace_id,
        "integration_commit_sha": args.integration_commit_sha,
        "remote_name": args.remote_name,
        "target_branch": args.target_branch,
        "expected_remote_head_sha": args.expected_remote_head_sha,
        "deployment_profile_id": args.deployment_profile_id,
        "allowed_services": _parse_services(args.allowed_services),
    }
    normalized = store.validate_release_details(details)
    expires_at = parse_expires_at(args.expires_in_minutes, args.expires_at)
    approval_id = args.approval_id or _new_cli_approval_id()
    created_by = args.created_by or getpass.getuser()
    preview = {
        "approval_id": approval_id,
        **normalized,
        "expires_at": expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "created_by": created_by,
    }
    _confirm_or_raise(approval_id, preview, args.confirm)
    created = store.create_approval(
        approval_id=approval_id,
        release_details=normalized,
        created_by=created_by,
        expires_at=expires_at,
    )
    _json_print({"ok": True, "approval": created})


def cmd_list(args: argparse.Namespace) -> None:
    config = ExecutorConfig.from_cli_args(args)
    store = ReleaseStateStore(config)
    state = args.state
    if state is not None and state not in APPROVAL_STATES:
        raise ValueError(f"state must be one of {', '.join(APPROVAL_STATES)}")
    result = store.list_approvals(state=state, limit=args.limit)
    _json_print({"ok": True, **result})


def cmd_show(args: argparse.Namespace) -> None:
    config = ExecutorConfig.from_cli_args(args)
    store = ReleaseStateStore(config)
    approval = store.get_approval(args.approval_id)
    _json_print({"ok": True, "approval": approval})


def cmd_revoke(args: argparse.Namespace) -> None:
    config = ExecutorConfig.from_cli_args(args)
    store = ReleaseStateStore(config)
    approval = store.revoke_approval(args.approval_id)
    _json_print({"ok": True, "approval": approval})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Host-only release approval CLI")
    parser.add_argument("--state-dir", default=None, help="Override private state directory")
    parser.add_argument("--state-db-path", default=None, help="Override private state SQLite path")
    parser.add_argument("--policy-file", default=None, help="Override trusted policy file path")
    parser.add_argument("--workspaces-root", default=None, help="Override managed workspaces root")
    parser.add_argument("--workspace-meta-root", default=None, help="Override workspace metadata root")

    subparsers = parser.add_subparsers(dest="command", required=True)

    approve = subparsers.add_parser("approve", help="Create an approval record")
    approve.add_argument("--approval-id", default=None, help="Optional explicit approval ID")
    approve.add_argument("--repository-id", required=True, help="Managed repository ID from trusted policy")
    approve.add_argument("--integration-workspace-id", required=True, help="Integration workspace ID")
    approve.add_argument("--integration-commit-sha", required=True, help="Exact integration commit SHA")
    approve.add_argument("--remote-name", required=True, help="Approved remote name from policy")
    approve.add_argument("--target-branch", required=True, help="Approved target branch from policy")
    approve.add_argument("--expected-remote-head-sha", required=True, help="Expected current remote HEAD SHA")
    approve.add_argument("--deployment-profile-id", required=True, help="Deployment profile ID from policy")
    approve.add_argument(
        "--allowed-services",
        required=True,
        help="Comma-separated services subset allowed by deployment profile",
    )
    approve.add_argument(
        "--expires-in-minutes",
        type=int,
        default=60,
        help="Approval expiry in minutes (ignored when --expires-at is set)",
    )
    approve.add_argument(
        "--expires-at",
        default=None,
        help="Explicit RFC3339 expiry timestamp (UTC recommended)",
    )
    approve.add_argument("--created-by", default=None, help="Creator identity override")
    approve.add_argument(
        "--confirm",
        default=None,
        help="Non-interactive confirmation phrase: APPROVE <approval-id>",
    )
    approve.set_defaults(func=cmd_approve)

    list_cmd = subparsers.add_parser("list", help="List approvals")
    list_cmd.add_argument("--state", default=None, help="Optional state filter")
    list_cmd.add_argument("--limit", type=int, default=50, help="Maximum rows (1-500)")
    list_cmd.set_defaults(func=cmd_list)

    show = subparsers.add_parser("show", help="Show one approval")
    show.add_argument("--approval-id", required=True)
    show.set_defaults(func=cmd_show)

    revoke = subparsers.add_parser("revoke", help="Revoke one approved approval")
    revoke.add_argument("--approval-id", required=True)
    revoke.set_defaults(func=cmd_revoke)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
