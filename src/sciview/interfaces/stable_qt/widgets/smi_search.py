"""Automatic SMI browsing: all recent scans → cycle → proposal → project."""
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QComboBox, QLabel, QPushButton, QApplication

from sciview.interfaces.services.latest_job import LatestJob
from sciview.sources.smi_facets import SmiFacets, cycle_choices
from sciview.sources.tiled_client import tiled_manager


class SmiSearchPanel(QWidget):
    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.job = LatestJob(self)
        self.cycles_job = LatestJob(self)
        self.service = None
        self._epoch = 0
        self._worker_epoch = -1
        self._cycle_scope = {}
        self.activation_timer = QTimer(self)
        self.activation_timer.setSingleShot(True)
        self.activation_timer.timeout.connect(self.activate)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.cycle = QComboBox(); self.proposal = QComboBox(); self.project = QComboBox()
        self.cycle.addItem("All cycles", "")
        self.cycle.addItem("Commissioning", "commissioning")
        for value in ("2026-3", "2026-2", "2026-1", "2025-3", "2025-2", "2025-1"):
            self.cycle.addItem(value, value)
        self._replace(self.proposal, "All proposals", [])
        self._replace(self.project, "All projects", [])
        self.proposal.setEnabled(False); self.project.setEnabled(False)
        for label, widget in (("Cycle", self.cycle), ("Proposal", self.proposal), ("Project", self.project)):
            widget.setMinimumWidth(0)
            widget.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            widget.setMinimumContentsLength(12)
            form.addRow(label, widget)
        layout.addLayout(form)
        self.status = QLabel("Showing newest scans first. Select a cycle to narrow the list.")
        self.status.setWordWrap(True); layout.addWidget(self.status)
        reset = QPushButton("Clear filters / newest scans")
        reset.clicked.connect(self.clear); layout.addWidget(reset)
        self.advanced_button = QPushButton("Advanced: scan ID / text search")
        self.advanced_button.setCheckable(True)
        self.advanced_button.toggled.connect(self._advanced)
        layout.addWidget(self.advanced_button)
        self.cycle.currentIndexChanged.connect(self.cycle_changed)
        self.proposal.currentIndexChanged.connect(self.proposal_changed)
        self.project.currentIndexChanged.connect(self.project_changed)
        QApplication.instance().aboutToQuit.connect(self.close_jobs)

    def close_jobs(self):
        self.activation_timer.stop()
        self.job.close(); self.cycles_job.close()

    def _advanced(self, checked):
        self.tab.legacy_search_widget.setVisible(checked)
        self.tab.more_filters_button.setVisible(checked)
        if not checked:
            self.tab.advanced_filters_widget.hide()
            self.tab.more_filters_button.setChecked(False)

    def _replace(self, combo, all_label, entries):
        combo.blockSignals(True)
        combo.clear(); combo.addItem(all_label, "")
        for entry in entries:
            value, count = str(entry["value"]), entry.get("count")
            label = entry.get("label", value)
            combo.addItem(f"{label} ({count:,})" if count is not None else label, value)
        combo.blockSignals(False)

    def _service(self, epoch):
        if self.service is None or self._worker_epoch != epoch:
            catalog = tiled_manager.get_or_load_catalog("smi_migration")
            if catalog is None:
                raise RuntimeError("Sign in to load proposal choices")
            self.service = SmiFacets(catalog)
            self._worker_epoch = epoch
        return self.service

    def activate(self):
        if self.job._closed:
            return
        self._epoch += 1
        self.job.invalidate(); self.cycles_job.invalidate()
        self.setVisible(self.tab.smi_controls.active())
        for widget in self.tab.legacy_scope_widgets:
            widget.setVisible(not self.tab.smi_controls.active())
        if not self.tab.smi_controls.active():
            self.tab.legacy_search_widget.show()
            self.tab.more_filters_button.show()
            return
        self.advanced_button.setChecked(False); self._advanced(False)
        # Always start unfiltered: an old proposal must not hide newly taken runs.
        self.clear()
        epoch = self._epoch
        def done(cycles):
            if epoch != self._epoch or not self.tab.smi_controls.active(): return
            value = self.cycle.currentData()
            self.cycle.blockSignals(True)
            self.cycle.clear(); self.cycle.addItem("All cycles", ""); self.cycle.addItem("Commissioning", "commissioning")
            for cycle in cycles: self.cycle.addItem(cycle, cycle)
            self.cycle.setCurrentIndex(max(0, self.cycle.findData(value)))
            self.cycle.blockSignals(False)
        self.cycles_job.submit(cycle_choices, done, lambda exc: None)

    def clear(self):
        self.cycle.blockSignals(True); self.cycle.setCurrentIndex(0); self.cycle.blockSignals(False)
        self.cycle_changed()

    def cycle_changed(self, *_):
        if not self.tab.smi_controls.active(): return
        self.job.invalidate()
        cycle = self.cycle.currentData() or ""
        self._cycle_scope = {} if cycle in ("", "commissioning") else {"start.cycle": cycle}
        if cycle == "commissioning":
            self._cycle_scope = {"data_sessions": []}
        self._replace(self.proposal, "All proposals", [])
        self._replace(self.project, "All projects", [])
        self.proposal.setEnabled(False); self.project.setEnabled(False)
        if cycle != "commissioning":
            self.tab.smi_controls.search(dict(self._cycle_scope))
        else:
            self.tab.smi_controls.clear_results()
            self.tab.search_status_label.setText("Resolving commissioning proposals…")
        if not cycle:
            self.status.setText("All scans, newest first. Select a cycle to load proposals and their scan counts.")
            return  # no expensive 2.7-million-run distinct query on startup
        self.status.setText("Loading proposals and scan counts…")
        epoch = self._epoch
        def work():
            service = self._service(epoch)
            scope = service.cycle_filter(cycle)
            try:
                entries = service.distinct("start.data_session", scope)
                return scope, entries, None
            except Exception as exc:
                entries = [{"value": value, "count": None} for value in scope.get("data_sessions", [])]
                return scope, entries, str(exc)
        def done(payload):
            scope, entries, error = payload
            self._cycle_scope = scope
            if cycle == "commissioning": self.tab.smi_controls.search(dict(scope))
            self._replace(self.proposal, "All proposals", sorted(entries, key=lambda e: str(e["value"]), reverse=True))
            self.proposal.setEnabled(bool(entries))
            self.status.setText(f"Proposal counts unavailable: {error}. Scan browsing still works." if error else
                                f"{len(entries)} proposals. Choose one, or leave All proposals selected.")
        self.job.submit(work, done, self.error)

    def proposal_changed(self, *_):
        if not self.tab.smi_controls.active(): return
        self.job.invalidate()
        proposal = self.proposal.currentData() or ""
        scope = dict(self._cycle_scope)
        if proposal: scope["start.data_session"] = proposal
        self._replace(self.project, "All projects", [])
        self.project.setEnabled(False)
        self.tab.smi_controls.search(scope)
        if not proposal:
            self.status.setText("Showing all proposals in the selected cycle.")
            return
        self.status.setText("Loading projects and scan counts…")
        epoch = self._epoch
        def done(entries):
            self._replace(self.project, "All projects", sorted(entries, key=lambda e: str(e["value"]).lower()))
            self.project.setEnabled(bool(entries))
            self.status.setText(f"{len(entries)} projects. Leave All projects selected to see the whole proposal.")
        self.job.submit(lambda: self._service(epoch).distinct("start.project_name", scope), done, self.error)

    def filters(self):
        scope = dict(self._cycle_scope)
        for key, combo in (("start.data_session", self.proposal), ("start.project_name", self.project)):
            value = combo.currentData()
            if value: scope[key] = value
        return scope

    def project_changed(self, *_):
        if self.tab.smi_controls.active(): self.tab.smi_controls.search(self.filters())

    def error(self, exc):
        self.status.setText(f"Dropdown lookup failed: {exc}. Use Refresh or select the cycle again.")

    def show_count(self, count):
        # Exact selected-scope counts; unselected cycle counts remain lazy.
        combo = self.project if self.project.currentData() else self.proposal if self.proposal.currentData() else self.cycle
        value = combo.currentData()
        label = ("Commissioning" if value == "commissioning" else str(value)) if value else "All cycles"
        combo.setItemText(combo.currentIndex(), f"{label} ({count:,})")
