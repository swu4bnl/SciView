import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading
import time
from PyQt5.QtWidgets import QApplication
from sciview.interfaces.services.latest_job import LatestJob


def test_latest_job_bounds_queue_and_delivers_on_main_thread():
    app = QApplication.instance() or QApplication([])
    job = LatestJob()
    started, release = threading.Event(), threading.Event()
    executed, shown, errors = [], [], []
    main = threading.get_ident()
    def first():
        executed.append(1); started.set()
        assert release.wait(5)
        return 1
    def apply(value):
        assert threading.get_ident() == main
        shown.append(value)
    job.submit(first, apply, errors.append)
    assert started.wait(5)
    job.submit(lambda: executed.append(2), apply, errors.append)
    job.submit(lambda: (executed.append(3), 3)[1], apply, errors.append)
    release.set()
    until = time.monotonic() + 5
    while not shown and time.monotonic() < until:
        app.processEvents(); time.sleep(.01)
    job.close()
    assert executed == [1, 3]
    assert shown == [3]
    assert not errors
