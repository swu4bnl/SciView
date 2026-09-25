"""Searchable run metadata tree and baseline/configuration tables.

All filtering operates on already-loaded data; expanding JSON never reads Tiled.
"""
import json
import math

import numpy as np
from PyQt5.QtCore import Qt, QSortFilterProxyModel
from PyQt5.QtGui import QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel,
    QTreeView, QTableView, QStackedWidget, QSplitter, QPlainTextEdit,
    QApplication, QCheckBox, QHeaderView, QAbstractItemView,
)


def plain(value):
    if isinstance(value, np.ndarray): return plain(value.tolist())
    if isinstance(value, np.generic): return plain(value.item())
    if isinstance(value, bytes): return value.decode("utf-8", errors="replace")
    if isinstance(value, dict): return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value): return str(value)
    if value is None or isinstance(value, (str, int, float, bool)): return value
    return str(value)


def display(value):
    if isinstance(value, str): return value
    return json.dumps(plain(value), ensure_ascii=False)


def baseline_rows(data):
    rows = []
    for field, values in data.items():
        samples = plain(np.atleast_1d(values))
        before = samples[0] if samples else None
        after = samples[-1] if len(samples) > 1 else None
        changed = len(samples) > 1 and before != after
        delta = None
        if (len(samples) > 1 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                    for v in (before, after))):
            delta = after - before
        detail = dict(field=field, samples=samples, before=before, after=after,
                      changed=changed, delta=delta)
        cells = [field, display(before) if samples else "", display(after) if len(samples)>1 else "",
                 display(delta) if delta is not None else "", "Yes" if changed else "No" if len(samples)>1 else "—", len(samples)]
        rows.append((cells, detail, changed))
    return rows


def configuration_rows(data):
    """Flatten scientific values, retaining device, descriptor units and full paths."""
    rows = []
    def add(device, field, value, path, descriptor=None):
        descriptor = descriptor if isinstance(descriptor, dict) else {}
        detail = dict(device=device, field=field, value=plain(value), path=path, descriptor=plain(descriptor))
        rows.append(([device, field, display(value), descriptor.get("units", ""),
                      descriptor.get("source", ""), descriptor.get("dtype", ""), path], detail, False))

    def walk(device, value, path):
        if isinstance(value, dict) and isinstance(value.get("data"), dict):
            descriptors = value.get("data_keys") or {}
            for field, item in value["data"].items():
                add(device, field, item, f"{path}.data.{field}", descriptors.get(field))
            # Preserve auxiliary metadata, including timestamps, in searchable rows.
            for key, item in value.items():
                if key not in ("data", "data_keys"): walk(device, item, f"{path}.{key}")
        elif isinstance(value, dict) and value:
            for key, item in value.items(): walk(device, item, f"{path}.{key}")
        else:
            add(device, path.rsplit(".", 1)[-1], value, path)

    if not data: return rows
    config = data.get("configuration", {}) if "config_nodes" in data else data
    for device, block in config.items(): walk(str(device), block, f"configuration.{device}")
    if "config_nodes" in data:
        def nodes(node, path="config", device=""):
            for key, value in node.items():
                if key == "children" and isinstance(value, dict):
                    for name, child in value.items(): nodes(child, f"{path}.{name}", device or name)
                elif value not in ({}, []): walk(device, value, f"{path}.{key}")
        nodes(data["config_nodes"])
    return rows


class DetailFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query = ""
        self.changed_only = False
        self.setRecursiveFilteringEnabled(True)
        self.setSortCaseSensitivity(Qt.CaseInsensitive)

    def filterAcceptsRow(self, row, parent):
        model = self.sourceModel()
        index = model.index(row, 0, parent)
        if self.changed_only and not index.data(Qt.UserRole+2): return False
        if not self.query: return True
        # Parent matches keep their descendants visible; recursive filtering
        # also retains parent paths when only a descendant matches.
        while index.isValid():
            if self.query in (index.data(Qt.UserRole+1) or "").casefold(): return True
            index = index.parent()
        return False


