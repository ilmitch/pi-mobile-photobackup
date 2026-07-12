"""Preflight file classification.

Implements PRD v0.3 FILE-005 (already-backed-up definition), FILE-006 (classification
set), and FILE-007 (filename collision protection). Pure logic: identity resolution and
the destination lookups are supplied as callables, so this module is independent of the
database and fully unit-testable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from aethereal.backup.identity import ContentIdentity


class FileClassification(str, Enum):
    """The FILE-006 classification set."""

    NEW = "NEW"
    ALREADY_BACKED_UP = "ALREADY_BACKED_UP"
    POTENTIAL_CONFLICT = "POTENTIAL_CONFLICT"
    UNSUPPORTED = "UNSUPPORTED"
    UNREADABLE = "UNREADABLE"


@dataclass(frozen=True, slots=True)
class ClassificationInput:
    """A single candidate source file to classify.

    ``identity`` is ``None`` when the file could not be read (which forces UNREADABLE);
    ``unsupported`` marks symlinks/special objects excluded by FILE-001.
    """

    relative_path: str
    identity: ContentIdentity | None
    unreadable: bool = False
    unsupported: bool = False


# Returns True if a VERIFIED canonical object already exists for this identity (FILE-005).
VerifiedLookup = Callable[[ContentIdentity], bool]
# Returns the identity currently occupying a destination-relative path, or None (FILE-007).
OccupantLookup = Callable[[str], "ContentIdentity | None"]


def classify(
    item: ClassificationInput,
    *,
    verified: VerifiedLookup,
    occupant: OccupantLookup | None = None,
) -> FileClassification:
    """Classify one candidate source file.

    Order of precedence: unsupported (symlink/special) then unreadable are terminal; then
    a destination path already holding *different* content is a conflict (FILE-007); then
    an identity with an existing VERIFIED object is already backed up (FILE-005); otherwise
    it is new.
    """
    if item.unsupported:
        return FileClassification.UNSUPPORTED
    if item.unreadable or item.identity is None:
        return FileClassification.UNREADABLE

    if occupant is not None:
        occupying = occupant(item.relative_path)
        if occupying is not None and occupying != item.identity:
            return FileClassification.POTENTIAL_CONFLICT

    if verified(item.identity):
        return FileClassification.ALREADY_BACKED_UP
    return FileClassification.NEW
