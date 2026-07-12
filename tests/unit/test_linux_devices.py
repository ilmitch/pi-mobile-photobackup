"""Unit tests for lsblk JSON parsing, identity, and validation (SRC-005, DST-001/002/004)."""

from __future__ import annotations

from aethereal.linux.devices import find_by_uuid, flatten_devices, parse_lsblk_json
from aethereal.linux.validation import find_source_candidates, validate_destination

# A realistic `lsblk --json --bytes` snapshot: a system disk, an ext4 backup SSD, and an
# inserted exFAT camera card.
LSBLK = {
    "blockdevices": [
        {
            "name": "mmcblk0",
            "path": "/dev/mmcblk0",
            "fstype": None,
            "uuid": None,
            "label": None,
            "size": 32000000000,
            "ro": False,
            "mountpoint": None,
            "type": "disk",
            "model": None,
            "serial": "SD-SYS",
            "partuuid": None,
            "children": [
                {
                    "name": "mmcblk0p2",
                    "path": "/dev/mmcblk0p2",
                    "fstype": "ext4",
                    "uuid": "system-root-uuid",
                    "label": "rootfs",
                    "size": 31000000000,
                    "ro": False,
                    "mountpoint": "/",
                    "type": "part",
                    "model": None,
                    "serial": None,
                    "partuuid": "aaaa-0002",
                },
            ],
        },
        {
            "name": "sdb",
            "path": "/dev/sdb",
            "fstype": None,
            "uuid": None,
            "label": None,
            "size": 2000000000000,
            "ro": False,
            "mountpoint": None,
            "type": "disk",
            "model": "Backup SSD",
            "serial": "SSD-123",
            "children": [
                {
                    "name": "sdb1",
                    "path": "/dev/sdb1",
                    "fstype": "ext4",
                    "uuid": "dest-ssd-uuid",
                    "label": "AETHEREAL",
                    "size": 2000000000000,
                    "ro": False,
                    "mountpoint": "/Backups",
                    "type": "part",
                    "model": None,
                    "serial": None,
                    "partuuid": "bbbb-0001",
                },
            ],
        },
        {
            "name": "sda",
            "path": "/dev/sda",
            "fstype": None,
            "uuid": None,
            "label": None,
            "size": 64000000000,
            "ro": False,
            "mountpoint": None,
            "type": "disk",
            "model": "USB Reader",
            "serial": "CARD-RDR",
            "children": [
                {
                    "name": "sda1",
                    "path": "/dev/sda1",
                    "fstype": "exfat",
                    "uuid": "card-uuid",
                    "label": "CANON",
                    "size": 64000000000,
                    "ro": False,
                    "mountpoint": None,
                    "type": "part",
                    "model": None,
                    "serial": None,
                    "partuuid": "cccc-0001",
                },
            ],
        },
    ]
}


def test_parse_and_flatten() -> None:
    devices = parse_lsblk_json(LSBLK)
    flat = flatten_devices(devices)
    # 3 disks + 3 partitions.
    assert len(flat) == 6
    ssd = find_by_uuid(devices, "dest-ssd-uuid")
    assert len(ssd) == 1
    assert ssd[0].fstype == "ext4"
    assert ssd[0].size_bytes == 2000000000000


def test_validate_destination_ok() -> None:
    devices = parse_lsblk_json(LSBLK)
    result = validate_destination(devices, configured_uuid="dest-ssd-uuid")
    assert result.ok is True
    assert result.device is not None and result.device.path == "/dev/sdb1"
    assert result.reasons == ()


def test_validate_destination_absent() -> None:
    devices = parse_lsblk_json(LSBLK)
    result = validate_destination(devices, configured_uuid="not-present")
    assert result.ok is False
    assert any("not present" in r for r in result.reasons)


def test_validate_destination_rejects_wrong_disk_by_uuid() -> None:
    # A different USB disk (the card) must not validate as the destination.
    devices = parse_lsblk_json(LSBLK)
    result = validate_destination(devices, configured_uuid="card-uuid")
    assert result.ok is False  # exfat card is not ext4, and it's the source anyway
    assert any("required" in r for r in result.reasons)


def test_validate_destination_requires_ext4() -> None:
    devices = parse_lsblk_json(
        {
            "blockdevices": [
                {
                    "name": "sdb1",
                    "path": "/dev/sdb1",
                    "fstype": "exfat",
                    "uuid": "d",
                    "label": None,
                    "size": 1,
                    "ro": False,
                    "mountpoint": "/Backups",
                    "type": "part",
                    "model": None,
                    "serial": None,
                    "partuuid": None,
                },
            ]
        }
    )
    result = validate_destination(devices, configured_uuid="d")
    assert result.ok is False
    assert any("required 'ext4'" in r for r in result.reasons)


def test_validate_destination_must_be_mounted() -> None:
    devices = parse_lsblk_json(
        {
            "blockdevices": [
                {
                    "name": "sdb1",
                    "path": "/dev/sdb1",
                    "fstype": "ext4",
                    "uuid": "d",
                    "label": None,
                    "size": 1,
                    "ro": False,
                    "mountpoint": None,
                    "type": "part",
                    "model": None,
                    "serial": None,
                    "partuuid": None,
                },
            ]
        }
    )
    result = validate_destination(devices, configured_uuid="d")
    assert result.ok is False
    assert any("not mounted" in r for r in result.reasons)


def test_source_candidates_exclude_destination_and_system() -> None:
    devices = parse_lsblk_json(LSBLK)
    candidates = find_source_candidates(devices, destination_uuid="dest-ssd-uuid")
    # Only the exFAT card qualifies (ext4 system + ext4 dest are excluded).
    assert len(candidates) == 1
    assert candidates[0].uuid == "card-uuid"
    assert candidates[0].fstype == "exfat"


def test_read_only_flag_parsed_from_string_or_bool() -> None:
    devices = parse_lsblk_json(
        {
            "blockdevices": [
                {
                    "name": "a",
                    "path": "/dev/a",
                    "fstype": "exfat",
                    "uuid": "u1",
                    "label": None,
                    "size": 1,
                    "ro": "1",
                    "mountpoint": None,
                    "type": "part",
                    "model": None,
                    "serial": None,
                    "partuuid": None,
                },
                {
                    "name": "b",
                    "path": "/dev/b",
                    "fstype": "exfat",
                    "uuid": "u2",
                    "label": None,
                    "size": 1,
                    "ro": True,
                    "mountpoint": None,
                    "type": "part",
                    "model": None,
                    "serial": None,
                    "partuuid": None,
                },
            ]
        }
    )
    assert all(d.read_only for d in devices)
