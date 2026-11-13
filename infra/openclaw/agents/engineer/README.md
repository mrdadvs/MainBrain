# Engineer Agent Runtime Guide

This folder tracks the Git-managed instructions for the `engineer` OpenClaw agent.

## Architecture summary

Engineer runs as a constrained multi-service system:

1. **OpenClaw Engineer agent (gateway-side)**
   - Uses `engineer__*` tools only.
   - Follows tracked instructions in this folder and mirrored runtime instruction files.
2. **Engineer Code MCP (`engineer-code-mcp`)**
   - Allows repository/workspace read-edit/test/release preparation tools.
   - Enforces allowlisted repositories, workspace boundaries, and secret/path protections.
3. **Engineer Code Runner (`engineer-code-runner`)**
   - Executes approved checks/artifact renders in disposable, resource-limited containers.
   - Records trusted test evidence for exact integration commits through the release executor.
4. **Engineer Release Executor (`engineer-release-executor`)**
   - Host-side trusted authority for approvals, push, deployment, health verification, and rollback.
   - Uses a private state DB and trusted policy; does not trust Engineer-supplied remotes/commands.
5. **Engineer Discord Approver (`engineer-discord-approver`)**
   - Host-side slash-command bot (`/approve_engineer_release`) that creates single-use approvals in the same trusted approvals DB.
6. **Sandbox deployment target**
   - Trusted compose deployment profile for `engineer-sandbox-service`, localhost-only host access.

## Verified runtime capabilities

- Model: `openai/gpt-6-luna`
- MCP server: `engineer` (`http://engineer-code-mcp:9010/mcp`)
- Allowed tools (15):
  - `engineer__list_projects`
  - `engineer__list_files`
  - `engineer__read_file`
  - `engineer__search_code`
  - `engineer__create_workspace`
  - `engineer__apply_patch`
  - `engineer__get_diff`
  - `engineer__run_checks`
  - `engineer__render_artifact`
  - `engineer__resolve_artifact`
  - `engineer__commit_changes`
  - `engineer__merge_to_integration`
  - `engineer__test_merged_code`
  - `engineer__prepare_release`
  - `engineer__execute_release`

## End-to-end workflow

1. Inspect allowlisted repository content.
2. Create an isolated task workspace (default baseline is the latest trusted published release HEAD).
3. Read/edit using `workspace_id`, then confirm diffs.
4. Run approved checks in disposable sandboxes.
5. Commit task-branch changes.
6. Merge into isolated integration workspace.
7. Run checks on merged integration commit.
8. Prepare release report (`READY FOR APPROVAL`).
9. When media is requested, render via `render_artifact`, stage via `resolve_artifact`, then return standalone `MEDIA:` reference for outbound attachment.
10. Only when explicitly requested, execute approved release via `execute_release` using a human-issued approval ID.

## End-to-end release workflow

1. **Default development mode**
   - Engineer starts from an isolated task workspace and commits locally by default.
   - Follow-up work should reuse the existing task branch unless asked otherwise.
2. **Automatic branching and workspace reuse**
   - Task workspaces use managed `engineer/task-*` branches.
   - Integration workspaces use managed `engineer/integration-*` branches.
3. **Automatic trusted baseline synchronization**
   - `create_workspace` defaults to the latest trusted published revision (`sandbox-release/main`) and records base SHA metadata.
4. **Explicit release preparation**
   - `prepare_release` requires exact passing post-merge checks and emits a `READY FOR APPROVAL` report (no push/deploy).
5. **Trusted post-merge evidence**
   - `test_merged_code` runs on commit-locked snapshots and records release-eligible `actual_runner` evidence.
6. **Human approval**
   - Approval can be created via Discord (`/approve_engineer_release`) or host `releasectl` fallback.
   - Approval binds exact repository/workspace/commit/remote/branch/profile/services and is single-use + expiring.
7. **Push, deploy, verify, rollback**
   - `execute_release` validates approval + trusted evidence, pushes approved commit, deploys trusted profile, verifies health/version SHA, and auto-rolls back on deploy failure.
   - Reported outcomes include `AUTHORIZATION_REJECTED`, `PUSH_FAILED`, `DEPLOYMENT_SUCCEEDED`, `DEPLOYMENT_FAILED_ROLLED_BACK`, `DEPLOYMENT_FAILED_ROLLBACK_FAILED`.

