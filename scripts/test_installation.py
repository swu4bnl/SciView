from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


EXCLUDED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pixi",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "archive",
    "build",
    "dist",
    "external",
}


def _find_pixi() -> str:
    executable = shutil.which("pixi")
    if executable is not None:
        return executable

    home = Path.home()
    candidates = (
        home / ".pixi" / "bin" / ("pixi.exe" if os.name == "nt" else "pixi"),
        home / ".local" / "bin" / "pixi",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("Pixi was not found. Install Pixi before you run this test.")


def _git_visible_files(source: Path) -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=True,
        capture_output=True,
    )
    return [Path(os.fsdecode(path)) for path in result.stdout.split(b"\0") if path]


def _copy_install_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    for relative_path in _git_visible_files(source):
        if EXCLUDED_DIRECTORIES.intersection(relative_path.parts):
            continue
        source_path = source / relative_path
        if not source_path.is_file():
            continue
        destination_path = destination / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)


def _run(command: list[str], *, cwd: Path, environment: dict[str, str]) -> None:
    print(f"> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, env=environment, check=True)


def _run_installation_test(project_root: Path, workspace: Path) -> None:
    pixi = _find_pixi()
    test_project = workspace / "SciView"
    cache_directory = workspace / "pixi-cache"
    _copy_install_tree(project_root, test_project)

    environment = os.environ.copy()
    for variable in tuple(environment):
        if variable.startswith(("CONDA_", "PIXI_")):
            environment.pop(variable)
    for variable in (
        "INIT_CWD",
        "PYTHONHOME",
        "PYTHONPATH",
        "SSL_CERT_DIR",
        "VIRTUAL_ENV",
    ):
        environment.pop(variable, None)
    environment["PIXI_CACHE_DIR"] = str(cache_directory)
    environment["PIXI_NO_CONFIG"] = "1"
    environment["QT_QPA_PLATFORM"] = "offscreen"

    _run(
        [pixi, "install", "--locked"],
        cwd=test_project,
        environment=environment,
    )
    _run(
        [pixi, "run", "verify-installation"],
        cwd=test_project,
        environment=environment,
    )

    if os.name == "nt":
        launcher_command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/run_sciview_windows.ps1",
            "-SetupOnly",
            "-NoAutoPull",
        ]
    else:
        launcher_command = [
            "bash",
            "scripts/run_sciview_unix.sh",
            "--setup-only",
            "--no-auto-pull",
        ]
    _run(launcher_command, cwd=test_project, environment=environment)

    print(f"Installation test workspace: {test_project}")
    print("SciView installation test passed.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install SciView in an isolated workspace and verify the installation."
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the test workspace for debugging.",
    )
    arguments = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    if arguments.keep:
        workspace = Path(tempfile.mkdtemp(prefix="sciview-installation-"))
        print(f"Keeping the installation test workspace at {workspace}")
        _run_installation_test(project_root, workspace)
    else:
        with tempfile.TemporaryDirectory(prefix="sciview-installation-") as temporary:
            _run_installation_test(project_root, Path(temporary))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(f"Installation test failed with exit code {error.returncode}.", file=sys.stderr)
        raise SystemExit(error.returncode) from error