"""Integration tests for interrupted-backup recovery (REC-002/003/004, FI-REC-005/006).

Each test constructs a specific crash-window state (PENDING_FINALIZE record + on-disk
temp/final files) then runs reconciliation and checks the outcome against both the
filesystem and the manifest.
"""

from __future__ import annotations

from pathlib import Path

from aethereal.backup.identity import content_identity_of_bytes
from aethereal.backup.object_store import object_path, partial_path
from aethereal.backup.recovery import recover_destination
from aethereal.db.destination import open_destination_manifest
from aethereal.db.manifest_repo import ManifestRepository

JOB = "job-x"


def _setup(tmp_path: Path) -> tuple[ManifestRepository, Path]:
    conn = open_destination_manifest(tmp_path / "Backups" / "manifest.sqlite3")
    repo = ManifestRepository(conn)
    repo.create_backup_job(JOB, state="BACKUP_COPYING")
    store = tmp_path / "objects"
    store.mkdir(parents=True, exist_ok=True)
    return repo, store


def _make_pending(
    repo: ManifestRepository,
    store: Path,
    data: bytes,
    session_path: str,
    *,
    write_temp: bytes | None,
    write_final: bytes | None,
) -> None:
    identity = content_identity_of_bytes(data)
    final = object_path(store, identity.sha256)
    temp = partial_path(store, identity.sha256)
    identity_id = repo.upsert_content_identity(identity)
    object_id = repo.upsert_content_object_pending(identity_id, str(final), str(temp))
    repo.insert_session_entry(JOB, object_id, session_path, state="PENDING")
    final.parent.mkdir(parents=True, exist_ok=True)
    if write_temp is not None:
        temp.write_bytes(write_temp)
    if write_final is not None:
        final.write_bytes(write_final)


def test_finalize_from_valid_temp_before_rename(tmp_path: Path) -> None:
    # Crash after PENDING_FINALIZE commit, before rename (FI-REC-005).
    repo, store = _setup(tmp_path)
    data = b"canon frame bytes"
    session = str(tmp_path / "session" / "IMG.CR3")
    _make_pending(repo, store, data, session, write_temp=data, write_final=None)

    report = recover_destination(repo, object_store_root=store)

    assert report.finalized == 1
    identity = content_identity_of_bytes(data)
    final = object_path(store, identity.sha256)
    assert final.exists()
    assert not partial_path(store, identity.sha256).exists()  # temp renamed away
    assert Path(session).exists()
    assert Path(session).stat().st_ino == final.stat().st_ino
    assert repo.has_verified_object(identity)


def test_finalize_from_valid_final_after_rename(tmp_path: Path) -> None:
    # Crash after rename, before the verified commit (FI-REC-006).
    repo, store = _setup(tmp_path)
    data = b"drone clip bytes"
    session = str(tmp_path / "session" / "MOV.MP4")
    _make_pending(repo, store, data, session, write_temp=None, write_final=data)

    report = recover_destination(repo, object_store_root=store)

    assert report.finalized == 1
    identity = content_identity_of_bytes(data)
    assert repo.has_verified_object(identity)
    assert Path(session).exists()


def test_corrupt_temp_is_discarded(tmp_path: Path) -> None:
    repo, store = _setup(tmp_path)
    data = b"expected content"
    session = str(tmp_path / "session" / "IMG.CR3")
    _make_pending(repo, store, data, session, write_temp=b"CORRUPTED", write_final=None)

    report = recover_destination(repo, object_store_root=store)

    assert report.discarded == 1
    assert report.finalized == 0
    identity = content_identity_of_bytes(data)
    assert not repo.has_verified_object(identity)
    assert not partial_path(store, identity.sha256).exists()  # corrupt temp removed


def test_missing_candidate_is_discarded(tmp_path: Path) -> None:
    repo, store = _setup(tmp_path)
    data = b"neither on disk"
    session = str(tmp_path / "session" / "IMG.CR3")
    _make_pending(repo, store, data, session, write_temp=None, write_final=None)

    report = recover_destination(repo, object_store_root=store)

    assert report.discarded == 1
    assert not repo.has_verified_object(content_identity_of_bytes(data))


def test_orphan_partial_is_removed(tmp_path: Path) -> None:
    repo, store = _setup(tmp_path)
    # A stray partial with no pending record at all (REC-003).
    orphan = store / "ab" / "cd" / "deadbeef.aethereal-partial"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"leftover")

    report = recover_destination(repo, object_store_root=store)

    assert report.orphan_partials_removed == 1
    assert not orphan.exists()


def test_verified_objects_are_untouched(tmp_path: Path) -> None:
    # A completed VERIFIED object must not be affected by recovery (REC-004).
    repo, store = _setup(tmp_path)
    data = b"already done"
    identity = content_identity_of_bytes(data)
    final = object_path(store, identity.sha256)
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(data)
    identity_id = repo.upsert_content_identity(identity)
    repo.insert_content_object(identity_id, str(final), "VERIFIED", verified_at="t")

    report = recover_destination(repo, object_store_root=store)

    assert report.finalized == 0
    assert report.discarded == 0
    assert repo.has_verified_object(identity)
    assert final.exists()
