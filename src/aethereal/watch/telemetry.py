"""Host telemetry readers (CPU temperature, undervoltage, load, memory, storage).

Implements the data side of PRD THM-001, PWR-002, and LOG-004. Portable metrics come from
``psutil``/``shutil``; Raspberry Pi-specific ones (thermal zone, ``vcgencmd`` undervoltage)
return ``None`` off the Pi. Every read is best-effort — a missing metric is ``None``, never
an exception (WEB-008 "when available").
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import psutil

_THERMAL_ZONE = Path("/sys/class/thermal/thermal_zone0/temp")


@dataclass(frozen=True, slots=True)
class Telemetry:
    """A point-in-time snapshot of host health metrics (any may be None)."""

    cpu_temperature_celsius: float | None
    undervoltage: bool | None
    cpu_percent: float | None
    memory_percent: float | None
    storage_free_bytes: int | None
    storage_total_bytes: int | None


def _safe_float(read: Callable[[], float]) -> float | None:
    try:
        return float(read())
    except Exception:
        return None


def read_cpu_temperature_celsius() -> float | None:
    """CPU temperature in Celsius, or None if unavailable (e.g. on macOS)."""
    if _THERMAL_ZONE.exists():
        try:
            return int(_THERMAL_ZONE.read_text().strip()) / 1000.0
        except (OSError, ValueError):
            return None
    sensors = getattr(psutil, "sensors_temperatures", None)
    if sensors is not None:
        try:
            data = sensors()
        except Exception:
            return None
        for entries in data.values():
            if entries:
                return float(entries[0].current)
    return None


def read_undervoltage() -> bool | None:
    """Whether an undervoltage condition is present (Raspberry Pi ``vcgencmd``)."""
    if sys.platform != "linux":
        return None
    try:
        output = subprocess.run(
            ["vcgencmd", "get_throttled"], check=True, capture_output=True, text=True
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    try:
        value = int(output.strip().split("=")[1], 16)
    except (IndexError, ValueError):
        return None
    return bool(value & 0x1)  # bit 0: under-voltage currently detected


def read_telemetry(storage_path: str = "/") -> Telemetry:
    """Read all host metrics for ``storage_path`` (the appliance system disk)."""
    try:
        usage = psutil.disk_usage(storage_path)
        free: int | None = usage.free
        total: int | None = usage.total
    except Exception:
        free = total = None
    return Telemetry(
        cpu_temperature_celsius=read_cpu_temperature_celsius(),
        undervoltage=read_undervoltage(),
        cpu_percent=_safe_float(lambda: psutil.cpu_percent(interval=None)),
        memory_percent=_safe_float(lambda: psutil.virtual_memory().percent),
        storage_free_bytes=free,
        storage_total_bytes=total,
    )
