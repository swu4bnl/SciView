import numpy as np
import pytest

from sciview.core.image_collection import (
    ComparisonDisplay,
    ComparisonMode,
    ImageCollection,
    ImageReference,
    compare_image_arrays,
)


def test_collection_selection_is_ordered_lightweight_and_independent_of_active_image():
    collection = ImageCollection()
    collection.set_selection(["c.tif", "a.tif", "c.tif"])
    assert collection.selected_paths == ("c.tif", "a.tif")
    assert collection.references == []

    first = ImageReference(path="a.tif", filename="a.tif")
    second = ImageReference(path="b.tif", filename="b.tif")
    collection.add(first)
    assert collection.pin_current()
    collection.add(second)
    assert collection.references == [first, second]
    assert collection.current_reference is second
    assert collection.pinned_reference is first
    assert collection.select(0)
    assert collection.current_reference is first
    assert collection.selected_paths == ("c.tif", "a.tif")
    assert collection.pinned_path == "a.tif"
    collection.remove(0)
    assert collection.selected_paths == ("c.tif",)
    collection.clear()
    assert collection.selected_paths == ()


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (ComparisonMode.OPACITY, np.array([[2.0, 3.0], [4.0, 5.0]])),
        (ComparisonMode.ADD, np.array([[4.0, 6.0], [8.0, 10.0]])),
        (ComparisonMode.SPLIT, np.array([[1.0, 4.0], [3.0, 6.0]])),
        (ComparisonMode.DIFFERENCE, np.array([[-2.0, -2.0], [-2.0, -2.0]])),
    ],
)
def test_compare_image_arrays(mode, expected):
    reference = np.array([[1.0, 2.0], [3.0, 4.0]])
    current = reference + 2.0

    assert np.array_equal(
        compare_image_arrays(reference, current, mode),
        expected,
    )


@pytest.mark.parametrize(
    ("reference", "current"),
    [
        (np.zeros((2, 2)), np.zeros((2, 3))),
        (np.zeros((2, 2, 3)), np.zeros((2, 2, 3))),
        (np.full((2, 2), "x"), np.full((2, 2), "y")),
        (np.ones((2, 2), dtype=complex), np.ones((2, 2), dtype=complex)),
    ],
)
@pytest.mark.parametrize(
    "mode",
    [
        ComparisonMode.OPACITY,
        ComparisonMode.ADD,
        ComparisonMode.SPLIT,
        ComparisonMode.DIFFERENCE,
    ],
)
def test_numerical_comparison_rejects_incompatible_images(reference, current, mode):
    with pytest.raises(ValueError):
        compare_image_arrays(reference, current, mode)


def test_split_position_and_opacity_are_bounded():
    collection = ImageCollection()

    with pytest.raises(ValueError):
        collection.set_opacity(1.1)
    with pytest.raises(ValueError):
        collection.set_split_fraction(-0.1)


def test_comparison_display_validation():
    collection = ImageCollection()

    collection.set_comparison_display(
        ComparisonMode.ADD,
        ComparisonDisplay("viridis", "log", (1, 10)),
    )
    assert collection.comparison_displays[ComparisonMode.ADD].levels == (1.0, 10.0)
    collection.set_comparison_display(
        ComparisonMode.DIFFERENCE,
        ComparisonDisplay("coolwarm", "linear", (-2.0, 2.0)),
    )

    invalid = [
        (ComparisonMode.SPLIT, ComparisonDisplay("viridis")),
        (ComparisonMode.ADD, ComparisonDisplay("viridis", levels=(2.0, 1.0))),
        (ComparisonMode.ADD, ComparisonDisplay("viridis", levels=(0.0, float("inf")))),
        (ComparisonMode.DIFFERENCE, ComparisonDisplay("coolwarm", "log", (-1.0, 1.0))),
        (ComparisonMode.DIFFERENCE, ComparisonDisplay("coolwarm", levels=(-1.0, 2.0))),
    ]
    for mode, display in invalid:
        with pytest.raises(ValueError):
            collection.set_comparison_display(mode, display)


def test_add_mode_uses_selected_image_percentage():
    reference = np.array([[2.0, 4.0]])
    current = np.array([[8.0, 10.0]])

    result = compare_image_arrays(
        reference,
        current,
        ComparisonMode.ADD,
        current_weight=0.25,
    )

    np.testing.assert_array_equal(result, np.array([[4.0, 6.5]]))


