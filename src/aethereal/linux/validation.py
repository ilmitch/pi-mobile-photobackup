"""Destination and source validation over a block-device inventory.

Implements PRD DST-001/002/004 (the configured destination must be positively identified
by UUID, be ext4, and be mounted read-write) and the source-candidate side of SRC-008 /
FILE-001A (only vfat/exfat partitions are candidate sources, and the destination is never
a source). Pure logic over :class:`BlockDevice` lists, so it is fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aethereal.linux.devices import BlockDevice, flatten_devices

DEFAULT_SUPPORTED_SOURCE_FILESYSTEMS = ("vfat", "exfat")
REQUIRED_DESTINATION_FILESYSTEM = "ext4"


@dataclass(frozen=True, slots=True)
class DestinationValidation:
    """Result of validating the configured destination (DST-002)."""

    ok: bool
    device: BlockDevice | None
    reasons: tuple[str, ...] = field(default_factory=tuple)


def validate_destination(
    devices: list[BlockDevice],
    *,
    configured_uuid: str,
    required_filesystem: str = REQUIRED_DESTINATION_FILESYSTEM,
) -> DestinationValidation:
    """Validate that exactly one present filesystem is the configured, ext4 destination.

    Checks, in order (DST-001/002/004): the configured UUID is present; it is unique; it
    is the required filesystem (ext4 for the v1 correctness profile); and it is mounted.
    An arbitrary disk can never stand in — matching is by UUID only.
    """
    if not configured_uuid:
        return DestinationValidation(
            ok=False, device=None, reasons=("no destination UUID configured",)
        )

    matches = [d for d in flatten_devices(devices) if d.uuid == configured_uuid]
    if not matches:
        return DestinationValidation(
            ok=False,
            device=None,
            reasons=(f"configured destination {configured_uuid} not present",),
        )
    if len(matches) > 1:
        return DestinationValidation(
            ok=False, device=None, reasons=(f"multiple filesystems share UUID {configured_uuid}",)
        )

    device = matches[0]
    reasons: list[str] = []
    if device.fstype != required_filesystem:
        reasons.append(
            f"destination filesystem is {device.fstype!r}, required {required_filesystem!r}"
        )
    if not device.mountpoint:
        reasons.append("destination is not mounted")
    if device.read_only:
        reasons.append("destination is mounted read-only")

    return DestinationValidation(ok=not reasons, device=device, reasons=tuple(reasons))


def find_source_candidates(
    devices: list[BlockDevice],
    *,
    destination_uuid: str,
    supported_filesystems: tuple[str, ...] = DEFAULT_SUPPORTED_SOURCE_FILESYSTEMS,
) -> list[BlockDevice]:
    """Return partitions that are candidate sources (FILE-001A).

    A candidate is a filesystem whose type is supported (vfat/exfat) and whose UUID is not
    the configured destination. Whole-disk nodes and the destination are excluded.
    """
    candidates: list[BlockDevice] = []
    for device in flatten_devices(devices):
        if device.fstype not in supported_filesystems:
            continue
        if device.uuid is not None and device.uuid == destination_uuid:
            continue
        candidates.append(device)
    return candidates
