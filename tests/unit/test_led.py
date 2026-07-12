"""Unit tests for the LED pattern engine (LED-003/004/005, UT-005 progress buckets)."""

from __future__ import annotations

import pytest

from aethereal.backup.state_machine import BackupState
from aethereal.led.controller import (
    FakeLedOutput,
    led_state_for,
    render_pattern,
)
from aethereal.led.patterns import (
    PATTERNS,
    LedState,
    Pattern,
    pattern_for,
    progress_bucket,
    progress_overlay,
)


@pytest.mark.parametrize(
    ("percent", "bucket"),
    [
        (0, 0),
        (24.999, 0),
        (25, 1),
        (49.999, 1),
        (50, 2),
        (74.999, 2),
        (75, 3),
        (99.999, 3),
        (100, 4),
    ],
)
def test_progress_buckets(percent: float, bucket: int) -> None:
    assert progress_bucket(percent) == bucket


def test_progress_overlay_has_bucket_blinks() -> None:
    # A "blink" is an on-step; the overlay is [long pulse][pause][bucket short blinks].
    overlay = progress_overlay(3)
    short_on_steps = sum(1 for s in overlay.steps if s.on and s.duration_s <= 0.2)
    assert short_on_steps == 3


def test_progress_overlay_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        progress_overlay(5)


def test_every_led_state_has_a_pattern() -> None:
    for led_state in LedState:
        assert isinstance(pattern_for(led_state), Pattern)


def test_state_map_is_total() -> None:
    # Every backup state maps to an LED state (no silent default gaps).
    for backup_state in BackupState:
        assert isinstance(led_state_for(backup_state), LedState)


@pytest.mark.parametrize(
    ("backup_state", "led_state"),
    [
        (BackupState.IDLE, LedState.READY),
        (BackupState.BACKUP_COPYING, LedState.COPYING),
        (BackupState.BACKUP_VERIFYING, LedState.VERIFYING),
        (BackupState.BACKUP_COMPLETED, LedState.BACKUP_COMPLETE),
        (BackupState.SOURCE_SAFE_TO_REMOVE, LedState.SAFE_TO_REMOVE),
        (BackupState.BACKUP_FAILED, LedState.ERROR),
        (BackupState.SOURCE_PROTECTION_FAILURE, LedState.ERROR),
        (BackupState.PREFLIGHT_BLOCKED, LedState.ERROR),
        (BackupState.PREFLIGHT_HASHING, LedState.PREFLIGHT),
        (BackupState.PREFLIGHT_WARNING, LedState.WARNING),
    ],
)
def test_state_mapping(backup_state: BackupState, led_state: LedState) -> None:
    assert led_state_for(backup_state) is led_state


def test_render_pattern_writes_steps_then_off() -> None:
    output = FakeLedOutput()
    ticks: list[float] = []
    render_pattern(PATTERNS[LedState.READY], output, sleep=ticks.append)
    # READY = on(0.1), off(2.9); render finishes with a trailing off.
    assert output.writes == [True, False, False]
    assert ticks == [0.1, 2.9]


def test_copying_pattern_repeats() -> None:
    assert PATTERNS[LedState.COPYING].repeat is True
