"""Qt device-login dialog; all HTTP and polling happen off the GUI thread."""
import threading
from PyQt5.QtCore import pyqtSignal, pyqtSlot, QUrl, Qt
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QApplication
from sciview.interfaces.services.latest_job import LatestJob
from sciview.sources.tiled_auth import sign_in
from sciview.interfaces.stable_qt.widgets.status_label import readable_status


class TiledLoginDialog(QDialog):
    device_code = pyqtSignal(str, str)
    authenticated = pyqtSignal()

    def __init__(self, uri, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tiled sign-in")
        self.setMinimumWidth(450)
        self.cancel = threading.Event()
        self.uri = uri
        self.identity = None
        self._url = ""
        self.job = LatestJob(self)
        layout = QVBoxLayout(self)
        self.status = readable_status("Checking cached login…"); layout.addWidget(self.status)
        self.code = readable_status(); self.code.hide(); layout.addWidget(self.code)
        self.open_button = QPushButton("Open sign-in page"); self.open_button.setEnabled(False); layout.addWidget(self.open_button)
        self.copy_button = QPushButton("Copy code"); self.copy_button.setEnabled(False); layout.addWidget(self.copy_button)
        self.open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self._url)))
        self.copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.code.text()))
        self.retry_button = QPushButton("Sign in again / use another account")
        self.retry_button.setEnabled(False)
        self.retry_button.clicked.connect(lambda: self.start(force=True))
        layout.addWidget(self.retry_button)
        self.close_button = QPushButton("Close / Cancel")
        self.close_button.clicked.connect(self.reject); layout.addWidget(self.close_button)
        self.device_code.connect(self.show_code)
        self.finished.connect(self.stop)
        QApplication.instance().aboutToQuit.connect(self.stop)
        self.start()

    def start(self, *, force=False):
        self.identity = None
        self.code.clear()
        self.code.hide()
        self._url = ""
        self.open_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.close_button.setText("Close / Cancel")
        self.status.setText("Starting browser sign-in…" if force else "Checking cached login…")
        self.job.submit(lambda: sign_in(self.uri, self.cancel, self.device_code.emit, force=force),
                        self.success, self.failure)

    @pyqtSlot(str, str)
    def show_code(self, url, code):
        if self.cancel.is_set():
            return
        self._url = url
        self.status.setText(f"Open {url} and enter this code. Complete your institution's sign-in in the browser.")
        self.code.setText(code)
        self.code.show()
        self.open_button.setEnabled(True); self.copy_button.setEnabled(True)

    def success(self, info):
        identities = (info or {}).get("identities") or []
        self.identity = next((str(i["id"]) for i in identities if i.get("id")), "Tiled user")
        self.status.setText(
            f"Signed in as {self.identity}. Your Tiled session is ready; no further action is needed. "
            "An existing login may have been restored. Close this dialog to browse, "
            "or sign in again to choose another account."
        )
        self.code.clear()
        self.code.hide()
        self.open_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.retry_button.setEnabled(True)
        self.close_button.setText("Close")
        self.authenticated.emit()

    def failure(self, exc):
        self.status.setText(str(exc))
        self.open_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        self.retry_button.setEnabled(True)

    def stop(self, *_):
        self.cancel.set()
        self.job.close()
