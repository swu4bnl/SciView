"""Reduction and Transform results as reusable, persisted notebook objects."""

import os
from io import BytesIO
from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from PIL import Image

from sciview.core.notebook import (
    CurveFigure, FigureMetadata, ImageFigure, ImageState, Notebook, object_signature,
)
from sciview.data.notebook import load_notebook, save_notebook
from sciview.processing.notebook_results import reduction_figure, refresh_image_figure, transform_figure
from sciview.processing.plot_rendering import figure_preview_png
from sciview.processing.reduction import ReductionBackend, ReductionRequest
from sciview.processing.transform import TransformRequest, TransformResult
from sciview.processing.waterfall import notebook_waterfall_run, refresh_waterfall

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _detector_image():
    yy, xx = np.indices((24, 32))
    return np.exp(-((xx - 15.5) ** 2 + (yy - 11.5) ** 2) / 40.0) * 1000.0 + 5.0


def _calibration():
    return SimpleNamespace(
        width=32, height=24, wavelength_A=1.0, pixel_size_um=172.0, distance_m=2.0,
        x0=15.5, y0=11.5, incident_angle=0.12, clear_maps=lambda: None,
    )


def _reduction(image, mask):
    request = ReductionRequest(
        image=image, operation="circular_average", center_x=15.5, center_y=11.5, bins=12,
        q_min=0.0, q_max=10.0, radius_max=10.0, mask=mask, use_mask=True,
        metadata={
            "source_path": "C:/beamtime/sample_a.tif", "calibration_source": "From calibration tab",
            "mask_source": "From mask tab", "calibration_label": "None", "mask_label": "None",
        },
    )
    return request, ReductionBackend().run(request)


def _transform(image, mask):
    request = TransformRequest(
        image=image, operation="q_image", calibration=_calibration(), mask=mask, use_mask=True,
        bins_relative=0.5, metadata={"source_path": "C:/beamtime/sample_a.tif", "calibration_source": "From calibration tab"},
    )
    rows, columns = np.indices((10, 12))
    result = TransformResult(
        "q_image", (rows + 1.0) * (columns + 1.0) * 3.0, np.linspace(-1.2, 1.0, 12), np.linspace(0.0, 1.8, 10),
        "q_x (Å⁻¹)", "q_z (Å⁻¹)", {"source": "scianalysis", "backend": "transform", "method": "remesh_q_bin"},
    )
    result.image[0, 0] = np.nan
    return request, result


