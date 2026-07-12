"""Platform abstraction seam.

Isolates OS-specific operations behind a small protocol so the portable core (preflight,
planning, capacity) can be exercised on the macOS development host with a fake, while the
Raspberry Pi uses the real implementation. Only the operations the portable core needs
live here; mount/udev/block-device specifics belong in the Linux-only backup modules.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DiskUsage:
    """Total and available bytes for a filesystem."""

    total_bytes: int
    free_bytes: int


class PlatformOps(Protocol):
    """The host operations the portable core depends on."""

    def disk_usage(self, path: Path | str) -> DiskUsage: ...

    def evict_cache(self, fd: int, offset: int, length: int) -> None:
        """Best-effort request to drop cached pages for a file range (COPY-005).

        On Linux this is ``POSIX_FADV_DONTNEED`` so the subsequent verification read hits
        the storage device rather than the page cache. Where unsupported it is a no-op.
        """
        ...

    def power_off(self) -> None:
        """Shut the device down (WEB-004). Raises NotImplementedError where unsupported."""
        ...

    def reboot(self) -> None:
        """Reboot the device (WEB-004). Raises NotImplementedError where unsupported."""
        ...


class LocalPlatformOps:
    """Real implementation backed by the running OS (works on macOS and Linux)."""

    def disk_usage(self, path: Path | str) -> DiskUsage:
        usage = shutil.disk_usage(str(path))
        return DiskUsage(total_bytes=usage.total, free_bytes=usage.free)

    def evict_cache(self, fd: int, offset: int, length: int) -> None:
        # posix_fadvise is Linux-only; macOS has no equivalent here, so this is a no-op
        # on the dev host and a real cache-eviction request on the Pi.
        fadvise = getattr(os, "posix_fadvise", None)
        dontneed = getattr(os, "POSIX_FADV_DONTNEED", None)
        if fadvise is not None and dontneed is not None:
            fadvise(fd, offset, length, dontneed)

    def power_off(self) -> None:
        self._power(["systemctl", "poweroff"])

    def reboot(self) -> None:
        self._power(["systemctl", "reboot"])

    @staticmethod
    def _power(command: list[str]) -> None:
        # Refuse on non-Linux hosts so a dev machine (macOS) is never shut down.
        if sys.platform != "linux":
            raise NotImplementedError(f"power control is not available on {sys.platform}")
        subprocess.run(command, check=True)


@dataclass(frozen=True, slots=True)
class FakePlatformOps:
    """Deterministic test double with fixed capacity figures."""

    total_bytes: int
    free_bytes: int

    def disk_usage(self, path: Path | str) -> DiskUsage:  # noqa: ARG002 - signature parity
        return DiskUsage(total_bytes=self.total_bytes, free_bytes=self.free_bytes)

    def evict_cache(self, fd: int, offset: int, length: int) -> None:  # noqa: ARG002
        return None

    def power_off(self) -> None:
        return None

    def reboot(self) -> None:
        return None
