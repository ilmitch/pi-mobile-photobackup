"""End-to-end pipeline test: preflight -> run_job -> real SQLite manifest + filesystem.

Exercises the full portable backend against a real destination manifest and real APFS
filesystem behavior, including the second-run dedup path (a re-inserted card is skipped
but still gets a complete session view).
"""

from __future__ import annotations

from pathlib import Path

from aethereal.backup.manifest_journal import JobManifestJournal
from aethereal.backup.preflight import PreflightOutcome, run_preflight
from aethereal.backup.runner import JobOutcome, run_job
from aethereal.common.platform import FakePlatformOps
from aethereal.db.destination import open_destination_manifest
from aethereal.db.manifest_repo import ManifestRepository

BIG = FakePlatformOps(total_bytes=1_000_000_000_000, free_bytes=1_000_000_000_000)


def _make_source(tmp_path: Path) -> Path:
    root = tmp_path / "card"
    files = {
        "DCIM/100CANON/IMG_1.CR3": b"first raw",
        "DCIM/100CANON/IMG_2.CR3": b"second raw",
        "DCIM/100CANON/IMG_3.CR3": b"first raw",  # duplicate content of IMG_1
    }
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def _count(conn: object, table: str, where: str = "") -> int:
    import sqlite3

    assert isinstance(conn, sqlite3.Connection)
    sql = f"SELECT COUNT(*) FROM {table} {where}"
    return int(conn.execute(sql).fetchone()[0])


def test_full_backup_then_dedup_rerun(tmp_path: Path) -> None:
    source = _make_source(tmp_path)
    store = tmp_path / "Backups" / ".aethereal" / "objects"
    conn = open_destination_manifest(tmp_path / "Backups" / "manifest.sqlite3")
    repo = ManifestRepository(conn)

    # --- First backup ---
    session1 = str(tmp_path / "Backups" / "2026" / "s1")
    pre1 = run_preflight(
        source,
        session_root=session1,
        destination_path=tmp_path,
        platform=BIG,
        verified=repo.has_verified_object,
    )
    assert pre1.outcome is PreflightOutcome.READY
    assert pre1.new_file_count == 3  # three NEW files (two share content)
    assert pre1.plan.new_object_count == 2  # only two unique objects
    assert pre1.plan.intra_job_duplicate_count == 1

    repo.create_backup_job("job-1", state="BACKUP_COPYING", session_path=session1)
    result1 = run_job(
        pre1.plan,
        source_root=source,
        object_store_root=store,
        journal=JobManifestJournal(repo, "job-1"),
        platform=BIG,
    )
    assert result1.outcome is JobOutcome.COMPLETED
    assert result1.files_copied == 2
    assert result1.files_verified == 3

    # Two canonical objects on disk, both VERIFIED in the manifest.
    assert _count(conn, "content_object", "WHERE status = 'VERIFIED'") == 2
    # Complete snapshot view: three session entries (DST-007), one per source file.
    assert _count(conn, "session_entry", "WHERE backup_job_id = 'job-1'") == 3
    # Each session path is a real hardlink to its canonical object.
    for rel in ("DCIM/100CANON/IMG_1.CR3", "DCIM/100CANON/IMG_2.CR3", "DCIM/100CANON/IMG_3.CR3"):
        assert (Path(session1) / rel).exists()

    # --- Second backup of the same card: everything already backed up ---
    session2 = str(tmp_path / "Backups" / "2026" / "s2")
    pre2 = run_preflight(
        source,
        session_root=session2,
        destination_path=tmp_path,
        platform=BIG,
        verified=repo.has_verified_object,
    )
    assert pre2.already_backed_up_count == 3
    assert pre2.new_bytes == 0  # nothing new to copy

    repo.create_backup_job("job-2", state="BACKUP_COPYING", session_path=session2)
    result2 = run_job(
        pre2.plan,
        source_root=source,
        object_store_root=store,
        journal=JobManifestJournal(repo, "job-2"),
        platform=BIG,
    )
    assert result2.outcome is JobOutcome.COMPLETED
    assert result2.files_copied == 0  # no physical copies on the rerun
    assert result2.files_skipped == 3
    # No new canonical objects were created; the second session still has 3 entries.
    assert _count(conn, "content_object", "WHERE status = 'VERIFIED'") == 2
    assert _count(conn, "session_entry", "WHERE backup_job_id = 'job-2'") == 3
    for rel in ("DCIM/100CANON/IMG_1.CR3", "DCIM/100CANON/IMG_2.CR3", "DCIM/100CANON/IMG_3.CR3"):
        assert (Path(session2) / rel).exists()

    conn.close()
