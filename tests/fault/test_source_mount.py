"""Loopback integration tests for read-only source enforcement (SRC-001/002, DST-004).

These require Linux + root + loop-device access, so they run under
``docker compose run --rm privileged`` and skip everywhere else (macOS, the non-privileged
container). They format a real filesystem on a loopback device and prove that our mount
path makes a source effectively read-only (writes fail) and that a real ext4 destination
validates end to end.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from aethereal.linux.devices import list_block_devices
from aethereal.linux.media import LinuxMountService, MediaManager
from aethereal.linux.mount import (
    SourceProtectionFailure,
    effective_read_only,
    mount_read_only,
    mount_source_read_only,
    set_block_read_only,
    unmount,
)
from aethereal.linux.validation import validate_destination


def _skip_unless_privileged_linux() -> None:
    if sys.platform != "linux":
        pytest.skip("loopback mount tests require Linux")
    if os.geteuid() != 0:
        pytest.skip("loopback mount tests require root")


def _make_loop(tmp_path: Path, mkfs: list[str], size_mb: int = 32) -> str:
    _skip_unless_privileged_linux()
    image = tmp_path / "media.img"
    subprocess.run(
        ["dd", "if=/dev/zero", f"of={image}", "bs=1M", f"count={size_mb}"],
        check=True, capture_output=True,
    )
    try:
        subprocess.run([*mkfs, str(image)], check=True, capture_output=True)
    except FileNotFoundError:
        pytest.skip(f"{mkfs[0]} not installed")
    try:
        return subprocess.run(
            ["losetup", "--find", "--show", str(image)],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        pytest.skip(f"losetup unavailable (needs privileged container): {exc}")


def _detach(loop: str) -> None:
    subprocess.run(["losetup", "-d", loop], check=False, capture_output=True)


def _uuid_of(device: str) -> str:
    # -p probes the superblock directly (no stale cache across loop-device reuse).
    return subprocess.run(
        ["blkid", "-p", "-s", "UUID", "-o", "value", device],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def vfat_loop(tmp_path: Path) -> Iterator[str]:
    loop = _make_loop(tmp_path, ["mkfs.vfat"])
    try:
        yield loop
    finally:
        _detach(loop)


@pytest.fixture
def ext4_loop(tmp_path: Path) -> Iterator[str]:
    loop = _make_loop(tmp_path, ["mkfs.ext4", "-F"])
    try:
        yield loop
    finally:
        _detach(loop)


def test_source_mounts_read_only_and_writes_fail(vfat_loop: str, tmp_path: Path) -> None:
    mount_point = tmp_path / "mnt"
    try:
        result = mount_source_read_only(vfat_loop, mount_point, fstype="vfat")
        assert result.mount_read_only is True
        assert result.block_read_only is True
        # The core guarantee (SRC-001): a write to the source must fail.
        with pytest.raises(OSError):
            (mount_point / "should_not_write.txt").write_bytes(b"nope")
    finally:
        if effective_read_only(mount_point):
            unmount(mount_point)


def test_read_only_source_via_manual_mount(vfat_loop: str, tmp_path: Path) -> None:
    mount_point = tmp_path / "src"
    set_block_read_only(vfat_loop, read_only=True)
    mount_read_only(vfat_loop, mount_point, fstype="vfat")
    try:
        assert effective_read_only(mount_point) is True
    finally:
        unmount(mount_point)


def test_writable_mount_is_detected(vfat_loop: str, tmp_path: Path) -> None:
    # A device mounted read-write must be reported as NOT read-only (drives SRC-002 block).
    mount_point = tmp_path / "mnt"
    set_block_read_only(vfat_loop, read_only=False)
    mount_point.mkdir()
    subprocess.run(
        ["mount", "-o", "rw", "-t", "vfat", vfat_loop, str(mount_point)],
        check=True, capture_output=True,
    )
    try:
        assert effective_read_only(mount_point) is False
    finally:
        unmount(mount_point)


def test_ext4_destination_validates_end_to_end(ext4_loop: str, tmp_path: Path) -> None:
    mount_point = tmp_path / "backups"
    mount_point.mkdir()
    subprocess.run(["mount", ext4_loop, str(mount_point)], check=True, capture_output=True)
    try:
        (mount_point / "probe").write_bytes(b"ok")  # destination is writable
        result = validate_destination(list_block_devices(), configured_uuid=_uuid_of(ext4_loop))
        assert result.ok is True
        assert result.device is not None
        assert result.device.fstype == "ext4"
    finally:
        unmount(mount_point)


def test_media_manager_mounts_real_source_read_only(vfat_loop: str, tmp_path: Path) -> None:
    # End-to-end: the media manager detects our loop card, mounts it read-only, and the
    # SourceRef it returns is a read-only tree (writes fail). Scoped to our device.
    def lister() -> list:  # type: ignore[type-arg]
        return [d for d in list_block_devices() if d.path == vfat_loop]

    manager = MediaManager(
        destination_uuid="not-present",
        source_mount_root=tmp_path / "src",
        device_lister=lister,
        mount_service=LinuxMountService(),
    )
    try:
        ref = manager.current_source()
        assert ref is not None
        with pytest.raises(OSError):
            (ref.root / "should_not_write").write_bytes(b"nope")
    finally:
        manager.eject_all()


def test_source_protection_failure_type_exists() -> None:
    # Always-run sanity check (importable on any platform).
    assert issubclass(SourceProtectionFailure, Exception)