def test_difference_subtracts_selected_image_percentage():
    collection = ImageCollection()
    collection.set_subtract_b_percentage(25)
    result = compare_image_arrays(
        np.array([[2.0, 4.0]]),
        np.array([[8.0, 10.0]]),
        ComparisonMode.DIFFERENCE,
        current_weight=collection.subtract_b_percentage / 100,
    )

    np.testing.assert_array_equal(result, np.array([[0.0, 1.5]]))
    with pytest.raises(ValueError):
        collection.set_subtract_b_percentage(101)


def test_add_percentage_is_bounded_integer():
    collection = ImageCollection()

    collection.set_add_b_percentage(35)
    assert collection.add_b_percentage == 35
    for value in (-1, 101, 25.5, True):
        with pytest.raises(ValueError):
            collection.set_add_b_percentage(value)

    with pytest.raises(ValueError):
        compare_image_arrays(
            np.ones((1, 1)),
            np.ones((1, 1)),
            ComparisonMode.ADD,
            current_weight=1.1,
        )


def test_calculated_comparison_filename_mirrors_operation_without_parsing():
    collection = ImageCollection()
    reference = np.full((2, 2), 10.0)
    current = np.full((2, 2), 4.0)

    collection.comparison_mode = ComparisonMode.DIFFERENCE
    collection.set_subtract_b_percentage(80)
    np.testing.assert_allclose(
        collection.calculate_comparison(reference, current), 10.0 - 0.8 * 4.0
    )
    assert collection.comparison_formula() == "A - B*0.80"
    assert "minus" in collection.suggest_comparison_filename("ref.tiff", "cur.tif")

    collection.comparison_mode = ComparisonMode.OPACITY
    collection.set_opacity(0.3)
    np.testing.assert_allclose(
        collection.calculate_comparison(reference, current), 10.0 * 0.7 + 4.0 * 0.3
    )

    collection.comparison_mode = ComparisonMode.ADD
    long_name = "a" * 20 + "MIDDLE" + "z" * 20 + ".tiff"
    suggestion = collection.suggest_comparison_filename(long_name, 'bad:name?.tif')
    assert suggestion.endswith(".tiff")
    assert len(suggestion) < len(long_name) + len('bad:name?.tif')
    assert not any(character in suggestion for character in '<>:"/\\|?*')

    collection.comparison_mode = ComparisonMode.SPLIT
    with pytest.raises(ValueError):
        collection.calculate_comparison(reference, current)


def test_scientific_figure_labels_use_plain_text_and_keep_legacy_source_metadata():
    from sciview.core.notebook import CurveData, FigureMetadata
    from sciview.processing.scientific_labels import (
        reduction_axis_labels, scientific_plot_title, transform_axis_labels,
    )

    for operation in ("circular_average", "sector_average", "linecut_q", "linecut_angle"):
        for calibrated in (True, False):
            for label in (*reduction_axis_labels(operation, calibrated=calibrated), scientific_plot_title(operation)):
                assert "$" not in label and "\\" not in label
    for operation in ("q_image", "q_phi_image", "qr_qz_image"):
        for label in (*transform_axis_labels(operation), scientific_plot_title(operation)):
            assert "$" not in label and "\\" not in label
    assert reduction_axis_labels("linecut_angle") == ("χ (°)", "I(χ) (a.u.)")
    assert reduction_axis_labels("circular_average") == ("q (Å⁻¹)", "I(q) (a.u.)")
    curve = CurveData(
        index=0, source="source.tif", x=np.array([1.0]), y=np.array([2.0]),
        x_label=r"$q$ ($\mathrm{\AA}^{-1}$)", y_label=r"$I(\chi)$ (a.u.)",
    )
    metadata = FigureMetadata.from_curves([curve])
    assert (metadata.x_label, metadata.x_units) == ("q", "Å⁻¹")
    assert (metadata.y_label, metadata.y_units) == ("I(χ)", "a.u.")
    assert curve.x_label == r"$q$ ($\mathrm{\AA}^{-1}$)"
    assert curve.y_label == r"$I(\chi)$ (a.u.)"
    loaded = FigureMetadata(x_label=r"$\chi$", x_units=r"$^\circ$")
    assert (loaded.x_label, loaded.x_units) == ("χ", "°")
    assert FigureMetadata.plain_label("Cost $5; custom $E=mc^2$") == "Cost $5; custom $E=mc^2$"


