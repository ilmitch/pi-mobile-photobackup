"""Threshold evaluation: turn telemetry into warning conditions.

Implements PRD THM-002 (thermal warning), PWR-002 (power warning), and LOG-004 (system
storage protection). Pure logic over a :class:`Telemetry` snapshot, fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from aethereal.watch.telemetry import Telemetry


class WarningKind(str, Enum):
    THERMAL = "THERMAL"
    POWER = "POWER"
    STORAGE = "STORAGE"


@dataclass(frozen=True, slots=True)
class HealthWarning:
    kind: WarningKind
    message: str


def evaluate(
    telemetry: Telemetry,
    *,
    thermal_warning_celsius: float,
    storage_critical_bytes: int,
) -> list[HealthWarning]:
    """Return the active warnings implied by ``telemetry`` and the configured thresholds."""
    warnings: list[HealthWarning] = []

    temperature = telemetry.cpu_temperature_celsius
    if temperature is not None and temperature >= thermal_warning_celsius:
        warnings.append(
            HealthWarning(
                WarningKind.THERMAL,
                f"CPU temperature {temperature:.1f}C at or above {thermal_warning_celsius}C",
            )
        )

    if telemetry.undervoltage:
        warnings.append(HealthWarning(WarningKind.POWER, "undervoltage detected"))

    free = telemetry.storage_free_bytes
    if free is not None and free <= storage_critical_bytes:
        warnings.append(
            HealthWarning(WarningKind.STORAGE, f"system storage low: {free} bytes free")
        )

    return warnings
