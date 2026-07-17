"""Unit tests for the media manager selection logic (SRC-008), using injected fakes."""

from __future__ import annotations

from pathlib import Path

from aethereal.linux.devices import BlockDevice
from aethereal.linux.media import MediaManager, MediaState
from aethereal.linux.mount import SourceMount

DEST_UUID = "dest-ssd-uuid"
MOUNT_ROOT = "/run/aethereal/source"


class FakeMountService:
    def __init__(self) -> None:
        self.mount_calls = 0
        self.unmounted: list[str] = []

    def mount_source_read_only(
        self, device: str, mount_point: Path, *, fstype: str | None
    ) -> SourceMount:
        self.mount_calls += 1
        return SourceMount(
            device=device,
            mount_point=str(mount_point),
            block_read_only=True,
            mount_read_only=True,
        )

    def unmount(self, mount_point: Path) -> None:
        self.unmounted.append(str(mount_point))


def _dev(
    name: str,
    uuid: str,
    *,
    fstype: str = "exfat",
    label: str | None = None,
    mountpoint: str | None = None,
) -> BlockDevice:
    return BlockDevice(
        name=name,
        path=f"/dev/{name}",
        fstype=fstype,
        uuid=uuid,
        label=label,
        size_bytes=64_000_000_000,
        read_only=False,
        mountpoint=mountpoint,
        dev_type="part",
        model=None,
        serial=None,
        partuuid=None,
    )


_DEST = _dev("sdb1", DEST_UUID, fstype="ext4", label="AETHEREAL", mountpoint="/Backups")


def _manager(devices: list[BlockDevice], mounts: FakeMountService) -> MediaManager:
    return MediaManager(
        destination_uuid=DEST_UUID,
        source_mount_root=MOUNT_ROOT,
        device_lister=lambda: list(devices),
        mount_service=mounts,
    )


def test_no_source() -> None:
    mgr = _manager([_DEST], FakeMountService())
    assert mgr.state() is MediaState.NO_SOURCE
    assert mgr.current_source() is None


def test_single_source_mounts_and_names() -> None:
    mounts = FakeMountService()
    card = _dev("sda1", "card-uuid", label="CANON_R6")
    mgr = _manager([_DEST, card], mounts)

    assert mgr.state() is MediaState.SINGLE_SOURCE
    ref = mgr.current_source()
    assert ref is not None
    assert ref.logical_name == "CANON_R6"
    assert ref.root == Path(MOUNT_ROOT) / "card-uuid"
    assert mounts.mount_calls == 1


def test_current_source_is_idempotent() -> None:
    mounts = FakeMountService()
    mgr = _manager([_DEST, _dev("sda1", "card-uuid")], mounts)
    mgr.current_source()
    mgr.current_source()
    assert mounts.mount_calls == 1  # mounted once, not re-mounted on every poll


def test_multiple_sources_require_selection() -> None:
    mounts = FakeMountService()
    a = _dev("sda1", "card-a", label="CARD_A")
    b = _dev("sdc1", "card-b", label="CARD_B")
    mgr = _manager([_DEST, a, b], mounts)

    assert mgr.state() is MediaState.MULTIPLE_SOURCES
    assert mgr.current_source() is None  # ambiguous until selected
    assert mounts.mount_calls == 0

    mgr.select("card-b")
    ref = mgr.current_source()
    assert ref is not None and ref.logical_name == "CARD_B"


def test_source_removal_unmounts() -> None:
    mounts = FakeMountService()
    devices = [_DEST, _dev("sda1", "card-uuid")]
    mgr = _manager(devices, mounts)
    ref = mgr.current_source()
    assert ref is not None

    # Card pulled: only the destination remains.
    devices[:] = [_DEST]
    assert mgr.current_source() is None
    assert str(Path(MOUNT_ROOT) / "card-uuid") in mounts.unmounted


def test_default_name_without_label() -> None:
    mounts = FakeMountService()
    mgr = _manager([_DEST, _dev("sda1", "abcd1234ef", label=None)], mounts)
    ref = mgr.current_source()
    assert ref is not None
    assert ref.logical_name == "CARD-abcd1234"


def test_destination_validation() -> None:
    mgr = _manager([_DEST, _dev("sda1", "card-uuid")], FakeMountService())
    result = mgr.destination()
    assert result.ok is True
    assert result.device is not None and result.device.fstype == "ext4"


def test_eject_all_unmounts_everything() -> None:
    mounts = FakeMountService()
    mgr = _manager([_DEST, _dev("sda1", "card-uuid")], mounts)
    mgr.current_source()
    mgr.eject_all()
    assert str(Path(MOUNT_ROOT) / "card-uuid") in mounts.unmounted


def test_eject_suppresses_remount_until_physically_removed() -> None:
    mounts = FakeMountService()
    devices = [_DEST, _dev("sda1", "card-uuid", label="CANON")]
    mgr = _manager(devices, mounts)

    # Mounted and in use.
    assert mgr.current_source() is not None
    assert mounts.mount_calls == 1

    # Eject: unmounted, and while still physically present it is "safe to remove".
    assert mgr.eject() == 1
    assert str(Path(MOUNT_ROOT) / "card-uuid") in mounts.unmounted
    assert mgr.awaiting_removal() is True
    assert mgr.state() is MediaState.NO_SOURCE

    # Crucially, polling does NOT re-mount the ejected card (the whole point of eject).
    assert mgr.current_source() is None
    assert mgr.source_candidates() == []
    assert mounts.mount_calls == 1  # still 1 — no re-mount

    # Physically remove the card: ejection mark clears.
    devices[:] = [_DEST]
    assert mgr.awaiting_removal() is False

    # Re-insert the same card: detected and mountable again as normal.
    devices[:] = [_DEST, _dev("sda1", "card-uuid", label="CANON")]
    assert mgr.state() is MediaState.SINGLE_SOURCE
    assert mgr.current_source() is not None
    assert mounts.mount_calls == 2


def test_eject_with_no_card_is_noop() -> None:
    mgr = _manager([_DEST], FakeMountService())
    assert mgr.eject() == 0
    assert mgr.awaiting_removal() is False


def test_reformatted_card_at_same_slot_is_not_suppressed() -> None:
    # Eject a card, then (without any poll clearing it) the same slot reappears with a NEW
    # filesystem UUID — a camera reformat. It must be detected, not suppressed by the old
    # ejection: suppression is keyed by UUID, not by the /dev/sdX slot.
    mounts = FakeMountService()
    devices = [_DEST, _dev("sda1", "CA08-1CF9", label="EOS_DIGITAL")]
    mgr = _manager(devices, mounts)
    assert mgr.current_source() is not None
    assert mgr.eject() == 1

    # Reformatted in-camera: same slot /dev/sda1, new UUID. No intervening poll.
    devices[:] = [_DEST, _dev("sda1", "0A75-1333", label="EOS_DIGITAL")]
    assert mgr.state() is MediaState.SINGLE_SOURCE
    ref = mgr.current_source()
    assert ref is not None
    assert ref.root == Path(MOUNT_ROOT) / "0A75-1333"
    assert mgr.awaiting_removal() is False
