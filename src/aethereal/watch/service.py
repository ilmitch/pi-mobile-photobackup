"""System watcher: snapshot host health and clock trust for the web/LED layers.

Composes telemetry + thresholds + clock trust (PRD sections 27-29) into a single
``SystemHealth`` snapshot. The telemetry reader is injectable so the service is testable
with deterministic values.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from aethereal.watch.clock import ClockState, ClockTrust
from aethereal.watch.telemetry import Telemetry, read_telemetry
from aethereal.watch.thresholds import HealthWarning, evaluate


@dataclass(frozen=True, slots=True)
class SystemHealth:
    telemetry: Telemetry
    warnings: tuple[HealthWarning, ...]
    clock_state: ClockState


class WatchService:
    """Reads telemetry and evaluates warnings against configured thresholds."""

    def __init__(
        self,
        *,
        thermal_warning_celsius: float,
        storage_critical_bytes: int,
        storage_path: str = "/",
        clock: ClockTrust | None = None,
        telemetry_reader: Callable[[str], Telemetry] = read_telemetry,
    ) -> None:
        self._thermal_warning_celsius = thermal_warning_celsius
        self._storage_critical_bytes = storage_critical_bytes
        self._storage_path = storage_path
        self.clock = clock or ClockTrust()
        self._read = telemetry_reader

    def snapshot(self) -> SystemHealth:
        telemetry = self._read(self._storage_path)
        warnings = evaluate(
            telemetry,
            thermal_warning_celsius=self._thermal_warning_celsius,
            storage_critical_bytes=self._storage_critical_bytes,
        )
        return SystemHealth(
            telemetry=telemetry,
            warnings=tuple(warnings),
            clock_state=self.clock.state,
        )
