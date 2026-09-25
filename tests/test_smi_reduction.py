import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
import numpy as np
import pytest

pytest.importorskip("smi_tiled")
import xarray as xr
import h5py

from sciview.processing.smi_reduction import (
    SmiReductionRequest, save_reduction, describe_result, read_curves, read_map,
)


def make_result():
    q, chi = np.linspace(1, 3, 5), np.linspace(-90, 90, 3)
    iq = xr.Dataset({"I": ("q", np.arange(5.)+1), "saxs_I": ("q", np.ones(5))}, coords={"q": q})
    pf = xr.Dataset({"I": (("frame", "q"), np.ones((2, 5))),
                     "energy_energy": ("frame", [2400., 2500.])}, coords={"q": q, "frame": [0, 1]})
    image = np.arange(15.).reshape(5, 3)
    qchi = xr.Dataset({"intensity": (("q", "chi"), image)}, coords={"q": q, "chi": chi})
    frames = xr.Dataset({"intensity": (("q", "chi", "frame"), np.stack([image, image+10], axis=2))},
                        coords={"q": q, "chi": chi, "frame": [0, 1]})
    return SimpleNamespace(merged_iq=iq, per_frame_iq=pf, merged_qchi=qchi,
        saxs={"q_chi_frames": frames}, waxs=None, reduction_parameters={"energy": 2400}, timing={})


def test_request_uses_metadata_defaults_and_bypasses_partial_caches(tmp_path):
    request = SmiReductionRequest("uid")
    name, kwargs = request.backend_call(tmp_path)
    assert name == "reduce_smi_combined"
    assert kwargs["image_cache_path"] is None
    assert kwargs["populate_disk_cache"] is False
    assert "saxs_beam_delta_px" not in kwargs
    assert kwargs["build_detector_ds"] is False
    override = SmiReductionRequest("uid", saxs_beam_delta=(0, 0), saxs_distance_delta=0)
    assert override.backend_call(tmp_path)[1]["saxs_beam_delta_px"] == (0, 0)
    assert override.backend_call(tmp_path)[1]["saxs_distance_delta_mm"] == 0
    with pytest.raises(ValueError, match="primary only"):
        SmiReductionRequest("uid", stream="arc20").backend_call(tmp_path)


def test_transmission_storage_uses_named_dimensions_and_peak_handoff(tmp_path):
    from sciview.processing.smi_cache import read_profiles
    result = make_result()
    path = save_reduction(result, SmiReductionRequest("real-uid"), tmp_path / "result.h5")
    desc = describe_result(path)
    assert desc["uid"] == "real-uid" and desc["frames"] == 2
    x, y, image, xlabel, ylabel = read_map(path, "saxs_frames", 1)
    np.testing.assert_array_equal(image, np.arange(15.).reshape(5, 3).T+10)
    assert image.shape == (len(y), len(x))
    assert xlabel == "q (nm⁻¹)" and ylabel == "χ (°)"
    q, curves = read_curves(path)
    np.testing.assert_array_equal(curves["Merged"], result.merged_iq.I.values)
    profiles = read_profiles(path)
    assert profiles.uid == "real-uid"  # not 'result' filename
    np.testing.assert_array_equal(profiles.axes["energy_energy"], [2400, 2500])
    assert desc["provenance"]["resolved"] == {"energy": 2400}


def test_cancelled_storage_never_publishes_or_overwrites(tmp_path):
    path = tmp_path / "result.h5"
    path.write_bytes(b"previous complete result")
    with pytest.raises(InterruptedError):
        save_reduction(make_result(), SmiReductionRequest("uid"), path, cancel=lambda: True)
    assert path.read_bytes() == b"previous complete result"
    assert not path.with_suffix(".partial.h5").exists()


