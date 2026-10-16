from __future__ import annotations

import importlib
import importlib.metadata
import shutil
import subprocess
import sys
from pathlib import Path


REQUIRED_DISTRIBUTIONS = (
    "bluesky-tiled-plugins",
    "numpy",
    "Pillow",
    "PyQt5",
    "scitoolsscianalysis",
    "tiled",
)

REQUIRED_MODULES = (
    "bluesky_tiled_plugins",
    "main",
    "numpy",
    "PIL",
    "PyQt5.QtCore",
    "sciview.launchers",
    "tiled.client",
)


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(project_root), str(project_root / "src")]

    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(f"Expected Python 3.12, found {sys.version.split()[0]}")

    environment_root = Path(sys.prefix).resolve()
    git_executable = shutil.which("git")
    if git_executable is None:
        raise RuntimeError("Git is not available in the installed environment")

    git_path = Path(git_executable).resolve()
    if not git_path.is_relative_to(environment_root):
        raise RuntimeError(
            f"Git resolved outside the Pixi environment: {git_path} (prefix: {environment_root})"
        )

    git_version = subprocess.run(
        [git_executable, "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    versions = {
        distribution: importlib.metadata.version(distribution)
        for distribution in REQUIRED_DISTRIBUTIONS
    }
    for module in REQUIRED_MODULES:
        importlib.import_module(module)

    from bluesky_tiled_plugins import subscribe_to_streams

    if not callable(subscribe_to_streams):
        raise RuntimeError("bluesky_tiled_plugins.subscribe_to_streams is not callable")

    print(f"Python: {sys.version.split()[0]}")
    print(f"Environment: {environment_root}")
    print(f"Git: {git_version} ({git_path})")
    for distribution, version in versions.items():
        print(f"{distribution}: {version}")
    print("SciView installation verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())