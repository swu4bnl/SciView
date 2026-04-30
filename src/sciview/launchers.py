"""Launch entry points for the stable Qt interface."""

from __future__ import annotations

import argparse
import importlib
from typing import Sequence


def launch_stable() -> None:
    """Start the current stable Qt application."""

    candidate_modules = (
        "sciview.stable_app.main",
        "main",
    )

    for module_name in candidate_modules:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue

        stable_main = getattr(module, "main", None)
        if callable(stable_main):
            stable_main()
            return

    raise ImportError(
        "Could not locate the stable Qt entry point. Expected a callable "
        "`main()` in `sciview.stable_app.main` for installed usage, or in "
        "the legacy repository-root `main` module when running from a "
        "source checkout."
    )


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
