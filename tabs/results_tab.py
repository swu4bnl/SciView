"""Interactive presentation of a calibrated reduction collection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from html import escape
from pathlib import Path
from threading import Event

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QEvent, QSignalBlocker, QThread, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QIcon, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QColorDialog, QComboBox, QFormLayout, QFrame, QGroupBox, QLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSlider, QSplitter,
    QShortcut, QStackedWidget, QVBoxLayout, QWidget,
)

from sciview.interfaces.text import tr
from sciview.interfaces.stable_qt.widgets.colormap_items import show_colormap_previews
from sciview.interfaces.stable_qt.widgets.image_viewer import ImageViewer
from sciview.interfaces.stable_qt.widgets.notebook_editor import NotebookEditor
from sciview.interfaces.stable_qt.widgets.viewer_tools import (
    export_plot_view, load_toolbar_icon, make_labeled_tool_cell, make_tool_button,
)
from sciview.interfaces.theme.app_style import (
    AppStyle, apply_emphasis_button_style, apply_toolbar_text_button_style, setup_splitter_layout,
)
from sciview.processing.notebook_results import refresh_image_figure
from sciview.processing.waterfall import (
    WaterfallCurve, WaterfallInputError, WaterfallRequest, WaterfallRun,
    export_waterfall, load_waterfall_image, run_waterfall, snapshot_waterfall,
    notebook_waterfall, notebook_waterfall_run, refresh_waterfall,
)
from sciview.core.notebook import (
    CurveFigure, CurveStyle, FigureMetadata, ImageFigure, PlotState, ScientificObject,
)
from sciview.session.session_cache import choose_path
from sciview.settings.plot_style import resolve_plot_style
from sciview.settings.viewer_config import VIEWER_BEHAVIOR, VIEWER_COLORS, VIEWER_TOOLBAR_ACTIONS, ViewerToolbarAction

logger = logging.getLogger(__name__)


@dataclass
class CurveMark:
    curve_index: int
    point_index: int
    dot: pg.ScatterPlotItem
    label: pg.TextItem


class WaterfallWorker(QThread):
    curve_ready = pyqtSignal(object)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, request: WaterfallRequest):
        super().__init__(QApplication.instance())
        self.request = request
        self._cancel = Event()
        self.setObjectName("waterfall-processing")
        self.finished.connect(self.deleteLater)

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            result = run_waterfall(
                self.request, cancelled=self._cancel.is_set,
                on_curve=self.curve_ready.emit,
            )
        except Exception as exc:
            logger.exception("Waterfall job failed")
            self.failed.emit(str(exc))
        else:
            self.completed.emit(result)


class ResultsTab(QWidget):
    """Own plot interaction; scientific requests and results remain backend values."""

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self._paths: tuple[str, ...] = ()
        self._requested_paths: tuple[str, ...] = ()
        self._run: WaterfallRun | None = None
        self._worker: WaterfallWorker | None = None
        self._next_request: WaterfallRequest | None = None
        self._queued_settings_changed = False
        self._settings_changed = False
        self._lines: dict[int, pg.PlotDataItem] = {}
        self._marks: list[CurveMark] = []
        self._items: dict[int, QListWidgetItem] = {}
        self._hovered_curve_index: int | None = None
        self._pending_curves: list[WaterfallCurve] = []
        self._showing_current_run = False
        self._hidden_paths: set[str] = set()
        self._curve_styles: dict[int, CurveStyle] = {}
        self._default_line_style = "solid"
        self._default_line_width: float | None = None
        self._spacing_value = 0.0
        self._spacing_reference = 1.0
        self._initialize_spacing = True
        self._closing = False
        self._active_object: str | None = None
        self._inline_selected_object: str | None = None
        self._latest_run: WaterfallRun | None = None
        self._latest_state: PlotState | None = None
        self._restoring = False
        self._insert_pending_run: WaterfallRun | None = None
        self._update_target: str | None = None
        self._finished_update = False
        self._retry_pending = False
        self._restore_notebook_path: str | None = None
        self._notebook_timer = QTimer(self)
        self._notebook_timer.setSingleShot(True)
        self._notebook_timer.setInterval(200)
        self._notebook_timer.timeout.connect(self._sync_notebook_plot)
        self._build_ui()
        self.view_box.sigRangeChanged.connect(self._schedule_notebook_update)
        self._mouse_proxy = pg.SignalProxy(
            self.plot.scene().sigMouseMoved, rateLimit=20, slot=self._hover_plot,
        )
        self._undo_shortcut = QShortcut(QKeySequence.Undo, self.canvas)
        self._undo_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._undo_shortcut.activated.connect(self._undo_mark)
        self._escape_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self.canvas)
        self._escape_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._escape_shortcut.activated.connect(lambda: self._select_navigation("pan"))
        self._redraw_timer = QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.setInterval(100)
        self._redraw_timer.timeout.connect(self._flush_curves)
        self._draw()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self._root_layout = layout
        self.workspace = QStackedWidget()
        self.explorer = QWidget()
        layout.addWidget(self.workspace, 1)
        self.workspace.addWidget(self.explorer)
        layout = QVBoxLayout(self.explorer)
        layout.setContentsMargins(*([AppStyle.LAYOUT["panel_inner_margin"]] * 4))
        layout.setSpacing(AppStyle.LAYOUT["section_spacing"])
        header = QHBoxLayout()
        back = QPushButton(tr("notebook.back"))
        apply_emphasis_button_style(back)
        back.clicked.connect(self._compose_notebook)
        header.addWidget(back)
        heading = QWidget()
        heading_layout = QVBoxLayout(heading)
        heading_layout.setContentsMargins(0, 0, 0, 0)
        heading_layout.setSpacing(0)
        self.title = QLabel(tr("results.title"))
        heading_layout.addWidget(self.title)
        self.settings_label = QLabel(tr("results.empty"))
        self.settings_label.setToolTip(tr("results.settings.tooltip"))
        heading_layout.addWidget(self.settings_label)
        header.addWidget(heading, 1)
        self.latest_button = QPushButton(tr("notebook.latest"))
        apply_toolbar_text_button_style(self.latest_button)
        self.latest_button.hide()
        self.latest_button.clicked.connect(self._show_latest)
        header.addWidget(self.latest_button)
        self.update_button = QPushButton(tr("results.recalculate"))
        apply_toolbar_text_button_style(self.update_button)
        self.update_button.setEnabled(False)
        self.update_button.setToolTip(tr("results.recalculate.tooltip"))
        self.update_button.clicked.connect(self._recalculate)
        self.update_button.hide()
        header.addWidget(self.update_button)
        self.add_notebook_button = QPushButton(tr("notebook.add"))
        apply_emphasis_button_style(self.add_notebook_button)
        self.add_notebook_button.setEnabled(False)
        self.add_notebook_button.hide()
        self.add_notebook_button.clicked.connect(self._add_to_notebook)
        header.addWidget(self.add_notebook_button)
        self.export_button = QPushButton(tr("results.export"))
        apply_toolbar_text_button_style(self.export_button)
        self.export_menu = QMenu(self.export_button)
        self.save_plot_action = self.export_menu.addAction(tr("results.save_plot"))
        self.save_plot_action.triggered.connect(self._save_plot)
        self.export_curves_action = self.export_menu.addAction(tr("results.export_curves"))
        self.export_curves_action.triggered.connect(self._export)
        self.export_button.setMenu(self.export_menu)
        self.export_button.setEnabled(False)
        header.addWidget(self.export_button)
        layout.addLayout(header)

        self.issue_container = QWidget()
        issue_row = QHBoxLayout(self.issue_container)
        issue_row.setContentsMargins(0, 0, 0, 0)
        self.issue_label = QLabel()
        issue_row.addWidget(self.issue_label, 1)
        self.fix_button = QPushButton()
        self.fix_button.hide()
        self.fix_button.clicked.connect(self._open_issue_settings)
        issue_row.addWidget(self.fix_button)
        self.issue_container.hide()
        feedback_row = QHBoxLayout()
        feedback_row.addWidget(self.issue_container, 1)
        feedback_row.addStretch(1)
        feedback_row.addWidget(self.update_button)
        self._root_layout.insertLayout(0, feedback_row)

        splitter = QSplitter(Qt.Horizontal)
        self.explorer_splitter = splitter
        plot_panel = QWidget()
        plot_layout = QVBoxLayout(plot_panel)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = pg.PlotWidget()
        self.plot = self.canvas.getPlotItem()
        self.view_box = self.plot.getViewBox()
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.getAxis("bottom").enableAutoSIPrefix(False)
        self.plot.getAxis("left").enableAutoSIPrefix(False)
        self.view_box.setMouseMode(pg.ViewBox.PanMode)
        plot_layout.addWidget(self.canvas, 1)
        self.toolbar = QWidget()
        tools_layout = QHBoxLayout(self.toolbar)
        tools_layout.setContentsMargins(*([AppStyle.LAYOUT["panel_margin"]] * 4))
        tools_layout.setSpacing(AppStyle.LAYOUT["toolbar_spacing"])
        actions = {action.key: action for action in VIEWER_TOOLBAR_ACTIONS}
        self._tool_buttons = {}
        for key in ("pan", "zoom", "home", "mark"):
            action = actions[key] if key != "mark" else ViewerToolbarAction(
                "mark", "annotations.toolbar", "results.mark.tooltip",
            )
            button = make_tool_button(action, load_toolbar_icon("beam_center" if key == "mark" else key))
            button.setCheckable(key != "home")
            button.clicked.connect(lambda _checked=False, key=key: self._select_navigation(key))
            tools_layout.addWidget(make_labeled_tool_cell(tr(action.label_id), button))
            self._tool_buttons[key] = button
        self._tool_buttons["pan"].setChecked(True)
        self._tool_buttons["pan"].setToolTip(tr("results.pan.tooltip"))
        self._tool_buttons["home"].setToolTip(tr("results.home.tooltip"))
        self.mark_controls = QWidget()
        mark_layout = QHBoxLayout(self.mark_controls)
        mark_layout.setContentsMargins(0, 0, 0, 0)
        for message, callback in (
            ("annotations.undo", self._undo_mark), ("annotations.clear", self._clear_marks),
        ):
            button = QPushButton(tr(message))
            button.clicked.connect(callback)
            mark_layout.addWidget(button)
        self.mark_controls.hide()
        self.cursor_label = QLabel(tr("results.hover.empty"))
        self.cursor_label.setMinimumWidth(0)
        self.cursor_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.cursor_label.setToolTip(tr("results.hover.tooltip"))
        tools_layout.addWidget(self.cursor_label, 1)
        plot_layout.addWidget(self.toolbar)
        plot_layout.addWidget(self.mark_controls)
        splitter.addWidget(plot_panel)

        self.source_panel = QWidget()
        source_panel_layout = QVBoxLayout(self.source_panel)
        source_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.source_scroll = QScrollArea()
        self.source_scroll.setWidgetResizable(True)
        self.source_scroll.setFrameShape(QFrame.NoFrame)
        source_content = QWidget()
        source_layout = QVBoxLayout(source_content)
        source_layout.setSizeConstraint(QLayout.SetMinimumSize)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(AppStyle.LAYOUT["section_spacing"])
        source_layout.addWidget(QLabel(tr("results.curves")))
        self.curve_search = QLineEdit()
        self.curve_search.setClearButtonEnabled(True)
        self.curve_search.setPlaceholderText(tr("results.curve_search"))
        self.curve_search.textChanged.connect(self._filter_curves)
        source_layout.addWidget(self.curve_search)
        self.curve_list = QListWidget()
        self.curve_list.setTextElideMode(Qt.ElideMiddle)
        self.curve_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.curve_list.setUniformItemSizes(True)
        self.curve_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.curve_list.setMinimumHeight(0)
        self.curve_list.setMouseTracking(True)
        self.curve_list.viewport().setMouseTracking(True)
        self.curve_list.itemEntered.connect(self._hover_source_item)
        self.curve_list.viewport().installEventFilter(self)
        self.curve_list.itemChanged.connect(self._visibility_changed)
        self.curve_list.currentItemChanged.connect(self._selection_changed)
        source_layout.addWidget(self.curve_list, 1)
        self.source_button = QPushButton(tr("results.show_source"))
        self.source_button.setEnabled(False)
        self.source_button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.source_button.hide()
        self.source_button.clicked.connect(self._show_source)
        source_layout.addWidget(self.source_button)

        self.spacing_slider = QSlider(Qt.Horizontal)
        self.spacing_slider.setRange(0, 300)
        self.spacing_slider.setSingleStep(5)
        self.spacing_slider.setPageStep(25)
        self.spacing_slider.setValue(0)
        self.spacing_slider.setAccessibleName(tr("results.spacing"))
        self.spacing_slider.setToolTip(tr("results.spacing.tooltip"))
        self.spacing_slider.valueChanged.connect(self._spacing_changed)
        self.spacing_value_label = QLabel()
        spacing_controls = QWidget()
        spacing_layout = QHBoxLayout(spacing_controls)
        spacing_layout.setContentsMargins(0, 0, 0, 0)
        spacing_layout.addWidget(self.spacing_slider, 1)
        spacing_layout.addWidget(self.spacing_value_label)
        self.palette = QComboBox()
        self.palette.addItems(["viridis", "plasma", "cividis", "turbo"])
        self.palette.setAccessibleName(tr("results.colors"))
        self.palette.setToolTip(tr("results.colors.tooltip"))
        show_colormap_previews(self.palette)
        self.palette.currentTextChanged.connect(self._update_artists)
        display_form = QFormLayout()
        display_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        display_form.addRow(tr("results.spacing"), spacing_controls)
        display_form.addRow(tr("results.colors"), self.palette)
        display_group = QGroupBox(tr("results.waterfall_display"))
        display_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        display_group.setLayout(display_form)
        source_layout.addWidget(display_group)

        self.curve_appearance = QGroupBox(tr("results.curve_appearance"))
        self.curve_appearance.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        appearance_form = QFormLayout(self.curve_appearance)
        appearance_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.curve_color_button = QPushButton()
        self.curve_color_button.clicked.connect(self._choose_curve_color)
        self.curve_palette_button = QPushButton(tr("results.use_palette"))
        self.curve_palette_button.clicked.connect(lambda: self._set_curve_style(color=None))
        color_controls = QWidget()
        color_layout = QHBoxLayout(color_controls)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.addWidget(self.curve_color_button, 1)
        color_layout.addWidget(self.curve_palette_button)
        appearance_form.addRow(tr("results.curve_color"), color_controls)
        self.curve_line_style = QComboBox()
        for key, message in (
            ("solid", "results.line.solid"), ("dash", "results.line.dash"),
            ("dot", "results.line.dot"), ("dash_dot", "results.line.dash_dot"),
        ):
            self.curve_line_style.addItem(tr(message), key)
        self.curve_line_style.currentIndexChanged.connect(self._line_style_changed)
        appearance_form.addRow(tr("results.line_style"), self.curve_line_style)
        self.curve_width_slider = QSlider(Qt.Horizontal)
        self.curve_width_slider.setRange(1, 8)
        self.curve_width_label = QLabel()
        width_controls = QWidget()
        width_layout = QHBoxLayout(width_controls)
        width_layout.setContentsMargins(0, 0, 0, 0)
        width_layout.addWidget(self.curve_width_slider, 1)
        width_layout.addWidget(self.curve_width_label)
        self.curve_width_slider.valueChanged.connect(self._line_width_changed)
        appearance_form.addRow(tr("results.line_width"), width_controls)
        self.curve_gain_slider = QSlider(Qt.Horizontal)
        self.curve_gain_slider.setRange(0, 300)
        self.curve_gain_slider.setSingleStep(5)
        self.curve_gain_label = QLabel()
        gain_controls = QWidget()
        gain_layout = QHBoxLayout(gain_controls)
        gain_layout.setContentsMargins(0, 0, 0, 0)
        gain_layout.addWidget(self.curve_gain_slider, 1)
        gain_layout.addWidget(self.curve_gain_label)
        self.curve_gain_slider.valueChanged.connect(self._gain_changed)
        appearance_form.addRow(tr("results.display_gain"), gain_controls)
        self.curve_appearance.hide()
        source_layout.addWidget(self.curve_appearance)
        self.source_scroll.setWidget(source_content)
        source_panel_layout.addWidget(self.source_scroll)
        splitter.addWidget(self.source_panel)
        setup_splitter_layout(splitter, [3, 2])
        layout.addWidget(splitter, 1)

        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.hide()
        progress_row.addWidget(self.progress, 1)
        self.cancel_button = QPushButton(tr("results.cancel"))
        self.cancel_button.clicked.connect(self._cancel)
        self.cancel_button.hide()
        progress_row.addWidget(self.cancel_button)
        self._root_layout.addLayout(progress_row)
        self.notebook = NotebookEditor(self.parent_app)
        self.notebook.ready.connect(self._update_notebook_action)
        self.notebook.ready.connect(lambda: QTimer.singleShot(0, self._notebook_ready))
        self.notebook.insert_latest_requested.connect(self._insert_latest_notebook_plot)
        self.notebook.update_requested.connect(self.update_figure)
        self.notebook.plot_selection_changed.connect(self._notebook_plot_selected)
        self.notebook.curve_hovered.connect(self._notebook_curve_hovered)
        self.notebook.curve_selected.connect(self._notebook_curve_selected)
        self.notebook.plot_presentation_changed.connect(self._notebook_plot_presentation_changed)
        self.notebook.document_replaced.connect(self._document_replaced)
        self.notebook.prepare_save = self._sync_notebook_plot
        self.notebook_workspace = QWidget()
        notebook_layout = QVBoxLayout(self.notebook_workspace)
        notebook_layout.setContentsMargins(0, 0, 0, 0)
        notebook_layout.addWidget(self.notebook)
        self.workspace.addWidget(self.notebook_workspace)
        self._show_workspace_page(self.notebook_workspace)

    def _show_workspace_page(self, page: QWidget):
        if page is self.notebook_workspace:
            if (
                self._inline_selected_object is not None
                and self._inline_selected_object != self._active_object
                and self.notebook.editor_ready
            ):
                self.notebook.page.runJavaScript("sciview.clearSelection()")
                self._inline_selected_object = None
            self.source_panel.hide()
        else:
            self.explorer_splitter.addWidget(self.source_panel)
            self.source_panel.show()
        self.workspace.setCurrentWidget(page)
        self._refresh_update_button()

    def _run_incomplete(self) -> bool:
        return self._run is None or self._run.cancelled or len(self._run.curves) < len(self._paths) or any(
            curve.result is None for curve in self._run.curves
        )

    def _refresh_update_button(self):
        """The corner action serves the unlinked latest run; linked figures update from their own card."""
        if self._worker is not None or not self._paths:
            self.update_button.setVisible(False)
        elif self.workspace.currentWidget() is self.explorer:
            self.update_button.setVisible(self._settings_changed or self._run_incomplete())
        else:
            self.update_button.setVisible(self._retry_pending)

    def _show_input_issue(self, exc: WaterfallInputError):
        self._issue_destination = exc.destination
        self._set_issue_message(tr("results.attention", error=str(exc)))
        self.fix_button.setText(tr(f"results.open.{exc.destination}"))
        self.fix_button.show()

    def explore(self, paths: tuple[str, ...]):
        if self._closing:
            return
        self._show_workspace_page(self.notebook_workspace)
        self._requested_paths = tuple(paths)
        try:
            reduction_tab = self.parent_app.processing_tab("reduction")
            request = snapshot_waterfall(tuple(paths), reduction_tab.build_waterfall_request())
        except WaterfallInputError as exc:
            if self._run is None:
                self._paths = tuple(paths)
                self.update_button.setEnabled(True)
            self._retry_pending = True
            self._show_input_issue(exc)
            self._refresh_update_button()
            return
        except Exception as exc:
            self.parent_app.report_error(tr("results.failed", error=str(exc)), exc)
            self._set_issue_message(tr("results.failed", error=str(exc)))
            return
        self._set_issue_message("")
        self.fix_button.hide()
        if self._worker is not None:
            self._next_request = request
            self._queued_settings_changed = False
            self._cancel()
            return
        self._start(request)

    def _recalculate(self):
        if self._active_object in self.notebook.document.objects:
            self.update_figure(self._active_object)
        else:
            self.explore(self._requested_paths)

    def update_figure(self, key: str):
        """Recompute one figure's own sources with the current settings and replace it in place."""
        if self._closing:
            return
        if self._worker is not None:
            self.parent_app.show_status(tr("notebook.processing"))
            return
        plot = self.notebook.document.objects.get(key)
        if plot is None:
            self.notebook._error(tr("notebook.missing_object"))
            return
        if not self._sync_notebook_plot():
            return
        if isinstance(plot, ImageFigure):
            self._update_image_figure(key, plot)
            return
        if not isinstance(plot, CurveFigure):
            self._set_issue_message(tr("results.update_unsupported"))
            return
        try:
            reduction_tab = self.parent_app.processing_tab("reduction")
            request = snapshot_waterfall(tuple(plot.sources), reduction_tab.build_waterfall_request())
        except WaterfallInputError as exc:
            self._show_input_issue(exc)
            return
        except Exception as exc:
            self.parent_app.report_error(tr("results.failed", error=str(exc)), exc)
            self._set_issue_message(tr("results.failed", error=str(exc)))
            return
        self._set_issue_message("")
        self.fix_button.hide()
        self._requested_paths = tuple(plot.sources)
        self._update_target = key
        if not self._start(request):
            self._update_target = None

    def _update_image_figure(self, key: str, plot: ImageFigure):
        try:
            transform_tab = self.parent_app.processing_tab("transform")
            image = load_waterfall_image(plot.sources[0])
            request = transform_tab.build_transform_request(image, plot.sources[0])
            if request is None:
                raise WaterfallInputError("A calibration is required to update this map.", "calibration")
            refresh_image_figure(plot, request, transform_tab.backend.run(request))
        except WaterfallInputError as exc:
            self._show_input_issue(exc)
            return
        except Exception as exc:
            self.parent_app.report_error(tr("results.failed", error=str(exc)), exc)
            self._set_issue_message(tr("results.failed", error=str(exc)))
            return
        self._set_issue_message("")
        self.fix_button.hide()
        self.notebook.set_stale(key, False)
        self.notebook.set_dirty()
        self.notebook.update_objects()

    def _start(self, request: WaterfallRequest) -> bool:
        if not self._sync_notebook_plot():
            return False
        self._retry_pending = False
        self._active_object = None
        self._insert_pending_run = None
        self.latest_button.hide()
        self.add_notebook_button.setEnabled(False)
        self._set_hovered_curve(None)
        self._clear_marks()
        if self._paths != request.paths:
            self._initialize_spacing = True
            self._curve_styles.clear()
            self._default_line_style = "solid"
            self._default_line_width = None
        self._hidden_paths.intersection_update(request.paths)
        self._paths = request.paths
        self._run = WaterfallRun(request)
        self._settings_changed = False
        self.update_button.setText(tr("results.recalculate"))
        self.update_button.hide()
        self._showing_current_run = False
        self._pending_curves.clear()
        self.curve_search.clear()
        self.curve_list.clear()
        self._items.clear()
        for index, path in enumerate(self._paths):
            item = QListWidgetItem(tr("results.pending", name=Path(path).name))
            item.setData(Qt.UserRole, index)
            item.setToolTip(path)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.curve_list.addItem(item)
            self._items[index] = item
        self.title.setText(tr("results.collection", count=len(request.paths)))
        self._show_processing_settings(request)
        self.update_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.save_plot_action.setEnabled(False)
        self.export_curves_action.setEnabled(False)
        self.source_button.setEnabled(False)
        self.progress.setRange(0, len(request.paths))
        self.progress.setValue(0)
        self.progress.setFormat(tr("results.progress"))
        self.progress.show()
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText(tr("results.cancel"))
        self.cancel_button.show()
        self._set_issue_message(tr("results.previous") if self._lines else "")
        worker = WaterfallWorker(request)
        self._worker = worker
        worker.curve_ready.connect(self._receive_curve)
        worker.completed.connect(self._processed)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._finished)
        worker.start()
        self._update_notebook_action()
        return True

    def _show_processing_settings(self, request: WaterfallRequest):
        self.settings_label.setText(tr(
            "results.settings",
            operation=tr(f"reduction.operation.{request.reduction.operation}"),
            calibration=self._source_label(request, "calibration"),
            mask=self._source_label(request, "mask"),
        ))
        self.settings_label.setToolTip(self.settings_label.text())

    @staticmethod
    def _source_label(request, kind):
        source = request.provenance[f"{kind}_source"]
        if kind == "mask" and request.provenance["mask"] is None:
            return tr("results.none")
        label = request.reduction.metadata.get(f"{kind}_label", "")
        return Path(label).name if source in {"Custom profile", "Custom mask"} else tr("results.shared")

    def _receive_curve(self, curve):
        if self._closing:
            return
        self._pending_curves.append(curve)
        if not self._redraw_timer.isActive():
            self._redraw_timer.start()

    def _flush_curves(self):
        if self._run is None or not self._pending_curves:
            return
        if not self._showing_current_run:
            self._lines.clear()
            self.plot.clear()
            self._clear_marks()
            self.view_box.enableAutoRange()
            request = self._run.request.reduction
            if request.q_min is not None and request.q_max is not None:
                self.view_box.setXRange(request.q_min, request.q_max, padding=0)
            self._showing_current_run = True
            self.source_button.setEnabled(False)
            self._set_issue_message("")
        with QSignalBlocker(self.curve_list):
            for curve in self._pending_curves:
                self._run.curves.append(curve)
                item = self._items[curve.index]
                if curve.result is None:
                    item.setText(tr("results.curve_failed", name=Path(curve.path).name))
                    item.setToolTip(f"{curve.path}\n{curve.error}")
                else:
                    item.setText(Path(curve.path).name)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Unchecked if curve.path in self._hidden_paths else Qt.Checked)
                    line = self.plot.plot(curve.result.x, curve.result.y, connect="finite")
                    line.setCurveClickable(True)
                    line.sigClicked.connect(
                        lambda _line, event, index=curve.index: self._pick_curve(index, event),
                    )
                    self._lines[curve.index] = line
        self._pending_curves.clear()
        self.progress.setValue(len(self._run.curves))
        if self._initialize_spacing and self._lines:
            first = next(curve.result for curve in self._run.curves if curve.result is not None)
            values = first.y[np.isfinite(first.y)]
            low, high = np.percentile(values, [5, 95])
            self._set_spacing_control(max(high - low, abs(high), abs(low)) * 0.1, initialize=True)
            self._initialize_spacing = False
        self._update_artists()
        self._refresh_curve_highlights()

    def _completed(self, run: WaterfallRun):
        if self._closing:
            return
        self._flush_curves()
        self._run = run
        processed = {curve.index for curve in run.curves}
        with QSignalBlocker(self.curve_list):
            for index, item in self._items.items():
                if index not in processed:
                    item.setText(tr("results.not_processed", name=Path(self._paths[index]).name))
        if not self._showing_current_run:
            self._lines.clear()
            self.plot.clear()
            self._clear_marks()
            self._showing_current_run = True
        good = sum(curve.result is not None for curve in run.curves)
        self.progress.setValue(len(run.curves))
        status_id = "results.cancelled" if run.cancelled else (
            "results.incomplete" if good < len(run.request.paths) else "results.complete"
        )
        if not self._restoring:
            self._set_issue_message(tr(status_id, good=good, total=len(run.request.paths)))
        self.export_button.setEnabled(good > 0)
        self.save_plot_action.setEnabled(good > 0)
        self.export_curves_action.setEnabled(good > 0)
        self._draw()

    def _failed(self, message):
        self._insert_pending_run = None
        self._update_target = None
        self._set_issue_message(tr("results.failed", error=message))
        self.parent_app.report_error(message)

    def _finished(self):
        self._worker = None
        if self._closing:
            return
        self.cancel_button.hide()
        self.progress.hide()
        self.update_button.setEnabled(bool(self._paths))
        self._refresh_update_button()
        request = self._next_request
        stale = self._queued_settings_changed
        self._next_request = None
        self._queued_settings_changed = False
        if request is not None:
            self._start(request)
            if stale:
                self.mark_settings_changed("reduction")
        else:
            # An in-place update belongs to its figure; it is not a new insertable result.
            if not self._finished_update:
                self._latest_run = self._run if self._run and any(curve.result is not None for curve in self._run.curves) else None
                self._latest_state = self._plot_state()
            self._finished_update = False
            self._insert_completed_notebook_plot()
            self._update_notebook_action()

    def _processed(self, run: WaterfallRun):
        self._completed(run)
        key, self._update_target = self._update_target, None
        if key is None:
            self._insert_pending_run = run if any(curve.result is not None for curve in run.curves) else None
            return
        self._insert_pending_run = None
        plot = self.notebook.document.objects.get(key)
        if plot is None:
            return
        try:
            refresh_waterfall(plot, run)
        except ValueError:
            good = sum(curve.result is not None for curve in run.curves)
            self._set_issue_message(tr("results.update_kept", good=good, total=len(run.request.paths)))
            return
        self.notebook.set_stale(key, False)
        self._finished_update = True
        self._active_object = key
        self._restore_plot(notebook_waterfall_run(plot), plot.state)
        self.notebook.set_dirty()
        self.notebook.update_objects()
        self._set_issue_message("")

    def _insert_completed_notebook_plot(self):
        run = self._insert_pending_run
        if run is None or self._worker is not None or not self.notebook.editor_ready:
            return
        self._insert_pending_run = None
        try:
            plot = self._create_notebook_plot(run, self._plot_state())
            self._active_object = plot.id
            self._inline_selected_object = None
            self._show_workspace_page(self.notebook_workspace)
            if not run.cancelled and all(curve.result is not None for curve in run.curves):
                self._set_issue_message("")
        except Exception as exc:
            self.notebook._error(str(exc))

    def _notebook_ready(self):
        if self._restore_notebook_path:
            path, self._restore_notebook_path = self._restore_notebook_path, None
            self.notebook.open_document(path)
        self._insert_completed_notebook_plot()

    def get_session_state(self) -> dict:
        path = self.notebook.document.path
        return {"notebook_path": str(path)} if path else {}

    def restore_session_state(self, state: dict):
        path = state.get("notebook_path")
        if not isinstance(path, str) or not path:
            return
        if self.notebook.editor_ready:
            self.notebook.open_document(path)
        else:
            self._restore_notebook_path = path

    def _cancel(self):
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setText(tr("results.cancelling"))
            self.cancel_button.setEnabled(False)

    @staticmethod
    def _figure_affected(plot: ScientificObject, kind: str) -> bool:
        if kind == "reduction":
            return isinstance(plot, CurveFigure)
        if kind == "transform":
            return isinstance(plot, ImageFigure)
        source = plot.provenance.get("mask_source" if kind == "mask_editing" else "calibration_source")
        return source in {"From mask tab", "From calibration tab"}

    def mark_settings_changed(self, kind: str):
        for key, plot in self.notebook.document.objects.items():
            if self._figure_affected(plot, kind):
                self.notebook.set_stale(key, True)
        if not self._paths or kind == "transform":
            return
        request = self._next_request or (self._run.request if self._run is not None else None)
        if request is not None and kind != "reduction":
            source = request.provenance.get(
                "mask_source" if kind == "mask_editing" else "calibration_source",
            )
            if source not in {"From mask tab", "From calibration tab"}:
                return
        self._settings_changed = True
        if self._next_request is not None:
            self._queued_settings_changed = True
        self.update_button.setText(tr("results.recalculate_changed"))
        self.update_button.setEnabled(self._worker is None and bool(self._paths))
        self._refresh_update_button()

    def _set_issue_message(self, message: str):
        self.issue_label.setText(message)
        self.issue_container.setVisible(bool(message))

    @staticmethod
    def _spacing_for_run(run: WaterfallRun | None) -> float:
        if run is None:
            return 1.0
        curve = next((item.result for item in run.curves if item.result is not None), None)
        if curve is None:
            return 1.0
        values = curve.y[np.isfinite(curve.y)]
        if not values.size:
            return 1.0
        low, high = np.percentile(values, [5, 95])
        return float(max(high - low, abs(high), abs(low)) * 0.1)

    def _set_spacing_control(
        self, value: float, *, initialize: bool = False, run: WaterfallRun | None = None,
    ):
        baseline = float(self._spacing_for_run(run or self._run))
        value = float(value)
        if initialize:
            self._spacing_reference = max(baseline, np.finfo(float).eps)
            value = baseline
        else:
            self._spacing_reference = max(baseline, value / 3, np.finfo(float).eps)
        self._spacing_value = value
        slider_value = round(value / self._spacing_reference * 100)
        with QSignalBlocker(self.spacing_slider):
            self.spacing_slider.setValue(max(0, min(300, slider_value)))
        self._update_spacing_label()

    def _update_spacing_label(self):
        result = next(
            (curve.result for curve in self._run.curves if curve.result is not None),
            None,
        ) if self._run else None
        axis_label = result.y_label.strip() if result is not None else ""
        units = ""
        if axis_label.endswith(")") and "(" in axis_label:
            units = axis_label.rsplit("(", 1)[-1][:-1].strip()
        value = f"{self._spacing_value:.4g}"
        if units:
            value = tr("results.spacing_value", value=value, units=units).strip()
        self.spacing_value_label.setText(value)

    def _spacing_changed(self, value: int):
        self._spacing_value = self._spacing_reference * value / 100
        self._update_spacing_label()
        self._update_artists()

    def _curve_style(self, index: int) -> CurveStyle:
        return self._curve_styles.get(index, CurveStyle())

    def _palette_color(self, index: int, palette: np.ndarray | None = None) -> QColor:
        lut = palette if palette is not None else ImageViewer.colormap_lut(self.palette.currentText())
        total = max(1, len(self._paths) - 1)
        return QColor(*map(int, lut[round((0.2 + 0.6 * index / total) * 255)]))

    def _curve_pen(self, index: int, *, highlighted: bool = False):
        state = PlotState(
            curve_styles=self._curve_styles, default_line_style=self._default_line_style,
            default_line_width=self._default_line_width,
        )
        style = state.resolved_curve_style(index, resolve_plot_style(self.parent_app).line_width)
        color = QColor(style.color) if style.color else self._palette_color(index)
        color.setAlphaF(style.opacity)
        width = style.line_width or resolve_plot_style(self.parent_app).line_width
        if highlighted:
            width *= 1.8
        line_styles = {
            "solid": Qt.SolidLine, "dash": Qt.DashLine,
            "dot": Qt.DotLine, "dash_dot": Qt.DashDotLine,
        }
        return pg.mkPen(color, width=width, style=line_styles[style.line_style or "solid"])

    def _set_curve_style(self, **changes):
        item = self.curve_list.currentItem()
        if item is None:
            return
        index = item.data(Qt.UserRole)
        if index not in self._lines:
            return
        style = replace(self._curve_style(index), **changes)
        style.validate()
        self._curve_styles[index] = style
        self._update_artists()

    def _choose_curve_color(self):
        item = self.curve_list.currentItem()
        if item is None:
            return
        index = item.data(Qt.UserRole)
        style = self._curve_style(index)
        initial = QColor(style.color) if style.color else self._palette_color(index)
        color = QColorDialog.getColor(initial, self, tr("results.curve_color"))
        if color.isValid():
            self._set_curve_style(color=color.name())

    def _line_style_changed(self, _index: int):
        self._set_curve_style(line_style=self.curve_line_style.currentData())

    def _line_width_changed(self, value: int):
        self.curve_width_label.setText(str(value))
        self._set_curve_style(line_width=float(value))

    def _gain_changed(self, value: int):
        self.curve_gain_label.setText(tr("results.gain_value", value=f"{value / 100:.2f}"))
        self._set_curve_style(gain=value / 100)

    def _selection_changed(self, current, _previous=None):
        self._highlight_curve(current)
        index = current.data(Qt.UserRole) if current is not None else None
        valid = index in self._lines if index is not None else False
        self.source_button.setEnabled(valid)
        self.source_button.setVisible(valid)
        self.curve_appearance.setVisible(valid)
        if not valid:
            return
        style = self._curve_style(index)
        with (
            QSignalBlocker(self.curve_line_style),
            QSignalBlocker(self.curve_width_slider),
            QSignalBlocker(self.curve_gain_slider),
        ):
            default_style = self._default_line_style
            default_width = self._default_line_width
            style_index = self.curve_line_style.findData(style.line_style or default_style)
            self.curve_line_style.setCurrentIndex(max(0, style_index))
            self.curve_width_slider.setValue(round(
                style.line_width or default_width or resolve_plot_style(self.parent_app).line_width,
            ))
            self.curve_gain_slider.setValue(round(style.gain * 100))
        self.curve_width_label.setText(str(round(
            style.line_width or default_width or resolve_plot_style(self.parent_app).line_width,
        )))
        self.curve_gain_label.setText(tr("results.gain_value", value=f"{style.gain:.2f}"))
        color = QColor(style.color) if style.color else self._palette_color(index)
        pixmap = QPixmap(AppStyle.viewer_toolbar_icon_size())
        pixmap.fill(color)
        self.curve_color_button.setIcon(QIcon(pixmap))
        self.curve_color_button.setIconSize(AppStyle.viewer_toolbar_icon_size())
        self.curve_color_button.setText(style.color or tr("results.palette_color"))
        self.curve_palette_button.setEnabled(style.color is not None)

    def _filter_curves(self, text: str):
        needle = text.casefold().strip()
        for item in self._items.values():
            item.setHidden(
                bool(needle) and needle not in item.text().casefold()
                and needle not in item.toolTip().casefold()
            )

    def _update_artists(self, *_args):
        if self._run is None or not self._showing_current_run:
            return
        palette = ImageViewer.colormap_lut(self.palette.currentText())
        curves = {curve.index: curve for curve in self._run.curves}
        with QSignalBlocker(self.curve_list):
            for index, line in self._lines.items():
                curve = curves[index]
                style = self._curve_style(index)
                line.setData(
                    curve.result.x,
                    curve.result.y * style.gain + index * self._spacing_value,
                    connect="finite",
                )
                color = QColor(style.color) if style.color else self._palette_color(index, palette)
                line.setPen(self._curve_pen(index))
                item = self._items[index]
                item.setData(Qt.DecorationRole, color)
                line.setVisible(item.checkState() == Qt.Checked)
        self._draw()
        self._refresh_curve_highlights()
        self._schedule_notebook_update()

    def _draw(self):
        if self._run is not None and self._showing_current_run:
            first = next((curve.result for curve in self._run.curves if curve.result is not None), None)
            notebook = getattr(self, "notebook", None)
            active = notebook.document.objects.get(self._active_object) if notebook else None
            figure = active.figure if active else FigureMetadata.from_labels(
                first.x_label if first else "", first.y_label if first else "",
            )
            self.plot.setLabel("bottom", escape(figure.x_label), units=escape(figure.x_units) or None)
            self.plot.setLabel("left", escape(figure.y_label), units=escape(figure.y_units) or None)
            title = escape(active.title) if active else ""
            self.plot.setTitle(title)
            legend = self.plot.legend or self.plot.addLegend()
            legend.clear()
            legend.setVisible(figure.show_legend)
            if figure.show_legend:
                for index, line in self._lines.items():
                    if self._paths[index] not in self._hidden_paths:
                        legend.addItem(line, escape(figure.legend_names.get(index, Path(self._paths[index]).name)))
        self.canvas.setBackground(AppStyle.theme_colors()["base"])
        AppStyle.apply_pyqtgraph_plot_theme(self.plot)
        AppStyle.apply_widget_style(self.toolbar, "viewer_toolbar")
        for key, button in self._tool_buttons.items():
            AppStyle.apply_widget_style(button, "compact_button")
            button.setFixedSize(AppStyle.viewer_toolbar_button_size())
            button.setIcon(load_toolbar_icon("beam_center" if key == "mark" else key))
            button.setIconSize(AppStyle.viewer_toolbar_icon_size())
        self._update_marks()

    def _visibility_changed(self, item):
        path = self._paths[item.data(Qt.UserRole)]
        if item.checkState() == Qt.Checked:
            self._hidden_paths.discard(path)
        else:
            self._hidden_paths.add(path)
        self._update_artists()

    def _hover_plot(self, event):
        if not self._showing_current_run:
            self.cursor_label.setText(tr("results.hover.empty"))
            self._set_hovered_curve(None)
            return
        scene_pos = event[0]
        if not self.plot.sceneBoundingRect().contains(scene_pos):
            self.cursor_label.setText(tr("results.hover.empty"))
            self._set_hovered_curve(None)
            return
        point = self.view_box.mapSceneToView(scene_pos)
        x_pixel, y_pixel = self.view_box.viewPixelSize()
        if x_pixel <= 0 or y_pixel <= 0:
            self._set_hovered_curve(None)
            return
        nearest = None
        curves = {curve.index: curve.result for curve in self._run.curves if curve.result is not None}
        for index, line in self._lines.items():
            if not line.isVisible():
                continue
            result = curves[index]
            curve_x, curve_y = line.getData()
            if curve_x is None or curve_y is None or not len(curve_x):
                continue
            finite = np.isfinite(curve_x) & np.isfinite(curve_y)
            if len(curve_x) == 1:
                point_index = 0
                candidate = float(
                    ((curve_x[0] - point.x()) / x_pixel) ** 2
                    + ((curve_y[0] - point.y()) / y_pixel) ** 2
                ) if finite[0] else float("inf")
            else:
                dx = np.diff(curve_x) / x_pixel
                dy = np.diff(curve_y) / y_pixel
                px = (point.x() - curve_x[:-1]) / x_pixel
                py = (point.y() - curve_y[:-1]) / y_pixel
                length_squared = dx * dx + dy * dy
                fraction = np.divide(
                    px * dx + py * dy,
                    length_squared,
                    out=np.zeros_like(length_squared),
                    where=length_squared > 0,
                )
                fraction = np.clip(fraction, 0, 1)
                distance = (px - fraction * dx) ** 2 + (py - fraction * dy) ** 2
                distance[~(finite[:-1] & finite[1:])] = np.inf
                segment_index = int(np.argmin(distance))
                candidate = float(distance[segment_index])
                point_index = segment_index + int(fraction[segment_index] >= 0.5)
            if nearest is None or candidate < nearest[0]:
                nearest = candidate, index, point_index, result, curve_y[point_index]
        if nearest is None or not np.isfinite(nearest[0]) or nearest[0] > 64:
            self.cursor_label.setText(tr("results.hover.empty"))
            self._set_hovered_curve(None)
            return
        _, index, point_index, result, display_y = nearest
        self._set_hovered_curve(index)
        self.cursor_label.setText(tr(
            "results.hover.value",
            coordinate=f"{result.x[point_index]:.6g}",
            coordinate_units=FigureMetadata.plain_label(result.x_label) or "q",
            intensity=f"{result.y[point_index]:.6g}",
            intensity_units=FigureMetadata.plain_label(result.y_label) or "a.u.",
            display=f"{display_y:.6g}",
        ))

    def _refresh_curve_highlights(self):
        current = self.curve_list.currentItem()
        selected = current.data(Qt.UserRole) if current is not None else None
        if self._showing_current_run:
            for key, line in self._lines.items():
                line.setPen(self._curve_pen(
                    key, highlighted=key in {selected, self._hovered_curve_index},
                ))

    def _highlight_curve(self, current, _previous=None):
        self._refresh_curve_highlights()
        self._schedule_notebook_update()

    def _set_hovered_curve(self, index: int | None):
        if index not in self._lines:
            index = None
        if self._hovered_curve_index == index:
            return
        previous = self._items.get(self._hovered_curve_index)
        if previous is not None:
            previous.setData(Qt.BackgroundRole, QBrush())
        self._hovered_curve_index = index
        item = self._items.get(index)
        if item is not None and item is not self.curve_list.currentItem():
            item.setData(
                Qt.BackgroundRole,
                QBrush(AppStyle.theme_colors()["control_hover"]),
            )
        self._refresh_curve_highlights()
        if self._active_object is not None:
            self.notebook.highlight_curve(self._active_object, index)

    def _hover_source_item(self, item: QListWidgetItem | None):
        index = item.data(Qt.UserRole) if item is not None else None
        self._set_hovered_curve(index)

    def eventFilter(self, watched, event):
        if (
            hasattr(self, "curve_list")
            and watched is self.curve_list.viewport()
            and event.type() == QEvent.Leave
        ):
            self._set_hovered_curve(None)
        return super().eventFilter(watched, event)

    def _pick_curve(self, index, event):
        if not self._showing_current_run or self._tool_buttons["zoom"].isChecked():
            return
        if self.curve_search.text():
            self.curve_search.clear()
        self.curve_list.setCurrentItem(self._items[index])
        self.curve_list.scrollToItem(self._items[index])
        if self._tool_buttons["mark"].isChecked():
            result = next(curve.result for curve in self._run.curves if curve.index == index)
            point = self.view_box.mapSceneToView(event.scenePos())
            x_pixel, y_pixel = self.view_box.viewPixelSize()
            style = self._curve_style(index)
            display_y = result.y * style.gain + index * self._spacing_value
            distance = ((result.x - point.x()) / x_pixel) ** 2 + (
                (display_y - point.y()) / y_pixel
            ) ** 2
            distance[~(np.isfinite(result.x) & np.isfinite(result.y))] = np.inf
            point_index = int(np.argmin(distance))
            dot = pg.ScatterPlotItem(size=VIEWER_BEHAVIOR.default_point_size)
            label = pg.TextItem(anchor=(0, 1))
            dot.setAcceptedMouseButtons(Qt.NoButton)
            label.setAcceptedMouseButtons(Qt.NoButton)
            self.plot.addItem(dot, ignoreBounds=True)
            self.plot.addItem(label, ignoreBounds=True)
            self._marks.append(CurveMark(index, point_index, dot, label))
            self._update_marks()
            self._schedule_notebook_update()
        event.accept()

    def _select_navigation(self, key: str):
        if key == "home":
            self.view_box.autoRange()
            if self._run is not None:
                request = self._run.request.reduction
                if request.q_min is not None and request.q_max is not None:
                    self.view_box.setXRange(request.q_min, request.q_max, padding=0)
            return
        for name, button in self._tool_buttons.items():
            if name in {"pan", "zoom", "mark"}:
                button.setChecked(name == key)
        self.mark_controls.setVisible(key == "mark")
        self.view_box.setMouseEnabled(x=key != "mark", y=key != "mark")
        self.view_box.setMouseMode(pg.ViewBox.RectMode if key == "zoom" else pg.ViewBox.PanMode)
        self.canvas.setCursor(Qt.CrossCursor if key == "mark" else Qt.ArrowCursor)

    def _update_marks(self):
        if self._run is None:
            return
        curves = {curve.index: curve.result for curve in self._run.curves}
        color = AppStyle.theme_colors()["text"]
        for mark in self._marks:
            result = curves[mark.curve_index]
            x, intensity = result.x[mark.point_index], result.y[mark.point_index]
            y = (
                intensity * self._curve_style(mark.curve_index).gain
                + mark.curve_index * self._spacing_value
            )
            mark.dot.setData([x], [y], pen=pg.mkPen(color), brush=pg.mkBrush(VIEWER_COLORS.default_annotation))
            mark.label.setText(f"q={x:.6g} \u00c5\u207b\u00b9, I={intensity:.6g} (a.u.)", color=color)
            mark.label.setPos(x, y)
            visible = self._lines[mark.curve_index].isVisible()
            mark.dot.setVisible(visible)
            mark.label.setVisible(visible)

    def _undo_mark(self):
        if self._marks:
            mark = self._marks.pop()
            self.plot.removeItem(mark.dot)
            self.plot.removeItem(mark.label)
            self._schedule_notebook_update()

    def _clear_marks(self):
        while self._marks:
            self._undo_mark()

    def _save_plot(self):
        path, _ = choose_path(
            self, tr("results.save_plot"), mode="save",
            file_filter=tr("viewer.png_images_png_all_files"), default_name="waterfall.png",
        )
        if path:
            if Path(path).suffix.lower() != ".png":
                path += ".png"
            try:
                export_plot_view(self.plot, path)
            except Exception as exc:
                self.parent_app.report_error(tr("results.failed", error=str(exc)), exc)

    def _show_source(self):
        item = self.curve_list.currentItem()
        if item is not None:
            self.parent_app.show_waterfall_source(self._paths[item.data(Qt.UserRole)])

    def _open_issue_settings(self):
        self.parent_app.show_processing_tab(self._issue_destination)

    def _export(self):
        if self._run is None:
            return
        path, _ = choose_path(
            self, tr("results.export"), mode="save", file_filter=tr("results.zip_filter"),
            default_name="waterfall.zip",
        )
        if not path:
            return
        if Path(path).suffix.lower() != ".zip":
            path += ".zip"
        try:
            export_waterfall(self._run, path)
        except Exception as exc:
            self.parent_app.report_error(tr("results.failed", error=str(exc)), exc)
            self._set_issue_message(tr("results.failed", error=str(exc)))
        else:
            self.parent_app.show_status(tr("results.exported", path=path))

    def refresh_theme(self):
        self._draw()
        self.notebook.refresh_theme()

    def on_plot_style_changed(self):
        self._draw()

    def closeEvent(self, event):
        self._closing = True
        self._notebook_timer.stop()
        self._redraw_timer.stop()
        self._next_request = None
        if self._worker is not None:
            self._worker.cancel()
        super().closeEvent(event)

    def confirm_close(self) -> bool:
        return self._closing or self.notebook.confirm_discard()

    def _update_notebook_action(self):
        available = (
            self.notebook.editor_ready and self._worker is None and self._run is not None
            and any(curve.result is not None for curve in self._run.curves)
        )
        can_add = available and self._active_object is None
        self.add_notebook_button.setEnabled(can_add)
        self.add_notebook_button.setVisible(can_add)
        self.notebook.set_latest_available(self._latest_run is not None)

    def _compose_notebook(self):
        if self._sync_notebook_plot():
            self._show_workspace_page(self.notebook_workspace)

    def add_scientific_object(self, scientific_object: ScientificObject) -> None:
        """Insert a result produced elsewhere; the notebook numbers it like its own figures."""
        if not self._sync_notebook_plot():
            raise RuntimeError(tr("notebook.processing"))
        scientific_object.title = tr(
            "notebook.figure_number", name=scientific_object.title,
            number=len(self.notebook.document.objects) + 1,
        )
        self.notebook.add_object(scientific_object)
        self._inline_selected_object = None
        self._show_workspace_page(self.notebook_workspace)

    def _view_is_home(self) -> bool:
        """True while the view still shows the run's own framing rather than a pan/zoom."""
        auto_x, auto_y = self.view_box.autoRangeEnabled()
        if not auto_y:
            return False
        if auto_x:
            return True
        request = self._run.request.reduction if self._run is not None else None
        if request is None or request.q_min is None or request.q_max is None:
            return False
        return np.allclose(self.view_box.viewRange()[0], [request.q_min, request.q_max], rtol=1e-9, atol=1e-12)

    def _plot_state(self) -> PlotState:
        self.view_box.updateAutoRange()
        current = self.curve_list.currentItem()
        previous = self.notebook.document.objects.get(self._active_object)
        return PlotState(
            spacing=self._spacing_value, palette=self.palette.currentText(),
            hidden_sources=sorted(self._hidden_paths),
            view_range=None if self._view_is_home() else self.view_box.viewRange(),
            selected_index=current.data(Qt.UserRole) if current is not None else None,
            marks=[[mark.curve_index, mark.point_index] for mark in self._marks],
            curve_styles=self._curve_styles.copy(),
            width=previous.state.width if previous else 100,
            height=previous.state.height if previous else 320,
            default_line_style=self._default_line_style,
            default_line_width=self._default_line_width,
        )

    def _add_to_notebook(self):
        if self._run is None or self._worker is not None:
            return
        try:
            plot = self._create_notebook_plot(self._run, self._plot_state())
            self._active_object = plot.id
            self.latest_button.show()
            self.title.setText(tr("notebook.exploring", title=plot.title))
            self._update_notebook_action()
            self._compose_notebook()
        except Exception as exc:
            self.notebook._error(str(exc))

    def _create_notebook_plot(self, run: WaterfallRun, state: PlotState) -> CurveFigure:
        plot = notebook_waterfall(run, state, tr(
            "notebook.figure_number", name=tr("results.waterfall"),
            number=len(self.notebook.document.objects) + 1,
        ))
        self.notebook.add_object(plot)
        return plot

    def _insert_latest_notebook_plot(self):
        if self._worker is not None:
            self.parent_app.show_status(tr("notebook.processing"))
            return
        run = self._latest_run
        state = self._latest_state
        if run is None and self._active_object is None and self._run is not None:
            run, state = self._run, self._plot_state()
        if run is None:
            self.parent_app.show_status(tr("results.empty"))
            return
        try:
            self._create_notebook_plot(run, state or PlotState())
        except Exception as exc:
            self.notebook._error(str(exc))

    def _schedule_notebook_update(self, *_args):
        if not self._restoring and self._active_object is not None:
            self._notebook_timer.start()

    def _notebook_plot_selected(self, key: str):
        if self._worker is not None:
            self._inline_selected_object = key or None
            return
        if not key:
            if self._active_object is not None and not self._sync_notebook_plot():
                return
            self._inline_selected_object = None
            return
        plot = self.notebook.document.objects.get(key)
        if plot is None:
            self.notebook._error(tr("notebook.missing_object"))
            return
        if not isinstance(plot, CurveFigure):
            # Image figures are edited entirely in the document; the curve explorer keeps its state.
            if self._active_object is not None and not self._sync_notebook_plot():
                return
            self._inline_selected_object = key
            return
        if self._active_object != key:
            if self._active_object is not None and not self._sync_notebook_plot():
                return
            if self._active_object is None and self._run is not None:
                self._latest_run, self._latest_state = self._run, self._plot_state()
            self._active_object = key
            self._restore_plot(notebook_waterfall_run(plot), plot.state)
        self._inline_selected_object = key

    def _notebook_curve_hovered(self, key: str, index: int, point_index: int):
        if key != self._active_object:
            return
        if index < 0:
            self._set_hovered_curve(None)
            self.cursor_label.setText(tr("results.hover.empty"))
            return
        curve = next((item for item in self._run.curves if item.index == index), None) if self._run else None
        if curve is None or curve.result is None or not 0 <= point_index < len(curve.result.x):
            return
        self._set_hovered_curve(index)
        result = curve.result
        display = result.y[point_index] * self._curve_style(index).gain + index * self._spacing_value
        self.cursor_label.setText(tr(
            "results.hover.value",
            coordinate=f"{result.x[point_index]:.6g}",
            coordinate_units=FigureMetadata.plain_label(result.x_label) or "q",
            intensity=f"{result.y[point_index]:.6g}",
            intensity_units=FigureMetadata.plain_label(result.y_label) or "a.u.",
            display=f"{display:.6g}",
        ))

    def _notebook_curve_selected(self, key: str, index: int):
        if key not in self.notebook.document.objects:
            self.notebook._error(tr("notebook.missing_object"))
            return
        if self._active_object != key:
            self._notebook_plot_selected(key)
        if self._active_object != key:
            return
        if index == -1:
            self.curve_list.setCurrentItem(None)
            plot = self.notebook.document.objects[key]
            if plot.state.selected_index is not None:
                plot.state.selected_index = None
                self.notebook.update_plot_state(key)
            return
        item = self._items.get(index)
        if item is not None:
            self.curve_list.setCurrentItem(item)
            self.curve_list.scrollToItem(item)
            plot = self.notebook.document.objects[key]
            if plot.state.selected_index != index:
                plot.state.selected_index = index
                self.notebook.update_plot_state(key)

    def _notebook_plot_presentation_changed(self, key: str):
        if key != self._active_object or self._worker is not None:
            return
        plot = self.notebook.document.objects.get(key)
        if plot is None:
            return
        self._restore_plot(notebook_waterfall_run(plot), plot.state)
        self._notebook_timer.start()

    def _sync_notebook_plot(self) -> bool:
        self._notebook_timer.stop()
        if self._restoring or self._active_object is None:
            return True
        plot = self.notebook.document.objects.get(self._active_object)
        if plot is None:
            return True
        try:
            state = self._plot_state()
            if state != plot.state:
                state.validate(plot.curves)
                plot.state = state
                self.notebook.set_dirty()
                self.notebook.update_objects()
        except Exception as exc:
            self.notebook._error(str(exc))
            return False
        return True

    def _restore_plot(self, run: WaterfallRun, state: PlotState):
        self._restoring = True
        try:
            self._set_hovered_curve(None)
            self._clear_marks()
            self._paths = self._requested_paths = run.request.paths
            self._hidden_paths = set(state.hidden_sources)
            self._curve_styles = state.curve_styles.copy()
            self._default_line_style = state.default_line_style
            self._default_line_width = state.default_line_width
            self._initialize_spacing = False
            self._showing_current_run = False
            self.curve_search.clear()
            self.curve_list.clear()
            self._items.clear()
            for index, path in enumerate(self._paths):
                item = QListWidgetItem(Path(path).name)
                item.setData(Qt.UserRole, index)
                item.setToolTip(path)
                self.curve_list.addItem(item)
                self._items[index] = item
            with QSignalBlocker(self.palette):
                self.palette.setCurrentText(state.palette)
            self._set_spacing_control(state.spacing, run=run)
            self._run = WaterfallRun(run.request)
            self._pending_curves = list(run.curves)
            self._completed(run)
            self._update_spacing_label()
            for index, point in state.marks:
                dot = pg.ScatterPlotItem(size=VIEWER_BEHAVIOR.default_point_size)
                label = pg.TextItem(anchor=(0, 1))
                dot.setAcceptedMouseButtons(Qt.NoButton)
                label.setAcceptedMouseButtons(Qt.NoButton)
                self.plot.addItem(dot, ignoreBounds=True)
                self.plot.addItem(label, ignoreBounds=True)
                self._marks.append(CurveMark(index, point, dot, label))
            self._update_marks()
            if state.selected_index is not None:
                self.curve_list.setCurrentItem(self._items[state.selected_index])
            if state.view_range is not None:
                self.view_box.setRange(xRange=state.view_range[0], yRange=state.view_range[1], padding=0)
            self.update_button.setEnabled(bool(self._paths))
            self.update_button.setText(tr("results.recalculate"))
            self._update_notebook_action()
        finally:
            self._restoring = False

    def _show_latest(self):
        if self._worker is not None or self._latest_run is None:
            return
        if not self._sync_notebook_plot():
            return
        self._active_object = None
        self._restore_plot(self._latest_run, self._latest_state)
        self._show_processing_settings(self._latest_run.request)
        self.title.setText(tr("notebook.latest"))
        self.latest_button.hide()
        self._show_workspace_page(self.explorer)

    def _document_replaced(self):
        self._notebook_timer.stop()
        self._active_object = None
        self._inline_selected_object = None
        self.latest_button.hide()
        self._update_notebook_action()
        self._show_workspace_page(self.notebook_workspace)
