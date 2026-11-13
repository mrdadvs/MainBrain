#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/mdv/mainbrain"
SOCKET_PATH="${ENGINEER_RUNNER_SOCKET_PATH:-${ROOT}/data/engineer-code-runner/runner.sock}"
ALLOWED_PEER_UID="${ENGINEER_RUNNER_ALLOWED_PEER_UID:-1000}"
AUTH_TOKEN="${ENGINEER_RUNNER_AUTH_TOKEN:-engineer-runner-dev-token}"
RELEASE_EXECUTOR_SOCKET_PATH="${ENGINEER_RELEASE_EXECUTOR_SOCKET_PATH:-${ROOT}/data/engineer-release-executor/release-executor.sock}"
RELEASE_EXECUTOR_TIMEOUT_SECONDS="${ENGINEER_RELEASE_EXECUTOR_TIMEOUT_SECONDS:-30}"
RELEASE_EVIDENCE_AUTH_TOKEN="${ENGINEER_RELEASE_EXECUTOR_EVIDENCE_AUTH_TOKEN:-engineer-release-evidence-dev-token}"

if [[ -z "${AUTH_TOKEN}" ]]; then
  echo "ENGINEER_RUNNER_AUTH_TOKEN must not be empty" >&2
  exit 1
fi
if [[ -z "${RELEASE_EVIDENCE_AUTH_TOKEN}" ]]; then
  echo "ENGINEER_RELEASE_EXECUTOR_EVIDENCE_AUTH_TOKEN must not be empty" >&2
  exit 1
fi

mkdir -p "$(dirname "${SOCKET_PATH}")"
export ENGINEER_RUNNER_AUTH_TOKEN="${AUTH_TOKEN}"
export ENGINEER_RELEASE_EXECUTOR_SOCKET_PATH="${RELEASE_EXECUTOR_SOCKET_PATH}"
export ENGINEER_RELEASE_EXECUTOR_TIMEOUT_SECONDS="${RELEASE_EXECUTOR_TIMEOUT_SECONDS}"
export ENGINEER_RELEASE_EXECUTOR_EVIDENCE_AUTH_TOKEN="${RELEASE_EVIDENCE_AUTH_TOKEN}"

exec python3 "${ROOT}/apps/engineer_code_runner/run_job.py" serve \
  --socket-path "${SOCKET_PATH}" \
  --allowed-peer-uid "${ALLOWED_PEER_UID}"
