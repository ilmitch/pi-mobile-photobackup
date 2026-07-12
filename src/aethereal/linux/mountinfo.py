"""Parse Linux ``/proc/self/mountinfo`` for effective mount state.

Implements the effective-read-only verification of SRC-002 / Implementation Plan v0.3
section 9: the backup engine must confirm a source is *actually* mounted read-only, not
merely that read-only was requested. The parser is pure so it is unit-testable on any
host; only :func:`read_mountinfo` touches the Linux-specific file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")


def _unescape(field: str) -> str:
    """Decode mountinfo octal escapes (e.g. spaces are ``\\040``)."""
    return _OCTAL_ESCAPE.sub(lambda m: chr(int(m.group(1), 8)), field)


@dataclass(frozen=True, slots=True)
class MountInfoEntry:
    """One line of ``/proc/self/mountinfo``."""

    mount_id: int
    parent_id: int
    major_minor: str
    root: str
    mount_point: str
    mount_options: tuple[str, ...]
    fstype: str
    mount_source: str
    super_options: tuple[str, ...]

    @property
    def read_only(self) -> bool:
        """True when the VFS mount itself is read-only (the effective state, SRC-002)."""
        return "ro" in self.mount_options


def parse_mountinfo(text: str) -> list[MountInfoEntry]:
    """Parse the full contents of a mountinfo file.

    Each line is ``ID PARENT MAJ:MIN ROOT MOUNTPOINT OPTIONS [optional tags] - FSTYPE
    SOURCE SUPEROPTIONS``. The variable number of optional tags before ``-`` is skipped.
    Malformed lines are ignored rather than raising.
    """
    entries: list[MountInfoEntry] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or " - " not in line:
            continue
        left, right = line.split(" - ", 1)
        left_fields = left.split()
        right_fields = right.split()
        if len(left_fields) < 6 or len(right_fields) < 3:
            continue
        entries.append(
            MountInfoEntry(
                mount_id=int(left_fields[0]),
                parent_id=int(left_fields[1]),
                major_minor=left_fields[2],
                root=_unescape(left_fields[3]),
                mount_point=_unescape(left_fields[4]),
                mount_options=tuple(left_fields[5].split(",")),
                fstype=right_fields[0],
                mount_source=_unescape(right_fields[1]),
                super_options=tuple(right_fields[2].split(",")),
            )
        )
    return entries


def read_mountinfo() -> list[MountInfoEntry]:
    """Read and parse the current process's mountinfo (Linux only)."""
    return parse_mountinfo(Path("/proc/self/mountinfo").read_text(encoding="utf-8"))


def find_by_mount_point(entries: list[MountInfoEntry], mount_point: str) -> MountInfoEntry | None:
    """Return the entry mounted at ``mount_point``, or None."""
    target = str(Path(mount_point))
    for entry in entries:
        if str(Path(entry.mount_point)) == target:
            return entry
    return None


def find_by_source(entries: list[MountInfoEntry], mount_source: str) -> list[MountInfoEntry]:
    """Return all entries backed by the given device (``mount_source``)."""
    return [e for e in entries if e.mount_source == mount_source]
