"""Offline Milkdown document editor and its deliberately small Qt bridge."""

from __future__ import annotations

from base64 import b64encode
from collections.abc import Callable
from dataclasses import asdict, replace
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
from PyQt5.QtCore import QEventLoop, QObject, QTimer, QUrl, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QDesktopServices, QKeySequence
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWebEngineCore import QWebEngineUrlRequestInterceptor
from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineView
from PyQt5.QtWidgets import QLabel, QMessageBox, QShortcut, QVBoxLayout, QWidget

from sciview.core.notebook import (
    IMAGE_COLORMAPS, CurveFigure, CurveStyle, ImageFigure, Notebook, ScientificObject, object_signature,
)
from sciview.data.notebook import load_notebook, save_notebook
from sciview.interfaces.text import tr
from sciview.interfaces.theme.app_style import AppStyle
from sciview.processing.plot_rendering import curve_appearances, figure_preview_png
from sciview.session.session_cache import choose_path
from sciview.settings.plot_style import resolve_plot_style
from sciview.settings.viewer_config import SUPPORTED_IMAGE_SCALES, colormap_lut


EDITOR_ROOT = Path(__file__).resolve().parents[1] / "notebook" / "dist"
EDITOR_STRINGS = (
    "preview_failed", "image_failed", "resize",
    "placeholder", "plot_block", "outline", "untitled_heading",
    "app_name", "outline_heading", "insert_result", "file_menu",
    "new", "open", "save_as", "save", "saved_state", "unsaved",
    "curve_controls", "figure_controls", "display_settings", "appearance", "separation",
    "palette", "curves", "line_style", "line_width", "display_gain",
    "color", "use_palette", "close_inspector", "solid", "dash",
    "dot", "dash_dot", "missing_object", "expand", "collapse",
    "outline_show", "outline_hide", "outline_empty", "display_note",
    "pan", "zoom", "home", "mark", "undo_mark", "formatting",
    "figure_title", "x_label", "x_units", "y_label", "y_units",
    "legend", "legend_name", "collection_settings", "move", "label_note", "curve_visible", "more_curve_tools",
    "default_line_style", "default_line_width", "measurements", "opacity",
    "figure_section", "curves_section", "waterfall_section", "default_appearance",
    "line", "style", "width", "edit_title_hint", "edit_axis_hint", "edit_legend_hint", "scaling_hint",
    "image_section", "colormap", "intensity_scale", "intensity_min", "intensity_max",
    "auto_intensity", "linear", "log", "intensity", "hover_map",
)


