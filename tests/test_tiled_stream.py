from __future__ import annotations

from typing import Callable

import pytest

import sciview.sources.tiled_stream as tiled_stream
from sciview.sources.tiled_stream import TiledLiveEvent, TiledLiveMonitor

pytestmark = pytest.mark.experimental


def test_tiled_child_created_accepts_access_tags() -> None:
    from tiled.client import stream as tiled_client_stream

    child_created_model = tiled_client_stream.UPDATE_MESSAGE_TYPES[
        "container-child-created"
    ]
    update = child_created_model.model_validate(
        {
            "sequence": 1,
            "timestamp": "2026-10-05T00:00:00Z",
            "key": "run-uid",
            "structure_family": "container",
            "specs": [],
            "metadata": {},
            "data_sources": [],
            "access_tags": ["pass-321599"],
            "subscription": object.__new__(tiled_client_stream.ContainerSubscription),
        }
    )

    assert update.access_tags == ["pass-321599"]


class FakeSubscription:
    def __init__(self, *, error: Exception | None = None):
        self.error = error
        self.disconnect_calls = 0

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        if self.error is not None:
            raise self.error


def start_monitor(
    monkeypatch: pytest.MonkeyPatch,
    subscription: FakeSubscription,
    callback: Callable[[TiledLiveEvent], None],
) -> TiledLiveMonitor:
    monkeypatch.setattr(
        tiled_stream,
        "subscribe_to_streams",
        lambda *args, **kwargs: subscription,
    )
    monitor = TiledLiveMonitor("test", catalog=object())
    monitor.start(callback)
    return monitor


def test_stop_disconnects_and_clears_state(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[TiledLiveEvent] = []
    subscription = FakeSubscription()
    monitor = start_monitor(monkeypatch, subscription, events.append)
    monitor._seen_runs.add("run-uid")

    monitor.stop()

    assert subscription.disconnect_calls == 1
    assert not monitor.is_running
    assert monitor._catalog_subscription is None
    assert not monitor._seen_runs
    assert monitor._callback is None
    assert [event.event_type for event in events] == ["started", "stopped"]


def test_stop_failure_preserves_subscription_ownership(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[TiledLiveEvent] = []
    error = RuntimeError("disconnect failed")
    subscription = FakeSubscription(error=error)
    callback = events.append
    monitor = start_monitor(monkeypatch, subscription, callback)
    monitor._seen_runs.add("run-uid")

    with pytest.raises(RuntimeError, match="disconnect failed"):
        monitor.stop()

    assert subscription.disconnect_calls == 1
    assert monitor.is_running
    assert monitor._catalog_subscription is subscription
    assert monitor._seen_runs == {"run-uid"}
    assert monitor._callback is callback
    assert [event.event_type for event in events] == ["started", "error"]
    assert events[-1].error == "disconnect failed"


def test_callback_failure_does_not_break_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    subscription = FakeSubscription()

    def failing_callback(event: TiledLiveEvent) -> None:
        raise RuntimeError(f"callback failed for {event.event_type}")

    monitor = start_monitor(monkeypatch, subscription, failing_callback)
    assert monitor.is_running

    monitor.stop()

    assert subscription.disconnect_calls == 1
    assert not monitor.is_running
    assert "Tiled live event callback failed" in caplog.text
