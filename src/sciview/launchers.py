"""Launch entry points for the SciView Qt application."""

from __future__ import annotations

import argparse
import importlib
import os
from typing import Sequence


def launch_app() -> None:
    """Start the SciView Qt application."""

    candidate_modules = (
        ("sciview.stable_app.main", True),
        ("main", False),
    )

    for module_name, allow_missing_module in candidate_modules:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            if allow_missing_module:
                continue
            raise

        app_main = getattr(module, "main", None)
        if callable(app_main):
            app_main()
            return

    raise ImportError(
        "Could not locate the SciView Qt entry point. Expected a callable "
        "`main()` in `sciview.stable_app.main` for installed usage, or in "
        "the legacy repository-root `main` module when running from a "
        "source checkout."
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Run a named SciView launcher."""

    parser = argparse.ArgumentParser(prog="python -m sciview.launchers")
    parser.add_argument(
        "--scianalysis-source",
        choices=("auto", "pixi", "local", "custom"),
        default=None,
        help="Select the SciAnalysis source to use.",
    )
    parser.add_argument(
        "--scianalysis-path",
        default=None,
        help="Path to a local or custom SciAnalysis checkout.",
    )
    parser.add_argument(
        "launcher",
        nargs="?",
        default="app",
        help="Launcher to run.",
    )
    args = parser.parse_args(argv)

    if args.scianalysis_source is not None:
        os.environ["SCIVIEW_SCIANALYSIS_SOURCE"] = args.scianalysis_source
    if args.scianalysis_path is not None:
        os.environ["SCIVIEW_SCIANALYSIS_PATH"] = args.scianalysis_path

    if args.launcher in {"app", "stable"}:
        launch_app()
        return

    parser.error(f"unknown launcher: {args.launcher}")


if __name__ == "__main__":
    main()
