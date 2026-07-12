"""Unit tests for file classification (FILE-005/006/007)."""

from __future__ import annotations

from aethereal.backup.classification import (
    ClassificationInput,
    FileClassification,
    classify,
)
from aethereal.backup.identity import ContentIdentity, content_identity_of_bytes


def _never_verified(_: ContentIdentity) -> bool:
    return False


def _always_verified(_: ContentIdentity) -> bool:
    return True


def test_new_when_not_verified() -> None:
    item = ClassificationInput("a.cr3", content_identity_of_bytes(b"a"))
    assert classify(item, verified=_never_verified) is FileClassification.NEW


def test_already_backed_up_when_verified() -> None:
    item = ClassificationInput("a.cr3", content_identity_of_bytes(b"a"))
    assert classify(item, verified=_always_verified) is FileClassification.ALREADY_BACKED_UP


def test_unreadable_when_no_identity() -> None:
    item = ClassificationInput("a.cr3", None, unreadable=True)
    assert classify(item, verified=_always_verified) is FileClassification.UNREADABLE


def test_unsupported_object() -> None:
    item = ClassificationInput("link", content_identity_of_bytes(b"x"), unsupported=True)
    assert classify(item, verified=_never_verified) is FileClassification.UNSUPPORTED


def test_conflict_when_path_holds_different_content() -> None:
    incoming = content_identity_of_bytes(b"new content")
    existing = content_identity_of_bytes(b"old content")
    item = ClassificationInput("DCIM/IMG_0001.CR3", incoming)

    def occupant(path: str) -> ContentIdentity | None:
        return existing if path == "DCIM/IMG_0001.CR3" else None

    assert (
        classify(item, verified=_never_verified, occupant=occupant)
        is FileClassification.POTENTIAL_CONFLICT
    )


def test_same_content_at_path_is_not_a_conflict() -> None:
    same = content_identity_of_bytes(b"same")
    item = ClassificationInput("DCIM/IMG_0001.CR3", same)

    def occupant(_: str) -> ContentIdentity | None:
        return same

    # Occupant identical -> not a conflict; falls through to already-backed-up/new.
    assert (
        classify(item, verified=_always_verified, occupant=occupant)
        is FileClassification.ALREADY_BACKED_UP
    )
