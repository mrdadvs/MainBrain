#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/mdv/mainbrain"
IMAGE_TAG="${1:-mainbrain-engineer-render:py312-mpl-ffmpeg}"

docker build \
  -f "${ROOT}/infra/openclaw/Dockerfile.engineer_render_runner" \
  -t "${IMAGE_TAG}" \
  "${ROOT}"
