import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace

from sciview.sources.smi_facets import SmiFacets
from sciview.sources.frame_source import filtered_catalog


def test_exact_project_scope_and_commissioning_membership():
    queries = []
    class Node:
        def search(self, q): queries.append(q); return self
    filtered_catalog(Node(), {"start.project_name": "sample", "data_sessions": ["pass-1", "pass-2"]})
    assert type(queries[0]).__name__ == "Eq"
    assert type(queries[1]).__name__ == "In"
    assert queries[1].value == ["pass-1", "pass-2"]
    filtered_catalog(Node(), {"data_sessions": []})
    assert queries[-1].value == []


def test_scoped_distinct_counts_cached_without_enumerating_runs():
    calls = []
    class Node:
        item = {"links": {"self": "https://example/api/v1/metadata/smi/migration"}}
        _queries_as_params = {"filter[eq][condition][value]": "pass-1"}
        def search(self, q): return self
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            "metadata": {"start.project_name": [{"value": "one", "count": 12}, {"value": None, "count": 2}]}})
    node = Node(); node.context = SimpleNamespace(http_client=SimpleNamespace(get=get))
    service = SmiFacets(node)
    entries = service.distinct("start.project_name", {"start.data_session": "pass-1"})
    assert entries == [{"value": "one", "count": 12}]
    assert service.distinct("start.project_name", {"start.data_session": "pass-1"}) == entries
    assert len(calls) == 1
    assert calls[0][1]["params"]["filter[eq][condition][value]"] == "pass-1"


def test_cascade_starts_unfiltered_resets_children_and_searches_automatically(monkeypatch):
    from PyQt5.QtWidgets import QApplication
    from main import SciAnaApp
    from tabs.tiled_browser_tab import TiledBrowserTab
    app = QApplication.instance() or QApplication([])
    window = SciAnaApp(); tab = TiledBrowserTab(window)
    panel = tab.smi_search
    queries = []
    requests = []
    monkeypatch.setattr(tab.smi_controls, "search", lambda filters, offset=0: queries.append(dict(filters)))
    monkeypatch.setattr(panel.cycles_job, "submit", lambda work, done, error: done(["2026-3", "2026-2"]))
    monkeypatch.setattr(panel.job, "submit", lambda work, done, error: requests.append((work, done)))
    class Facets:
        def cycle_filter(self, cycle): return {"start.cycle": cycle}
        def distinct(self, field, scope):
            return [{"value": "pass-123" if field == "start.data_session" else "project A", "count": 12}]
    monkeypatch.setattr(panel, "_service", lambda epoch: Facets())
    tab.catalog_combo.setCurrentIndex(tab.catalog_combo.findData("smi_migration"))
    panel.activation_timer.stop(); panel.activate()
    assert queries == [{}]
    assert tab.legacy_search_widget.isHidden()
    assert panel.cycle.findData("commissioning") >= 0
    panel.cycle.setCurrentIndex(panel.cycle.findData("2026-3"))
    assert queries[-1] == {"start.cycle": "2026-3"}
    work, done = requests.pop(); done(work())
    assert panel.proposal.itemText(1) == "pass-123 (12)"
    panel.proposal.setCurrentIndex(1)
    assert queries[-1] == {"start.cycle": "2026-3", "start.data_session": "pass-123"}
    work, done = requests.pop(); done(work())
    panel.project.setCurrentIndex(1)
    assert queries[-1]["start.project_name"] == "project A"
    panel.cycle.setCurrentIndex(panel.cycle.findData("2026-2"))
    assert panel.proposal.currentData() == panel.project.currentData() == ""
    assert queries[-1] == {"start.cycle": "2026-2"}
    panel.clear()
    assert queries[-1] == {}
    panel.advanced_button.setChecked(True)
    assert not tab.legacy_search_widget.isHidden()
    tab.close(); window.close()
