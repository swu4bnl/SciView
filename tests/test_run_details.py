import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
import numpy as np

from sciview.sources.run_details import read_scalar_columns, read_configuration, scalar_points


class Node(dict):
    def __init__(self, *args, metadata=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.metadata = metadata or {}


class Array:
    def __init__(self, data): self.data = np.asarray(data)
    def structure(self): return SimpleNamespace(shape=self.data.shape)
    def read(self):
        assert self.data.ndim <= 1, "Detector/config image arrays must not be read"
        return self.data


def test_scalar_baseline_and_configuration_without_image_reads():
    run = Node(primary=Node({"data": Node(det_image=Array(np.zeros((4, 8, 9))),
                    seq_num=Array([2, 1]), energy=Array([2500., 2400.])),
                    "config": Node(detector=Node(gain=Array([1]), image=Array(np.zeros((20, 30)))))},
                    metadata={"configuration": {"detector": {"data": {"offset": 12}}}}),
               baseline=Node(seq_num=Array([1, 2]), motor=Array([5., 6.])))
    columns = read_scalar_columns(run, "primary")
    np.testing.assert_array_equal(columns["energy"], [2400, 2500])
    assert "det_image" not in columns
    baseline = read_scalar_columns(run, "baseline")
    np.testing.assert_array_equal(baseline["motor"], [5, 6])
    config = read_configuration(run, "primary")
    assert config["configuration"]["detector"]["data"]["offset"] == 12
    assert config["config_nodes"]["children"]["detector"]["children"]["image"]["shape"] == [20, 30]


def test_stream_metadata_configuration_fallback():
    run = {"primary": Node(metadata={"configuration": {"device": {"data": {"gain": 2}}}})}
    assert read_configuration(run, "primary")["device"]["data"]["gain"] == 2


def test_scalar_point_mapping_keeps_duplicates_and_drops_nan():
    arrays, indices = scalar_points({"x": [2, 1, 1, np.nan], "y": [0, 1, 1, 2], "z": [3, 4, 5, 6]}, "x", "y", "z")
    np.testing.assert_array_equal(indices, [0, 1, 2])
    np.testing.assert_array_equal(arrays[2], [3, 4, 5])


def test_native_scalar_plot_and_detector_panel(monkeypatch):
    from PyQt5.QtWidgets import QApplication
    from main import SciAnaApp
    from tabs.tiled_browser_tab import TiledBrowserTab
    from sciview.sources.tiled_source import TiledScanSummary
    app = QApplication.instance() or QApplication([])
    window = SciAnaApp(); tab = TiledBrowserTab(window)
    tab.smi_search.activation_timer.stop()
    tab.scan_rows = [TiledScanSummary("one", 1, detectors=["a_image"]),
                     TiledScanSummary("two", 2, detectors=["a_image", "b_image"])]
    tab._populate_scan_table()
    assert tab.scan_table.cellWidget(0, 1) is None
    assert tab.scan_table.item(1, 1).text() == "a_image, b_image"
    tab._set_panel_detectors(["a_image"])
    assert not tab.detector_select.isEnabled()
    tab._set_panel_detectors(["a_image", "b_image"])
    assert tab.detector_select.isEnabled()
    assert tab.compare_select.findData("b_image") >= 0
    explorer = tab.run_explorer
    explorer.use_columns("primary", ["primary", "arc20"], {"x": np.array([2., 1., 1.]), "y": np.array([4., 5., 6.])})
    explorer.populate_scalars()
    explorer.x.setCurrentText("x"); explorer.y.setCurrentText("y")
    assert len(explorer.scatter.points()) == 3
    frames = []
    explorer.frame_selected.connect(lambda stream, index: frames.append((stream, index)))
    explorer.point_clicked(None, [explorer.scatter.points()[2]])
    assert frames == [("primary", 2)]
    explorer.mode.setCurrentIndex(1); explorer.z.setCurrentText("y")
    assert len(explorer.scatter.points()) == 3
    tab.close(); window.close()


def test_baseline_rows_preserve_samples_and_changes():
    from sciview.interfaces.stable_qt.widgets.metadata_view import baseline_rows
    rows = baseline_rows({"motor": [1., 2., 3.], "state": [b"pin", b"rod"],
                          "constant": [np.nan, np.nan], "single": [0]})
    assert rows[0][0] == ["motor", "1.0", "3.0", "2.0", "Yes", 3]
    assert rows[0][1]["samples"] == [1., 2., 3.]
    assert rows[1][0][1:3] == ["pin", "rod"]
    assert rows[2][2] is False
    assert rows[3][0][2] == ""  # no fabricated after sample


def test_configuration_table_preserves_device_units_and_paths():
    from sciview.interfaces.stable_qt.widgets.metadata_view import configuration_rows
    rows = configuration_rows({"detector": {"data": {"distance": 2.4},
        "data_keys": {"distance": {"units": "m", "source": "PV:SDD", "dtype": "number"}},
        "timestamps": {"distance": 123}}})
    assert rows[0][0] == ["detector", "distance", "2.4", "m", "PV:SDD", "number", "configuration.detector.data.distance"]
    assert rows[1][0][-1] == "configuration.detector.timestamps.distance"


def test_structured_metadata_search_and_table_filters():
    from PyQt5.QtWidgets import QApplication
    from sciview.interfaces.stable_qt.widgets.metadata_view import MetadataView
    app = QApplication.instance() or QApplication([])
    view = MetadataView()
    view.set_document("Run metadata", {"start": {"sample": "AgB", "nested": {"energy": 16000}}, "stop": {"status": "success"}})
    view.search.setText("energy")
    assert view.proxy.rowCount() == 1
    parent = view.proxy.index(0, 0)
    assert parent.data() == "start"
    assert view.proxy.index(0, 0, parent).data() == "nested"
    assert view.tree.isExpanded(parent)
    view.search.clear(); view.collapse.click()
    assert not view.tree.isExpanded(view.proxy.index(0, 0))
    view.set_document("Baseline", {"motor": [1, 3], "constant": [4, 4], "one": [2]})
    view.changed.setChecked(True)
    assert view.proxy.rowCount() == 1
    assert view.proxy.index(0, 0).data() == "motor"
    view.search.setText("constant")
    assert view.proxy.rowCount() == 0
    view.changed.setChecked(False)
    assert view.proxy.rowCount() == 1
    view.set_document("Configuration", {"det": {"data": {"gain": 7}}})
    view.search.setText("gain")
    assert view.proxy.rowCount() == 1
    view.table.setCurrentIndex(view.proxy.index(0, 0))
    assert '"gain"' in view.detail.toPlainText()
    view.close()