def test_reduction_and_transform_results_become_reusable_notebook_objects(tmp_path):
    image = _detector_image()
    mask = np.zeros(image.shape, dtype=bool)
    mask[:2, :] = True
    request, result = _reduction(image, mask)
    curve_figure = reduction_figure(request, result, title="Circular Average")
    assert curve_figure.kind == "curves"
    assert curve_figure.sources == ["C:/beamtime/sample_a.tif"]
    assert curve_figure.provenance["backend"] == "numpy"
    assert curve_figure.provenance["parameters"]["operation"] == "circular_average"
    assert curve_figure.provenance["parameters"]["center_x"] == 15.5
    assert curve_figure.provenance["calibration"] is None
    assert curve_figure.provenance["shape"] == [24, 32]
    assert curve_figure.provenance["mask"]["excluded_pixels"] == 64
    assert (curve_figure.figure.x_label, curve_figure.figure.x_units) == ("Detector radius", "px")
    np.testing.assert_array_equal(curve_figure.curves[0].y, result.y)
    mask[:] = False
    assert curve_figure.mask[0, 0]
    restored_run = notebook_waterfall_run(curve_figure)
    assert restored_run.request.reduction.center_x == 15.5
    assert restored_run.request.reduction.radius_max == 10.0
    np.testing.assert_array_equal(restored_run.curves[0].result.x, result.x)

    transform_request, transform_result = _transform(image, np.zeros(image.shape, dtype=bool))
    image_figure = transform_figure(
        transform_request, transform_result, title="Q Image", state=ImageState(scale="log"),
    )
    assert image_figure.kind == "image"
    assert image_figure.provenance["calibration"]["beam_x"] == 15.5
    assert image_figure.provenance["calibration"]["incident_angle"] == 0.12
    assert image_figure.provenance["parameters"]["method"] == "remesh_q_bin"
    assert image_figure.provenance["mask"]["excluded_pixels"] == 0
    assert (image_figure.figure.x_label, image_figure.figure.x_units) == ("q_x", "Å⁻¹")
    assert (image_figure.figure.y_label, image_figure.figure.y_units) == ("q_z", "Å⁻¹")
    np.testing.assert_allclose(image_figure.extent(), [[-1.3, 1.1], [-0.1, 1.9]])
    low, high = image_figure.intensity_limits()
    assert 0 < low < high
    for figure in (curve_figure, image_figure):
        preview = Image.open(BytesIO(figure_preview_png(figure, (320, 180))))
        assert preview.size == (320, 180)
    with pytest.raises(ValueError):
        transform_figure(
            transform_request, transform_result, title="Q Image", state=ImageState(vmin=5.0),
        )
    with pytest.raises(ValueError):
        transform_figure(
            transform_request, transform_result, title="Q Image", state=ImageState(colormap="unknown"),
        )
    with pytest.raises(ValueError):
        ImageFigure(
            title="Broken", sources=[], image=transform_result.image, provenance={}, state=ImageState(),
            x_axis=np.linspace(1, 0, 12),
        ).validate()

    curve_figure.preview = figure_preview_png(curve_figure)
    image_figure.preview = figure_preview_png(image_figure)
    notebook = Notebook(markdown=(
        f'# Sample A\n\n![curve](curve.png "sciview:{curve_figure.id}")\n\n'
        f'Observed a ring.\n\n![map](map.png "sciview:{image_figure.id}")\n'
    ))
    notebook.add_object(curve_figure)
    notebook.add_object(image_figure)
    baseline = notebook.content_signature()
    image_figure.preview = b"responsive"
    curve_figure.state.selected_index = 0
    assert notebook.content_signature() == baseline
    image_figure.state.colormap = "plasma"
    image_figure.state.vmin, image_figure.state.vmax = 3.0, 900.0
    image_figure.title = "Reciprocal map"
    image_figure.figure.y_units = "1/Å"
    curve_figure.figure.x_units = "pixel"
    assert notebook.content_signature() != baseline
    image_figure.preview = figure_preview_png(image_figure)

    saved = save_notebook(notebook, tmp_path / "sample a.md")
    manifest_path = saved.parent / yaml.safe_load(saved.read_text(encoding="utf-8").split("---\n")[1])["sciview"]["manifest"]
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["version"] == 2
    assert {record["kind"] for record in manifest["objects"].values()} == {"curves", "image"}
    restored = load_notebook(saved)
    assert isinstance(restored.objects[curve_figure.id], CurveFigure)
    recovered_image = restored.objects[image_figure.id]
    assert isinstance(recovered_image, ImageFigure)
    assert recovered_image.title == "Reciprocal map"
    assert recovered_image.state == image_figure.state
    assert recovered_image.figure == image_figure.figure
    assert recovered_image.provenance == image_figure.provenance
    np.testing.assert_array_equal(recovered_image.image, transform_result.image)
    np.testing.assert_array_equal(recovered_image.x_axis, transform_result.x_axis)
    np.testing.assert_array_equal(recovered_image.mask, image_figure.mask)
    assert restored.objects[curve_figure.id].figure.x_units == "pixel"
    assert object_signature(restored.objects[curve_figure.id]) == object_signature(curve_figure)
    assert restored.content_signature() == notebook.content_signature()
    assert f'"sciview:{image_figure.id}"' in restored.markdown

    tampered = restored.objects[image_figure.id]
    tampered.mask = ~tampered.mask
    with pytest.raises(ValueError, match="mask"):
        tampered.validate()
    manifest["objects"][image_figure.id]["kind"] = "hologram"
    manifest_path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="hologram"):
        load_notebook(saved)
    manifest["objects"][image_figure.id]["kind"] = "image"
    manifest_path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (manifest_path.parent / f"{image_figure.id}.npz").unlink()
    with pytest.raises(FileNotFoundError):
        load_notebook(saved)

    legacy = Notebook(markdown=f'![curve](curve.png "sciview:{curve_figure.id}")\n')
    legacy.add_object(curve_figure)
    legacy_path = save_notebook(legacy, tmp_path / "legacy.md")
    legacy_manifest_path = legacy_path.parent / yaml.safe_load(
        legacy_path.read_text(encoding="utf-8").split("---\n")[1],
    )["sciview"]["manifest"]
    legacy_manifest = yaml.safe_load(legacy_manifest_path.read_text(encoding="utf-8"))
    legacy_manifest["version"] = 1
    del legacy_manifest["objects"][curve_figure.id]["kind"]
    legacy_manifest_path.write_text(yaml.safe_dump(legacy_manifest), encoding="utf-8")
    legacy_plot = load_notebook(legacy_path).objects[curve_figure.id]
    assert isinstance(legacy_plot, CurveFigure)
    np.testing.assert_array_equal(legacy_plot.curves[0].y, result.y)
    assert FigureMetadata.from_labels("q (Å⁻¹)", "I(q) (a.u.)") == FigureMetadata("q", "Å⁻¹", "I(q)", "a.u.")

    # In-place refresh keeps identity, title, labels and presentation; incomplete runs are rejected.
    doubled = TransformResult(
        "q_image", transform_result.image * 2, transform_result.x_axis, transform_result.y_axis,
        transform_result.x_label, transform_result.y_label, dict(transform_result.metadata),
    )
    refresh_image_figure(image_figure, transform_request, doubled)
    assert (image_figure.title, image_figure.state.colormap, image_figure.figure.y_units) == ("Reciprocal map", "plasma", "1/Å")
    np.testing.assert_array_equal(image_figure.image, transform_result.image * 2)
    cancelled = notebook_waterfall_run(curve_figure)
    cancelled.cancelled = True
    with pytest.raises(ValueError):
        refresh_waterfall(curve_figure, cancelled)
    np.testing.assert_array_equal(curve_figure.curves[0].y, result.y)


