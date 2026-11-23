"""CodSpeed benchmarks for the image-processing backends behind the main tabs.

Run with ``pixi run bench``. Inputs are synthetic and small enough for CPU
simulation; they keep the shape of real data (rings on a decaying background,
a detector-gap mask, an off-center beam).
"""

import numpy as np
import pytest

from sciview.masking.drawing import paint_brush_segment, paint_polygon
from sciview.masking.layers import MaskLayer, compose_mask_layers
from sciview.masking.operations import close_mask_holes, sobel_edge_mask, watershed_fill_mask
from sciview.processing.batch import _deserialize_calibration
from sciview.processing.calibration_profiles import compute_calibration_profiles
from sciview.processing.reduction import ReductionBackend, ReductionRequest
from sciview.processing.transform import TransformBackend, TransformRequest

HEIGHT, WIDTH = 512, 512
BEAM_X, BEAM_Y = 256.0, 300.0


@pytest.fixture(scope="module")
def image():
    rows, cols = np.indices((HEIGHT, WIDTH))
    radius = np.hypot(cols - BEAM_X, rows - BEAM_Y)
    rings = sum(amplitude * np.exp(-(((radius - ring) / 4.0) ** 2)) for ring, amplitude in ((90, 400), (150, 200), (220, 80)))
    background = 1000.0 * np.exp(-radius / 80.0)
    noise = np.random.default_rng(0).poisson(5, (HEIGHT, WIDTH))
    return background + rings + noise


@pytest.fixture(scope="module")
def mask():
    # SciView convention: True is masked. Two detector gaps and a beamstop arm.
    data = np.zeros((HEIGHT, WIDTH), dtype=bool)
    data[:, 200:206] = True
    data[340:346, :] = True
    data[int(BEAM_Y) - 4 : int(BEAM_Y) + 4, int(BEAM_X) :] = True
    return data


def _calibration():
    # A new calibration per round, so SciAnalysis recomputes its q maps as it
    # does whenever geometry changes or a batch file is processed.
    return _deserialize_calibration(
        {
            "wavelength_A": 0.9184,
            "width": WIDTH,
            "height": HEIGHT,
            "pixel_size_um": 172.0,
            "beam_position": [BEAM_X, BEAM_Y],
            "distance_m": 0.261,
        }
    )


@pytest.mark.parametrize("operation", ["circular_average", "sector_average"])
def test_reduction(benchmark, image, mask, operation):
    def setup():
        request = ReductionRequest(
            image=image,
            operation=operation,
            center_x=BEAM_X,
            center_y=BEAM_Y,
            angle_start_deg=60.0,
            angle_end_deg=120.0,
            calibration=_calibration(),
            mask=mask,
        )
        return (request,), {}

    result = benchmark.pedantic(ReductionBackend().run, setup=setup)
    assert result.metadata["source"] == "scianalysis"
    assert np.isfinite(result.y).any()


@pytest.mark.parametrize("operation", ["q_image", "q_phi_image", "qr_qz_image"])
def test_transform(benchmark, image, mask, operation):
    def setup():
        request = TransformRequest(image=image, operation=operation, calibration=_calibration(), mask=mask)
        return (request,), {}

    result = benchmark.pedantic(TransformBackend().run, setup=setup)
    assert result.image.ndim == 2


def test_calibration_profiles(benchmark, image, mask):
    def setup():
        return (), {"image": image, "calibration": _calibration(), "mask": mask, "use_mask": True}

    profiles = benchmark.pedantic(compute_calibration_profiles, setup=setup)
    assert np.isfinite(profiles.circular.y).any()


def test_mask_watershed_fill(benchmark, image):
    filled = benchmark(watershed_fill_mask, image, (int(BEAM_Y) + 120, int(BEAM_X)), seed_radius=3)
    assert filled.any()


def test_mask_sobel_edges(benchmark, image):
    edges = benchmark(sobel_edge_mask, image, percentile=92.0, smooth_sigma=1.0)
    assert edges.any()


def test_mask_close_holes(benchmark, mask):
    closed = benchmark(close_mask_holes, mask, radius=3)
    assert closed.any()


def test_mask_paint_polygon(benchmark):
    points = [(40, 40), (60, 400), (300, 470), (480, 260), (250, 120)]

    def paint():
        target = np.zeros((HEIGHT, WIDTH), dtype=bool)
        paint_polygon(target, points, True)
        return target

    assert benchmark(paint).any()


def test_mask_paint_brush_stroke(benchmark):
    stroke = [(50, 50), (120, 300), (260, 420), (450, 380), (400, 100)]

    def paint():
        target = np.zeros((HEIGHT, WIDTH), dtype=bool)
        for start, end in zip(stroke, stroke[1:]):
            paint_brush_segment(target, start, end, 8, True)
        return target

    assert benchmark(paint).any()


def test_mask_compose_layers(benchmark, mask):
    rng = np.random.default_rng(1)
    layers = [MaskLayer(mask, "gaps")]
    layers += [
        MaskLayer(rng.random((HEIGHT, WIDTH)) > 0.99, f"hot pixels {index}", combine_mode=mode)
        for index, mode in enumerate(["OR", "OR", "AND", "OR"])
    ]
    assert benchmark(compose_mask_layers, layers).any()
