"""Unit tests for mountinfo parsing and effective read-only detection (SRC-002)."""

from __future__ import annotations

from aethereal.linux.mountinfo import (
    find_by_mount_point,
    find_by_source,
    parse_mountinfo,
)

# A representative /proc/self/mountinfo with a read-only vfat source and a rw ext4 dest.
SAMPLE = """\
23 28 0:21 / /proc rw,nosuid,nodev,noexec,relatime shared:14 - proc proc rw
41 28 8:1 / /run/aethereal/source/cardA ro,nosuid,nodev,relatime shared:1 - vfat /dev/sda1 ro,fmask=0022
42 28 8:17 / /Backups rw,relatime shared:2 - ext4 /dev/sdb1 rw,errors=remount-ro
43 28 8:33 / /mnt/space\\040dir rw,relatime - ext4 /dev/sdc1 rw
"""


def test_parses_all_entries() -> None:
    entries = parse_mountinfo(SAMPLE)
    assert len(entries) == 4


def test_read_only_source_is_detected() -> None:
    entries = parse_mountinfo(SAMPLE)
    src = find_by_mount_point(entries, "/run/aethereal/source/cardA")
    assert src is not None
    assert src.fstype == "vfat"
    assert src.mount_source == "/dev/sda1"
    assert src.read_only is True


def test_read_write_destination_is_not_read_only() -> None:
    entries = parse_mountinfo(SAMPLE)
    dest = find_by_mount_point(entries, "/Backups")
    assert dest is not None
    assert dest.fstype == "ext4"
    assert dest.read_only is False


def test_octal_escapes_in_mount_point_are_decoded() -> None:
    entries = parse_mountinfo(SAMPLE)
    assert find_by_mount_point(entries, "/mnt/space dir") is not None


def test_find_by_source() -> None:
    entries = parse_mountinfo(SAMPLE)
    matches = find_by_source(entries, "/dev/sda1")
    assert len(matches) == 1
    assert matches[0].mount_point == "/run/aethereal/source/cardA"


def test_malformed_lines_are_skipped() -> None:
    bad = "garbage line without separator\n" + SAMPLE
    assert len(parse_mountinfo(bad)) == 4


def test_optional_fields_before_separator_are_ignored() -> None:
    # The 'shared:1' optional tag must not shift field parsing.
    line = "41 28 8:1 / /mnt rw shared:1 master:2 - ext4 /dev/sda1 rw"
    entry = parse_mountinfo(line)[0]
    assert entry.fstype == "ext4"
    assert entry.mount_source == "/dev/sda1"
