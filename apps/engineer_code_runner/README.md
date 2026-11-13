# Engineer test-runner PoC (Checkpoint 2B2A)

This is a minimal **trusted job controller** that executes Python tests in a disposable untrusted container.

## Components

1. **Trusted controller**: [run_job.py](/home/mdv/mainbrain/apps/engineer_code_runner/run_job.py)
   - Validates approved worktree paths
   - Creates a temporary snapshot of the worktree
   - Launches an isolated container with strict limits
   - Collects logs + exit code
   - Cleans up snapshot after completion
   - Exposes a restricted Unix socket API for MCP integration
   - For integration workspaces, snapshots the exact merged commit via trusted Git archive and records trusted evidence in the release executor

2. **Untrusted execution environment**: ephemeral `python:3.12.8-slim` container
   - Receives only a read-only snapshot mount at `/workspace`
   - No network access (`--network none`)
   - Non-root user (`65534:65534`)
   - No elevated capabilities (`--cap-drop ALL`, `no-new-privileges`)
   - CPU/memory/pid/time limits
   - Disposable (`--rm`)

## Unix socket controller API

`run_job.py serve` listens on a Unix socket and only accepts:

- `workspace_id`
- `check_id`
- `artifact_id`
- `artifact_filename` (optional)
- `auth_token`

The socket is created with mode `0660`, and the controller can enforce an allowed peer UID (`--allowed-peer-uid`, default `1000`) using `SO_PEERCRED`.

No host path, shell command, Docker arguments, or executable names are accepted.

Approved checks are hardcoded in the trusted controller:

- `python_unit` (discovers `tests/test_*.py` in the workspace, excluding `test_intentional_failure.py` and `test_isolation.py`) (`config_version=python_unit_v2`)
- `python_isolation`
- `python_fail_demo`

For integration workspaces, `check` requests:

- require a clean working tree;
- validate `HEAD` equals metadata `integration_commit_sha`;
- run tests from an immutable archive snapshot of that exact commit;
- record trusted evidence through the release executor with a host-only evidence token.

Approved render profiles are also hardcoded:

- `python_animation_v1` (matplotlib + Pillow + FFmpeg profile; allows `animation_*.py`)

Approved artifact delivery extensions are hardcoded:

- `.mp4`, `.gif`, `.png`, `.jpg`, `.jpeg`, `.webm`

Rendered artifacts are written to:

- `/home/mdv/mainbrain/data/engineer-artifacts/<artifact-id>/`

Artifact delivery staging is restricted to:

- Host path: `/home/mdv/mainbrain/data/openclaw/workspace/engineer/artifact-staging/<stage-token>/`
- Gateway-visible path: `/home/node/.openclaw/workspace/engineer/artifact-staging/<stage-token>/`

The controller never accepts arbitrary host paths for delivery; it validates `artifact_id` and optional `artifact_filename` under the approved artifact root, then copies only allowed media files into staging.

## Render image build

Build the approved rendering image (matplotlib + Pillow + FFmpeg):

```bash
/home/mdv/mainbrain/infra/openclaw/scripts/build-engineer-render-image.sh
```

Default tag:

- `mainbrain-engineer-render:py312-mpl-ffmpeg`

## How Code MCP can submit jobs without Docker/socket access

Code MCP should not invoke Docker directly. Instead:

1. Code MCP calls a narrow local API exposed by the trusted controller (for example via Unix socket).
2. The controller validates workspace ID/path against allowlists and policy.
3. The controller snapshots and runs tests in the disposable container.
4. The controller returns structured results (status, logs, timing), never shell access.

This keeps Docker and host execution privileges in a separate trusted boundary.

## Persistent host service (systemd --user)

Install and start the controller as a persistent user service:

```bash
mkdir -p ~/.config/systemd/user
cp /home/mdv/mainbrain/infra/openclaw/systemd/engineer-code-runner.service ~/.config/systemd/user/
chmod +x /home/mdv/mainbrain/infra/openclaw/scripts/run-engineer-code-runner.sh
systemctl --user daemon-reload
systemctl --user enable --now engineer-code-runner.service
systemctl --user status engineer-code-runner.service --no-pager
```

Notes:

- The service reads `/home/mdv/mainbrain/infra/openclaw/.env.local` if present.
- `ENGINEER_RUNNER_AUTH_TOKEN` defaults to `engineer-runner-dev-token` to match current Compose defaults.
- Socket path defaults to `/home/mdv/mainbrain/data/engineer-code-runner/runner.sock`.
- `ENGINEER_RELEASE_EXECUTOR_EVIDENCE_AUTH_TOKEN` is required for trusted evidence recording and must not be mounted into Engineer Code MCP.
- For availability after logout/reboot, enable lingering for the service user:
  `sudo loginctl enable-linger mdv`
- Verify lingering is active:
  `loginctl show-user mdv -p Linger`
