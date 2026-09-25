import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pytest
from PyQt5.QtWidgets import QApplication


def test_smi_controls_construct_and_preserve_cms_default():
    from main import SciAnaApp
    from tabs.tiled_browser_tab import TiledBrowserTab
    app = QApplication.instance() or QApplication([])
    window = SciAnaApp()
    tab = TiledBrowserTab(window)
    assert tab.catalog_combo.findData("smi_migration") >= 0
    tab.catalog_combo.setCurrentIndex(tab.catalog_combo.findData("smi_migration"))
    assert tab.measure_type_input.text() == ""
    assert tab.smi_controls.active()
    tab.catalog_combo.setCurrentIndex(tab.catalog_combo.findData("cms_raw"))
    assert tab.measure_type_input.text() == "measure"
    tab.close(); window.close()


def test_cached_peak_ui_and_composite(tmp_path):
    pytest.importorskip("smi_tiled")
    import h5py
    from main import SciAnaApp
    from tabs.smi_peak_tab import SmiPeakTab
    from sciview.processing.smi_cache import read_profiles
    app = QApplication.instance() or QApplication([])
    window = SciAnaApp(); tab = SmiPeakTab(window)
    q = np.linspace(1, 3, 100)
    path = tmp_path / "uid.h5"
    with h5py.File(path, "w") as f:
        f.create_dataset("reduction/pf_iq_I", data=np.ones((4, 100)))
        f.create_dataset("reduction/pf_iq_q", data=q)
    tab.loaded(read_profiles(path)); tab.add_peak()
    peak = tab.peaks()[0]
    tab.profiles.fits[peak.key()] = {"area": np.arange(4, dtype=float)}
    tab.render_map()
    assert len(tab.scatter.points()) == 4
    tab.mode.setCurrentIndex(1)
    assert len(tab.scatter.points()) == 4
    tab.select_frame(2, navigate=False)
    assert tab.frame.value() == 2
    tab.shutdown(); tab.close(); window.close()


def test_axis_order_keeps_acquisition_identity_and_duplicates():
    from main import SciAnaApp
    from tabs.tiled_browser_tab import TiledBrowserTab
    from sciview.sources.frame_source import FrameSequence, FrameRef
    app = QApplication.instance() or QApplication([])
    window = SciAnaApp(); tab = TiledBrowserTab(window)
    tab.catalog_combo.setCurrentIndex(tab.catalog_combo.findData("smi_migration"))
    controls = tab.smi_controls
    controls.sequence = FrameSequence("smi_migration", "u", "primary", {"det_image": (3, 4, 5)},
                                     {"energy_energy": np.array([2500., 2400., 2400.])}, ["primary"])
    controls._guard = True
    controls.detector.addItem("det_image"); controls._populate_axes()
    controls._guard = False
    controls._show(FrameRef("smi_migration", "u", "primary", "det_image", 2), np.ones((4, 5)))
    controls.axis.setCurrentText("energy_energy")
    assert list(controls.order) == [1, 2, 0]
    assert controls.index.value() == 2
    assert tab.frame_slider.value() == 1
    assert "occurrence 2/2" in tab.frame_label.text()
    tab.close(); window.close()
