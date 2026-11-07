#!/bin/bash
# OpenClaw Log Viewer - Stream or view gateway logs

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-follow}"  # follow (default, -f) or tail (static)
LINES="${2:-100}"

case "${MODE}" in
    follow|live)
        echo "Following OpenClaw gateway logs (Ctrl+C to stop)..."
        docker compose -f "${SCRIPT_DIR}/docker-compose.yml" logs -f --tail=${LINES} openclaw-gateway
        ;;
    
    tail|static)
        echo "Last ${LINES} lines of OpenClaw gateway logs:"
        docker compose -f "${SCRIPT_DIR}/docker-compose.yml" logs --tail=${LINES} openclaw-gateway
        ;;
    
    *)
        echo "Usage: $0 {follow|tail} [lines]"
        echo ""
        echo "Modes:"
        echo "  follow  - Stream logs live (default)"
        echo "  tail    - Show last N lines (default 100)"
        echo ""
        echo "Examples:"
        echo "  $0              # Follow logs"
        echo "  $0 tail 50      # Last 50 lines"
        echo ""
        exit 1
        ;;
esac
