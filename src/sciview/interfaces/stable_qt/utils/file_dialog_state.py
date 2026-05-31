"""Shared file dialog state utilities.

This module provides a minimal global default path memory for all file I/O dialogs.
It persists the most recent directory and optional per-operation directories so users
can continue from their last location without re-navigating each time.
"""

import json
from pathlib import Path
from typing import Iterable, Optional

from PyQt5.QtCore import QStandardPaths
from PyQt5.QtWidgets import QFileDialog


def _get_state_file() -> Path:
    """Return the on-disk JSON file used to persist dialog state."""
    base_dir = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    if not base_dir:
        base_dir = str(Path.home() / ".sciview")

    state_dir = Path(base_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "dialog_state.json"


def _load_state() -> dict:
    """Load persisted dialog state from JSON."""
    state_file = _get_state_file()
    if not state_file.exists():
        return {"last_dir": "", "by_key": {}}

    try:
        with state_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {"last_dir": "", "by_key": {}}

    if not isinstance(data, dict):
        return {"last_dir": "", "by_key": {}}

    data.setdefault("last_dir", "")
    data.setdefault("by_key", {})
    if not isinstance(data["by_key"], dict):
        data["by_key"] = {}

    return data


def _save_state(state: dict) -> None:
    """Persist dialog state to JSON."""
    state_file = _get_state_file()
    with state_file.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)


def _normalize_to_directory(path_text: str) -> Optional[str]:
    """Convert a selected path into a directory path suitable for dialogs."""
    if not path_text:
        return None

    path = Path(path_text).expanduser()

    if path.is_dir():
        return str(path)

    parent = path.parent
    if parent and parent.exists():
        return str(parent)

    if path.parent:
        return str(path.parent)

    return None


def get_dialog_start_dir(key: Optional[str] = None) -> str:
    """Get the best starting directory for a dialog."""
    state = _load_state()
    by_key = state.get("by_key", {})

    if key and key in by_key:
        start_dir = _normalize_to_directory(by_key.get(key, ""))
        if start_dir:
            return start_dir

    start_dir = _normalize_to_directory(state.get("last_dir", ""))
    if start_dir:
        return start_dir

    return str(Path.home())


def remember_dialog_path(selection: Optional[str], key: Optional[str] = None) -> None:
    """Remember a selected file or directory path for future dialogs."""
    if not selection:
        return

    remembered_dir = _normalize_to_directory(selection)
    if not remembered_dir:
        return

    state = _load_state()
    state["last_dir"] = remembered_dir

    if key:
        state.setdefault("by_key", {})
        state["by_key"][key] = remembered_dir

    _save_state(state)


def dialog_open_file(parent, title: str, file_filter: str, key: Optional[str] = None):
    """Open a single-file dialog with remembered start directory."""
    start_dir = get_dialog_start_dir(key)
    file_path, selected_filter = QFileDialog.getOpenFileName(parent, title, start_dir, file_filter)
    remember_dialog_path(file_path, key)
    return file_path, selected_filter


def dialog_open_files(parent, title: str, file_filter: str, key: Optional[str] = None):
    """Open a multi-file dialog with remembered start directory."""
    start_dir = get_dialog_start_dir(key)
    file_paths, selected_filter = QFileDialog.getOpenFileNames(parent, title, start_dir, file_filter)
    if file_paths:
        remember_dialog_path(file_paths[0], key)
    return file_paths, selected_filter


def dialog_save_file(parent, title: str, default_name: str, file_filter: str, key: Optional[str] = None):
    """Open a save-file dialog with remembered start directory."""
    start_dir = get_dialog_start_dir(key)
    default_path = str(Path(start_dir) / default_name) if default_name else start_dir
    file_path, selected_filter = QFileDialog.getSaveFileName(parent, title, default_path, file_filter)
    remember_dialog_path(file_path, key)
    return file_path, selected_filter


def dialog_select_directory(parent, title: str, key: Optional[str] = None):
    """Open a directory selection dialog with remembered start directory."""
    start_dir = get_dialog_start_dir(key)
    folder = QFileDialog.getExistingDirectory(parent, title, start_dir)
    remember_dialog_path(folder, key)
    return folder
