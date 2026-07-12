"""Typed operational event model and in-process event bus.

Implements Implementation Plan v0.3 section 19 (event model) and the reconnect support
of section 20: every event carries a monotonically increasing sequence identifier so a
web client can detect gaps after a WebSocket reconnect. The bus is thread-safe so the
backup engine's I/O worker pool (Impl §2.2) can publish progress across the thread
boundary; subscribers are invoked outside the lock.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EventSeverity(str, Enum):
    """Log/event severities (PRD WEB-007)."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventType(str, Enum):
    """The minimum typed events from Implementation Plan v0.3 section 19."""

    SYSTEM_STATE_CHANGED = "SYSTEM_STATE_CHANGED"
    SOURCE_DETECTED = "SOURCE_DETECTED"
    SOURCE_REMOVED = "SOURCE_REMOVED"
    SOURCE_MOUNTED_READ_ONLY = "SOURCE_MOUNTED_READ_ONLY"
    SOURCE_PROTECTION_FAILURE = "SOURCE_PROTECTION_FAILURE"
    DESTINATION_VALIDATED = "DESTINATION_VALIDATED"
    PREFLIGHT_STARTED = "PREFLIGHT_STARTED"
    PREFLIGHT_PROGRESS = "PREFLIGHT_PROGRESS"
    PREFLIGHT_COMPLETED = "PREFLIGHT_COMPLETED"
    BACKUP_STARTED = "BACKUP_STARTED"
    FILE_COPY_STARTED = "FILE_COPY_STARTED"
    FILE_COPY_PROGRESS = "FILE_COPY_PROGRESS"
    FILE_COPY_COMPLETED = "FILE_COPY_COMPLETED"
    FILE_VERIFICATION_STARTED = "FILE_VERIFICATION_STARTED"
    FILE_VERIFICATION_COMPLETED = "FILE_VERIFICATION_COMPLETED"
    FILE_VERIFICATION_FAILED = "FILE_VERIFICATION_FAILED"
    BACKUP_PROGRESS = "BACKUP_PROGRESS"
    BACKUP_COMPLETED = "BACKUP_COMPLETED"
    BACKUP_FAILED = "BACKUP_FAILED"
    BACKUP_CANCELLED = "BACKUP_CANCELLED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    RECOVERY_STARTED = "RECOVERY_STARTED"
    RECOVERY_COMPLETED = "RECOVERY_COMPLETED"
    POWER_WARNING = "POWER_WARNING"
    THERMAL_WARNING = "THERMAL_WARNING"
    SYSTEM_STORAGE_WARNING = "SYSTEM_STORAGE_WARNING"


@dataclass(frozen=True, slots=True)
class Event:
    """A single published event with a monotonic sequence number."""

    sequence: int
    timestamp: datetime
    type: EventType
    severity: EventSeverity
    component: str
    message: str
    backup_job_id: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)


Subscriber = Callable[[Event], None]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EventBus:
    """Thread-safe in-process pub/sub with monotonic sequencing and a replay buffer.

    ``recent_capacity`` bounds the buffer used by :meth:`events_since` so a reconnecting
    client can fill a small gap without unbounded memory growth.
    """

    def __init__(
        self, *, recent_capacity: int = 1024, clock: Callable[[], datetime] = _utc_now
    ) -> None:
        self._lock = threading.Lock()
        self._sequence = 0
        self._subscribers: list[Subscriber] = []
        self._recent: deque[Event] = deque(maxlen=recent_capacity)
        self._clock = clock

    def subscribe(self, callback: Subscriber) -> Callable[[], None]:
        """Register ``callback``; returns a function that unsubscribes it."""
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def publish(
        self,
        event_type: EventType,
        severity: EventSeverity,
        component: str,
        message: str,
        *,
        backup_job_id: str | None = None,
        details: Mapping[str, object] | None = None,
    ) -> Event:
        """Assign the next sequence number, record, and dispatch an event."""
        with self._lock:
            self._sequence += 1
            event = Event(
                sequence=self._sequence,
                timestamp=self._clock(),
                type=event_type,
                severity=severity,
                component=component,
                message=message,
                backup_job_id=backup_job_id,
                details=dict(details) if details is not None else {},
            )
            self._recent.append(event)
            subscribers = tuple(self._subscribers)
        # Dispatch outside the lock so a slow or re-entrant subscriber cannot deadlock.
        for callback in subscribers:
            callback(event)
        return event

    def events_since(self, sequence: int) -> list[Event]:
        """Return buffered events with a sequence strictly greater than ``sequence``."""
        with self._lock:
            return [event for event in self._recent if event.sequence > sequence]

    @property
    def last_sequence(self) -> int:
        with self._lock:
            return self._sequence
