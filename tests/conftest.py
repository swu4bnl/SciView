"""Initialize Chromium before any test creates a QApplication."""

from PyQt6 import QtWebEngineWidgets
import pytest


@pytest.fixture(autouse=True)
def isolate_session_cache(tmp_path, monkeypatch):
    """Keep app and dialog state writes inside each test's temporary directory."""
    from sciview.session import session_cache

    cache_dir = tmp_path.parent / f"{tmp_path.name}-sciview-session"

    def test_session_dir():
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    monkeypatch.setattr(session_cache, "session_dir", test_session_dir)
