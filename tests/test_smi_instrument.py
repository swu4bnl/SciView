import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
import numpy as np
import pytest

pytest.importorskip("smi_tiled")
from sciview.processing.smi_geometry import (
    GeometrySnapshot, exclusion_polygons, compose_mask_spec, fit_ring_points,
    generated_masks, q_map, AGB_Q1,
)


def snapshot(kind="saxs", shape=(150, 170)):
    return GeometrySnapshot("uid", kind, shape, 0, 70., 80., 1000., 16000., .172,
                            0., 0., 0., (0, 0, 0), {},
                            SimpleNamespace(active_beamstop="pin", beamstop_pos_mm={}))


def test_raster_polygon_roundtrip_is_exact_including_holes_and_edges():
    from smi_tiled.integrator import polygons_to_mask
    rng = np.random.default_rng(14)
    masks = [rng.random((21, 34))>.7, np.eye(12, dtype=bool), np.ones((5, 7), bool)]
    hole = np.ones((10, 10), bool); hole[3:7, 3:7] = False; masks.append(hole)
    for mask in masks:
        valid = polygons_to_mask(mask.shape, exclusion_polygons(mask))
        np.testing.assert_array_equal(valid, ~mask)


def test_composed_spec_preserves_dynamic_beamstop_and_waxs_orientation():
    from smi_tiled.integrator import make_waxs_mask_callable_from_dict
    base = {"static_regions": {"gap": [[1, 1], [2, 1], [2, 5], [1, 5]]},
            "beamstops": {"beamstop": {"polygons": [[[4, 1], [6, 1], [6, 3], [4, 3]]]}},
            "custom_provenance": {"keep": True}}
    user = np.zeros((11, 17), bool); user[8, 14] = True
    combined = compose_mask_spec(base, user, "waxs")
    assert combined["beamstops"] == base["beamstops"]
    assert combined["custom_provenance"] == base["custom_provenance"]
    assert len(base["static_regions"]) == 1
    original_fn = make_waxs_mask_callable_from_dict(base)
    combined_fn = make_waxs_mask_callable_from_dict(combined)
    for angle, bsx in ((0., 0.), (0., .3), (20., 0.)):
        original, actual = original_fn(user.shape, angle, bsx), combined_fn(user.shape, angle, bsx)
        np.testing.assert_array_equal(actual, original & ~user.T)
    assert not combined_fn(user.shape, 20, 0).T[8, 14]


def test_saxs_beam_relative_mask_spec_is_not_flattened():
    from smi_tiled.integrator import make_saxs_mask_from_dict
    base = {"static_regions": {}, "beamstops": {"pin": {
        "polygon_offsets_from_beam": [[-1,-1],[1,-1],[1,1],[-1,1]], "reference_mm": {"x": 2}}}}
    user = np.zeros((10, 12), bool); user[0, 0] = True
    spec = compose_mask_spec(base, user, "saxs")
    for center in ((4, 5), (6, 8)):
        original = make_saxs_mask_from_dict(user.shape, base, "pin", beam_center_px=center)
        actual = make_saxs_mask_from_dict(user.shape, spec, "pin", beam_center_px=center)
        np.testing.assert_array_equal(actual, original & ~user)


def test_known_ring_recovers_metadata_relative_center_and_distance():
    reference = snapshot()
    truth = reference.corrected((3., -2., 15.))
    q = .6
    angle = 2*np.arcsin(q*(1239.84198/truth.energy_ev)/(4*np.pi))
    radius = truth.distance_mm*np.tan(angle)/truth.pixel_mm
    phi = np.linspace(0, 2*np.pi, 20, endpoint=False)
    points = np.column_stack([truth.col+radius*np.cos(phi), truth.row+radius*np.sin(phi)])
    result = fit_ring_points(reference, points, q, fit_distance=True)
    np.testing.assert_allclose(result["delta"], [3, -2, 15], atol=.001)
    assert result["rms"] < 1e-6
    # With unknown q, center can still be recovered while distance remains fixed.
    center_only = fit_ring_points(reference, points)
    np.testing.assert_allclose(center_only["delta"], [3, -2, 0], atol=.001)


def test_waxs_q_map_matches_native_backend_transpose():
    from smi_tiled.integrator import WAXSCalibration, MultiPanelArcDetector
    reference = snapshot("waxs", (619, 1475))
    cal = WAXSCalibration(energy_kev=16., beam_center_row=70., beam_center_col=80., sample_distance_mm=1000., beam_col_per_arc_deg=.08)
    detector = MultiPanelArcDetector(reference.shape[::-1], cal.make_panel_specs(), cal.wavelength_nm,
        sample_distance_mm=1000., beam_center_px=cal.beam_center_at_angle(0))
    np.testing.assert_allclose(q_map(reference), detector.qmap(0).qabs.values.T)


