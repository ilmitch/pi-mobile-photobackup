"""Read-only source mounting and enforcement (PRD SRC-001/002, Impl Plan v0.3 section 9).

Belt-and-suspenders protection of source media: request block-device read-only *and* mount
read-only, then confirm the mount is *effectively* read-only via ``/proc/self/mountinfo``.
A source that does not end up read-only raises :class:`SourceProtectionFailure` and the
mount is torn down. All operations are Linux-only (subprocess to util-linux tools) and are
integration-tested with loopback devices in the privileged container.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from aethereal.linux.mountinfo import find_by_mount_point, read_mountinfo


class SourceProtectionFailure(Exception):
    """Raised when a source cannot be confirmed read-only (SRC-002)."""


@dataclass(frozen=True, slots=True)
class SourceMount:
    """A successfully mounted, verified read-only source."""

    device: str
    mount_point: str
    block_read_only: bool
    mount_read_only: bool


def _run(command: list[str]) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def _require_linux() -> None:
    if sys.platform != "linux":
        raise NotImplementedError(f"source mounting requires Linux, not {sys.platform}")


def set_block_read_only(device: str, *, read_only: bool = True) -> None:
    """Set the block device read-only (or writable) at the kernel block layer."""
    _require_linux()
    _run(["blockdev", "--setro" if read_only else "--setrw", device])


def get_block_read_only(device: str) -> bool:
    """Return whether the block device is currently read-only (``blockdev --getro``)."""
    _require_linux()
    return _run(["blockdev", "--getro", device]).strip() == "1"


def mount_read_only(device: str, mount_point: Path | str, *, fstype: str | None = None) -> None:
    """Mount ``device`` read-only at ``mount_point`` with hardened options."""
    _require_linux()
    point = Path(mount_point)
    point.mkdir(parents=True, exist_ok=True)
    command = ["mount", "-o", "ro,noexec,nodev,nosuid"]
    if fstype is not None:
        command += ["-t", fstype]
    command += [device, str(point)]
    _run(command)


def unmount(mount_point: Path | str) -> None:
    """Unmount the filesystem at ``mount_point``."""
    _require_linux()
    _run(["umount", str(mount_point)])


def effective_read_only(mount_point: Path | str) -> bool:
    """Return whether the mount at ``mount_point`` is effectively read-only (SRC-002)."""
    entry = find_by_mount_point(read_mountinfo(), str(mount_point))
    return entry is not None and entry.read_only


def mount_source_read_only(
    device: str, mount_point: Path | str, *, fstype: str | None = None
) -> SourceMount:
    """Enforce and verify read-only access to a source device (SRC-001/002).

    Requests block-device read-only, mounts read-only, then confirms the *effective* mount
    state. If the mount is not read-only it is torn down and ``SourceProtectionFailure`` is
    raised — the backup must never proceed against a writable source.
    """
    _require_linux()
    set_block_read_only(device, read_only=True)
    block_ro = get_block_read_only(device)
    mount_read_only(device, mount_point, fstype=fstype)
    mount_ro = effective_read_only(mount_point)
    if not mount_ro:
        try:
            unmount(mount_point)
        except subprocess.CalledProcessError:
            pass
        raise SourceProtectionFailure(f"source {device} did not mount read-only")
    return SourceMount(
        device=device,
        mount_point=str(mount_point),
        block_read_only=block_ro,
        mount_read_only=mount_ro,
    )
