import sys
import os
import numpy as np

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QFileDialog,
    QDoubleSpinBox,
    QLineEdit,
    QComboBox
)
from PyQt5.QtCore import Qt

import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar
)

# Physical constant: hc/e in eV·Å
HC_E = 12398.425

# Ensure SciAnalysis is on the path
SCIANALYSIS_PATH = os.getenv(
    'SCIANA_PATH',
    # 'C:/Users/dimo1/GitHub/SciAnalysis/'
    '/Users/siyuwu/Documents/GitHub/SciAnalysis'
)
if SCIANALYSIS_PATH not in sys.path:
    sys.path.append(SCIANALYSIS_PATH)

from SciAnalysis.XSAnalysis.Data import Data2DScattering
from SciAnalysis.XSAnalysis.DataRQconv import CalibrationRQconv


class CalibrationApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SciAnalysis Detector Calibration GUI")
        self.image_data = None
        self.status = self.statusBar()

        # Calibration defaults
        self.calibration = CalibrationRQconv(wavelength_A=0.9184)
        self.calibration.set_pixel_size(pixel_size_um=172.0)
        self.calibration.set_distance(0.261)

        self._build_ui()

    def _build_ui(self):
        # Main container
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setStretch(0, 3)
        main_layout.setStretch(1, 2)

        # Left panel: Raw image + controls
        left_panel = QVBoxLayout()
        self.fig_raw, self.ax_raw = plt.subplots(figsize=(6, 6))
        self.canvas_raw = FigureCanvas(self.fig_raw)
        left_panel.addWidget(self.canvas_raw)
        left_panel.addWidget(NavigationToolbar(self.canvas_raw, self))

        # Image contrast & scale controls
        img_ctrl = QHBoxLayout()

        img_ctrl.addWidget(QLabel("vmin:"))
        self.vmin_input = QLineEdit("0")
        self.vmin_input.setFixedWidth(60)
        self.vmin_input.editingFinished.connect(self.update_plot)
        img_ctrl.addWidget(self.vmin_input)

        img_ctrl.addWidget(QLabel("vmax:"))
        self.vmax_input = QLineEdit("10000")
        self.vmax_input.setFixedWidth(60)
        self.vmax_input.editingFinished.connect(self.update_plot)
        img_ctrl.addWidget(self.vmax_input)

        img_ctrl.addWidget(QLabel("cmap:"))
        self.cmap_selector = QComboBox()
        self.cmap_selector.addItems(plt.colormaps())
        self.cmap_selector.setCurrentText("gray")
        self.cmap_selector.currentTextChanged.connect(self.update_plot)
        img_ctrl.addWidget(self.cmap_selector)

        img_ctrl.addWidget(QLabel("scale:"))
        self.img_scale_combo = QComboBox()
        self.img_scale_combo.addItems(["linear", "log"]
        )
        self.img_scale_combo.currentTextChanged.connect(self.update_plot)
        img_ctrl.addWidget(self.img_scale_combo)

        left_panel.addLayout(img_ctrl)
        main_layout.addLayout(left_panel)

        # Right panel: Parameters & combined plot
        right_panel = QVBoxLayout()

        # Load image button
        btn_load = QPushButton("Load Image")
        btn_load.clicked.connect(self.load_image)
        right_panel.addWidget(btn_load)

        # Beam center & detector geometry
        for attr, params in [
            ("spin_x",      ("Beam Center X", 0, 2000, 476, 1)),
            ("spin_y",      ("Beam Center Y", 0, 2000, 800, 1)),
            ("spin_orient", ("Detector Orient (°)", -180, 180, 0, 1)),
            ("spin_tilt",   ("Detector Tilt (°)",   -180, 180, 0, 1)),
            ("spin_phi",    ("Detector Phi (°)",    -180, 180, 0, 1)),
            ("spin_dist",   ("Distance (m)", 0.1, 5.0, 0.261, 0.001)),
            ("spin_pixel",  ("Pixel Size (µm)", 50, 500, 172.0, 0.1)),
        ]:
            setattr(
                self,
                attr,
                self._create_spin(*params, parent=right_panel)
            )

        # Wavelength & energy
        wl_layout = QHBoxLayout()

        wl_layout.addWidget(QLabel("Wavelength (Å):"))
        self.spin_wl_ang = QDoubleSpinBox()
        self.spin_wl_ang.setRange(0.01, 10.0)
        self.spin_wl_ang.setSingleStep(0.001)
        self.spin_wl_ang.setValue(0.9184)
        self.spin_wl_ang.editingFinished.connect(
            self.on_wavelength_changed
        )
        wl_layout.addWidget(self.spin_wl_ang)

        wl_layout.addWidget(QLabel("Energy (eV):"))
        self.spin_energy_ev = QDoubleSpinBox()
        self.spin_energy_ev.setRange(100.0, 50000.0)
        self.spin_energy_ev.setSingleStep(1.0)
        self.spin_energy_ev.setValue(HC_E / 0.9184)
        self.spin_energy_ev.editingFinished.connect(
            self.on_energy_changed
        )
        wl_layout.addWidget(self.spin_energy_ev)

        right_panel.addLayout(wl_layout)

        # Calibrate button
        btn_cal = QPushButton("Calibrate")
        btn_cal.clicked.connect(self.update_plot)
        right_panel.addWidget(btn_cal)

        # Plot scaling option
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("Plot scale:"))
        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["linear", "logx", "logy", "loglog"])  
        self.scale_combo.currentTextChanged.connect(self.update_plot)
        scale_layout.addWidget(self.scale_combo)
        right_panel.addLayout(scale_layout)

        # Combined Q–I plot
        self.fig_plot, self.ax_plot = plt.subplots(figsize=(6, 4))
        self.canvas_plot = FigureCanvas(self.fig_plot)
        right_panel.addWidget(self.canvas_plot)
        right_panel.addWidget(
            NavigationToolbar(self.canvas_plot, self)
        )

        main_layout.addLayout(right_panel)

        # Mouse move events for status bar
        self.canvas_raw.mpl_connect(
            'motion_notify_event', self.on_mouse_move
        )
        self.canvas_plot.mpl_connect(
            'motion_notify_event', self.on_mouse_move
        )

    def _create_spin(
        self, label, mn, mx, default, step, parent
    ):
        lay = QHBoxLayout()
        lay.addWidget(QLabel(label))
        spin = QDoubleSpinBox()
        spin.setRange(mn, mx)
        spin.setSingleStep(step)
        spin.setValue(default)
        lay.addWidget(spin)
        parent.addLayout(lay)
        return spin

    def on_wavelength_changed(self):
        wl = self.spin_wl_ang.value()
        ev = HC_E / wl
        self.spin_energy_ev.blockSignals(True)
        self.spin_energy_ev.setValue(ev)
        self.spin_energy_ev.blockSignals(False)
        self.update_plot()

    def on_energy_changed(self):
        ev = self.spin_energy_ev.value()
        wl = HC_E / ev if ev != 0 else self.spin_wl_ang.value()
        self.spin_wl_ang.blockSignals(True)
        self.spin_wl_ang.setValue(wl)
        self.spin_wl_ang.blockSignals(False)
        self.update_plot()

    def load_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Image File", "", 
            "*.tiff *.tif *.h5 *.dat"
        )
        if not path:
            return
        try:
            self.image_data = Data2DScattering(
                path, calibration=self.calibration
            )
        except Exception as e:
            print(f"Error loading image: {e}")
            return
        h, w = self.image_data.data.shape
        self.calibration.set_image_size(w, height=h)
        self.calibration.clear_maps()
        self.update_plot()

    def update_plot(self):
        if self.image_data is None:
            return

        # Preserve view limits
        raw_xlim, raw_ylim = (
            self.ax_raw.get_xlim(),
            self.ax_raw.get_ylim()
        )
        plot_xlim, plot_ylim = (
            self.ax_plot.get_xlim(),
            self.ax_plot.get_ylim()
        )

        # Update calibration
        cal = self.calibration
        cal.set_beam_position(
            self.spin_x.value(), self.spin_y.value()
        )
        cal.set_angles(
            det_orient=self.spin_orient.value(),
            det_tilt=self.spin_tilt.value(),
            det_phi=self.spin_phi.value()
        )
        cal.set_distance(self.spin_dist.value())
        cal.set_pixel_size(
            pixel_size_um=self.spin_pixel.value()
        )
        cal.set_wavelength(self.spin_wl_ang.value())
        cal.clear_maps()

        # Compute averages
        circ = self.image_data.circular_average_q_bin(
            apply_mask=False
        )
        hor = self.image_data.sector_average_q_bin(
            angle=0, dangle=5, apply_mask=False
        )
        ver = self.image_data.sector_average_q_bin(
            angle=90, dangle=5, apply_mask=False
        )

        # Raw image display
        self.ax_raw.clear()
        try:
            vmin = float(self.vmin_input.text())
            vmax = float(self.vmax_input.text())
        except ValueError:
            vmin = vmax = None
        cmap = self.cmap_selector.currentText()
        scale = self.img_scale_combo.currentText()

        if scale == 'log':
            norm = (
                LogNorm(vmin=vmin, vmax=vmax)
                if vmin and vmax else LogNorm()
            )
            self.ax_raw.imshow(
                self.image_data.data,
                origin='upper',
                cmap=cmap,
                norm=norm
            )
        else:
            self.ax_raw.imshow(
                self.image_data.data,
                origin='upper',
                cmap=cmap,
                vmin=vmin,
                vmax=vmax
            )

        # self.ax_raw.invert_yaxis()
        self.ax_raw.axhline(
            self.spin_y.value(), color='r', ls='--'
        )
        self.ax_raw.axvline(
            self.spin_x.value(), color='r', ls='--'
        )
        self.ax_raw.set_title(
            'Raw Image (Y-flipped)', fontsize=10
        )
        self.ax_raw.tick_params(labelsize=8)

        if not np.allclose(raw_xlim, (0, 1)):
            self.ax_raw.set_xlim(raw_xlim)
        if not np.allclose(raw_ylim, (0, 1)):
            self.ax_raw.set_ylim(raw_ylim)

        self.canvas_raw.draw()

        # Combined Q–I plot
        self.ax_plot.clear()
        self.ax_plot.plot(circ.x, circ.y, label='Circular')
        self.ax_plot.plot(hor.x, hor.y, label='Horizontal')
        self.ax_plot.plot(ver.x, ver.y, label='Vertical')
        self.ax_plot.set_xlabel('Q')
        self.ax_plot.set_ylabel('Intensity')
        self.ax_plot.legend(fontsize=8)
        self.ax_plot.tick_params(labelsize=8)

        ps = self.scale_combo.currentText()
        self.ax_plot.set_xscale(
            'log' if 'logx' in ps else 'linear'
        )
        self.ax_plot.set_yscale(
            'log' if 'logy' in ps else 'linear'
        )

        if not np.allclose(plot_xlim, (0, 1)):
            self.ax_plot.set_xlim(plot_xlim)
        if not np.allclose(plot_ylim, (0, 1)):
            self.ax_plot.set_ylim(plot_ylim)

        self.fig_plot.tight_layout()
        self.canvas_plot.draw()

    def on_mouse_move(self, event):
        if not event.inaxes:
            return

        if (
            event.inaxes == self.ax_raw
            and self.image_data is not None
        ):
            x, y = int(event.xdata), int(event.ydata)
            h, w = self.image_data.data.shape
            if 0 <= x < w and 0 <= y < h:
                val = self.image_data.data[y, x]
                self.status.showMessage(
                    f"Raw Pixel (x={x}, y={y}) = {val:.2f}"
                )
        elif event.inaxes == self.ax_plot:
            x, y = event.xdata, event.ydata
            self.status.showMessage(
                f"Q={x:.3f}, I={y:.2f}"
            )

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.update_plot()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = CalibrationApp()
    win.resize(1200, 800)
    win.show()
    sys.exit(app.exec_())