## Runner and rendering operations

- Runner service unit: [engineer-code-runner.service](/home/mdv/mainbrain/infra/openclaw/systemd/engineer-code-runner.service)
- Runner launcher: [run-engineer-code-runner.sh](/home/mdv/mainbrain/infra/openclaw/scripts/run-engineer-code-runner.sh)
- Rendering image build script: [build-engineer-render-image.sh](/home/mdv/mainbrain/infra/openclaw/scripts/build-engineer-render-image.sh)
- Rendering Dockerfile: [Dockerfile.engineer_render_runner](/home/mdv/mainbrain/infra/openclaw/Dockerfile.engineer_render_runner)

For reboot/logout persistence, user lingering must stay enabled:

```bash
sudo loginctl enable-linger mdv
loginctl show-user mdv -p Linger
```

## Artifact persistence and delivery

- Persistent artifacts root: `/home/mdv/mainbrain/data/engineer-artifacts/`
- Restricted staging root: `/home/mdv/mainbrain/data/openclaw/workspace/engineer/artifact-staging/`
- Gateway-visible staging root: `/home/node/.openclaw/workspace/engineer/artifact-staging/`

The delivery path is validated and staged by the trusted runner before being used in a `MEDIA:` line. Engineer does not receive arbitrary file-read or shell execution capability.

## Operations and recovery runbook

### 1) MCP service rebuild + stale session recovery

- Rebuild/restart the MCP service:

```bash
cd /home/mdv/mainbrain/infra/openclaw
docker compose build engineer-code-mcp
docker compose up -d engineer-code-mcp
```

- If Engineer reports tools missing (`transport is closed` / `tools.engineer__* is not a function`) after MCP restart, start a **fresh Engineer session key/thread** rather than reusing the stale long-lived session.
- Verify with an actual Engineer call to `engineer__list_projects` (not only direct SDK probes).

### 2) Systemd unit installation and synchronization

- Tracked unit files live under `/home/mdv/mainbrain/infra/openclaw/systemd/`.
- Installed user units must match these files in `~/.config/systemd/user/`.
- Sync/install:

```bash
mkdir -p ~/.config/systemd/user
cp /home/mdv/mainbrain/infra/openclaw/systemd/engineer-*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now engineer-code-runner.service engineer-release-executor.service engineer-discord-approver.service
```

### 3) Runner/executor persistence and health

- Runner socket: `/home/mdv/mainbrain/data/engineer-code-runner/runner.sock`
- Release executor socket: `/home/mdv/mainbrain/data/engineer-release-executor/release-executor.sock`
- Release executor persistent state: `/home/mdv/.local/state/mainbrain/engineer-release-executor/state.db`
- Confirm services:

```bash
systemctl --user --no-pager status engineer-code-runner.service engineer-release-executor.service engineer-discord-approver.service
```

### 4) Interrupted release reconciliation

- New releases are blocked when deployment state has `reconcile_required=1`.
- Inspect current trusted state:

```bash
sqlite3 /home/mdv/.local/state/mainbrain/engineer-release-executor/state.db \
  "SELECT service_id,last_stage,reconcile_required,current_commit_sha,last_execution_id,updated_at FROM service_deployments;"
```

- Reconcile by:
  1. Verifying actual deployed SHA from `/version` and health from `/health`.
  2. Verifying remote HEAD in trusted release remote.
  3. Confirming last release execution state/failure cause in `release_executions`.
  4. Only after operator confirmation of known-good deployed state, clear reconciliation flag in trusted state store before allowing another release.

### 5) Failed deployment handling

- `DEPLOYMENT_FAILED_ROLLED_BACK`: deployment failed but automatic rollback restored prior healthy commit.
- `DEPLOYMENT_FAILED_ROLLBACK_FAILED`: deployment failed and rollback also failed; executor sets reconciliation required. Operator intervention is mandatory before further releases.
