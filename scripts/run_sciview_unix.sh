#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

export PYTHONPATH="$PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

ORIGINAL_ARGS=("$@")
SETUP_ONLY=0
AUTO_PULL="${SCIVIEW_AUTO_PULL:-1}"
ACCEPT_PIXI_INSTALL="${SCIVIEW_ACCEPT_PIXI_INSTALL:-0}"
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
        --accept-pixi-install)
            ACCEPT_PIXI_INSTALL=1
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
fi

# When started from a desktop entry or Finder, keep the window open so the
# user can read what happened before it closes.
pause_before_exit() {
    local exit_code=$?
    if [[ "$KEEP_SHELL_OPEN" == "1" ]]; then
        echo ""
        if [[ "$exit_code" -ne 0 ]]; then
            echo "SciView stopped with exit code $exit_code. Review the messages above."
        fi
        read -r -p "Press Enter to close this window. " _ || true
    fi
}
trap pause_before_exit EXIT

echo_step() {
    printf "\n%s\n" "$1"
}

ask_yes_no() {
    # Usage: ask_yes_no "Question? [Y/n]" default-letter
    local answer
    read -r -p "$1 " answer || answer=""
    answer="${answer:-$2}"
    case "$answer" in
        [Yy]|[Yy][Ee][Ss]) return 0 ;;
        *) return 1 ;;
    esac
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
    echo "Installing Pixi for this user account..." >&2
    if ! curl -fsSL https://pixi.sh/install.sh | bash >&2; then
        echo "ERROR: Pixi installation failed." >&2
        return 1
    fi
    export PATH="$HOME/.pixi/bin:$HOME/.local/bin:$PATH"
    find_pixi
}

maybe_auto_pull() {
    local pixi_bin="${1:-}"

    if [[ "$AUTO_PULL" != "1" ]]; then
        echo "Skipping SciView source update check (--no-auto-pull)."
        return 0
    fi
    if [[ ! -d "$PROJECT_ROOT/.git" ]]; then
        echo "Skipping SciView source update check (not a git checkout)."
        return 0
    fi

    local git_cmd=()
    if [[ -n "$pixi_bin" ]]; then
        git_cmd=("$pixi_bin" run -- git)
    elif command -v git >/dev/null 2>&1; then
        git_cmd=("$(command -v git)")
    elif [[ -x /usr/bin/git ]]; then
        git_cmd=(/usr/bin/git)
    else
        echo "Skipping SciView source update check (git not available)."
        return 0
    fi

    echo_step "Checking for SciView source updates..."
    if ! "${git_cmd[@]}" -C "$PROJECT_ROOT" fetch --quiet; then
        echo "Skipping source auto-update (git fetch failed)."
        return 0
    fi

    local upstream
    if ! upstream="$("${git_cmd[@]}" -C "$PROJECT_ROOT" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)" || [[ -z "$upstream" ]]; then
        echo "Skipping SciView source update (current branch has no upstream)."
        return 0
    fi

    local behind
    if ! behind="$("${git_cmd[@]}" -C "$PROJECT_ROOT" rev-list --count "HEAD..$upstream")"; then
        echo "Skipping source auto-update (unable to compare with $upstream)."
        return 0
    fi
    if [[ "$behind" == "0" ]]; then
        echo "SciView is up to date."
        return 0
    fi

    echo "$behind update commit(s) available from $upstream."
    if ! ask_yes_no "Update SciView now? [y/N]" n; then
        echo "Skipping SciView source update."
        return 0
    fi

    if "${git_cmd[@]}" -C "$PROJECT_ROOT" merge --ff-only "$upstream"; then
        echo "SciView source updated. Restarting the launcher..."
        # The update may have changed this script on disk. Bash reads scripts
        # incrementally, so restart instead of continuing with stale code.
        exec "$SCRIPT_DIR/run_sciview_unix.sh" --no-auto-pull ${ORIGINAL_ARGS[@]+"${ORIGINAL_ARGS[@]}"}
    fi
    echo "Skipping source auto-update (fast-forward merge failed)."
}

offer_app_entry() {
    # Best effort: a failed application-list step must not block SciView.
    bash "$SCRIPT_DIR/install_sciview_launcher_unix.sh" --from-launcher \
        || echo "SciView could not update its application-list entry; continuing."
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

    offer_app_entry
    echo_step "Starting SciView..."
    "$PROJECT_ROOT/.venv/bin/python" main.py "$@"
}

PIXI_BIN="$(find_pixi || true)"
if [[ -z "$PIXI_BIN" || ! -d "$PROJECT_ROOT/.pixi/envs/default" ]]; then
    echo_step "First-time setup: SciView installs its Python environment once. This takes a few minutes."
fi

if [[ -z "$PIXI_BIN" ]]; then
    echo "SciView uses Pixi, a small Python environment manager, installed for this user account only."
    if [[ "$ACCEPT_PIXI_INSTALL" == "1" ]] || ask_yes_no "Install Pixi now? [Y/n]" y; then
        PIXI_BIN="$(install_pixi || true)"
    else
        echo "Setup was cancelled. SciView needs Pixi before it can start."
        exit 1
    fi
fi

if [[ -n "$PIXI_BIN" ]]; then
    echo_step "Preparing SciView dependencies..."
    if ! "$PIXI_BIN" install; then
        echo "ERROR: SciView could not prepare its dependencies. Review the error above, then run the launcher again."
        exit 1
    fi

    maybe_auto_pull "$PIXI_BIN"

    if [[ "$SETUP_ONLY" == "1" ]]; then
        echo "SciView setup is ready (pixi mode)."
        exit 0
    fi

    offer_app_entry
    echo_step "Starting SciView..."
    "$PIXI_BIN" run launch-app "$@"
    exit 0
fi

echo "Pixi is not available. Falling back to a local Python venv."
maybe_auto_pull ""
run_with_venv "$@"
