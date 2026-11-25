"""Telemetry bridge. Background threads push log lines into a queue; the Tk main loop
drains it. Widgets are never touched from worker threads."""

from __future__ import annotations

import logging
import queue
from dataclasses import dataclass
from datetime import datetime

_events: queue.Queue["TelemetryEvent"] = queue.Queue(maxsize=5000)


@dataclass(frozen=True)
class TelemetryEvent:
    timestamp: datetime
    level: str
    message: str


class QueueHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        event = TelemetryEvent(
            timestamp=datetime.fromtimestamp(record.created),
            level=record.levelname,
            message=self.format(record),
        )
        try:
            _events.put_nowait(event)
        except queue.Full:
            pass  # drop rather than block a worker thread


def install() -> None:
    handler = QueueHandler()
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    root = logging.getLogger("synaptiq")
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def drain(limit: int = 100) -> list[TelemetryEvent]:
    """Called from the Tk main loop via after(). Returns up to limit events."""
    events: list[TelemetryEvent] = []
    while len(events) < limit:
        try:
            events.append(_events.get_nowait())
        except queue.Empty:
            break
    return events