def test_waterfall_freezes_scientific_inputs_reports_failures_and_exports_original_curves(tmp_path, monkeypatch):
    import json
    import yaml
    from dataclasses import asdict, replace
    from threading import Event
    from types import SimpleNamespace
    from zipfile import ZipFile

    import sciview.processing.waterfall as waterfall
    from sciview.processing.reduction import ReductionRequest, ReductionResult

    monkeypatch.setattr(waterfall, "_load_scianalysis_classes", lambda: (object, object, object))
    calibration = SimpleNamespace(
        width=2, height=2, wavelength_A=1.0, pixel_size_um=172, distance_m=1.0,
        x0=1.0, y0=1.0, clear_maps=lambda: None,
    )
    mask = np.array([[True, False], [False, False]])
    template = ReductionRequest(
        image=None, operation="circular_average", center_x=1, center_y=1,
        calibration=calibration, mask=mask, q_min=0.1, q_max=1,
        metadata={"calibration_source": "From calibration tab", "mask_source": "From mask tab"},
    )
    paths = tuple(str(tmp_path / name) for name in ("first.tif", "bad.tif", "fallback.tif", "last.tif"))
    request = waterfall.snapshot_waterfall(paths, template)
    calibration.x0 = 99
    mask[:] = False
    assert request.reduction.calibration.x0 == 1
    assert request.reduction.mask[0, 0]
    assert request.reduction.image is None

    arrays = {path: np.full((2, 2), index) for index, path in enumerate(paths)}
    arrays[paths[1]] = np.ones((3, 2))
    seen = []

    class Backend:
        def run(self, req):
            seen.append(req.metadata["source_path"])
            assert req.calibration.x0 == 1
            assert req.mask[0, 0]
            assert req.image is arrays[req.metadata["source_path"]]
            return ReductionResult(
                "circular_average", np.array([0.1, 0.3]), np.array([2.0, 4.0]),
                "q", "Intensity", metadata={
                    "source": "fallback" if req.metadata["source_path"] == paths[2] else "scianalysis",
                    "y_err": [float("nan"), 1.0],
                },
            )

    run = waterfall.run_waterfall(request, load_image=arrays.__getitem__, backend=Backend())
    assert [curve.path for curve in run.curves] == list(paths)
    assert [curve.result is not None for curve in run.curves] == [True, False, False, True]
    assert "shape" in run.curves[1].error
    assert "fallback" in run.curves[2].error
    assert seen == [paths[0], paths[2], paths[3]]
    archive_path = waterfall.export_waterfall(run, tmp_path / "curves.zip")
    with ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["inputs"] == list(paths)
        assert manifest["calibration"]["beam_x"] == 1
        assert manifest["mask"]["excluded_pixels"] == 1
        assert manifest["curves"][0]["metadata"]["y_err"] == [None, 1.0]
        from io import BytesIO
        np.testing.assert_array_equal(
            np.load(BytesIO(archive.read("mask.npy")), allow_pickle=False), request.reduction.mask,
        )
        table = np.loadtxt(BytesIO(archive.read("curve_00001.csv")), delimiter=",")
        np.testing.assert_array_equal(table[:, 1], [2, 4])
        assert "curve_00002.csv" not in archive.namelist()
    original_archive = archive_path.read_bytes()
    run.request.provenance["invalid"] = object()
    with pytest.raises(TypeError):
        waterfall.export_waterfall(run, archive_path)
    assert archive_path.read_bytes() == original_archive
    assert list(tmp_path.glob("*.zip")) == [archive_path]
    del run.request.provenance["invalid"]

    from sciview.core.notebook import CurveStyle, Notebook, PlotState
    from sciview.data.notebook import load_notebook, save_notebook

    state = PlotState(
        spacing=35.0, palette="plasma", hidden_sources=[paths[3]],
        view_range=[[0.1, 0.3], [0, 10]], marks=[[0, 1]],
        width=67, height=285,
        default_line_style="dot", default_line_width=2.5,
        curve_styles={0: CurveStyle(
            color="#123456", line_style="dash_dot", line_width=3.0, gain=15.0, opacity=.4,
        )},
    )
    legacy_state = asdict(state)
    legacy_state.pop("curve_styles")
    assert PlotState(**legacy_state).curve_styles == {}
    plot = waterfall.notebook_waterfall(run, state, "First finding")
    assert plot.figure.x_label == "q"
    assert plot.figure.x_units == "Å⁻¹"
    assert plot.figure.show_legend
    plot.figure.y_label = "Scattered intensity"
    plot.figure.y_units = "a.u."
    plot.figure.legend_names[0] = "Before heating"
    plot.preview = b"preview"
    notebook = Notebook()
    notebook.add_object(plot)
    notebook.markdown = f'# Findings\n\n![First finding](plot.png "sciview:{plot.id}")\n\n**Observation**\n'
    saved = save_notebook(notebook, tmp_path / "measurement notes.md")
    restored = load_notebook(saved)
    recovered = restored.objects[plot.id]
    assert recovered.figure == plot.figure
    clean_signature = restored.content_signature()
    recovered.state.selected_index = 0
    recovered.preview = b"responsive-preview"
    assert restored.content_signature() == clean_signature
    recovered.figure.legend_names[0] = "After heating"
    assert restored.content_signature() != clean_signature
    recovered.figure.legend_names[0] = "Before heating"
    assert restored.content_signature() == clean_signature
    recovered.state.selected_index = None
    for invalid_metadata in (
        replace(plot.figure, legend_names={9: "Unknown"}),
        replace(plot.figure, x_units="unit\nline"),
    ):
        with pytest.raises(ValueError):
            invalid_metadata.validate(plot.curves)
    restored_run = waterfall.notebook_waterfall_run(recovered)
    assert "**Observation**" in restored.markdown
    assert recovered.state == state
    for invalid_width in (49, 101, 67.5):
        with pytest.raises(ValueError, match="dimensions"):
            replace(state, width=invalid_width).validate(plot.curves)
    assert recovered.state.curve_styles[0] == CurveStyle(
        color="#123456", line_style="dash_dot", line_width=3.0, gain=15.0, opacity=.4,
    )
    assert recovered.state.resolved_curve_style(2, 1).line_style == "dot"
    assert recovered.state.resolved_curve_style(2, 1).line_width == 2.5
    assert recovered.state.resolved_curve_style(0, 1).line_width == 3.0
    assert 2 not in recovered.state.curve_styles
    for opacity in (-.1, 1.1, np.nan):
        with pytest.raises(ValueError, match="opacity"):
            CurveStyle(opacity=opacity).validate()
    for invalid_value in (-1, np.inf):
        with pytest.raises(ValueError):
            CurveStyle(gain=invalid_value).validate()
        with pytest.raises(ValueError):
            replace(state, spacing=invalid_value).validate(plot.curves)
    assert PlotState(**{
        key: value for key, value in legacy_state.items()
        if key not in {"default_line_style", "default_line_width"}
    }).resolved_curve_style(0, 2).line_style == "solid"
    assert recovered.sources == list(paths)
    assert recovered.curves[1].error == run.curves[1].error
    assert recovered.curves[0].metadata["y_err"][1] == 1
    assert np.isnan(recovered.curves[0].metadata["y_err"][0])
    assert recovered.provenance == run.request.provenance
    np.testing.assert_array_equal(recovered.mask, request.reduction.mask)
    np.testing.assert_array_equal(restored_run.curves[0].result.y, [2, 4])
    header = yaml.safe_load(saved.read_text(encoding="utf-8").split("---\n")[1])
    manifest_path = saved.parent / header["sciview"]["manifest"]
    legacy_manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    del legacy_manifest["objects"][plot.id]["figure"]
    manifest_path.write_text(yaml.safe_dump(legacy_manifest), encoding="utf-8")
    legacy_plot = load_notebook(saved).objects[plot.id]
    assert legacy_plot.figure.x_label == "q"
    assert legacy_plot.figure.x_units == "Å⁻¹"
    assert legacy_plot.figure.y_label == "Intensity"
    assert legacy_plot.figure.legend_names == {}
    assert legacy_plot.figure.show_legend
    original_document = saved.read_bytes()
    plot.provenance["invalid"] = object()
    with pytest.raises(yaml.representer.RepresenterError):
        save_notebook(notebook, saved)
    assert saved.read_bytes() == original_document
    assert len(list((tmp_path / "measurement notes.assets").iterdir())) == 1
    del plot.provenance["invalid"]

    stop = Event()
    partial = waterfall.run_waterfall(
        request, load_image=arrays.__getitem__, backend=Backend(), cancelled=stop.is_set,
        on_curve=lambda _curve: stop.set(),
    )
    assert partial.cancelled
    assert len(partial.curves) == 1
    for invalid in (
        replace(template, operation="linecut_q"),
        replace(template, calibration=None),
        replace(template, mask=np.ones((3, 3))),
    ):
        with pytest.raises(waterfall.WaterfallInputError):
            waterfall.snapshot_waterfall(paths, invalid)
