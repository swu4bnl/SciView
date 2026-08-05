#!/usr/bin/env bash
export DEV_TOOLS=1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

exec "$SCRIPT_DIR/scripts/run_sciview_unix.sh" "$@"
