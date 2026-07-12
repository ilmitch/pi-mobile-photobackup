"""Trusted wall-clock model (PRD TIME-001..003).

A clockless, offline Raspberry Pi must not stamp backup sessions with a bogus date. This
tracks an explicit trust level; a dated backup session may only be created once the clock
is trusted (RTC, phone sync, or network time). Pure and unit-testable.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum


class ClockState(str, Enum):
    CLOCK_UNTRUSTED = "CLOCK_UNTRUSTED"
    CLOCK_RTC = "CLOCK_RTC"
    CLOCK_PHONE_SYNCED = "CLOCK_PHONE_SYNCED"
    CLOCK_NETWORK_SYNCED = "CLOCK_NETWORK_SYNCED"


class ClockTrust:
    """Tracks the appliance's wall-clock trust state (TIME-001)."""

    def __init__(self, initial: ClockState = ClockState.CLOCK_UNTRUSTED) -> None:
        self._state = initial

    @property
    def state(self) -> ClockState:
        return self._state

    @property
    def is_trusted(self) -> bool:
        """A dated session may be created only when this is True (TIME-001)."""
        return self._state is not ClockState.CLOCK_UNTRUSTED

    def mark_rtc(self) -> None:
        self._state = ClockState.CLOCK_RTC

    def mark_phone_synced(self) -> None:
        self._state = ClockState.CLOCK_PHONE_SYNCED

    def mark_network_synced(self) -> None:
        self._state = ClockState.CLOCK_NETWORK_SYNCED

    def mark_untrusted(self) -> None:
        self._state = ClockState.CLOCK_UNTRUSTED


def clock_skew_seconds(a: datetime, b: datetime) -> float:
    """Absolute difference between two timestamps, in seconds."""
    return abs((a - b).total_seconds())


def exceeds_skew(system_time: datetime, reference_time: datetime, max_skew_seconds: int) -> bool:
    """Whether the system clock differs from a reference by more than the allowed skew."""
    return clock_skew_seconds(system_time, reference_time) > max_skew_seconds
