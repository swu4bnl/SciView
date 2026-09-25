from types import SimpleNamespace
import pytest
from sciview.sources.tiled_auth import sign_in


def test_device_flow_pending_slowdown_success(monkeypatch):
    from tiled.client.context import Context
    calls, notices, saved, waits = [], [], [], []
    responses = iter([
        (200, {"verification_uri": "https://login.example/device", "user_code": "CODE", "device_code": "secret", "expires_in": 100, "interval": 1}),
        (400, {"error": "authorization_pending"}),
        (400, {"error": "slow_down"}),
        (200, {"access_token": "token"}),
    ])
    def post(url, **kwargs):
        calls.append((url, kwargs))
        status, payload = next(responses)
        return SimpleNamespace(status_code=status, json=lambda: payload, is_error=False)
    provider = SimpleNamespace(mode="external", extra_scopes=[], links={
        "auth_endpoint": "https://login.example/start", "client_id": "id", "token_endpoint": "https://login.example/token"})
    context = SimpleNamespace(use_cached_tokens=lambda: False,
        server_info=SimpleNamespace(authentication=SimpleNamespace(providers=[provider])),
        http_client=SimpleNamespace(post=post), configure_auth=lambda t, **kw: saved.append(t), whoami=lambda: {"identities": []})
    monkeypatch.setattr(Context, "from_any_uri", lambda *_: (context, None))
    monkeypatch.setattr("tiled.client.utils.handle_error", lambda response: response)
    cancel = SimpleNamespace(wait=lambda interval: waits.append(interval) or False, is_set=lambda: False)
    sign_in("https://tiled.example", cancel, lambda *args: notices.append(args))
    assert notices == [("https://login.example/device", "CODE")]
    assert waits == [1, 1, 6]
    assert saved == [{"access_token": "token"}]


def test_device_login_reuses_cached_session(monkeypatch):
    from tiled.client.context import Context
    context = SimpleNamespace(use_cached_tokens=lambda: True, whoami=lambda: {"identities": [{"id": "user"}]})
    monkeypatch.setattr(Context, "from_any_uri", lambda *_: (context, None))
    assert sign_in("https://tiled.example", None, None)["identities"][0]["id"] == "user"


def test_startup_identity_never_starts_device_login(monkeypatch):
    from tiled.client.context import Context
    from sciview.sources.tiled_auth import cached_identity
    context = SimpleNamespace(use_cached_tokens=lambda: True, whoami=lambda: {"identities": [{"id": "saved-user"}]})
    monkeypatch.setattr(Context, "from_any_uri", lambda *a, **kw: (context, None))
    assert cached_identity("https://tiled.example") == "saved-user"
    context.use_cached_tokens = lambda: False
    context.whoami = lambda: (_ for _ in ()).throw(AssertionError("No token should not call whoami"))
    assert cached_identity("https://tiled.example") is None


def test_startup_saved_login_populates_list_without_dialog(monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    from main import SciAnaApp
    from tabs.tiled_browser_tab import TiledBrowserTab
    app = QApplication.instance() or QApplication([])
    window = SciAnaApp(); tab = TiledBrowserTab(window)
    calls = []
    monkeypatch.setattr("sciview.sources.tiled_auth.cached_identity", lambda uri: "saved-user")
    monkeypatch.setattr(tab.auth_job, "submit", lambda work, done, error: done(work()))
    monkeypatch.setattr(tab.smi_controls, "search", lambda filters: calls.append(filters))
    tab.catalog_combo.blockSignals(True)
    tab.catalog_combo.setCurrentIndex(tab.catalog_combo.findData("smi_migration"))
    tab.catalog_combo.blockSignals(False)
    tab.smi_search.activation_timer.stop()
    tab._refresh_auth_state()
    assert "saved-user" in tab.auth_status_label.text()
    assert calls == [{}]
    assert "_smi_login" not in tab.__dict__
    tab.close(); window.close()


def test_forced_login_does_not_short_circuit_on_cached_session(monkeypatch):
    from tiled.client.context import Context
    def cached():
        raise AssertionError("Forced login must bypass cached-token shortcut")
    context = SimpleNamespace(use_cached_tokens=cached,
        server_info=SimpleNamespace(authentication=SimpleNamespace(providers=[])))
    monkeypatch.setattr(Context, "from_any_uri", lambda *_: (context, None))
    with pytest.raises(RuntimeError, match="no external provider"):
        sign_in("https://tiled.example", None, None, force=True)


def test_login_dialog_stays_open_after_cached_success(monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    from sciview.interfaces.stable_qt.widgets import tiled_login
    app = QApplication.instance() or QApplication([])
    requests = []
    monkeypatch.setattr(tiled_login.LatestJob, "submit", lambda self, work, apply, error: requests.append(work))
    monkeypatch.setattr(tiled_login, "sign_in", lambda *a, **kw: kw["force"])
    dialog = tiled_login.TiledLoginDialog("https://tiled.example")
    emitted = []
    dialog.authenticated.connect(lambda: emitted.append(True))
    dialog.show()
    dialog.success({"identities": [{"id": "test-user"}]})
    app.processEvents()
    assert dialog.isVisible()
    assert "test-user" in dialog.status.text()
    assert emitted == [True]
    assert dialog.close_button.text() == "Close"
    assert requests[0]() is False
    dialog.retry_button.click()
    assert requests[1]() is True
    dialog.failure(RuntimeError("expired"))
    assert dialog.isVisible()
    assert dialog.retry_button.isEnabled()
    dialog.close_button.click()
    assert not dialog.isVisible()
