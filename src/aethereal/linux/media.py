"""Media manager: detect source cards, mount them read-only, validate the destination.

Ties the Linux primitives (devices, validation, mount) into the appliance media lifecycle
(single vs. multiple sources, SRC-008) and produces a :class:`SourceRef` the web layer
consumes. Device enumeration and mounting are injected, so the manager's selection logic is
fully unit-testable on any host with fakes; the real implementations are Linux-only.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Protocol

from aethereal.common.source import SourceRef
from aethereal.linux.devices import BlockDevice, list_block_devices
from aethereal.linux.mount import SourceMount, mount_source_read_only, unmount
from aethereal.linux.validation import (
    DEFAULT_SUPPORTED_SOURCE_FILESYSTEMS,
    DestinationValidation,
    find_source_candidates,
    validate_destination,
)


class MediaState(str, Enum):
    """How many usable source cards are currently present (SRC-008)."""

    NO_SOURCE = "NO_SOURCE"
    SINGLE_SOURCE = "SINGLE_SOURCE"
    MULTIPLE_SOURCES = "MULTIPLE_SOURCES"


class MountService(Protocol):
    """The mount operations the media manager needs (injected for testability)."""

    def mount_source_read_only(
        self, device: str, mount_point: Path, *, fstype: str | None
    ) -> SourceMount: ...

    def unmount(self, mount_point: Path) -> None: ...


class LinuxMountService:
    """Real mount service backed by ``aethereal.linux.mount`` (Linux only)."""

    def mount_source_read_only(
        self, device: str, mount_point: Path, *, fstype: str | None
    ) -> SourceMount:
        return mount_source_read_only(device, mount_point, fstype=fstype)

    def unmount(self, mount_point: Path) -> None:
        unmount(mount_point)


def _default_name(device: BlockDevice) -> str:
    if device.label:
        return device.label
    if device.uuid:
        return f"CARD-{device.uuid[:8]}"
    return device.name or "CARD"


def _device_key(device: BlockDevice) -> str:
    return device.path or device.name


class MediaManager:
    """Owns source detection, read-only mounting, and destination validation."""

    def __init__(
        self,
        *,
        destination_uuid: str,
        source_mount_root: Path | str,
        device_lister: Callable[[], list[BlockDevice]] = list_block_devices,
        mount_service: MountService | None = None,
        supported_filesystems: tuple[str, ...] = DEFAULT_SUPPORTED_SOURCE_FILESYSTEMS,
        name_resolver: Callable[[BlockDevice], str] = _default_name,
    ) -> None:
        self._destination_uuid = destination_uuid
        self._mount_root = Path(source_mount_root)
        self._list = device_lister
        self._mounts: MountService = mount_service or LinuxMountService()
        self._supported = supported_filesystems
        self._name = name_resolver
        self._mounted: dict[str, SourceMount] = {}
        self._selected_uuid: str | None = None

    def source_candidates(self) -> list[BlockDevice]:
        """Candidate source cards currently present (vfat/exfat, not the destination)."""
        return find_source_candidates(
            self._list(),
            destination_uuid=self._destination_uuid,
            supported_filesystems=self._supported,
        )

    def state(self) -> MediaState:
        count = len(self.source_candidates())
        if count == 0:
            return MediaState.NO_SOURCE
        if count == 1:
            return MediaState.SINGLE_SOURCE
        return MediaState.MULTIPLE_SOURCES

    def destination(self) -> DestinationValidation:
        """Validate the configured destination (DST-001/002/004)."""
        return validate_destination(self._list(), configured_uuid=self._destination_uuid)

    def select(self, uuid: str) -> None:
        """Choose which card is active when multiple are present (SRC-008)."""
        self._selected_uuid = uuid

    def current_source(self) -> SourceRef | None:
        """Return the active source, mounting it read-only on demand.

        None when there is no card, or when several are present and none is selected. Cards
        that are no longer present are unmounted and forgotten.
        """
        candidates = self.source_candidates()
        self._release_absent(candidates)
        device = self._select_device(candidates)
        if device is None:
            return None
        mount = self._ensure_mounted(device)
        return SourceRef(root=Path(mount.mount_point), logical_name=self._name(device))

    def eject_all(self) -> None:
        """Unmount every tracked source (used during shutdown / safe removal)."""
        for key in list(self._mounted):
            self._unmount_key(key)

    # --- internals ---

    def _select_device(self, candidates: list[BlockDevice]) -> BlockDevice | None:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        if self._selected_uuid is not None:
            for candidate in candidates:
                if candidate.uuid == self._selected_uuid:
                    return candidate
        return None

    def _ensure_mounted(self, device: BlockDevice) -> SourceMount:
        key = _device_key(device)
        existing = self._mounted.get(key)
        if existing is not None:
            return existing
        mount_point = self._mount_root / (device.uuid or device.name)
        mount = self._mounts.mount_source_read_only(
            device.path or "", mount_point, fstype=device.fstype
        )
        self._mounted[key] = mount
        return mount

    def _release_absent(self, present: list[BlockDevice]) -> None:
        present_keys = {_device_key(d) for d in present}
        for key in list(self._mounted):
            if key not in present_keys:
                self._unmount_key(key)

    def _unmount_key(self, key: str) -> None:
        mount = self._mounted.pop(key, None)
        if mount is None:
            return
        try:
            self._mounts.unmount(Path(mount.mount_point))
        except Exception:  # best-effort cleanup; a failed unmount must not break detection
            pass
