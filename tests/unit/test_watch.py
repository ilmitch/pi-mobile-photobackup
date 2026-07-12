"""Unit tests for the watch package: telemetry, thresholds, clock trust (TIME/THM/PWR)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aethereal.watch.clock import (
    ClockState,
    ClockTrust,
    clock_skew_seconds,
    exceeds_skew,
)
from aethereal.watch.service import WatchService
from aethereal.watch.telemetry import Telemetry, read_telemetry
from aethereal.watch.thresholds import WarningKind, evaluate


def _telemetry(**kwargs: object) -> Telemetry:
    base: dict[str, object] = {
        "cpu_temperature_celsius": None,
        "undervoltage": None,
        "cpu_percent": 10.0,
        "memory_percent": 20.0,
        "storage_free_bytes": 500_000_000_000,
        "storage_total_bytes": 1_000_000_000_000,
    }
    base.update(kwargs)
    return Telemetry(**base)  # type: ignore[arg-type]


# --- telemetry ---


def test_read_telemetry_returns_portable_metrics() -> None:
    telemetry = read_telemetry("/")
    # These are always available (psutil/shutil), even on macOS.
    assert telemetry.cpu_percent is not None
    assert telemetry.memory_percent is not None
    assert telemetry.storage_total_bytes is not None
    assert telemetry.storage_free_bytes is not None


# --- thresholds ---


def test_no_warnings_when_healthy() -> None:
    assert evaluate(_telemetry(), thermal_warning_celsius=75, storage_critical_bytes=1) == []


def test_thermal_warning() -> None:
    warnings = evaluate(
        _telemetry(cpu_temperature_celsius=80.0),
        thermal_warning_celsius=75,
        storage_critical_bytes=1,
    )
    assert [w.kind for w in warnings] == [WarningKind.THERMAL]


def test_power_warning_on_undervoltage() -> None:
    warnings = evaluate(
        _telemetry(undervoltage=True), thermal_warning_celsius=75, storage_critical_bytes=1
    )
    assert WarningKind.POWER in [w.kind for w in warnings]


def test_storage_warning_when_low() -> None:
    warnings = evaluate(
        _telemetry(storage_free_bytes=500),
        thermal_warning_celsius=75,
        storage_critical_bytes=1_000_000_000,
    )
    assert WarningKind.STORAGE in [w.kind for w in warnings]


def test_missing_metrics_do_not_warn() -> None:
    # Off-Pi, temperature/undervoltage are None and must not trip warnings.
    warnings = evaluate(
        _telemetry(cpu_temperature_celsius=None, undervoltage=None),
        thermal_warning_celsius=75,
        storage_critical_bytes=1,
    )
    assert warnings == []


# --- clock trust ---


def test_clock_starts_untrusted() -> None:
    clock = ClockTrust()
    assert clock.state is ClockState.CLOCK_UNTRUSTED
    assert clock.is_trusted is False


def test_clock_trust_transitions() -> None:
    clock = ClockTrust()
    clock.mark_phone_synced()
    assert clock.state is ClockState.CLOCK_PHONE_SYNCED
    assert clock.is_trusted is True
    clock.mark_untrusted()
    assert clock.is_trusted is False


def test_clock_skew() -> None:
    now = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)
    later = now + timedelta(seconds=400)
    assert clock_skew_seconds(now, later) == 400
    assert exceeds_skew(now, later, max_skew_seconds=300) is True
    assert exceeds_skew(now, later, max_skew_seconds=500) is False


# --- watch service ---


def test_watch_service_snapshot() -> None:
    watch = WatchService(
        thermal_warning_celsius=75,
        storage_critical_bytes=1_000_000_000,
        telemetry_reader=lambda _path: _telemetry(
            cpu_temperature_celsius=90.0, storage_free_bytes=100
        ),
    )
    health = watch.snapshot()
    kinds = {w.kind for w in health.warnings}
    assert WarningKind.THERMAL in kinds
    assert WarningKind.STORAGE in kinds
    assert health.clock_state is ClockState.CLOCK_UNTRUSTED
    watch.clock.mark_rtc()
    assert watch.snapshot().clock_state is ClockState.CLOCK_RTC
