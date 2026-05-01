#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

run_with_venv() {
    if [[ ! -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
        "$SCRIPT_DIR/bootstrap_env.sh" --mode venv
    fi

    exec "$PROJECT_ROOT/.venv/bin/python" main.py
}

if command -v pixi >/dev/null 2>&1; then
    PIXI_BIN="$(command -v pixi)"
elif [[ -x "$HOME/.pixi/bin/pixi" ]]; then
    PIXI_BIN="$HOME/.pixi/bin/pixi"
else
    PIXI_BIN=""
fi

if [[ -n "$PIXI_BIN" ]]; then
    "$PIXI_BIN" install
    exec "$PIXI_BIN" run launch-app
fi

run_with_venv
