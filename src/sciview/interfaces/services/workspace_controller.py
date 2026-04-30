"""Shared workspace state controller for GUI frontends."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from sciview.data.models import Dataset, ImageRef


Callback = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class WorkspaceController:
    """In-memory source of truth for active UI context."""

    active_image_ref: ImageRef | None = None
    active_dataset: Dataset | None = None
    active_task: str = "calibration"
    task_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    _listeners: dict[str, list[Callback]] = field(
        default_factory=lambda: defaultdict(list),
        repr=False,
    )

    def subscribe(self, event_name: str, callback: Callback) -> None:
        self._listeners[event_name].append(callback)

    def _emit(self, event_name: str, payload: dict[str, Any]) -> None:
        for callback in self._listeners.get(event_name, []):
            callback(payload)

    def set_active_image(self, image_ref: ImageRef) -> None:
        self.active_image_ref = image_ref
        self._emit("active_image_changed", {"image_ref": image_ref})

    def set_active_dataset(self, dataset: Dataset) -> None:
        self.active_dataset = dataset
        self._emit("active_dataset_changed", {"dataset": dataset})

    def set_active_task(self, task_name: str) -> None:
        self.active_task = task_name
        self._emit("active_task_changed", {"task": task_name})

    def set_task_state(self, task_name: str, payload: dict[str, Any]) -> None:
        self.task_state[task_name] = dict(payload)
        self._emit("task_state_changed", {"task": task_name, "state": dict(payload)})