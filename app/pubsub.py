"""Thread-safe in-memory pub/sub broker with retained last messages."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

Handler = Callable[[Any], None]


class PubSub:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[str, set[Handler]] = {}
        self._last: dict[str, Any] = {}

    def subscribe(self, topic: str, handler: Handler) -> Callable[[], None]:
        with self._lock:
            self._subscribers.setdefault(topic, set()).add(handler)
            retained = self._last.get(topic)

        if retained is not None:
            try:
                handler(retained)
            except Exception as exc:  # noqa: BLE001
                print(f'[pubsub] retained handler error on "{topic}": {exc}')

        def unsubscribe() -> None:
            with self._lock:
                handlers = self._subscribers.get(topic)
                if not handlers:
                    return
                handlers.discard(handler)
                if not handlers:
                    self._subscribers.pop(topic, None)

        return unsubscribe

    def publish(self, topic: str, payload: Any) -> None:
        with self._lock:
            self._last[topic] = payload
            handlers = list(self._subscribers.get(topic, set()))

        for handler in handlers:
            try:
                handler(payload)
            except Exception as exc:  # noqa: BLE001
                print(f'[pubsub] handler error on "{topic}": {exc}')

    def get_last(self, topic: str) -> Any | None:
        with self._lock:
            return self._last.get(topic)


TOPICS = {
    "SENSOR_DATA": "sensors/water/data",
    "SENSOR_STATUS": "sensors/water/status",
    "SYSTEM": "system/events",
}