def test_gi_axes_and_scope(tmp_path):
    qxy, qz = np.linspace(-1, 1, 4), np.linspace(0, 2, 3)
    image = np.arange(12.).reshape(4, 3)
    frames = xr.Dataset({"intensity": (("frame", "qxy", "qz"), image[None])}, coords={"frame": [0], "qxy": qxy, "qz": qz})
    result = SimpleNamespace(summed=image, qxy_grid=qxy, qz_grid=qz, q_chi_frames=frames)
    request = SmiReductionRequest("uid", geometry="grazing", incident_angle=.5)
    name, kwargs = request.backend_call(tmp_path)
    assert name == "reduce_smi_gi" and kwargs["incident_angle_deg"] == .5
    assert "solid_angle_correction" not in kwargs
    path = save_reduction(result, request, tmp_path / "result.h5")
    np.testing.assert_array_equal(read_map(path, "gi_merged")[2], image.T)
    assert not describe_result(path)["has_profiles"]


def test_qt_processing_views_switch_and_ignore_stale_result(tmp_path):
    from PyQt5.QtWidgets import QApplication
    from main import SciAnaApp
    from tabs.reduction_tab import ReductionTab
    from tabs.smi_processing_tab import BackendTab, SmiReductionTab, SmiTransformTab
    from sciview.interfaces.services.smi_processing import SmiProcessingController
    from sciview.sources.frame_source import FrameRef
    app = QApplication.instance() or QApplication([])
    window = SciAnaApp()
    controller = window.smi_processing = SmiProcessingController(window)
    cms = ReductionTab(window)
    view = SmiReductionTab(window, controller)
    host = BackendTab(cms, view)
    window.add_tab(host, "Reduction")
    transform = SmiTransformTab(window, controller)
    window.publish_frame_context(FrameRef("smi_migration", "uid", "primary", "pil2M_image", 0))
    assert host.currentWidget() is view and view.run_button.isEnabled()
    window.publish_frame_context(FrameRef("smi_migration", "uid", "arc20", "pil900KW_image", 0))
    assert not view.run_button.isEnabled()
    window.publish_shared_image(np.ones((10, 10)))
    assert host.currentWidget() is cms
    assert cms.image_data.shape == (10, 10)
    controller.close(); view.io.close(); transform.io.close(); window.close()


def test_controller_rejects_result_after_selection_changes(tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QApplication
    from sciview.interfaces.services.smi_processing import SmiProcessingController
    from sciview.sources.frame_source import FrameRef
    app = QApplication.instance() or QApplication([])
    controller = SmiProcessingController()
    controller.set_context(FrameRef("smi_migration", "one", "primary", "det", 0))
    callbacks = []
    monkeypatch.setattr(controller.io, "submit", lambda work, apply, error: callbacks.append(apply))
    controller.open_result("unused.h5")
    controller.set_context(FrameRef("smi_migration", "two", "primary", "det", 0))
    callbacks[0]({"uid": "one"})
    assert controller.result is None
    controller.close()


def test_cancel_process_does_not_publish_result(tmp_path):
    import sys
    import time
    from PyQt5.QtCore import QProcess
    from PyQt5.QtWidgets import QApplication
    from sciview.interfaces.services.smi_processing import SmiProcessingController
    app = QApplication.instance() or QApplication([])
    controller = SmiProcessingController()
    controller.directory = tmp_path
    controller.job_uid = "uid"
    controller.process = QProcess(controller)
    controller.process.finished.connect(controller._finished)
    controller.process.start(sys.executable, ["-c", "import time; time.sleep(60)"])
    assert controller.process.waitForStarted(5000)
    controller.cancel()
    assert (tmp_path / "cancel").exists()
    controller._kill_timer.start(10)
    deadline = time.monotonic()+5
    while controller.busy and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert not controller.busy
    assert controller.result is None
    controller.close()


def test_new_execution_revision_with_same_recipe(tmp_path):
    request = SmiReductionRequest("uid")
    a = save_reduction(make_result(), request, tmp_path / "a.h5", backend_kwargs={"frame_qchi_store": "/job/a"})
    b = save_reduction(make_result(), request, tmp_path / "b.h5", backend_kwargs={"frame_qchi_store": "/job/b"})
    assert describe_result(a)["provenance"]["recipe_fingerprint"] == describe_result(b)["provenance"]["recipe_fingerprint"]
    with h5py.File(a) as fa, h5py.File(b) as fb:
        assert fa["reduction"].attrs["_revision"] != fb["reduction"].attrs["_revision"]
