# Engineer Code MCP

This service provides the Engineer agent's initial safe repository tools:

- `list_projects`
- `list_files`
- `read_file`
- `search_code`
- `create_workspace`
- `apply_patch`
- `get_diff`
- `run_checks`
- `render_artifact`
- `resolve_artifact`
- `commit_changes`
- `merge_to_integration`
- `test_merged_code`
- `prepare_release`
- `execute_release`

## Verified Engineer workflow

1. Inspect an allowlisted project (`list_projects`, `list_files`, `read_file`, `search_code`).
2. Create an isolated task workspace (`create_workspace`).
3. Edit inside that workspace only (`apply_patch`) and confirm actual diffs (`get_diff`).
4. Run approved checks in disposable sandboxes (`run_checks`).
5. Commit to the isolated task branch (`commit_changes`).
6. Merge into an isolated integration workspace (`merge_to_integration`).
7. Run post-merge checks on the integration revision (`test_merged_code`).
8. Generate a `READY FOR APPROVAL` release report (`prepare_release`).
9. Execute a trusted release request (`execute_release`) using a human-provided approval ID.
10. For requested media delivery, render in sandbox (`render_artifact`), then stage a validated artifact for gateway delivery (`resolve_artifact`) and send the returned `MEDIA:` path.

## Security boundaries

- Explicit repository allowlist from [allowed_projects.json](/home/mdv/mainbrain/apps/engineer_code_mcp/config/allowed_projects.json)
- Rejects path traversal and absolute paths
- Rejects `.git` internals and secret-style files/directories (`.env*`, `secrets`, `credentials`, `.ssh`)
- Rejects edits to configuration allowlists and MCP/OpenClaw service code paths
- Rejects symlink traversal/escape
- `create_workspace` uses isolated clones under managed workspace storage
- `create_workspace` defaults to the current trusted published release HEAD from release policy (`sandbox-release/main` for `engineer-sandbox`) and records the selected base SHA in workspace metadata
- `list_files`, `read_file`, and `search_code` require exactly one scope: `project_id` or `workspace_id`
- `apply_patch` validates the full unified diff before applying
- `apply_patch` reports whether actual file changes occurred and treats no-op patches as non-successful
- `get_diff` reports status + diff (including untracked files) with output size limits
- `run_checks` only accepts approved `check_id` values and workspace IDs, then calls a trusted Unix-socket runner controller
- `render_artifact` only accepts approved rendering profiles plus workspace-local script paths, then renders in disposable runner sandboxes
- `resolve_artifact` only stages validated files from approved artifact IDs into Engineer's restricted artifact-staging directory and returns a gateway-safe MEDIA path
- `commit_changes` only operates on managed `engineer/task-*` branches, stages validated workspace paths, and commits with `--no-verify`
- `merge_to_integration` creates an isolated integration worktree, merges the committed task branch there, and reports conflicts safely
- `merge_to_integration` rebases integration on the current trusted release branch HEAD, detects baseline advancement vs. workspace creation, and carries the advancement flag for required re-test/re-approval flow
- `test_merged_code` executes approved checks only against merged integration workspaces
- `test_merged_code` uses trusted runner commit-locked snapshots for integration commits and records trusted release evidence in the private executor store
- `prepare_release` requires successful post-merge tests on the exact integration commit and emits a `READY FOR APPROVAL` report without push/deploy
- `execute_release` only accepts `integration_workspace_id` + `approval_id`
- `execute_release` returns explicit release statuses (`AUTHORIZATION_REJECTED`, `PUSH_FAILED`, `DEPLOYMENT_SUCCEEDED`, `DEPLOYMENT_FAILED_ROLLED_BACK`, `DEPLOYMENT_FAILED_ROLLBACK_FAILED`)
- `execute_release` returns deployment statuses (`NOT_ATTEMPTED`, `SUCCEEDED`, `FAILED_ROLLED_BACK`, `FAILED_ROLLBACK_FAILED`)
- `execute_release` includes trusted `service_access` output with host URL/port and container port (`127.0.0.1:18765` vs `8080`)
- `execute_release` can push only to trusted policy-approved sandbox remotes/branches through the host release executor
- No NAS, PostgreSQL, Docker socket, or production secret mounts required

## Container runtime

- Entrypoint: [mcp_server_http.py](/home/mdv/mainbrain/apps/engineer_code_mcp/mcp_server_http.py)
- Port (container-internal only): `9010`
- MCP path: `/mcp`
- Health path: `/health`

Configured in [docker-compose.yml](/home/mdv/mainbrain/infra/openclaw/docker-compose.yml) as `engineer-code-mcp` on the private OpenClaw Docker network only.

## Runner controller socket integration

- Code MCP connects to a restricted Unix socket path from `ENGINEER_RUNNER_SOCKET_PATH`.
- Authentication uses `ENGINEER_RUNNER_AUTH_TOKEN`.
- Socket permissions are `0660`; controller enforces allowed peer UID for clients.
- The MCP service does **not** receive Docker socket access.
- The trusted runner controller owns Docker execution and enforces predefined checks/limits.
- Artifact staging for delivery is restricted to files under `/home/mdv/mainbrain/data/engineer-artifacts`, copied into `/home/mdv/mainbrain/data/openclaw/workspace/engineer/artifact-staging`, and exposed to the gateway as `/home/node/.openclaw/workspace/engineer/artifact-staging`.

## Release executor socket integration

- Code MCP connects to the trusted release executor via `ENGINEER_RELEASE_EXECUTOR_SOCKET_PATH`.
- Authentication uses `ENGINEER_RELEASE_EXECUTOR_AUTH_TOKEN`.
- Only the executor socket directory is mounted into Code MCP.
- The private approval DB, trusted policy files, and release credentials remain host-side and are not mounted into the Code MCP container.
