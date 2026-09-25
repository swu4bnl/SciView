import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import numpy as np
import pytest
from PyQt5.QtWidgets import QApplication
from sciview.processing.frame_labels import frame_label, waterfall_values


def test_labels_and_log_waterfall_do_not_change_scientific_values():
    intensity = np.array([[1., 10.], [2., 20.]])
    original = intensity.copy()
    display = waterfall_values([1, 2], intensity, spacing=.5, logarithmic=True)
    np.testing.assert_allclose(display, [[0, 1], [np.log10(2)+.5, np.log10(20)+.5]])
    np.testing.assert_array_equal(intensity, original)
    assert frame_label(1, "energy_energy", {"energy_energy": [2400, 2500]}) == "Frame 1 · energy_energy=2500 eV"
    assert frame_label(2, "missing", {}) == "Frame 2"
    assert "sample" in frame_label(0, "name", {"name": [b"sample"]})


def test_appearance_preferences_roundtrip_and_contrast(tmp_path, monkeypatch):
    from PyQt5.QtCore import QSettings
    from PyQt5.QtGui import QColor
    from sciview.interfaces.theme import appearance
    from sciview.interfaces.theme.app_style import AppStyle
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "appearance.ini"), QSettings.IniFormat)
    settings.setValue("scale_percent", 175); settings.setValue("text_mode", "contrast")
    monkeypatch.setattr(appearance, "preferences", lambda: settings)
    old_fonts = dict(AppStyle.FONTS)
    old_mode = app.property("sciview_text_mode")
    old_custom = app.property("sciview_custom_text")
    try:
        appearance.load_appearance(app)
        assert AppStyle.font_px("body") == 19
        assert appearance.text_color(app, QColor("gray"), QColor("white")).name() == "#101010"
        assert appearance.text_color(app, QColor("gray"), QColor("black")).name() == "#ffffff"
        settings.setValue("text_mode", "custom"); settings.setValue("custom_text", "#123456")
        appearance.load_appearance(app)
        assert appearance.text_color(app, QColor("gray"), QColor("white")).name() == "#123456"
    finally:
        AppStyle.FONTS = old_fonts
        app.setProperty("sciview_text_mode", old_mode); app.setProperty("sciview_custom_text", old_custom)


def test_waterfall_default_map_slider_and_signal_labels(tmp_path):
    pytest.importorskip("smi_tiled")
    from test_smi_reduction import make_result
    from sciview.processing.smi_reduction import save_reduction, SmiReductionRequest, describe_result
    from sciview.interfaces.services.smi_processing import SmiProcessingController
    from tabs.smi_processing_tab import SmiReductionTab, SmiTransformTab
    app = QApplication.instance() or QApplication([])
    controller = SmiProcessingController()
    reduction = SmiReductionTab(None, controller); transform = SmiTransformTab(None, controller)
    path = save_reduction(make_result(), SmiReductionRequest("uid"), tmp_path / "result.h5")
    result = describe_result(path)
    reduction.result_changed(result); transform.result_changed(result)
    reduction.label_signal.setCurrentText("energy_energy")
    reduction.mode.setCurrentIndex(1)
    transform.product.setCurrentText("saxs_frames")
    transform.label_signal.setCurrentText("energy_energy")
    transform.frame_slider.setValue(1)
    deadline = time.monotonic()+10
    while (len(reduction._waterfall_lines) != 2 or transform._loaded_map is None or transform._loaded_map[2] != 1) and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert reduction.presentation.currentText() == "Waterfall"
    assert len(reduction._waterfall_lines) == 2
    assert not reduction.frame.isEnabled()
    assert transform.frame.value() == transform.frame_slider.value() == 1
    assert "energy_energy=2500 eV" in transform.frame_label.text()
    # Applying theme must preserve scientific traces and map pixels.
    reduction.refresh_theme(); transform.refresh_theme()
    assert len(reduction._waterfall_lines) == 2
    reduction.io.close(); transform.io.close(); controller.close()
    reduction.close(); transform.close()
