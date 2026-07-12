"""Unit tests for the event model and bus (Impl §19, §20 reconnect support)."""

from __future__ import annotations

from aethereal.common.events import Event, EventBus, EventSeverity, EventType


def _publish(bus: EventBus, message: str) -> Event:
    return bus.publish(
        EventType.SYSTEM_STATE_CHANGED, EventSeverity.INFO, "backupd", message
    )


def test_sequences_are_monotonic() -> None:
    bus = EventBus()
    e1 = _publish(bus, "one")
    e2 = _publish(bus, "two")
    e3 = _publish(bus, "three")
    assert [e1.sequence, e2.sequence, e3.sequence] == [1, 2, 3]
    assert bus.last_sequence == 3


def test_subscriber_receives_events() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(received.append)
    _publish(bus, "hello")
    assert len(received) == 1
    assert received[0].message == "hello"


def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    received: list[Event] = []
    unsubscribe = bus.subscribe(received.append)
    _publish(bus, "first")
    unsubscribe()
    _publish(bus, "second")
    assert [e.message for e in received] == ["first"]


def test_events_since_returns_gap() -> None:
    bus = EventBus()
    _publish(bus, "a")
    _publish(bus, "b")
    _publish(bus, "c")
    gap = bus.events_since(1)
    assert [e.message for e in gap] == ["b", "c"]


def test_recent_buffer_is_bounded() -> None:
    bus = EventBus(recent_capacity=2)
    for i in range(5):
        _publish(bus, str(i))
    # Only the last two remain buffered; older ones are dropped.
    assert [e.message for e in bus.events_since(0)] == ["3", "4"]
    assert bus.last_sequence == 5


def test_details_are_copied_defensively() -> None:
    bus = EventBus()
    payload = {"file": "IMG_1.CR3"}
    event = bus.publish(
        EventType.FILE_COPY_STARTED,
        EventSeverity.INFO,
        "copier",
        "start",
        details=payload,
    )
    payload["file"] = "MUTATED"
    assert event.details["file"] == "IMG_1.CR3"


def test_event_is_frozen() -> None:
    bus = EventBus()
    event = _publish(bus, "x")
    try:
        event.sequence = 99  # type: ignore[misc]
    except AttributeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Event should be immutable")