class MetadataView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.document = {}
        self.section = "Run metadata"
        self.identity = None
        root = QVBoxLayout(self)
        tools = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Filter fields, values, device names or paths…")
        self.search.setClearButtonEnabled(True); self.search.textChanged.connect(self.filter)
        tools.addWidget(self.search, 1)
        self.changed = QCheckBox("Changed only"); self.changed.toggled.connect(self.filter); tools.addWidget(self.changed)
        self.expand = QPushButton("Expand all"); self.collapse = QPushButton("Collapse all")
        tools.addWidget(self.expand); tools.addWidget(self.collapse)
        copy = QPushButton("Copy JSON"); copy.clicked.connect(self.copy_json); tools.addWidget(copy)
        root.addLayout(tools)
        self.count = QLabel(); root.addWidget(self.count)
        split = QSplitter(Qt.Vertical); root.addWidget(split, 1)
        self.stack = QStackedWidget(); split.addWidget(self.stack)
        self.tree = QTreeView(); self.tree.setAlternatingRowColors(True); self.tree.setUniformRowHeights(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # Preserve JSON array order (lexical sorting would put index 10 before 2).
        self.tree.setSortingEnabled(False)
        self.table = QTableView(); self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True); self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(False)
        self.stack.addWidget(self.tree); self.stack.addWidget(self.table)
        self.detail = QPlainTextEdit(); self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Select a field for its complete value and metadata. Copy JSON copies the selected item, or the full document.")
        split.addWidget(self.detail); split.setSizes([600, 150])
        self.expand.clicked.connect(self.tree.expandAll); self.collapse.clicked.connect(self.tree.collapseAll)
        self.proxy = DetailFilter(self)
        self.model = QStandardItemModel(self)
        self.proxy.setSourceModel(self.model)
        self.tree.setModel(self.proxy); self.table.setModel(self.proxy)
        self.tree.selectionModel().currentChanged.connect(self.selection)
        self.table.selectionModel().currentChanged.connect(self.selection)
        self.set_document("Run metadata", {})

    def set_document(self, section, data, identity=None):
        if identity is not None and identity == self.identity: return
        self.identity = identity
        self.section, self.document = section, plain(data)
        self.detail.clear()
        self.proxy.setSourceModel(None)
        old = self.model
        self.model = QStandardItemModel(self)
        tree_mode = section == "Run metadata"
        self.stack.setCurrentWidget(self.tree if tree_mode else self.table)
        self.expand.setVisible(tree_mode); self.collapse.setVisible(tree_mode)
        self.changed.setVisible(section == "Baseline")
        if tree_mode:
            self.model.setHorizontalHeaderLabels(["Key", "Value / Summary", "Type"])
            def add(parent, key, value, path):
                kind = "object" if isinstance(value, dict) else "array" if isinstance(value, list) else type(value).__name__
                summary = f"{{{len(value)} fields}}" if isinstance(value, dict) else f"[{len(value)} items]" if isinstance(value, list) else display(value)
                items = [QStandardItem(str(key)), QStandardItem(summary), QStandardItem(kind)]
                items[0].setData(value, Qt.UserRole)
                items[0].setData(f"{path} {summary}", Qt.UserRole+1)
                for item in items: item.setToolTip(path)
                parent.appendRow(items)
                children = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
                for child_key, child in children: add(items[0], child_key, child, f"{path}.{child_key}")
            for key, value in self.document.items(): add(self.model.invisibleRootItem(), key, value, str(key))
        else:
            if section == "Baseline":
                headers = ["Field", "Before", "After", "Δ (after − before)", "Changed", "Samples"]
                rows = baseline_rows(self.document)
            else:
                headers = ["Device", "Field", "Value", "Units", "Source", "Type", "Path"]
                rows = configuration_rows(self.document)
            self.model.setHorizontalHeaderLabels(headers)
            for cells, detail, changed in rows:
                items = [QStandardItem(str(c)) for c in cells]
                items[0].setData(detail, Qt.UserRole)
                items[0].setData(" ".join(str(c) for c in cells) + " " + display(detail), Qt.UserRole+1)
                items[0].setData(changed, Qt.UserRole+2)
                for item in items: item.setToolTip(item.text())
                self.model.appendRow(items)
        self.proxy.setSourceModel(self.model)
        old.deleteLater()
        self.filter()
        if tree_mode:
            self.tree.setColumnWidth(0, 300); self.tree.setColumnWidth(1, 500)
            self.tree.expandToDepth(0)
        else:
            for column in range(self.model.columnCount()): self.table.setColumnWidth(column, 220 if column<3 else 150)
            self.table.horizontalHeader().setStretchLastSection(True)

    def filter(self, *_):
        self.proxy.query = self.search.text().casefold().strip()
        self.proxy.changed_only = self.section == "Baseline" and self.changed.isChecked()
        self.proxy.invalidateFilter()
        if self.section == "Run metadata" and self.proxy.query: self.tree.expandAll()
        unit = "top-level branches" if self.section == "Run metadata" else "fields"
        self.count.setText(f"{self.proxy.rowCount()} / {self.model.rowCount()} {unit}" +
                           (" · before/after are first/last samples; select a row to see all samples" if self.section == "Baseline" else ""))

    def selection(self, current, _previous):
        if not current.isValid(): self.detail.clear(); return
        item = self.proxy.index(current.row(), 0, current.parent())
        self.detail.setPlainText(json.dumps(item.data(Qt.UserRole), indent=2, ensure_ascii=False))

    def copy_json(self):
        view = self.stack.currentWidget()
        index = view.currentIndex()
        value = self.proxy.index(index.row(), 0, index.parent()).data(Qt.UserRole) if index.isValid() else self.document
        QApplication.clipboard().setText(json.dumps(value, indent=2, ensure_ascii=False))

    def clear(self):
        self.set_document("Run metadata", {})
