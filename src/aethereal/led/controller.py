"""Map authoritative backup state to LED state, and drive an LED output.

Implements LED-005: the LED controller consumes the backup engine's authoritative state
(never infers status from filesystem activity). The state->LED mapping and the pattern
rendering are pure/injectable, so they are unit-testable; only the real GPIO output is
Pi-specific.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from aethereal.backup.state_machine import BackupState
from aethereal.led.patterns import LedState, Pattern

_STATE_MAP: dict[BackupState, LedState] = {
    BackupState.IDLE: LedState.READY,
    BackupState.SOURCE_DETECTED: LedState.SOURCE_DETECTED,
    BackupState.MULTIPLE_SOURCES_DETECTED: LedState.SOURCE_DETECTED,
    BackupState.SOURCE_MOUNTING: LedState.SOURCE_DETECTED,
    BackupState.SOURCE_READY: LedState.SOURCE_DETECTED,
    BackupState.SOURCE_PROTECTION_FAILURE: LedState.ERROR,
    BackupState.PREFLIGHT_SCANNING: LedState.PREFLIGHT,
    BackupState.PREFLIGHT_HASHING: LedState.PREFLIGHT,
    BackupState.PREFLIGHT_COMPARING: LedState.PREFLIGHT,
    BackupState.PREFLIGHT_CAPACITY_CHECK: LedState.PREFLIGHT,
    BackupState.PREFLIGHT_READY: LedState.PREFLIGHT,
    BackupState.PREFLIGHT_WARNING: LedState.WARNING,
    BackupState.PREFLIGHT_BLOCKED: LedState.ERROR,
    BackupState.BACKUP_QUEUED: LedState.PREFLIGHT,
    BackupState.BACKUP_COPYING: LedState.COPYING,
    BackupState.BACKUP_VERIFYING: LedState.VERIFYING,
    BackupState.BACKUP_CANCELLING: LedState.WARNING,
    BackupState.BACKUP_COMPLETED: LedState.BACKUP_COMPLETE,
    BackupState.BACKUP_COMPLETED_WITH_WARNINGS: LedState.BACKUP_COMPLETE,
    BackupState.BACKUP_CANCELLED: LedState.WARNING,
    BackupState.BACKUP_FAILED: LedState.ERROR,
    BackupState.SOURCE_SAFE_TO_REMOVE: LedState.SAFE_TO_REMOVE,
    BackupState.RECOVERY_REQUIRED: LedState.WARNING,
    BackupState.RECOVERING: LedState.PREFLIGHT,
}


def led_state_for(backup_state: BackupState) -> LedState:
    """Return the LED state for an authoritative backup state (LED-005)."""
    return _STATE_MAP.get(backup_state, LedState.READY)


class LedOutput(Protocol):
    """Minimal hardware interface: turn the LED on or off."""

    def set(self, on: bool) -> None: ...


class FakeLedOutput:
    """Records the on/off sequence written to the LED (for tests)."""

    def __init__(self) -> None:
        self.writes: list[bool] = []

    def set(self, on: bool) -> None:
        self.writes.append(on)


def render_pattern(
    pattern: Pattern,
    output: LedOutput,
    *,
    sleep: Callable[[float], None],
) -> None:
    """Play one cycle of ``pattern`` against ``output`` using the injected ``sleep``."""
    for step in pattern.steps:
        output.set(step.on)
        sleep(step.duration_s)
    output.set(False)
