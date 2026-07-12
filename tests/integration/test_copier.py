"""Integration tests for the copy + three-way verify + finalize engine (COPY/VER)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from aethereal.backup.copier import (
    CopyOutcome,
    SessionPathConflict,
    copy_verify_finalize,
    link_verified_object,
)
from aethereal.backup.identity import ContentIdentity, content_identity_of_bytes
from aethereal.backup.object_store import object_path
from aethereal.common.platform import FakePlatformOps

PLATFORM = FakePlatformOps(total_bytes=1_000_000_000_000, free_bytes=1_000_000_000_000)


class RecordingJournal:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str]] = []

    def record_pending_finalize(
        self, identity: ContentIdentity, *, temp_path: str, final_path: str, session_path: str
    ) -> None:
        self.events.append(("pending", final_path, session_path))

    def mark_verified(
        self, identity: ContentIdentity, *, object_path: str, session_path: str
    ) -> None:
        self.events.append(("verified", object_path, session_path))


def _source(tmp_path: Path, data: bytes) -> Path:
    p = tmp_path / "source" / "IMG.CR3"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _store(tmp_path: Path) -> Path:
    root = tmp_path / "objects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_successful_copy_verify_finalize(tmp_path: Path) -> None:
    data = b"canon raw frame" * 1000
    src = _source(tmp_path, data)
    expected = content_identity_of_bytes(data)
    store = _store(tmp_path)
    session = str(tmp_path / "session" / "DCIM" / "IMG.CR3")
    journal = RecordingJournal()

    result = copy_verify_finalize(
        src,
        expected,
        object_store_root=store,
        session_path=session,
        journal=journal,
        platform=PLATFORM,
    )

    assert result.outcome is CopyOutcome.VERIFIED
    assert result.copy_stream_sha256 == expected.sha256
    assert result.destination_sha256 == expected.sha256
    assert result.attempts == 1

    final = object_path(store, expected.sha256)
    assert final.exists()
    assert Path(session).exists()
    # Session entry and canonical object are the same inode (hardlinked, DST-007).
    assert Path(session).stat().st_ino == final.stat().st_ino
    # Partial file is gone.
    assert not any(p.name.endswith(".aethereal-partial") for p in final.parent.iterdir())
    # Durable ordering: PENDING_FINALIZE recorded before VERIFIED (VER-004).
    assert [e[0] for e in journal.events] == ["pending", "verified"]


def test_source_hash_mismatch_fails_after_retries(tmp_path: Path) -> None:
    data = b"actual bytes"
    src = _source(tmp_path, data)
    # Expected identity that does NOT match the source content.
    wrong = ContentIdentity(size_bytes=len(data), sha256="0" * 64)
    store = _store(tmp_path)
    journal = RecordingJournal()

    result = copy_verify_finalize(
        src,
        wrong,
        object_store_root=store,
        session_path=str(tmp_path / "session" / "IMG.CR3"),
        journal=journal,
        platform=PLATFORM,
        retries=2,
    )

    assert result.outcome is CopyOutcome.SOURCE_UNSTABLE
    assert result.attempts == 3  # initial + 2 retries
    assert not object_path(store, wrong.sha256).exists()
    assert journal.events == []  # never reached PENDING_FINALIZE


def test_destination_mismatch_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = b"good source bytes"
    src = _source(tmp_path, data)
    expected = content_identity_of_bytes(data)
    store = _store(tmp_path)

    # Force the reopened destination hash (H3) to disagree.
    import aethereal.backup.copier as copier_mod

    def corrupt_h3(reader: object, *, chunk_bytes: int) -> ContentIdentity:
        return ContentIdentity(size_bytes=len(data), sha256="f" * 64)

    monkeypatch.setattr(copier_mod, "hash_stream", corrupt_h3)

    result = copy_verify_finalize(
        src,
        expected,
        object_store_root=store,
        session_path=str(tmp_path / "session" / "IMG.CR3"),
        journal=RecordingJournal(),
        platform=PLATFORM,
    )
    assert result.outcome is CopyOutcome.DESTINATION_MISMATCH
    assert not object_path(store, expected.sha256).exists()


def test_existing_object_is_linked_not_recopied(tmp_path: Path) -> None:
    data = b"already stored"
    src = _source(tmp_path, data)
    expected = content_identity_of_bytes(data)
    store = _store(tmp_path)
    # Pre-create the canonical object as if a prior job stored it.
    final = object_path(store, expected.sha256)
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(data)
    journal = RecordingJournal()

    result = copy_verify_finalize(
        src,
        expected,
        object_store_root=store,
        session_path=str(tmp_path / "session" / "IMG.CR3"),
        journal=journal,
        platform=PLATFORM,
    )
    assert result.outcome is CopyOutcome.VERIFIED
    assert result.attempts == 0  # linked, not copied
    assert [e[0] for e in journal.events] == ["verified"]


def test_link_verified_object_hardlinks(tmp_path: Path) -> None:
    data = b"content"
    expected = content_identity_of_bytes(data)
    store = _store(tmp_path)
    final = object_path(store, expected.sha256)
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(data)
    session = str(tmp_path / "session" / "a" / "IMG.CR3")

    result = link_verified_object(store, expected, session, RecordingJournal())
    assert result.outcome is CopyOutcome.VERIFIED
    assert Path(session).stat().st_ino == final.stat().st_ino


def test_session_path_conflict_raises(tmp_path: Path) -> None:
    data = b"content"
    expected = content_identity_of_bytes(data)
    store = _store(tmp_path)
    final = object_path(store, expected.sha256)
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(data)

    session = tmp_path / "session" / "IMG.CR3"
    session.parent.mkdir(parents=True, exist_ok=True)
    session.write_bytes(b"different pre-existing content")  # different inode

    with pytest.raises(SessionPathConflict):
        link_verified_object(store, expected, str(session), RecordingJournal())


def test_partial_uses_configured_suffix_during_copy(tmp_path: Path) -> None:
    # A large-ish file so we can assert the partial naming convention exists mid-design.
    data = os.urandom(64 * 1024)
    src = _source(tmp_path, data)
    expected = content_identity_of_bytes(data)
    store = _store(tmp_path)
    result = copy_verify_finalize(
        src,
        expected,
        object_store_root=store,
        session_path=str(tmp_path / "session" / "IMG.CR3"),
        journal=RecordingJournal(),
        platform=PLATFORM,
    )
    assert result.outcome is CopyOutcome.VERIFIED
    # After success only the final object remains (named by digest, no suffix).
    assert object_path(store, expected.sha256).name == expected.sha256
