"""Opt-in native UI benchmark; no user session or cache is modified."""

from __future__ import annotations

import argparse
from contextlib import ExitStack, redirect_stdout
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
from time import perf_counter
from unittest.mock import patch


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _measure_worker(cache_dir: Path, samples: int) -> dict:
    started = perf_counter()
    root = Path(__file__).resolve().parents[3]
    if not (root / "main.py").is_file():
        raise RuntimeError("Run the UI benchmark from a SciView source checkout.")
    sys.path.insert(0, str(root))
    import main
    from PyQt5.QtCore import QCoreApplication, QEvent, QEventLoop, QStandardPaths
    from PyQt5.QtWidgets import QWidget
    from sciview.interfaces.theme.app_style import AppStyle

    imported = perf_counter()
    renders = 0
    original_render = AppStyle._render_svg_pixmap
    original_location = QStandardPaths.writableLocation

    def render(*args):
        nonlocal renders
        renders += 1
        return original_render(*args)

    def location(kind):
        if kind == QStandardPaths.GenericCacheLocation:
            return str(cache_dir)
        return original_location(kind)

    with ExitStack() as stack:
        for name in ("load_session", "load_dialog_state"):
            stack.enter_context(patch.object(main.session_cache, name, return_value={}))
        for name in ("save_session", "save_dialog_state"):
            stack.enter_context(patch.object(main.session_cache, name))
        stack.enter_context(patch.object(QStandardPaths, "writableLocation", location))
        stack.enter_context(patch.object(AppStyle, "_render_svg_pixmap", render))
        app, window = main.create_application()

        def settle():
            # Include queued layouts, paints and deferred canvas updates; no sleep.
            for _ in range(4):
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                app.processEvents(QEventLoop.AllEvents)
            app.sync()
            app.processEvents(QEventLoop.AllEvents)

        try:
            created = perf_counter()
            window.resize(1528, 980)
            window.show()
            settle()
            ready = perf_counter()
            if window.tab_widget.count() != 8 or any(
                type(window.tab_widget.widget(i)) is QWidget for i in range(8)
            ):
                raise RuntimeError("Benchmark requires all eight tabs to load successfully.")
            if any(
                name == prefix or name.startswith(prefix + ".")
                for name in sys.modules for prefix in ("tiled", "bluesky_tiled_plugins")
            ):
                raise RuntimeError("External Tiled dependencies were imported during startup.")
            result = {
                "startup_ms": {
                    "imports": (imported - started) * 1000,
                    "create": (created - imported) * 1000,
                    "show_and_events": (ready - created) * 1000,
                    "total": (ready - started) * 1000,
                },
                "startup_svg_renders": renders,
                "widgets": len(app.allWidgets()),
                "switches": {},
            }
            for name, action in (
                ("theme", window._toggle_dark_light_theme),
                ("contrast", lambda: AppStyle.set_high_contrast(
                    not AppStyle.high_contrast_enabled())),
                ("text_size", lambda: window._set_text_scale(
                    125 if AppStyle.FONTS["scale_pct"] == 100 else 100)),
                ("theme_while_contrast", window._toggle_dark_light_theme),
            ):
                AppStyle.set_high_contrast(name == "theme_while_contrast")
                settle()
                timings = []
                for _ in range(samples):
                    initial_renders = renders
                    t0 = perf_counter()
                    action()
                    returned = perf_counter()
                    settle()
                    timings.append({
                        "handler_ms": (returned - t0) * 1000,
                        "settled_ms": (perf_counter() - t0) * 1000,
                        "svg_renders": renders - initial_renders,
                    })
                result["switches"][name] = timings
            return result
        finally:
            # Do not close: normal close persists state and clears session scratch.
            window.hide()
            window.deleteLater()
            settle()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=_positive_int, default=3,
                        help="fresh processes; the first populates an isolated icon cache")
    parser.add_argument("--samples", type=_positive_int, default=4,
                        help="samples per appearance action in each process")
    parser.add_argument("--json", type=Path, help="optional path for raw measurements")
    parser.add_argument("--worker-cache", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_cache is not None:
        with redirect_stdout(sys.stderr):
            result = _measure_worker(args.worker_cache, args.samples)
        print(json.dumps(result))
        return

    runs = []
    env = dict(os.environ, DEV_TOOLS="0")
    with tempfile.TemporaryDirectory(prefix="sciview-benchmark-") as directory:
        for index in range(args.runs):
            completed = subprocess.run(
                [sys.executable, "-m", "sciview.dev.benchmark_ui",
                 "--worker-cache", directory, "--samples", str(args.samples)],
                env=env, capture_output=True, text=True, timeout=600,
            )
            if completed.returncode:
                raise RuntimeError(completed.stderr or completed.stdout)
            # Keep warnings and dependency failures visible, not just the timings.
            if completed.stderr:
                print(completed.stderr, file=sys.stderr, end="")
            result = json.loads(completed.stdout)
            runs.append(result)
            label = "empty icon cache" if index == 0 else "populated icon cache"
            print(
                f"Run {index + 1} ({label}): "
                f"{result['startup_ms']['total'] / 1000:.2f} s startup; "
                f"{result['startup_svg_renders']} SVG renders",
                flush=True,
            )
    print("\nAppearance action           Median     Maximum")
    for name in runs[0]["switches"]:
        values = [sample["settled_ms"] / 1000
                  for run in runs for sample in run["switches"][name]]
        print(f"{name:26} {statistics.median(values):6.2f} s  {max(values):6.2f} s")
    if args.json is not None:
        args.json.write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
