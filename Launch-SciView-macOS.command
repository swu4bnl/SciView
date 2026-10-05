#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

export SCIVIEW_KEEP_SHELL_OPEN=1
"$SCRIPT_DIR/scripts/run_sciview_unix.sh" "$@"
