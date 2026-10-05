"""Per-user restart state under Qt's generic data directory / sciview / session.

If two sessions for the same user are open at once, the last saved manifest wins.

Large/binary payloads (e.g. hand-edited mask layers) are stored as separate
compressed ``.npz`` files next to the JSON manifest, referenced by filename.
"""

import json
import shutil
import tempfile
from uuid import uuid4
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PyQt5.QtCore import QCoreApplication, QStandardPaths
from PyQt5.QtWidgets import QFileDialog

_SESSION_FILENAME = "session_state.json"
_DIALOG_FILENAME = "dialog_state.json"
_ARRAYS_SUBDIR = "arrays"
_LEGACY_QT_ORGANIZATION = "CMS (11-BM)"
_LEGACY_QT_APPLICATION = "SciAnalysis GUI"
_scratch_path: Path | None = None


def legacy_qt_dir(location: QStandardPaths.StandardLocation) -> Path | None:
    """Ask Qt for the path used by the previous application identity."""
    application = QCoreApplication.instance()
    if application is None:
        return None
    organization, name = application.organizationName(), application.applicationName()
    try:
        application.setOrganizationName(_LEGACY_QT_ORGANIZATION)
        application.setApplicationName(_LEGACY_QT_APPLICATION)
        return Path(QStandardPaths.writableLocation(location))
    finally:
        application.setApplicationName(name)
        application.setOrganizationName(organization)


def session_dir() -> Path:
    """Directory holding this user's session cache, created if missing."""
    base = QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)
    if not base:
        raise RuntimeError("No per-user data directory available")
    directory = Path(base) / "sciview" / "session"
    if not directory.exists():
        legacy_base = legacy_qt_dir(QStandardPaths.AppDataLocation)
        directory.parent.mkdir(parents=True, exist_ok=True)
        if legacy_base is not None:
            legacy_dir = legacy_base / "session"
            if legacy_dir.is_dir():
                shutil.move(str(legacy_dir), str(directory))
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _session_file() -> Path:
    return session_dir() / _SESSION_FILENAME


def _dialog_file() -> Path:
    target = session_dir() / _DIALOG_FILENAME
    if not target.exists():
        current = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
        old_locations = (Path(current) if current else None, legacy_qt_dir(QStandardPaths.AppConfigLocation))
        for directory in old_locations:
            if directory is None:
                continue
            previous = directory / _DIALOG_FILENAME
            if previous.is_file() and previous != target:
                shutil.move(str(previous), str(target))
                break
    return target


def _write_json(target: Path, state: dict[str, Any]) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(state, handle, indent=2)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_json(target: Path) -> dict[str, Any]:
    try:
        with target.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_dialog_state() -> dict[str, Any]:
    return _read_json(_dialog_file())


def save_dialog_state(state: dict[str, Any]) -> None:
    _write_json(_dialog_file(), state)


def choose_path(parent, title: str, *, mode: str = "open", file_filter: str = "",
                default_name: str = "", key: str | None = None):
    """Show one remembered file/directory dialog; return selection and filter."""
    state = load_dialog_state()
    by_key = state.get("by_key") if isinstance(state.get("by_key"), dict) else {}
    start_dir = by_key.get(key) if key else None
    start_dir = start_dir or state.get("last_dir") or str(Path.home())
    if not Path(start_dir).is_dir():
        start_dir = str(Path.home())

    dialog = QFileDialog(parent, title, start_dir, file_filter)
    if mode == "save":
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setFileMode(QFileDialog.AnyFile)
        if default_name:
            dialog.selectFile(default_name)
    elif mode == "directory":
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
    elif mode == "open_files":
        dialog.setFileMode(QFileDialog.ExistingFiles)
    elif mode == "open":
        dialog.setFileMode(QFileDialog.ExistingFile)
    else:
        raise ValueError(f"Unknown dialog mode: {mode}")

    if not dialog.exec_():
        return ([] if mode == "open_files" else ""), ""
    paths = dialog.selectedFiles()
    if not paths:
        return ([] if mode == "open_files" else ""), ""
    selection = paths if mode == "open_files" else paths[0]
    chosen_dir = paths[0] if mode == "directory" else str(Path(paths[0]).parent)
    state["last_dir"] = chosen_dir
    if key:
        by_key[key] = chosen_dir
        state["by_key"] = by_key
    save_dialog_state(state)
    return selection, dialog.selectedNameFilter()


def _arrays_dir() -> Path:
    directory = session_dir() / _ARRAYS_SUBDIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_array(name: str, array: np.ndarray) -> str:
    """Persist an array (e.g. a mask layer) and return its filename for the manifest."""
    filename = f"{name}-{uuid4().hex}.npz"
    path = _arrays_dir() / filename
    tmp_path = path.with_suffix(".npz.tmp")
    with tmp_path.open("wb") as handle:
        np.savez_compressed(handle, data=array)
    tmp_path.replace(path)
    return filename


def load_array(filename: str) -> Optional[np.ndarray]:
    """Load a previously saved array by filename, or None if missing/corrupt."""
    if not filename:
        return None
    path = _arrays_dir() / filename
    if not path.exists():
        return None
    try:
        with np.load(path) as npz:
            return npz["data"]
    except Exception:
        return None


def save_session(state: dict[str, Any]) -> None:
    """Atomically write the full session state dict as JSON."""
    _write_json(_session_file(), state)


def load_session() -> dict[str, Any]:
    """Load the last saved session state, or {} if missing/corrupt."""
    return _read_json(_session_file())


def scratch_dir() -> Path:
    """Private scratch space owned by this application instance."""
    global _scratch_path
    if _scratch_path is None:
        _scratch_path = Path(tempfile.mkdtemp(prefix="sciview-"))
    return _scratch_path


def new_scratch_path(name: str, suffix: str) -> Path:
    """Return a fresh scratch file path; the caller writes the actual file."""
    return scratch_dir() / f"{name}-{uuid4().hex}{suffix}"


def clear_scratch() -> None:
    """Remove only this instance's scratch files when no editor holds them open."""
    global _scratch_path
    if _scratch_path is not None:
        shutil.rmtree(_scratch_path, ignore_errors=True)
        _scratch_path = None


def clear_session() -> None:
    """Delete persisted session state and arrays (manual cleanup action)."""
    shutil.rmtree(session_dir(), ignore_errors=True)
