"""Unit tests for preflight capacity math.

Covers Verification Plan v0.3 UT-002 (safety margin) and UT-003 (capacity calculation
and boundaries), plus the PRE-007 / ST-PRE-004 exact-boundary rule.
"""

from __future__ import annotations

import pytest

from aethereal.backup.capacity import (
    DEFAULT_RESERVE_FLOOR_BYTES,
    assess_capacity,
    operational_reserve_bytes,
    safety_margin_bytes,
)

GB = 1_000_000_000  # decimal gigabyte, matching config safety_margin_min_bytes
TB = 1_000_000_000_000
MIB = 1024 * 1024


# --- UT-002: safety margin = max(percent of capacity, min_bytes) ---


def test_safety_margin_percent_greater_than_floor() -> None:
    # 5% of 1 TB = 50 GB, which exceeds the 10 GB floor.
    assert safety_margin_bytes(1 * TB) == 50 * GB


def test_safety_margin_floor_greater_than_percent() -> None:
    # 5% of 100 GB = 5 GB, below the 10 GB floor -> floor wins.
    assert safety_margin_bytes(100 * GB) == 10 * GB


def test_safety_margin_exact_equality() -> None:
    # 5% of 200 GB = 10 GB == floor.
    assert safety_margin_bytes(200 * GB) == 10 * GB


def test_safety_margin_rejects_bad_percent() -> None:
    with pytest.raises(ValueError):
        safety_margin_bytes(1 * TB, percent=101)


# --- PRE-006: operational reserve = max(largest_new_file, floor) + metadata ---


def test_reserve_uses_floor_when_files_small() -> None:
    assert operational_reserve_bytes(10 * MIB) == DEFAULT_RESERVE_FLOOR_BYTES


def test_reserve_uses_largest_file_when_bigger_than_floor() -> None:
    huge = 4 * GB
    assert operational_reserve_bytes(huge) == huge


def test_reserve_adds_metadata_estimate() -> None:
    assert operational_reserve_bytes(0, metadata_estimate_bytes=1234) == (
        DEFAULT_RESERVE_FLOOR_BYTES + 1234
    )


# --- UT-003: required = new + reserve + margin, with boundaries ---


def test_required_is_sum_of_components() -> None:
    a = assess_capacity(
        destination_capacity_bytes=1 * TB,
        available_bytes=1 * TB,
        new_file_bytes=100 * GB,
        largest_new_file_bytes=2 * GB,
    )
    assert a.required_bytes == (
        a.new_file_bytes + a.operational_reserve_bytes + a.safety_margin_bytes
    )
    assert a.operational_reserve_bytes == 2 * GB  # largest file > floor
    assert a.safety_margin_bytes == 50 * GB  # 5% of 1 TB


def test_exact_capacity_boundary_is_accepted() -> None:
    # ST-PRE-004: available == required must be sufficient with zero shortfall.
    probe = assess_capacity(
        destination_capacity_bytes=1 * TB,
        available_bytes=1 * TB,
        new_file_bytes=100 * GB,
        largest_new_file_bytes=2 * GB,
    )
    at_boundary = assess_capacity(
        destination_capacity_bytes=1 * TB,
        available_bytes=probe.required_bytes,
        new_file_bytes=100 * GB,
        largest_new_file_bytes=2 * GB,
    )
    assert at_boundary.sufficient is True
    assert at_boundary.shortfall_bytes == 0


def test_one_byte_short_is_blocked() -> None:
    # ST-PRE-004: available == required - 1 must be blocked with shortfall 1.
    probe = assess_capacity(
        destination_capacity_bytes=1 * TB,
        available_bytes=1 * TB,
        new_file_bytes=100 * GB,
        largest_new_file_bytes=2 * GB,
    )
    short = assess_capacity(
        destination_capacity_bytes=1 * TB,
        available_bytes=probe.required_bytes - 1,
        new_file_bytes=100 * GB,
        largest_new_file_bytes=2 * GB,
    )
    assert short.sufficient is False
    assert short.shortfall_bytes == 1


def test_zero_new_bytes_still_reserves_headroom() -> None:
    a = assess_capacity(
        destination_capacity_bytes=1 * TB,
        available_bytes=1 * TB,
        new_file_bytes=0,
        largest_new_file_bytes=0,
    )
    assert a.new_file_bytes == 0
    assert a.required_bytes == a.operational_reserve_bytes + a.safety_margin_bytes
    assert a.estimated_available_after_bytes == a.available_bytes


def test_single_very_large_file_drives_reserve() -> None:
    a = assess_capacity(
        destination_capacity_bytes=2 * TB,
        available_bytes=2 * TB,
        new_file_bytes=15 * GB,
        largest_new_file_bytes=15 * GB,
    )
    assert a.operational_reserve_bytes == 15 * GB


def test_estimated_available_after_subtracts_new_bytes() -> None:
    a = assess_capacity(
        destination_capacity_bytes=1 * TB,
        available_bytes=500 * GB,
        new_file_bytes=100 * GB,
        largest_new_file_bytes=2 * GB,
    )
    assert a.estimated_available_after_bytes == 400 * GB


def test_negative_available_rejected() -> None:
    with pytest.raises(ValueError):
        assess_capacity(
            destination_capacity_bytes=1 * TB,
            available_bytes=-1,
            new_file_bytes=0,
            largest_new_file_bytes=0,
        )
