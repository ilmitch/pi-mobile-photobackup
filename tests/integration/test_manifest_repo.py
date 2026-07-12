"""Integration tests for the manifest repository dedup lookups (FILE-005)."""

from __future__ import annotations

from pathlib import Path

from aethereal.backup.identity import content_identity_of_bytes
from aethereal.db.destination import open_destination_manifest
from aethereal.db.manifest_repo import ManifestRepository


def _repo(tmp_path: Path) -> ManifestRepository:
    conn = open_destination_manifest(tmp_path / "manifest.sqlite3")
    return ManifestRepository(conn)


def test_upsert_content_identity_is_idempotent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    ident = content_identity_of_bytes(b"photo")
    first = repo.upsert_content_identity(ident)
    second = repo.upsert_content_identity(ident)
    assert first == second


def test_has_verified_object_false_until_object_marked_verified(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    ident = content_identity_of_bytes(b"photo")
    assert repo.has_verified_object(ident) is False

    identity_id = repo.upsert_content_identity(ident)
    # An unverified (e.g. copying) object must not count as backed up (FILE-005).
    repo.insert_content_object(identity_id, "/Backups/.aethereal/objects/sha256/xx", "COPYING")
    assert repo.has_verified_object(ident) is False

    repo.insert_content_object(
        identity_id,
        "/Backups/.aethereal/objects/sha256/ab/cd/deadbeef",
        "VERIFIED",
        verified_at="2026-07-11T00:00:00+00:00",
    )
    assert repo.has_verified_object(ident) is True


def test_verified_object_path_returned(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    ident = content_identity_of_bytes(b"photo")
    identity_id = repo.upsert_content_identity(ident)
    path = "/Backups/.aethereal/objects/sha256/ab/cd/deadbeef"
    repo.insert_content_object(identity_id, path, "VERIFIED", verified_at="2026-07-11T00:00:00Z")
    assert repo.verified_object_path(ident) == path


def test_distinct_content_not_treated_as_verified(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    backed_up = content_identity_of_bytes(b"AAAA")
    other = content_identity_of_bytes(b"BBBB")  # same size, different content
    identity_id = repo.upsert_content_identity(backed_up)
    repo.insert_content_object(identity_id, "/objects/aaaa", "VERIFIED", verified_at="t")
    assert repo.has_verified_object(backed_up) is True
    assert repo.has_verified_object(other) is False
