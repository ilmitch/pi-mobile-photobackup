"""Preflight destination-capacity math.

Implements PRD v0.3 sections PRE-004 (capacity calculation), PRE-005 (safety margin),
PRE-006 (operational reserve), and PRE-007 (insufficient capacity), and Implementation
Plan v0.3 section 13.

Pure integer-byte arithmetic with no I/O, so it is deterministic and fully unit-testable
(Verification Plan UT-002, UT-003). The preflight orchestrator supplies the measured
byte figures; this module never touches the filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass

# PRE-005 defaults (mirror config/default.yaml: 5 percent, 10 GB decimal).
DEFAULT_SAFETY_MARGIN_PERCENT = 5
DEFAULT_SAFETY_MARGIN_MIN_BYTES = 10_000_000_000

# PRE-006 / Impl §13: operational reserve floor of 512 MiB.
DEFAULT_RESERVE_FLOOR_BYTES = 512 * 1024 * 1024


def safety_margin_bytes(
    destination_capacity_bytes: int,
    *,
    percent: int = DEFAULT_SAFETY_MARGIN_PERCENT,
    min_bytes: int = DEFAULT_SAFETY_MARGIN_MIN_BYTES,
) -> int:
    """PRE-005: the greater of ``percent`` of total capacity, or ``min_bytes``."""
    if destination_capacity_bytes < 0:
        raise ValueError("destination_capacity_bytes must be non-negative")
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    if min_bytes < 0:
        raise ValueError("min_bytes must be non-negative")
    percent_component = destination_capacity_bytes * percent // 100
    return max(percent_component, min_bytes)


def operational_reserve_bytes(
    largest_new_file_bytes: int,
    *,
    metadata_estimate_bytes: int = 0,
    reserve_floor_bytes: int = DEFAULT_RESERVE_FLOOR_BYTES,
) -> int:
    """PRE-006 / Impl §13: ``max(largest_new_file, floor) + metadata_estimate``.

    Covers the in-flight temporary object, manifest/session metadata growth, logs, and
    verification-related filesystem operations.
    """
    if largest_new_file_bytes < 0:
        raise ValueError("largest_new_file_bytes must be non-negative")
    if metadata_estimate_bytes < 0:
        raise ValueError("metadata_estimate_bytes must be non-negative")
    if reserve_floor_bytes < 0:
        raise ValueError("reserve_floor_bytes must be non-negative")
    return max(largest_new_file_bytes, reserve_floor_bytes) + metadata_estimate_bytes


@dataclass(frozen=True, slots=True)
class CapacityAssessment:
    """The full PRE-004/PRE-007 capacity picture for a single planned backup."""

    destination_capacity_bytes: int
    available_bytes: int
    new_file_bytes: int
    operational_reserve_bytes: int
    safety_margin_bytes: int
    required_bytes: int
    shortfall_bytes: int
    estimated_available_after_bytes: int
    sufficient: bool


def assess_capacity(
    *,
    destination_capacity_bytes: int,
    available_bytes: int,
    new_file_bytes: int,
    largest_new_file_bytes: int,
    safety_margin_percent: int = DEFAULT_SAFETY_MARGIN_PERCENT,
    safety_margin_min_bytes: int = DEFAULT_SAFETY_MARGIN_MIN_BYTES,
    metadata_estimate_bytes: int = 0,
    reserve_floor_bytes: int = DEFAULT_RESERVE_FLOOR_BYTES,
) -> CapacityAssessment:
    """Compute the complete capacity assessment for preflight.

    ``required = new_file_bytes + operational_reserve + safety_margin`` (PRE-004).
    A backup is sufficient only when ``available >= required``; the exact boundary is
    accepted and one byte short is blocked (PRE-007 / ST-PRE-004).
    """
    for name, value in (
        ("available_bytes", available_bytes),
        ("new_file_bytes", new_file_bytes),
    ):
        if value < 0:
            raise ValueError(f"{name} must be non-negative")

    margin = safety_margin_bytes(
        destination_capacity_bytes,
        percent=safety_margin_percent,
        min_bytes=safety_margin_min_bytes,
    )
    reserve = operational_reserve_bytes(
        largest_new_file_bytes,
        metadata_estimate_bytes=metadata_estimate_bytes,
        reserve_floor_bytes=reserve_floor_bytes,
    )
    required = new_file_bytes + reserve + margin
    sufficient = available_bytes >= required
    shortfall = 0 if sufficient else required - available_bytes

    return CapacityAssessment(
        destination_capacity_bytes=destination_capacity_bytes,
        available_bytes=available_bytes,
        new_file_bytes=new_file_bytes,
        operational_reserve_bytes=reserve,
        safety_margin_bytes=margin,
        required_bytes=required,
        shortfall_bytes=shortfall,
        estimated_available_after_bytes=available_bytes - new_file_bytes,
        sufficient=sufficient,
    )