class LocalRequests(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        url = info.requestUrl()
        allowed = url.scheme() in {"data", "qrc", "about"}
        if url.isLocalFile():
            allowed = Path(url.toLocalFile()).resolve().is_relative_to(EDITOR_ROOT.resolve())
        info.block(not allowed)


class EditorPage(QWebEnginePage):
    error = pyqtSignal(str)

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        return is_main_frame and url == QUrl.fromLocalFile(str(EDITOR_ROOT / "index.html"))

    def javaScriptConsoleMessage(self, level, message, line, source):
        if level == QWebEnginePage.ErrorMessageLevel:
            self.error.emit(f"{message} ({Path(source).name}:{line})")


class NotebookBridge(QObject):
    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane

    @pyqtSlot(result=str)
    def configuration(self):
        strings = {key: tr(f"notebook.{key}") for key in EDITOR_STRINGS}
        strings["visible_curves"] = tr("notebook.visible_curves", count="{count}")
        strings["hover_empty"] = tr("results.hover.empty")
        strings["update_stale"] = tr("results.update_changed")
        strings["update_stale_hint"] = tr("results.recalculate.tooltip")
        return json.dumps({
            "strings": strings, "colormaps": list(IMAGE_COLORMAPS), "scales": list(SUPPORTED_IMAGE_SCALES),
        })

    @pyqtSlot()
    def ready(self):
        self.pane.editor_ready = True
        self.pane.refresh_theme()
        self.pane._show_document()
        self.pane.status.clear()
        self.pane.ready.emit()

    @pyqtSlot(str)
    def changed(self, markdown):
        if markdown == self.pane.document.markdown:
            return
        self.pane.document.markdown = markdown
        self.pane.set_dirty()

    @pyqtSlot(str)
    def failed(self, message):
        self.pane._error(message)

    @pyqtSlot()
    def latest(self):
        self.pane.insert_latest_requested.emit()

    @pyqtSlot(str)
    def updateFigure(self, key):
        if key not in self.pane.document.objects:
            self.pane._error(tr("notebook.missing_object"))
            return
        self.pane.update_requested.emit(key)

    @pyqtSlot()
    def newDocument(self):
        QTimer.singleShot(0, self.pane.new_document)

    @pyqtSlot()
    def openDocument(self):
        QTimer.singleShot(0, self.pane.open_dialog)

    @pyqtSlot()
    def saveDocument(self):
        QTimer.singleShot(0, self.pane.save)

    @pyqtSlot()
    def saveAs(self):
        QTimer.singleShot(0, lambda: self.pane.save(save_as=True))

    @staticmethod
    def _curve_control(plot: CurveFigure, control: str, value: str):
        state = deepcopy(plot.state)
        if control == "spacing":
            spacing = float(value)
            if not np.isfinite(spacing) or spacing < 0:
                raise ValueError("Invalid waterfall spacing.")
            state.spacing = spacing
        elif control == "palette":
            state.palette = value
        elif control == "visibility":
            index = int(value)
            if not 0 <= index < len(plot.sources):
                raise ValueError("Unknown source curve.")
            source = plot.sources[index]
            if source in state.hidden_sources:
                state.hidden_sources.remove(source)
            else:
                state.hidden_sources.append(source)
        elif control == "view_range":
            state.view_range = None if value == "auto" else json.loads(value)
        elif control == "mark":
            point = json.loads(value)
            if (
                not isinstance(point, list) or len(point) != 2
                or any(not isinstance(item, int) for item in point)
            ):
                raise ValueError("Invalid curve annotation.")
            if point not in state.marks:
                state.marks.append(point)
        elif control == "undo_mark":
            if state.marks:
                state.marks.pop()
        elif control == "default_line_style":
            state.default_line_style = value
        elif control == "default_line_width":
            state.default_line_width = float(value)
        elif control in {"curve_color", "line_style", "line_width", "gain", "opacity"}:
            index = state.selected_index
            if index is None:
                raise ValueError("Select a curve before editing its appearance.")
            style = state.curve_styles.get(index, CurveStyle())
            if control == "curve_color":
                style.color = None if value == "palette" else value
            elif control == "line_style":
                style.line_style = value
            elif control == "line_width":
                style.line_width = float(value)
            elif control == "gain":
                style.gain = float(value)
            else:
                style.opacity = float(value)
            style.validate()
            state.curve_styles[index] = style
        else:
            raise ValueError("Unknown notebook plot control.")
        state.validate(plot.curves)
        return state

    @staticmethod
    def _image_control(plot: ImageFigure, control: str, value: str):
        state = deepcopy(plot.state)
        if control == "colormap":
            state.colormap = value
        elif control == "scale":
            state.scale = value
        elif control == "limits":
            if value == "auto":
                state.vmin = state.vmax = None
            else:
                low, high = (float(item) for item in json.loads(value))
                state.vmin, state.vmax = low, high
        elif control == "view_range":
            state.view_range = None if value == "auto" else json.loads(value)
        else:
            raise ValueError("Unknown notebook image control.")
        state.validate()
        replace(plot, state=state).intensity_limits()
        return state

    @pyqtSlot(str, str, str)
    def setPlotControl(self, key, control, value):
        try:
            plot = self.pane.document.objects[key]
            if control == "show_legend":
                figure = deepcopy(plot.figure)
                figure.show_legend = json.loads(value)
                figure.validate(getattr(plot, "curves", []))
                if figure == plot.figure:
                    return
                plot.figure = figure
            else:
                if isinstance(plot, CurveFigure):
                    state = self._curve_control(plot, control, value)
                elif isinstance(plot, ImageFigure):
                    state = self._image_control(plot, control, value)
                else:
                    raise ValueError("Unknown notebook plot control.")
                if state == plot.state:
                    return
                plot.state = state
        except (KeyError, TypeError, ValueError) as exc:
            self.pane._error(str(exc))
            if key in self.pane.document.objects:
                self.pane.update_plot_state(key)
            return
        self.pane.status.hide()
        self.pane.set_dirty()
        self.pane.update_plot_state(key)
        self.pane.plot_presentation_changed.emit(key)

    @pyqtSlot(str, str, str)
    def setFigureText(self, key, field, value):
        if self.pane.prepare_save is not None and not self.pane.prepare_save():
            return
        try:
            plot = self.pane.document.objects[key]
            figure = deepcopy(plot.figure)
            value = value.strip()
            curves = getattr(plot, "curves", [])
            if field == "title":
                if not value or len(value) > 256 or "\n" in value:
                    raise ValueError("Figure title must be nonempty single-line text up to 256 characters.")
                if plot.title == value:
                    return
                plot.title = value
            elif field in {"x_label", "x_units", "y_label", "y_units"}:
                setattr(figure, field, value)
                figure.validate(curves)
                if figure == plot.figure:
                    return
                plot.figure = figure
            elif field.startswith("legend:"):
                index = int(field.split(":", 1)[1])
                if not value:
                    raise ValueError("A measurement legend name cannot be empty.")
                figure.legend_names[index] = value
                figure.validate(curves)
                if figure == plot.figure:
                    return
                plot.figure = figure
            else:
                raise ValueError("Unknown scientific figure label.")
        except (KeyError, TypeError, ValueError) as exc:
            self.pane._error(str(exc))
            if key in self.pane.document.objects:
                self.pane.update_plot_state(key)
            return
        self.pane.set_dirty()
        self.pane.status.hide()
        self.pane.update_plot_state(key)
        self.pane.plot_presentation_changed.emit(key)

    @pyqtSlot(str, int, int)
    def curveHovered(self, key, index, point_index):
        self.pane.curve_hovered.emit(key, index, point_index)

    @pyqtSlot(str, int)
    def curveSelected(self, key, index):
        self.pane.curve_selected.emit(key, index)

    @pyqtSlot(str)
    def openLink(self, address):
        url = QUrl(address)
        if not url.isValid() or url.scheme() not in {"https", "http", "mailto"}:
            self.pane._error(tr("notebook.link_failed"))
        elif not QDesktopServices.openUrl(url):
            self.pane._error(tr("notebook.link_failed"))

    @pyqtSlot(str, int, int)
    def resizePlot(self, key, width, height):
        try:
            plot = self.pane.document.objects[key]
            state = deepcopy(plot.state)
            state.width, state.height = width, height
            if isinstance(plot, CurveFigure):
                state.validate(plot.curves)
            else:
                state.validate()
        except (KeyError, ValueError) as exc:
            self.pane._error(str(exc))
            return
        if state == plot.state:
            return
        plot.state = state
        self.pane.set_dirty()
        self.pane.update_plot_state(key)

    @pyqtSlot(str)
    def selectPlot(self, key):
        if key and key not in self.pane.document.objects:
            self.pane._error(tr("notebook.missing_object"))
            return
        self.pane.plot_selection_changed.emit(key)

    @pyqtSlot(str, int, int)
    def previewSize(self, key, width, height):
        if key not in self.pane.document.objects or width <= 0 or height <= 0:
            return
        scale = min(1.0, 4096 / width, 2400 / height, (16_777_216 / (width * height)) ** 0.5)
        self.pane._preview_sizes[key] = (max(1, round(width * scale)), max(1, round(height * scale)))


class NotebookEditor(QWidget):
    ready = pyqtSignal()
    document_replaced = pyqtSignal()
    insert_latest_requested = pyqtSignal()
    update_requested = pyqtSignal(str)
    plot_selection_changed = pyqtSignal(str)
    curve_hovered = pyqtSignal(str, int, int)
    curve_selected = pyqtSignal(str, int)
    plot_presentation_changed = pyqtSignal(str)

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.document = Notebook()
        self._saved_signature = self.document.content_signature()
        self.dirty = False
        self.editor_ready = False
        self._preview_sizes: dict[str, tuple[int, int]] = {}
        self._rendered_previews: dict[str, tuple[str, tuple[int, int] | None]] = {}
        # Figures whose inputs changed since they were computed; session state, never saved.
        self.stale: set[str] = set()
        self.prepare_save: Callable[[], bool] | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)
        self.view = QWebEngineView()
        # An unnamed profile keeps browser state in memory and separate from user browsing.
        self.profile = QWebEngineProfile()
        self.view.destroyed.connect(self.profile.deleteLater)
        self.interceptor = LocalRequests(self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.page = EditorPage(self.profile, self.view)
        self.page.error.connect(self._error)
        self.view.setPage(self.page)
        self.page.settings().setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
        self.page.settings().setAttribute(QWebEngineSettings.JavascriptCanAccessClipboard, True)
        self.page.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
        self.page.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, False)
        self.channel = QWebChannel(self.page)
        self.bridge = NotebookBridge(self)
        self.channel.registerObject("notebook", self.bridge)
        self.page.setWebChannel(self.channel)
        self.view.loadFinished.connect(self._load_finished)
        layout.addWidget(self.view, 1)
        self.view.load(QUrl.fromLocalFile(str(EDITOR_ROOT / "index.html")))
        self._save_shortcut = QShortcut(QKeySequence.Save, self)
        self._save_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._save_shortcut.activated.connect(self.save)

    def _error(self, message: str):
        self.status.setText(tr("notebook.failed", error=message))
        self.status.show()
        self.parent_app.report_error(self.status.text())

    def _load_finished(self, success):
        if not success:
            self._error(tr("notebook.load_failed"))

    def set_dirty(self):
        self.dirty = self.document.content_signature() != self._saved_signature
        self._update_title()

    def _update_title(self):
        name = self.document.path.name if self.document.path else tr("notebook.untitled")
        if self.editor_ready:
            self.page.runJavaScript(
                f"sciview.setDocumentTitle({json.dumps(name)}, {str(self.dirty).lower()})",
            )

    def _curve_presentation(self, plot: CurveFigure) -> dict:
        default_width = resolve_plot_style(self.parent_app).line_width
        return {
            "spacing_reference": self._spacing_reference(plot),
            "curves": [asdict(look) for look in curve_appearances(plot, default_width)],
            "state": {
                "spacing": plot.state.spacing,
                "palette": plot.state.palette,
                "hidden_sources": plot.state.hidden_sources,
                "view_range": plot.state.view_range,
                "selected_index": plot.state.selected_index,
                "marks": plot.state.marks,
                "default_line_style": plot.state.default_line_style,
                "default_line_width": plot.state.default_line_width or default_width,
            },
            "display_note": bool(plot.state.spacing or any(
                style.gain != 1 for style in plot.state.curve_styles.values()
            )),
        }

    @staticmethod
    def _image_presentation(plot: ImageFigure) -> dict:
        low, high = plot.intensity_limits()
        return {
            "state": {
                "colormap": plot.state.colormap,
                "scale": plot.state.scale,
                "auto": plot.state.vmin is None,
                "vmin": plot.state.vmin,
                "vmax": plot.state.vmax,
                "view_range": plot.state.view_range,
            },
            "limits": [low, high],
            "lut": ["#" + "".join(f"{int(channel):02x}" for channel in rgb) for rgb in colormap_lut(plot.state.colormap)],
            "display_note": False,
        }

    def _presentation(self, plot: ScientificObject) -> dict:
        payload = {
            "kind": plot.kind,
            "title": plot.title,
            "width": plot.state.width,
            "height": plot.state.height,
            "figure": asdict(plot.figure),
            "stale": plot.id in self.stale,
        }
        if isinstance(plot, CurveFigure):
            payload.update(self._curve_presentation(plot))
        elif isinstance(plot, ImageFigure):
            payload.update(self._image_presentation(plot))
        return payload

    def object_payload(self):
        payload = {}
        for key, plot in self.document.objects.items():
            entry = self._presentation(plot)
            if isinstance(plot, CurveFigure):
                looks = {look["index"]: look for look in entry.pop("curves")}
                entry["curves"] = [
                    {
                        **looks[curve.index],
                        "source": curve.source,
                        "x": curve.x.tolist() if curve.x is not None else [],
                        "y": curve.y.tolist() if curve.y is not None else [],
                    }
                    for curve in plot.curves
                ]
                entry["summary"] = tr(
                    "notebook.curve_count", count=sum(curve.x is not None for curve in plot.curves),
                )
            elif isinstance(plot, ImageFigure):
                height, width = plot.image.shape
                entry["image"] = {
                    "data": b64encode(np.ascontiguousarray(plot.image, dtype="<f4").tobytes()).decode("ascii"),
                    "width": width,
                    "height": height,
                    "extent": plot.extent(),
                }
                entry["summary"] = tr("notebook.image_size", width=width, height=height)
            payload[key] = entry
        return payload

    @staticmethod
    def _spacing_reference(plot: CurveFigure) -> float:
        reference = 1.0
        first_y = next((curve.y for curve in plot.curves if curve.y is not None), None)
        if first_y is not None:
            values = first_y[np.isfinite(first_y)]
            if values.size:
                low, high = np.percentile(values, [5, 95])
                reference = float(max(high - low, abs(high), abs(low)) * 0.1)
        return max(reference, plot.state.spacing / 3, np.finfo(float).eps)

    def highlight_curve(self, key: str, index: int | None):
        if self.editor_ready:
            value = -1 if index is None else index
            self.page.runJavaScript(
                f"sciview.highlightCurve({json.dumps(key)}, {value})",
            )

    def preview_size(self, key: str) -> tuple[int, int] | None:
        return self._preview_sizes.get(key)

    def update_objects(self):
        if self.editor_ready:
            self.page.runJavaScript(f"sciview.updateObjects({json.dumps(self.object_payload())})")

    def update_plot_state(self, key: str):
        if self.editor_ready and key in self.document.objects:
            self.page.runJavaScript(
                f"sciview.updatePlotState({json.dumps(key)}, "
                f"{json.dumps(self._presentation(self.document.objects[key]))})",
            )

    def set_stale(self, key: str, stale: bool):
        if stale:
            self.stale.add(key)
        else:
            self.stale.discard(key)
        if self.editor_ready and key in self.document.objects:
            self.page.runJavaScript(f"sciview.setStale({json.dumps(key)}, {str(stale).lower()})")

    def set_latest_available(self, available: bool):
        if self.editor_ready:
            self.page.runJavaScript(
                f"sciview.setLatestAvailable({str(available).lower()})",
            )

    def _show_document(self):
        if self.editor_ready:
            document = self.document
            was_clean = not self.dirty

            def normalized(markdown):
                if self.document is document and isinstance(markdown, str):
                    document.markdown = markdown
                    if was_clean:
                        self._saved_signature = document.content_signature()
                    self.set_dirty()

            self.page.runJavaScript(
                f"sciview.setDocument({json.dumps(self.document.markdown)}, {json.dumps(self.object_payload())}); sciview.flush()",
                normalized,
            )
            self.page.runJavaScript(
                f"sciview.setDocumentTitle("
                f"{json.dumps(self.document.path.name if self.document.path else tr('notebook.untitled'))}, "
                f"{str(self.dirty).lower()})",
            )
        self._update_title()
        self.status.hide()

    def add_object(self, plot: ScientificObject):
        if not self.editor_ready:
            raise RuntimeError(tr("notebook.loading"))
        self.document.add_object(plot)
        self._render_preview(plot.id)
        self.update_objects()
        self.page.runJavaScript(f"sciview.addPlot({json.dumps(plot.id)})")
        self.set_dirty()

    def _render_preview(self, key: str):
        plot = self.document.objects[key]
        size = self._preview_sizes.get(key)
        rendered = (object_signature(plot), size)
        if plot.preview and self._rendered_previews.get(key) == rendered:
            return
        plot.preview = figure_preview_png(plot, size)
        self._rendered_previews[key] = rendered

    def snapshot_markdown(self) -> str:
        if not self.editor_ready:
            raise RuntimeError(tr("notebook.loading"))
        result = []
        active = True
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)

        def received(value):
            if not active:
                return
            result.append(value)
            loop.quit()

        self.page.runJavaScript("sciview.flush()", received)
        timer.start(5000)
        loop.exec_()
        active = False
        timer.stop()
        if not result or not isinstance(result[0], str):
            raise RuntimeError(tr("notebook.snapshot_failed"))
        self.document.markdown = result[0]
        return result[0]

    def save(self, *, save_as=False) -> bool:
        path = self.document.path
        if save_as or path is None:
            name, _ = choose_path(
                self, tr("notebook.save"), mode="save", default_name="notebook.md",
                file_filter=tr("notebook.markdown_filter"),
            )
            if not name:
                return False
            path = Path(name)
            if path.suffix.lower() != ".md":
                path = path.with_suffix(".md")
        try:
            if self.prepare_save is not None and not self.prepare_save():
                return False
            self.snapshot_markdown()
            for key in self.document.objects:
                self._render_preview(key)
            save_notebook(self.document, path)
        except Exception as exc:
            self._error(str(exc))
            return False
        self.dirty = False
        self._saved_signature = self.document.content_signature()
        self.status.hide()
        self._update_title()
        self.parent_app.show_status(tr("notebook.saved", path=str(path)))
        return True

    def confirm_discard(self) -> bool:
        if self.prepare_save is not None and not self.prepare_save():
            return False
        if self.editor_ready:
            previous = self.document.markdown
            try:
                current = self.snapshot_markdown()
            except Exception as exc:
                self._error(str(exc))
                return False
            else:
                if current != previous:
                    self.set_dirty()
        self.set_dirty()
        if not self.dirty:
            return True
        response = QMessageBox.warning(
            self, tr("notebook.unsaved"), tr("notebook.unsaved_detail"),
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save,
        )
        if response == QMessageBox.Save:
            return self.save()
        if response == QMessageBox.Discard:
            self.dirty = False
            return True
        return False

    def _replace_document(self, document: Notebook):
        self.document = document
        self.dirty = False
        self._saved_signature = document.content_signature()
        self._preview_sizes.clear()
        self._rendered_previews.clear()
        self.stale.clear()
        self._show_document()
        self.document_replaced.emit()

    def new_document(self):
        if self.confirm_discard():
            self._replace_document(Notebook())

    def open_dialog(self):
        path, _ = choose_path(
            self, tr("notebook.open"), mode="open", file_filter=tr("notebook.markdown_filter"),
        )
        if path:
            self.open_document(path)

    def open_document(self, path: str | Path) -> bool:
        if not self.confirm_discard():
            return False
        try:
            document = load_notebook(path)
        except Exception as exc:
            self._error(str(exc))
            return False
        self._replace_document(document)
        return True

    def refresh_theme(self):
        if not self.editor_ready:
            return
        colors = AppStyle.theme_colors()
        font = AppStyle.make_font("body")
        properties = {f"--{key}": value.name() for key, value in colors.items()}
        properties["--font"] = f'{font.pixelSize()}px "{font.family()}", sans-serif'
        properties["--font-family"] = f'"{font.family()}", sans-serif'
        self.page.runJavaScript(
            "Object.entries(" + json.dumps(properties) + ").forEach(([key,value]) => "
            "document.documentElement.style.setProperty(key,value))",
        )