def test_native_tabs_keep_user_layers_and_apply_relative_corrections():
    from PyQt5.QtWidgets import QApplication
    from main import SciAnaApp
    from tabs.smi_instrument_tabs import SmiMaskTab, SmiCalibrationTab
    from sciview.interfaces.services.smi_instrument import SmiInstrumentController
    app = QApplication.instance() or QApplication([])
    window = SciAnaApp(); controller = SmiInstrumentController(window)
    masks = SmiMaskTab(window, controller); cal = SmiCalibrationTab(window, controller)
    reference = snapshot()
    payload = dict(array=np.ones(reference.shape), reference=reference, geometry=reference,
                   static=np.zeros(reference.shape, bool), dynamic=np.zeros(reference.shape, bool))
    masks.set_frame(payload); cal.set_frame(payload)
    masks.mask_layers[0].data[12, 17] = True
    masks._update_combined_mask()
    masks.set_frame(payload)
    assert masks.mask_layers[0].data[12, 17]
    assert controller.user_masks[("saxs", reference.shape)][12, 17]
    cal.spin_x.setValue(reference.col+2)
    cal.spin_y.setValue(reference.row-3)
    cal.apply_correction()
    np.testing.assert_allclose(controller.corrections["saxs"], [-3, 2, 0])
    cal.fit_job.close(); controller.close(); masks.close(); cal.close(); window.close()


def test_multi_ring_fit_and_session_roundtrip(tmp_path):
    from PyQt5.QtWidgets import QApplication
    from sciview.interfaces.services.smi_instrument import SmiInstrumentController
    from tabs.mask_tab import MaskLayer
    reference = snapshot(shape=(300, 340))
    truth = reference.corrected((2, -3, 12))
    points, targets = [], []
    for q in (.5, 1.):
        theta = 2*np.arcsin(q*(1239.84198/truth.energy_ev)/(4*np.pi))
        radius = truth.distance_mm*np.tan(theta)/truth.pixel_mm
        phi = np.linspace(-.3, 1.8, 15)
        points.extend(np.column_stack([truth.col+radius*np.cos(phi), truth.row+radius*np.sin(phi)]))
        targets.extend([q]*len(phi))
    fit = fit_ring_points(reference, points, targets, fit_distance=True)
    np.testing.assert_allclose(fit["delta"], [2, -3, 12], atol=.01)
    app = QApplication.instance() or QApplication([])
    controller = SmiInstrumentController()
    controller.corrections["saxs"] = (2, -3, 12)
    mask = np.eye(6, dtype=bool)
    controller.user_masks[("saxs", mask.shape)] = mask
    controller.layers[("saxs", mask.shape)] = [MaskLayer(mask, "brush marks")]
    path = tmp_path / "session.h5"
    controller.save_session(path)
    controller.corrections.clear(); controller.user_masks.clear(); controller.layers.clear()
    controller.load_session(path)
    assert controller.corrections["saxs"] == [2, -3, 12]
    np.testing.assert_array_equal(controller.user_masks[("saxs", mask.shape)], mask)
    assert controller.layers[("saxs", mask.shape)][0].name == "brush marks"
    controller.close()


def test_user_masks_reach_backend_call_without_losing_beamstop(tmp_path):
    from sciview.processing.smi_reduction import SmiReductionRequest
    from smi_tiled.integrator import make_waxs_mask_callable_from_dict
    mask = np.zeros((11, 17), bool); mask[8, 14] = True
    path = tmp_path / "user.npy"; np.save(path, mask)
    base = {"gap": [[1, 1], [2, 1], [2, 3], [1, 3]], "beamstop": [[4, 1], [6, 1], [6, 3], [4, 3]]}
    request = SmiReductionRequest("uid", user_mask_files={"waxs": str(path)}, base_mask_specs={"waxs": base})
    _, kwargs = request.backend_call(tmp_path)
    assert kwargs["waxs_mask"]["beamstop"] == base["beamstop"]
    fn = make_waxs_mask_callable_from_dict(kwargs["waxs_mask"])
    assert not fn(mask.shape, 20, 0).T[8, 14]


def test_intensity_refinement_moves_picks_to_ring_without_masked_pixels():
    from sciview.processing.smi_geometry import refine_ring_pixels
    reference = snapshot()
    rows, cols = np.indices(reference.shape)
    radius = 30.
    radial = np.hypot(cols-reference.col, rows-reference.row)
    image = 1 + 100*np.exp(-.5*((radial-radius)/.7)**2)
    phi = np.linspace(0, 2*np.pi, 12, endpoint=False)
    seeds = np.column_stack([reference.col+(radius+2)*np.cos(phi), reference.row+(radius+2)*np.sin(phi)])
    refined = np.asarray(refine_ring_pixels(image, reference, seeds))
    distances = np.hypot(refined[:, 0]-reference.col, refined[:, 1]-reference.row)
    np.testing.assert_allclose(distances, radius, atol=.4)
