# Engineer Agent Runtime Guide

This folder tracks the Git-managed instructions for the `engineer` OpenClaw agent.

## Verified runtime capabilities

- Model: `openai/gpt-6-luna`
- MCP server: `engineer` (`http://engineer-code-mcp:9010/mcp`)
- Allowed tools (14):
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

## End-to-end workflow

1. Inspect allowlisted repository content.
2. Create an isolated task workspace.
3. Read/edit using `workspace_id`, then confirm diffs.
4. Run approved checks in disposable sandboxes.
5. Commit task-branch changes.
6. Merge into isolated integration workspace.
7. Run checks on merged integration commit.
8. Prepare release report (`READY FOR APPROVAL`).
9. When media is requested, render via `render_artifact`, stage via `resolve_artifact`, then return standalone `MEDIA:` reference for outbound attachment.

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
