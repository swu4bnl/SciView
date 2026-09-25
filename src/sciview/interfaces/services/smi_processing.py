"""Qt process supervision and per-selection SMI result publication."""
from dataclasses import asdict
import json
from pathlib import Path
import sys
from uuid import uuid4

from PyQt5.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal

from sciview.interfaces.services.latest_job import LatestJob
from sciview.processing.smi_reduction import results_directory, describe_result


class SmiProcessingController(QObject):
    context_changed = pyqtSignal(object)
    result_changed = pyqtSignal(object)
    status_changed = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ref = None
        self.result = None
        self.process = None
        self.job_uid = None
        self.directory = None
        self.cancelled = False
        self._buffer = b""
        self._outcome = None
        self.io = LatestJob(self)
        self._kill_timer = QTimer(self)
        self._kill_timer.setSingleShot(True)
        self._kill_timer.timeout.connect(self._terminate)

    @property
    def busy(self):
        return self.process is not None

    def set_context(self, ref):
        previous = (self.ref.uid, self.ref.stream) if self.ref else None
        current = (ref.uid, ref.stream) if ref else None
        self.ref = ref
        if current != previous:
            self.io.invalidate()
            self.result = None
            self.result_changed.emit(None)
        self.context_changed.emit(ref)

    def start(self, request):
        if self.busy: raise RuntimeError("A reduction is already running")
        request.validate()
        if self.ref is None or (request.uid, request.stream) != (self.ref.uid, self.ref.stream):
            raise ValueError("Select the source run before reducing")
        self.io.invalidate()
        directory = results_directory() / f"{request.uid}-{uuid4().hex[:12]}"
        directory.mkdir(parents=True)
        (directory / "request.json").write_text(json.dumps(asdict(request), indent=2))
        self.directory, self.job_uid = directory, request.uid
        self.cancelled, self._outcome, self._buffer = False, None, b""
        process = QProcess(self)
        self.process = process
        process.setProcessChannelMode(QProcess.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1"); env.insert("PYTHONNOUSERSITE", "1")
        process.setProcessEnvironment(env)
        process.readyReadStandardOutput.connect(self._read)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._error)
        process.start(sys.executable, ["-m", "sciview.processing.smi_reduction", str(directory / "request.json")])
        self.busy_changed.emit(True)
        self.status_changed.emit(f"Reducing whole primary run {request.uid[:12]}…")

    def _read(self):
        if self.process is None: return
        chunk = bytes(self.process.readAllStandardOutput())
        with (self.directory / "job.log").open("ab") as log: log.write(chunk)
        self._buffer += chunk
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            if not line.startswith(b"SCIVIEW_JOB "): continue
            try: event = json.loads(line[len(b"SCIVIEW_JOB "):])
            except ValueError: continue
            if event["type"] == "progress" and not self.cancelled:
                self.status_changed.emit(f"{event['stage']}: {event['current']}/{event['total']} · {self.job_uid[:12]}")
            else:
                if event["type"] in ("result", "error", "cancelled"): self._outcome = event

    def _error(self, error):
        if error == QProcess.FailedToStart:
            self._outcome = dict(type="error", message=self.process.errorString())
            self._finished(-1, QProcess.CrashExit)

    def _finished(self, code, _status):
        if self.process is None: return
        self._read(); self._kill_timer.stop()
        process, self.process = self.process, None
        process.deleteLater()
        self.busy_changed.emit(False)
        outcome = self._outcome or dict(type="error", message=f"Worker exited ({code}); see {self.directory / 'job.log'}")
        if self.cancelled or outcome["type"] == "cancelled":
            self.status_changed.emit(f"Cancelled. Unpublished work is in {self.directory}")
        elif outcome["type"] == "result" and code == 0:
            path = outcome["path"]
            self.status_changed.emit(f"Complete: {path}")
            # A result for a previous selection remains on disk, never replaces
            # whichever scan the user is now inspecting.
            if self.ref is not None and self.ref.uid == self.job_uid and self.ref.stream == "primary":
                self.open_result(path)
        else:
            self.status_changed.emit(outcome.get("message", "Reduction failed"))

    def open_result(self, path):
        if self.ref is None or self.ref.stream != "primary":
            self.status_changed.emit("Select the source run's primary stream before opening a result")
            return
        ref = self.ref
        def apply(result):
            if self.ref is None or ref is None or self.ref.uid != ref.uid or self.ref.stream != "primary": return
            if result["uid"] != self.ref.uid:
                self.status_changed.emit("Result belongs to a different run; select that run first")
                return
            self.result = result
            self.result_changed.emit(result)
            self.status_changed.emit(f"Loaded {result['geometry']} products for {result['uid'][:12]}")
        self.io.submit(lambda: describe_result(path), apply, lambda exc: self.status_changed.emit(str(exc)))

    def cancel(self):
        if self.process is None: return
        self.cancelled = True
        (self.directory / "cancel").touch()
        self.status_changed.emit("Cancellation requested; stopping worker if it does not reach a progress checkpoint…")
        self._kill_timer.start(3000)

    def _terminate(self):
        if self.process is not None: self.process.kill()

    def close(self):
        self.io.close(); self._kill_timer.stop()
        if self.process is not None:
            self.cancelled = True
            self.process.kill()
            self.process.waitForFinished(3000)
