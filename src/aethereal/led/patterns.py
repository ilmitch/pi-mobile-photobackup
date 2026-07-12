"""LED status patterns and progress buckets (PRD LED-003, LED-004).

Pure data + logic: the visible LED states, their blink patterns, and the copy-progress
overlay. No hardware here — a driver renders these against an ``LedOutput``. Keeping this
pure makes the timing protocol and progress mapping unit-testable on any host.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LedState(str, Enum):
    """The states the physical LED communicates (LED-003)."""

    OFF = "OFF"
    BOOTING = "BOOTING"
    READY = "READY"
    SOURCE_DETECTED = "SOURCE_DETECTED"
    PREFLIGHT = "PREFLIGHT"
    COPYING = "COPYING"
    VERIFYING = "VERIFYING"
    SAFE_TO_REMOVE = "SAFE_TO_REMOVE"
    BACKUP_COMPLETE = "BACKUP_COMPLETE"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class PatternStep:
    """Hold the LED on/off for a duration."""

    on: bool
    duration_s: float


@dataclass(frozen=True, slots=True)
class Pattern:
    """A sequence of steps, optionally repeating."""

    steps: tuple[PatternStep, ...]
    repeat: bool


def _on(duration: float) -> PatternStep:
    return PatternStep(True, duration)


def _off(duration: float) -> PatternStep:
    return PatternStep(False, duration)


def _blinks(count: int, on_s: float = 0.1, off_s: float = 0.1) -> tuple[PatternStep, ...]:
    steps: list[PatternStep] = []
    for _ in range(count):
        steps.extend((_on(on_s), _off(off_s)))
    return tuple(steps)


# LED-003 protocol table.
PATTERNS: dict[LedState, Pattern] = {
    LedState.OFF: Pattern((_off(1.0),), repeat=True),
    LedState.BOOTING: Pattern((*_blinks(2), _off(0.5)), repeat=True),
    LedState.READY: Pattern((_on(0.1), _off(2.9)), repeat=True),
    LedState.SOURCE_DETECTED: Pattern((*_blinks(3), _off(0.5)), repeat=False),
    LedState.PREFLIGHT: Pattern((*_blinks(2), _off(0.6)), repeat=True),
    LedState.COPYING: Pattern((_on(1.0), _off(1.0)), repeat=True),
    LedState.VERIFYING: Pattern((_on(0.6), _off(0.2), _on(0.15), _off(0.6)), repeat=True),
    LedState.SAFE_TO_REMOVE: Pattern((_on(1.0), _off(0.3), *_blinks(4)), repeat=True),
    LedState.BACKUP_COMPLETE: Pattern(
        (_on(5.0), _off(0.3), _on(1.0), _off(0.3), *_blinks(4)), repeat=False
    ),
    LedState.WARNING: Pattern((*_blinks(3), _off(5.0)), repeat=True),
    LedState.ERROR: Pattern((*_blinks(5), _off(0.5)), repeat=True),
    # SOS: ... --- ...
    LedState.CRITICAL: Pattern(
        (*_blinks(3, 0.15, 0.15), *_blinks(3, 0.4, 0.15), *_blinks(3, 0.15, 0.15), _off(1.0)),
        repeat=True,
    ),
}


def pattern_for(led_state: LedState) -> Pattern:
    return PATTERNS[led_state]


def progress_bucket(percent: float) -> int:
    """LED-004: map copy percent to a blink count (0-4). Verified by UT-005 boundaries."""
    if percent >= 100:
        return 4
    if percent >= 75:
        return 3
    if percent >= 50:
        return 2
    if percent >= 25:
        return 1
    return 0


def progress_overlay(bucket: int) -> Pattern:
    """LED-004: long pulse, pause, then ``bucket`` short blinks (0-4)."""
    if not 0 <= bucket <= 4:
        raise ValueError("progress bucket must be 0..4")
    steps: list[PatternStep] = [_on(0.8), _off(0.4)]
    steps.extend(_blinks(bucket, 0.15, 0.2))
    steps.append(_off(0.8))
    return Pattern(tuple(steps), repeat=False)
