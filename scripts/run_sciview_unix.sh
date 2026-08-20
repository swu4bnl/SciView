#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

SETUP_ONLY=0
AUTO_PULL="${SCIVIEW_AUTO_PULL:-1}"
KEEP_SHELL_OPEN="${SCIVIEW_KEEP_SHELL_OPEN:-0}"
DEV_TOOLS_FLAG="${DEV_TOOLS:-0}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --setup-only)
            SETUP_ONLY=1
            shift
            ;;
        --no-auto-pull)
            AUTO_PULL=0
            shift
            ;;
        --dev-tools)
            DEV_TOOLS_FLAG=1
            shift
            ;;
        --no-dev-tools)
            DEV_TOOLS_FLAG=0
            shift
            ;;
        *)
            break
            ;;
    esac
done

export DEV_TOOLS="$DEV_TOOLS_FLAG"

if [[ "$DEV_TOOLS" == "1" ]]; then
    echo "Developer tools: ON"
else
    echo "Developer tools: OFF"
fi

echo_step() {
    printf "\n%s\n" "$1"
}

find_pixi() {
    if command -v pixi >/dev/null 2>&1; then
        command -v pixi
        return 0
    fi

    local candidates=(
        "$HOME/.pixi/bin/pixi"
        "$HOME/.local/bin/pixi"
        "/opt/homebrew/bin/pixi"
        "/usr/local/bin/pixi"
    )

    local candidate
    for candidate in "${candidates[@]}"; do
        if [[ -x "$candidate" ]]; then
            printf "%s\n" "$candidate"
            return 0
        fi
    done

    return 1
}

install_pixi() {
    echo "SciView needs Pixi to prepare the Python environment."
    echo "Installing Pixi for this user account..."
    if ! curl -fsSL https://pixi.sh/install.sh | bash; then
        echo "ERROR: Pixi installation failed."
        return 1
    fi
    export PATH="$HOME/.pixi/bin:$HOME/.local/bin:$PATH"
    find_pixi
}

maybe_auto_pull() {
    if [[ "$AUTO_PULL" != "1" ]]; then
        echo "Skipping SciView source update check (--no-auto-pull)."
        return 0
    fi
    if [[ ! -d "$PROJECT_ROOT/.git" ]]; then
        echo "Skipping SciView source update check (not a git checkout)."
        return 0
    fi
    if ! command -v git >/dev/null 2>&1 && [[ ! -x /usr/bin/git ]]; then
        echo "Skipping SciView source update check (git not available)."
        return 0
    fi

    local git_bin
    git_bin="$(command -v git || true)"
    if [[ -z "$git_bin" ]]; then
        git_bin="/usr/bin/git"
    fi

    echo_step "Checking for SciView source updates..."
    local pull_output
    if pull_output="$("$git_bin" -C "$PROJECT_ROOT" pull --ff-only 2>&1)"; then
        if [[ -n "$pull_output" ]]; then
            printf "%s\n" "$pull_output"
        fi
        echo "Source update check finished."
    else
        if [[ -n "$pull_output" ]]; then
            printf "%s\n" "$pull_output"
        fi
        echo "Skipping source auto-update (non-fatal)."
    fi
}

run_app_command() {
    "$@"
    local exit_code=$?

    if [[ "$KEEP_SHELL_OPEN" == "1" ]]; then
        echo ""
        echo "SciView exited with code $exit_code."
        echo "SciView Closed. Press Enter to Quit."
        read -r _
    fi

    exit "$exit_code"
}

run_with_venv() {
    if [[ ! -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
        echo_step "Preparing local venv dependencies..."
        "$SCRIPT_DIR/bootstrap_env.sh" --mode venv
    fi

    if [[ "$SETUP_ONLY" == "1" ]]; then
        echo "SciView setup is ready (.venv mode)."
        exit 0
    fi

    run_app_command "$PROJECT_ROOT/.venv/bin/python" main.py
}

maybe_auto_pull

PIXI_BIN="$(find_pixi || true)"
if [[ -z "$PIXI_BIN" ]]; then
    echo_step "Pixi not found. Installing..."
    PIXI_BIN="$(install_pixi || true)"
fi

if [[ -n "$PIXI_BIN" ]]; then
    echo_step "Preparing SciView dependencies..."
    "$PIXI_BIN" install

    if [[ "$SETUP_ONLY" == "1" ]]; then
        echo "SciView setup is ready (pixi mode)."
        exit 0
    fi

    run_app_command "$PIXI_BIN" run launch-app
fi

run_with_venv
