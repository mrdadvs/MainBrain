# Engineer Release Executor (Checkpoint 6C)

This service is a **trusted host-side release controller** for approval-bound sandbox releases.

Current state includes trusted sandbox push, deployment, health verification, rollback handling, and Discord-authenticated approval creation.

## Security model

- Runs as a host-side Unix socket service (not in Engineer's coding container).
- Requires a shared auth token and peer UID validation via `SO_PEERCRED`.
- Accepts only strict JSON request schemas.
- Rejects unknown actions and unknown request fields.
- Stores approval/release/test-evidence state in a private persistent DB path.

## Files

- Server: [server.py](/home/mdv/mainbrain/apps/engineer_release_executor/server.py)
- Host CLI: [releasectl.py](/home/mdv/mainbrain/apps/engineer_release_executor/releasectl.py)
- Discord approver bot: [bot.py](/home/mdv/mainbrain/apps/engineer_discord_approver/bot.py)
- Trusted policy: [trusted_policy.json](/home/mdv/mainbrain/apps/engineer_release_executor/config/trusted_policy.json)
- Systemd unit: [engineer-release-executor.service](/home/mdv/mainbrain/infra/openclaw/systemd/engineer-release-executor.service)
- Launch script: [run-engineer-release-executor.sh](/home/mdv/mainbrain/infra/openclaw/scripts/run-engineer-release-executor.sh)

## Runtime defaults

- Socket: `/home/mdv/mainbrain/data/engineer-release-executor/release-executor.sock`
- State dir: `/home/mdv/.local/state/mainbrain/engineer-release-executor`
- State DB: `<state-dir>/state.db`
- Discord approval host secrets: `/home/mdv/.config/mainbrain/engineer-release-approver.env`

The state directory is intentionally outside current Engineer container bind mounts.

## Supported socket actions (6C)

- `ping` — health/availability probe
- `describe_contract` — returns schema/state-machine/interface contract
- `validate_execute_release_request` — validates strict future release request shape without performing release
- `authorize_release_preview` — validates approval binding + trusted evidence without consuming approval
- `authorize_release` — validates + atomically consumes a previously approved release authorization
- `execute_release` — consumes one valid approval, verifies remote/fast-forward safety, pushes exact approved commit, and records release outcome
- `record_test_evidence` — host-side trusted runner records real post-merge test evidence
- `discord_prepare_approval` — preview exact release details from trusted workspace metadata + evidence using trusted Discord interaction identity
- `discord_confirm_approval` — explicit-confirmation action that creates a single-use expiring approval in the same private approvals DB

All requests use this envelope:

```json
{
  "auth_token": "string",
  "action": "ping|describe_contract|validate_execute_release_request|execute_release|record_test_evidence|discord_prepare_approval|discord_confirm_approval",
  "payload": {}
}
```

Unknown envelope keys are rejected.

## Host-only approval CLI

`releasectl.py` supports:

- `approve`
- `list`
- `show`
- `revoke`

`approve` always requires explicit confirmation phrase:

`APPROVE <approval-id>`

Approval creation/revocation are intentionally **not** exposed by Engineer MCP.
`record_test_evidence` requires a separate host-only evidence auth token and is not callable with Engineer MCP's executor auth token.
Discord approval actions require a dedicated auth token (`ENGINEER_RELEASE_EXECUTOR_DISCORD_AUTH_TOKEN`) and trusted Discord metadata checks (authorized user/guild/channel IDs).

## Approval record schema (defined contract)

Each approval binds:

- `approval_id` (single-use ID)
- `repository_id`
- `integration_workspace_id`
- `integration_commit_sha`
- `remote_name`
- `target_branch`
- `expected_remote_head_sha`
- `deployment_profile_id`
- `allowed_services`
- `expires_at`

`describe_contract` returns the full field-level schema and regex/type constraints.

## Atomic consumption and locking

Release authorization uses one SQLite `BEGIN IMMEDIATE` transaction to:

1. Load + validate approval state/bindings/expiry.
2. Insert a `release_executions` row in `locked` state.
3. Insert unique scope lock (`repository + remote + branch`).
4. Mark approval consumed with consumed timestamp and execution ID.
5. Commit or rollback atomically.

Duplicate prevention comes from:

- unique `approval_id`
- unique `release_executions.approval_id`
- unique `execution_locks.lock_key`

## Trusted test evidence store

`trusted_test_evidence` in the private executor DB persists test evidence independently from Engineer workspace metadata.

- `evidence_kind=actual_runner` is release-eligible.
- fixture evidence remains stored but excluded from release authorization.
- release authorization requires the deployment profile's required check profiles (check ID + config version) to have latest `passed` `actual_runner` evidence for the exact repository/workspace/commit.

## Interrupted release reconciliation

Deployment state is tracked in `service_deployments`. During deployment, `reconcile_required` is set until healthy completion (or successful rollback) clears it.

- If `reconcile_required=1`, `execute_release` rejects new releases.
- Operator must reconcile trusted state first by verifying:
  - actual deployed service health/version,
  - trusted remote HEAD,
  - last `release_executions` failure state.
- Only after confirming known-good deployment state should reconciliation be cleared to resume releases.

## Trusted Git execution environment

Release Git operations run with:

- `GIT_CONFIG_NOSYSTEM=1`
- `GIT_CONFIG_GLOBAL=/dev/null`
- `GIT_TERMINAL_PROMPT=0`
- `GIT_ASKPASS=/bin/false`
- `HUSKY=0`
- git args including `-c core.hooksPath=/dev/null`

This prevents hook inheritance and interactive/untrusted config behavior.

## Trusted sandbox remote policy

- Approved remotes are resolved from trusted policy by `repository_id + remote_name`.
- Each approved remote must map to a trusted local path under `/home/mdv/mainbrain/repos`.
- Executor never accepts remote URLs or refspecs from Engineer MCP input.

## Deployment reporting details

`execute_release` responses include trusted `service_access` details:

- `application_url` (verified host URL)
- `health_url`
- `version_url`
- `host_port` (published localhost port, e.g. `18765`)
- `container_port` (internal container port, e.g. `8080`)

These values are resolved from trusted deployment policy, not inferred from agent text.