def test_processing_tabs_insert_results_into_notebook_and_reopen(tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from main import SciAnaApp
    from sciview.interfaces.theme.app_style import AppStyle
    from sciview.processing.transform import TransformBackend
    from sciview.session import session_cache
    from tabs.reduction_tab import ReductionTab
    from tabs.results_tab import ResultsTab
    from tabs.transform_tab import TransformTab
    from test_image_playback import read_editor_value, wait_until

    app = QApplication.instance() or QApplication([])
    AppStyle.apply_bundled_fonts(app)
    monkeypatch.setattr(SciAnaApp, "_setup_resource_monitor", lambda self: None)
    monkeypatch.setattr(SciAnaApp, "save_session_state", lambda self: None)
    monkeypatch.setattr(session_cache, "clear_scratch", lambda: None)
    # A modal prompt would block a failing test forever; the assertions check dirtiness explicitly.
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: QMessageBox.Discard)
    window = SciAnaApp()
    reduction = ReductionTab(window)
    reduction.auto_update_check.setChecked(False)
    window.add_tab(reduction, "Reduction", icon_key="reduction")
    transform = TransformTab(window)
    transform.auto_update_check.setChecked(False)
    window.add_tab(transform, "Transform", icon_key="transform")
    results = ResultsTab(window)
    window.add_tab(results, "Notebook", icon_key="results")
    window.show()
    image = _detector_image()
    image_path = tmp_path / "sample_a.tif"
    Image.fromarray(image.astype(np.float32)).save(image_path)
    window.publish_shared_image(image, str(image_path))
    _, transform_result = _transform(image, None)
    monkeypatch.setattr(TransformBackend, "run", lambda _backend, request: transform_result)
    try:
        wait_until(lambda: results.notebook.editor_ready)
        window.show_processing_tab("reduction")
        crop = reduction._operation_param_widgets["circular_average"]
        crop["auto_crop"].setChecked(False)
        crop["q_min"].setValue(0.0)
        crop["q_max"].setValue(10.0)
        reduction.refresh_preview()
        assert reduction._current_result is not None
        reduction.add_notebook_button.click()
        assert window.tab_widget.currentWidget() is results
        assert results.workspace.currentWidget() is results.notebook_workspace
        curve_key = next(iter(results.notebook.document.objects))
        curve_object = results.notebook.document.objects[curve_key]
        assert isinstance(curve_object, CurveFigure)
        assert curve_object.title == "Circular Average 1"
        assert curve_object.sources == [str(image_path)]
        assert curve_object.state.curve_styles[0].color == window.plot_style.line_color

        window.show_processing_tab("transform")
        window.publish_shared_calibration(_calibration())
        transform.color_auto_check.setChecked(False)
        transform.plot_vmin_spin.setValue(10.0)
        transform.plot_vmax_spin.setValue(400.0)
        transform.plot_scale_combo.setCurrentText("log")
        transform.refresh_preview()
        assert transform._current_result is transform_result
        transform.add_notebook_button.click()
        assert window.tab_widget.currentWidget() is results
        image_key = next(key for key in results.notebook.document.objects if key != curve_key)
        image_object = results.notebook.document.objects[image_key]
        assert isinstance(image_object, ImageFigure)
        assert image_object.title == "Q Image 2"
        assert image_object.state == ImageState(
            colormap=window.plot_style.colormap, scale="log", vmin=10.0, vmax=400.0,
        )
        assert image_object.provenance["calibration"]["distance_m"] == 2.0
        wait_until(lambda: read_editor_value(
            results.notebook.page, "document.querySelectorAll('.plot-card').length",
        ) == 2)
        wait_until(lambda: read_editor_value(
            results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{image_key}\"] image[data-image-map]') !== null",
        ))
        assert read_editor_value(
            results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{image_key}\"] .image-colorbar') !== null",
        )
        assert read_editor_value(
            results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{image_key}\"] .plot-legend').hidden",
        )
        assert read_editor_value(
            results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{image_key}\"] [data-plot-action=\"mark\"]') === null",
        )

        results.notebook.page.runJavaScript(
            f"document.querySelector('.plot-card[data-object-id=\"{image_key}\"]').dispatchEvent("
            "new MouseEvent('mousedown', {bubbles: true}))",
        )
        wait_until(lambda: results._inline_selected_object == image_key)
        assert results._active_object is None

        # Changed inputs mark dependent figures; Update recomputes each figure in place.
        import sciview.processing.waterfall as waterfall
        from sciview.processing.reduction import ReductionBackend, ReductionResult
        from sciview.processing.scientific_labels import reduction_axis_labels

        class Detector:
            def __init__(self, path):
                with Image.open(path) as handle:
                    self.data = np.asarray(handle, dtype=np.float64)

        monkeypatch.setattr(waterfall, "_load_scianalysis_classes", lambda: (object, Detector, object))
        reductions = []

        def reduce_image(_backend, request):
            reductions.append(request)
            return ReductionResult(
                request.operation, np.array([0.05, 0.1, 0.15]), np.array([7.0, 9.0, 8.0]),
                *reduction_axis_labels(request.operation), {"source": "scianalysis"},
            )

        monkeypatch.setattr(ReductionBackend, "run", reduce_image)
        assert curve_key in results.notebook.stale
        assert image_key not in results.notebook.stale
        window.publish_shared_mask(np.zeros(image.shape, dtype=bool))
        assert {curve_key, image_key} <= results.notebook.stale
        wait_until(lambda: not read_editor_value(
            results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{curve_key}\"] .plot-update').hidden",
        ))
        assert not results.update_button.isVisible()
        results.notebook.bridge.updateFigure(curve_key)
        wait_until(lambda: results._worker is None)
        wait_until(lambda: curve_key not in results.notebook.stale)
        assert results.notebook.document.objects[curve_key] is curve_object
        assert len(results.notebook.document.objects) == 2
        np.testing.assert_array_equal(curve_object.curves[0].y, [7, 9, 8])
        assert curve_object.provenance["calibration"]["beam_x"] == 15.5
        assert curve_object.provenance["mask"]["excluded_pixels"] == 0
        assert reductions[-1].metadata["source_path"] == str(image_path)
        assert curve_object.title == "Circular Average 1"
        assert curve_object.state.curve_styles[0].color == window.plot_style.line_color
        assert results._active_object == curve_key
        assert results._latest_run is None
        assert results.notebook.dirty
        wait_until(lambda: read_editor_value(
            results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{curve_key}\"] .plot-update').hidden",
        ))
        updated_result = TransformResult(
            "q_image", transform_result.image * 2, transform_result.x_axis, transform_result.y_axis,
            transform_result.x_label, transform_result.y_label, dict(transform_result.metadata),
        )
        monkeypatch.setattr(TransformBackend, "run", lambda _backend, request: updated_result)
        results.notebook.bridge.updateFigure(image_key)
        assert image_key not in results.notebook.stale
        assert results.notebook.document.objects[image_key] is image_object
        np.testing.assert_array_equal(image_object.image, transform_result.image * 2)
        assert image_object.title == "Q Image 2"
        assert image_object.provenance["mask"]["excluded_pixels"] == 0
        assert image_object.state.vmin == 10.0

        bridge = results.notebook.bridge
        bridge.setPlotControl(image_key, "colormap", "plasma")
        bridge.setPlotControl(image_key, "limits", "[2, 500]")
        bridge.setPlotControl(image_key, "view_range", "[[-1, 1], [0, 1.5]]")
        bridge.setFigureText(image_key, "title", "Reciprocal map")
        bridge.setFigureText(image_key, "y_units", "1/Å")
        bridge.setPlotControl(image_key, "colormap", "not-a-colormap")
        bridge.setPlotControl(image_key, "limits", "[500, 2]")
        bridge.setPlotControl(curve_key, "default_line_width", "2")
        bridge.setFigureText(curve_key, "x_units", "pixel")
        assert image_object.state == ImageState(
            colormap="plasma", scale="log", vmin=2.0, vmax=500.0, view_range=[[-1, 1], [0, 1.5]],
        )
        assert image_object.title == "Reciprocal map"
        assert image_object.figure.y_units == "1/Å"
        assert curve_object.figure.x_units == "pixel"
        assert curve_object.state.default_line_width == 2
        assert results.notebook.dirty
        results.notebook.page.runJavaScript(
            f"document.querySelector('.plot-card[data-object-id=\"{image_key}\"] [data-plot-action=\"settings\"]').click()",
        )
        wait_until(lambda: read_editor_value(
            results.notebook.page,
            "document.querySelector('#figure-settings select[aria-label=\"Colormap\"]')?.value",
        ) == "plasma")
        assert read_editor_value(
            results.notebook.page,
            "document.querySelector('#figure-settings input[aria-label=\"Intensity min\"]').value",
        ) == "2"
        assert read_editor_value(
            results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{image_key}\"] .plot-title').value",
        ) == "Reciprocal map"

        notebook_path = tmp_path / "sample a.md"
        import sciview.interfaces.stable_qt.widgets.notebook_editor as notebook_editor
        monkeypatch.setattr(notebook_editor, "choose_path", lambda *_args, **_kwargs: (str(notebook_path), ""))
        assert results.notebook.save()
        assert not results.notebook.dirty
        preview = Image.open(BytesIO(image_object.preview))
        assert preview.size == results.notebook.preview_size(image_key)

        previous = results.notebook.document
        assert results.notebook.open_document(notebook_path)
        assert results.notebook.document is not previous
        reopened = results.notebook.document.objects[image_key]
        assert isinstance(reopened, ImageFigure)
        assert reopened.state == image_object.state
        assert reopened.title == "Reciprocal map"
        assert reopened.figure.y_units == "1/Å"
        np.testing.assert_array_equal(reopened.image, updated_result.image)
        assert results.notebook.document.objects[curve_key].figure.x_units == "pixel"
        np.testing.assert_array_equal(
            results.notebook.document.objects[curve_key].curves[0].y, curve_object.curves[0].y,
        )
        wait_until(lambda: read_editor_value(
            results.notebook.page,
            f"document.querySelector('.plot-card[data-object-id=\"{image_key}\"] .plot-title')?.value",
        ) == "Reciprocal map")
        assert not results.notebook.dirty
    finally:
        window.close()
