"""Launch entry points for the stable Qt interface."""

from __future__ import annotations

import argparse
from typing import Sequence


def launch_stable() -> None:
    """Start the current stable Qt application."""

    from main import main as stable_main

    stable_main()


def main(argv: Sequence[str] | None = None) -> None:
    """Run a named SciView interface launcher."""

    parser = argparse.ArgumentParser(prog="python -m sciview.launchers")
    parser.add_argument(
        "interface",
        nargs="?",
        choices=["stable"],
        default="stable",
        help="Interface to launch.",
    )
    args = parser.parse_args(argv)

    if args.interface == "stable":
        launch_stable()


if __name__ == "__main__":
    main()
