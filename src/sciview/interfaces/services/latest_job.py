"""Bounded background I/O with Qt-thread delivery and stale-result rejection."""
from concurrent.futures import ThreadPoolExecutor

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot


class LatestJob(QObject):
    completed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sciview-io")
        self._generation = 0
        self._running = False
        self._pending = None
        self._closed = False
        self.completed.connect(self._finish)

    def invalidate(self):
        self._generation += 1
        self._pending = None

    def submit(self, work, apply, error):
        if self._closed:
            return
        self._generation += 1
        request = (self._generation, work, apply, error)
        if self._running:
            self._pending = request
        else:
            self._start(request)

    def _start(self, request):
        self._running = True
        generation, work, apply, error = request
        future = self._pool.submit(work)

        def done(future):
            try:
                result, exc = future.result(), None
            except Exception as failure:
                result, exc = None, failure
            try:
                self.completed.emit((generation, result, exc, apply, error))
            except RuntimeError:
                pass  # QObject was destroyed during shutdown
        future.add_done_callback(done)

    @pyqtSlot(object)
    def _finish(self, payload):
        generation, result, exc, apply, error = payload
        self._running = False
        try:
            if not self._closed and generation == self._generation:
                if exc is not None:
                    error(exc)
                else:
                    try:
                        apply(result)
                    except Exception as failure:
                        error(failure)
        finally:
            if self._pending is not None and not self._closed and not self._running:
                pending, self._pending = self._pending, None
                self._start(pending)

    def close(self):
        self._closed = True
        self.invalidate()
        self._pool.shutdown(wait=False, cancel_futures=True)
