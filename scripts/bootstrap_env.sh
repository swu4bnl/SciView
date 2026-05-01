#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

MODE="pixi"

print_usage() {
    echo "Usage: $0 [--mode pixi|venv]"
    echo ""
    echo "Modes:"
    echo "  pixi  Configure dependencies with pixi (recommended, default)"
    echo "  venv  Configure dependencies with Python venv + pip"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)
            if [[ $# -lt 2 ]]; then
                echo "ERROR: --mode requires a value: pixi or venv"
                exit 1
            fi
            MODE="$2"
            shift 2
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown argument: $1"
            print_usage
            exit 1
            ;;
    esac
done

setup_with_pixi() {
    echo "[1/2] Checking pixi..."
    if command -v pixi >/dev/null 2>&1; then
        PIXI_BIN="$(command -v pixi)"
    elif [[ -x "$HOME/.pixi/bin/pixi" ]]; then
        PIXI_BIN="$HOME/.pixi/bin/pixi"
    else
        echo "ERROR: pixi is not installed."
        echo "Install pixi first, then rerun this script:"
        echo "  curl -fsSL https://pixi.sh/install.sh | bash"
        exit 1
    fi

    echo "[2/2] Installing pixi environment from pixi.toml..."
    "$PIXI_BIN" install

    echo ""
    echo "Environment is ready. Start SciView with:"
    echo "  ./Launch-SciView-linux.sh"
    echo "  ./Launch-SciView-macOS.command"
    echo "  ./Launch-SciView-win64.cmd"
    echo "or"
    echo "  pixi run launch-app"
}

setup_with_venv() {
    echo "[1/4] Checking Python 3..."
    if ! command -v python3 >/dev/null 2>&1; then
        echo "ERROR: python3 not found. Install Python 3.10+ first."
        exit 1
    fi

    echo "[2/4] Creating local virtual environment in .venv..."
    python3 -m venv .venv

    VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
    VENV_PIP="$PROJECT_ROOT/.venv/bin/pip"

    echo "[3/4] Upgrading pip/setuptools/wheel..."
    "$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel

    echo "[4/4] Installing project dependencies..."
    "$VENV_PIP" install -e . --no-deps
    "$VENV_PIP" install PyQt5 matplotlib scipy psutil tiled PyYAML pillow numpy

    if ! "$VENV_PIP" install scitoolsscianalysis; then
        echo "ERROR: Required dependency scitoolsscianalysis could not be installed in venv mode."
        echo "Use the supported pixi setup instead:"
        echo "  ./scripts/bootstrap_env.sh"
        exit 1
    fi

    echo ""
    echo "Environment is ready. Start SciView with:"
    echo "  PYTHONPATH=src ./.venv/bin/python main.py"
}

case "$MODE" in
    pixi)
        setup_with_pixi
        ;;
    venv)
        setup_with_venv
        ;;
    *)
        echo "ERROR: Unsupported mode '$MODE'. Use pixi or venv."
        exit 1
        ;;
esac
