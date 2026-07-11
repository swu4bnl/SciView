"""Live Tiled subscription helpers.

This module keeps Tiled WebSocket subscription handling behind the data-source
layer.  GUI code should consume the structured events through ImageService and
must not call Tiled subscription objects directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sciview.sources.tiled_client import tiled_manager
from sciview.sources.tiled_source import TiledScanSummary, _summary_from_run


LiveEventCallback = Callable[["TiledLiveEvent"], None]


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
        self._child_subscriptions: list[Any] = []
        self._callback: LiveEventCallback | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, callback: LiveEventCallback) -> None:
        """Start listening for new Tiled entries and data patches."""

        if self._running:
            raise RuntimeError("Tiled live monitor is already running")

        self._callback = callback
        catalog = self._catalog or tiled_manager.get_or_load_catalog(self.profile_name)
        if catalog is None:
            raise RuntimeError(f"Could not load Tiled catalog for profile: {self.profile_name}")
        if not hasattr(catalog, "subscribe"):
            raise RuntimeError("Tiled catalog does not support subscriptions")

        self._catalog = catalog
        try:
            self._preflight_subscription(catalog)
            subscription = catalog.subscribe()
            subscription.child_created.add_callback(self._on_child_created)
            subscription.start_in_thread()
        except Exception:
            self._callback = None
            self._catalog_subscription = None
            self._running = False
            raise

        self._catalog_subscription = subscription
        self._running = True
        self._emit(TiledLiveEvent(profile_name=self.profile_name, event_type="started"))

    def _preflight_subscription(self, catalog: Any) -> None:
        """Verify the WebSocket handshake before starting Tiled's thread.

        Tiled's ``start_in_thread`` returns before the WebSocket handshake
        completes.  If the server rejects the stream, the exception otherwise
        lands in Tiled's background thread and bypasses SciView error handling.
        Newer/alternate Tiled clients may not expose the private hooks used
        here; in that case we skip the preflight and fall back to normal start.
        """

        subscription = catalog.subscribe()
        connect = getattr(subscription, "_connect", None)
        websocket = getattr(subscription, "_websocket", None)
        if not callable(connect) or websocket is None:
            return

        try:
            connect()
        except Exception as exc:
            raise RuntimeError(
                f"Tiled live stream connection failed for profile '{self.profile_name}': {exc}"
            ) from exc
        finally:
            raw_websocket = getattr(websocket, "_websocket", None)
            close = getattr(websocket, "close", None)
            if raw_websocket is not None and callable(close):
                try:
                    close()
                except Exception:
                    pass

    def stop(self) -> None:
        """Stop all active live subscriptions."""

        for subscription in [*self._child_subscriptions, self._catalog_subscription]:
            self._stop_subscription(subscription)
        self._child_subscriptions.clear()
        self._catalog_subscription = None
        was_running = self._running
        self._running = False
        if was_running:
            self._emit(TiledLiveEvent(profile_name=self.profile_name, event_type="stopped"))
        self._callback = None

    def _on_child_created(self, update: Any) -> None:
        try:
            child = update.child()
            summary = _summary_from_run(child, profile_name=self.profile_name)
            key = str(getattr(update, "key", "") or getattr(child, "key", "") or summary.uid)
            self._emit(
                TiledLiveEvent(
                    profile_name=self.profile_name,
                    event_type="child_created",
                    uid=summary.uid or None,
                    scan_id=summary.scan_id,
                    key=key,
                    scan=summary,
                    metadata=summary.metadata,
                )
            )
            self._subscribe_to_child(child, summary, key)
        except Exception as exc:
            self._emit_error(exc)

    def _subscribe_to_child(self, child: Any, summary: TiledScanSummary, key: str) -> None:
        if not hasattr(child, "subscribe"):
            return

        child_subscription = child.subscribe()

        def on_new_data(update: Any) -> None:
            self._on_new_data(update, summary, key)

        child_subscription.new_data.add_callback(on_new_data)
        child_subscription.start_in_thread(start=0)
        self._child_subscriptions.append(child_subscription)

    def _on_new_data(self, update: Any, summary: TiledScanSummary, key: str) -> None:
        try:
            data = update.data() if hasattr(update, "data") else None
            self._emit(
                TiledLiveEvent(
                    profile_name=self.profile_name,
                    event_type="new_data",
                    uid=summary.uid or None,
                    scan_id=summary.scan_id,
                    key=key,
                    scan=summary,
                    data=data,
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
        for method_name in ("stop", "close", "cancel"):
            method = getattr(subscription, method_name, None)
            if callable(method):
                method()
                return


def create_tiled_live_monitor(profile_name: str) -> TiledLiveMonitor:
    """Create a live monitor for a configured Tiled profile."""

    return TiledLiveMonitor(profile_name)