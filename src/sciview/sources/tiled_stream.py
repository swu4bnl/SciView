"""Live Tiled subscription helpers.

This module keeps Tiled WebSocket subscription handling behind the data-source
layer.  GUI code should consume the structured events through ImageService and
must not call Tiled subscription objects directly.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

try:
    from bluesky_tiled_plugins import subscribe_to_streams
except ImportError:
    subscribe_to_streams = None

from sciview.sources.tiled_client import tiled_manager
from sciview.sources.tiled_source import TiledScanSummary, _summary_from_run


LiveEventCallback = Callable[["TiledLiveEvent"], None]


def _install_child_created_compatibility() -> None:
    """Accept access-tag messages produced by servers newer than Tiled 0.2.18."""
    try:
        from pydantic import Field
        from tiled.client import stream as tiled_stream
    except ImportError:
        return

    child_created = tiled_stream.UPDATE_MESSAGE_TYPES.get("container-child-created")
    if child_created is None:
        return
    fields = child_created.model_fields
    access_blob_field = fields.get("access_blob")
    if "access_tags" in fields or access_blob_field is None or not access_blob_field.is_required():
        return

    class CompatibleLiveChildCreated(child_created):
        access_blob: dict = Field(default_factory=dict)
        access_tags: list[str] = Field(default_factory=list)

        def _item(self) -> dict[str, Any]:
            item = super()._item()
            item["attributes"]["access_tags"] = self.access_tags
            return item

    tiled_stream.UPDATE_MESSAGE_TYPES["container-child-created"] = CompatibleLiveChildCreated


@dataclass(slots=True)
class TiledLiveEvent:
    """Structured event emitted by a live Tiled subscription."""

    profile_name: str
    event_type: str
    uid: str | None = None
    scan_id: int | None = None
    key: str = ""
    scan: TiledScanSummary | None = None
    data: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class TiledLiveMonitor:
    """Manage one live Tiled catalog subscription."""

    def __init__(self, profile_name: str, *, catalog: Any | None = None):
        self.profile_name = profile_name
        self._catalog = catalog
        self._catalog_subscription: Any | None = None
        self._seen_runs: set[str] = set()
        self._seen_runs_lock = threading.Lock()
        self._callback: LiveEventCallback | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, callback: LiveEventCallback) -> None:
        """Start listening for new Tiled entries and data patches."""

        if self._running:
            raise RuntimeError("Tiled live monitor is already running")

        _install_child_created_compatibility()
        self._callback = callback
        catalog = self._catalog or tiled_manager.get_or_load_catalog(self.profile_name)
        if catalog is None:
            raise RuntimeError(f"Could not load Tiled catalog for profile: {self.profile_name}")
        if subscribe_to_streams is None:
            raise RuntimeError("Installed bluesky-tiled-plugins does not provide live streaming support")

        self._catalog = catalog
        try:
            subscription = subscribe_to_streams(
                catalog,
                self._on_stream_update,
                streams={"primary": None},
                start=None,
            )
        except Exception:
            self._callback = None
            self._catalog_subscription = None
            self._running = False
            raise

        self._catalog_subscription = subscription
        self._running = True
        self._emit(TiledLiveEvent(profile_name=self.profile_name, event_type="started"))

    def stop(self) -> None:
        """Stop all active live subscriptions."""

        self._stop_subscription(self._catalog_subscription)
        self._catalog_subscription = None
        self._seen_runs.clear()
        was_running = self._running
        self._running = False
        if was_running:
            self._emit(TiledLiveEvent(profile_name=self.profile_name, event_type="stopped"))
        self._callback = None

    def _on_stream_update(self, update: Any) -> None:
        try:
            run_uid = str(update.run_uid)
            run = self._catalog[run_uid]
            summary = _summary_from_run(run, profile_name=self.profile_name)
            with self._seen_runs_lock:
                first_update = run_uid not in self._seen_runs
                self._seen_runs.add(run_uid)
            if first_update:
                self._emit(
                    TiledLiveEvent(
                        profile_name=self.profile_name,
                        event_type="child_created",
                        uid=run_uid,
                        scan_id=summary.scan_id,
                        key=run_uid,
                        scan=summary,
                        metadata=summary.metadata,
                    )
                )
            self._emit(
                TiledLiveEvent(
                    profile_name=self.profile_name,
                    event_type="new_data",
                    uid=run_uid,
                    scan_id=summary.scan_id,
                    key=str(update.stream_name),
                    scan=summary,
                    metadata=summary.metadata,
                )
            )
        except Exception as exc:
            self._emit_error(exc)

    def _emit(self, event: TiledLiveEvent) -> None:
        if self._callback is not None:
            self._callback(event)

    def _emit_error(self, exc: Exception) -> None:
        self._emit(
            TiledLiveEvent(
                profile_name=self.profile_name,
                event_type="error",
                error=str(exc),
            )
        )

    @staticmethod
    def _stop_subscription(subscription: Any | None) -> None:
        if subscription is None:
            return
        for method_name in ("disconnect", "stop", "close", "cancel"):
            method = getattr(subscription, method_name, None)
            if callable(method):
                method()
                return


def create_tiled_live_monitor(profile_name: str) -> TiledLiveMonitor:
    """Create a live monitor for a configured Tiled profile."""

    return TiledLiveMonitor(profile_name)