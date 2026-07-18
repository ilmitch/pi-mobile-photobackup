"""Integration tests for the backup engine (job lifecycle, state, events, recovery)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aethereal.backup.engine import BackupEngine
from aethereal.backup.identity import content_identity_of_bytes
from aethereal.backup.object_store import object_path, partial_path
from aethereal.backup.preflight import PreflightOutcome
from aethereal.backup.runner import JobOutcome, JobRunResult
from aethereal.backup.state_machine import BackupState
from aethereal.common.events import Event, EventBus, EventType
from aethereal.common.platform import FakePlatformOps
from aethereal.db.destination import open_destination_manifest
from aethereal.db.manifest_repo import ManifestRepository

BIG = FakePlatformOps(total_bytes=1_000_000_000_000, free_bytes=1_000_000_000_000)
FIXED_CLOCK = lambda: datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)  # noqa: E731


def _engine(
    tmp_path: Path,
    *,
    platform: FakePlatformOps = BIG,
    bus: EventBus | None = None,
    is_clock_trusted: Callable[[], bool] | None = None,
) -> tuple[BackupEngine, ManifestRepository]:
    conn = open_destination_manifest(tmp_path / "Backups" / "manifest.sqlite3")
    repo = ManifestRepository(conn)
    engine = BackupEngine(
        repo=repo,
        object_store_root=tmp_path / "Backups" / ".aethereal" / "objects",
        backup_root=tmp_path / "Backups",
        platform=platform,
        event_bus=bus,
        clock=FIXED_CLOCK,
        is_clock_trusted=is_clock_trusted,
    )
    return engine, repo


def _session_path(repo: ManifestRepository, job_id: str | None) -> str:
    assert job_id is not None
    job = repo.get_backup_job(job_id)
    assert job is not None
    return str(job["session_path"])


def _source(tmp_path: Path, files: dict[str, bytes]) -> Path:
    root = tmp_path / "card"
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def test_run_backup_completes(tmp_path: Path) -> None:
    engine, repo = _engine(tmp_path)
    src = _source(tmp_path, {"DCIM/IMG_1.CR3": b"one", "DCIM/IMG_2.CR3": b"two"})

    result = engine.run_backup(src, "CANON_CARD_01")

    assert result.preflight_outcome is PreflightOutcome.READY
    assert result.job is not None and result.job.outcome is JobOutcome.COMPLETED
    assert result.state is BackupState.SOURCE_SAFE_TO_REMOVE
    assert result.job_id == "20260711-001"

    # Job row finished and counts persisted.
    row = repo._conn.execute(  # noqa: SLF001 - test inspection
        "SELECT state, files_copied FROM backup_job WHERE id = ?", (result.job_id,)
    ).fetchone()
    assert row[0] == "BACKUP_COMPLETED"
    assert row[1] == 2

    engine.reset()
    assert engine.state is BackupState.IDLE


def test_blocked_capacity_leaves_engine_recoverable(tmp_path: Path) -> None:
    engine, _repo = _engine(
        tmp_path, platform=FakePlatformOps(total_bytes=1_000_000_000_000, free_bytes=100)
    )
    src = _source(tmp_path, {"big.mp4": b"x" * 500})

    result = engine.run_backup(src, "CANON_CARD_01")

    assert result.preflight_outcome is PreflightOutcome.BLOCKED
    assert result.job is None
    blocked_state = engine.state
    assert blocked_state is BackupState.PREFLIGHT_BLOCKED
    # The blocked state is not a dead end: reset returns to IDLE.
    engine.reset()
    reset_state = engine.state
    assert reset_state is BackupState.IDLE


def test_dry_run_does_not_copy_or_change_state(tmp_path: Path) -> None:
    engine, repo = _engine(tmp_path)
    src = _source(tmp_path, {"IMG.CR3": b"data"})

    result = engine.dry_run(src, "CANON_CARD_01")

    assert result.outcome is PreflightOutcome.READY
    assert result.new_file_count == 1
    assert engine.state is BackupState.IDLE  # dry run never advances job state
    # No job row, no objects on disk.
    assert repo._conn.execute("SELECT COUNT(*) FROM backup_job").fetchone()[0] == 0  # noqa: SLF001
    assert not (tmp_path / "Backups" / ".aethereal" / "objects").exists()


def test_job_ids_increment_per_day(tmp_path: Path) -> None:
    engine, _repo = _engine(tmp_path)
    r1 = engine.run_backup(_source(tmp_path, {"a.cr3": b"a"}), "CARD")
    engine.reset()
    r2 = engine.run_backup(_source(tmp_path / "second", {"b.cr3": b"b"}), "CARD")
    assert r1.job_id == "20260711-001"
    assert r2.job_id == "20260711-002"


def test_events_are_emitted(tmp_path: Path) -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(received.append)
    engine, _repo = _engine(tmp_path, bus=bus)
    engine.run_backup(_source(tmp_path, {"a.cr3": b"a"}), "CARD")

    types = {e.type for e in received}
    assert EventType.SYSTEM_STATE_CHANGED in types
    assert EventType.BACKUP_STARTED in types
    assert EventType.BACKUP_PROGRESS in types
    assert EventType.BACKUP_COMPLETED in types
    # Progress events carry file counts and byte counts for the UI bar.
    progress = [e for e in received if e.type is EventType.BACKUP_PROGRESS]
    last = progress[-1].details
    assert last["done"] == last["total"]
    assert last["done_bytes"] == last["total_bytes"] == 1  # one 1-byte file copied


def test_reformat_and_rebackup_is_cumulative(tmp_path: Path) -> None:
    """Field scenario: back up a card, format it, shoot more, back up again.

    The first backup's files must survive; the appliance is additive, never a mirror
    (PRD section 3 non-goals). Verifies destination content is never deleted.
    """
    engine, repo = _engine(tmp_path)

    def make_card(name: str, files: dict[str, bytes]) -> Path:
        root = tmp_path / name
        for rel, data in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        return root

    # First card: A and B.
    card1 = make_card("card1", {"DCIM/A.CR3": b"alpha bytes", "DCIM/B.CR3": b"bravo bytes"})
    r1 = engine.run_backup(card1, "CARD")
    engine.reset()
    session1 = Path(_session_path(repo, r1.job_id))

    # "Format the card" and shoot a new file C (A and B are gone from the card).
    card2 = make_card("card2", {"DCIM/C.CR3": b"charlie bytes"})
    r2 = engine.run_backup(card2, "CARD")
    session2 = Path(_session_path(repo, r2.job_id))

    # The first session still holds A and B — nothing was deleted.
    assert (session1 / "DCIM/A.CR3").exists()
    assert (session1 / "DCIM/B.CR3").exists()
    # The second session reflects the reformatted card: only C.
    assert (session2 / "DCIM/C.CR3").exists()
    assert not (session2 / "DCIM/A.CR3").exists()

    # The destination cumulatively holds all three contents, all verified.
    assert repo.has_verified_object(content_identity_of_bytes(b"alpha bytes"))
    assert repo.has_verified_object(content_identity_of_bytes(b"bravo bytes"))
    assert repo.has_verified_object(content_identity_of_bytes(b"charlie bytes"))


def test_reinserting_same_card_dedups_without_recopy(tmp_path: Path) -> None:
    """Backing up the same card twice copies nothing new but keeps a complete session."""
    engine, repo = _engine(tmp_path)
    card = _source(tmp_path, {"DCIM/A.CR3": b"alpha", "DCIM/B.CR3": b"bravo"})

    r1 = engine.run_backup(card, "CARD")
    engine.reset()
    r2 = engine.run_backup(card, "CARD")

    assert r1.job is not None and r1.job.files_copied == 2
    assert r2.job is not None and r2.job.files_copied == 0  # nothing recopied
    assert r2.job.files_skipped == 2
    # Second session is still complete (hardlinks), not empty.
    session2 = Path(_session_path(repo, r2.job_id))
    assert (session2 / "DCIM/A.CR3").exists()
    assert (session2 / "DCIM/B.CR3").exists()


def test_untrusted_clock_blocks_backup(tmp_path: Path) -> None:
    # TIME-001: with an untrusted clock, the backup is blocked (no dated session created).
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(received.append)
    engine, repo = _engine(tmp_path, bus=bus, is_clock_trusted=lambda: False)

    result = engine.run_backup(_source(tmp_path, {"a.cr3": b"a"}), "CARD")

    assert result.preflight_outcome is PreflightOutcome.BLOCKED
    assert result.job is None
    assert engine.state is BackupState.PREFLIGHT_BLOCKED
    assert repo.list_backup_jobs() == []  # no dated session/job created
    reasons = [
        str(e.details.get("reasons")) for e in received if e.type is EventType.PREFLIGHT_COMPLETED
    ]
    assert any("untrusted" in r for r in reasons)


def test_request_cancellation_is_false_when_idle(tmp_path: Path) -> None:
    engine, _repo = _engine(tmp_path)
    assert engine.request_cancellation() is False


def test_cancelled_job_reaches_cancelled_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, repo = _engine(tmp_path)
    src = _source(tmp_path, {"a.cr3": b"a", "b.cr3": b"b"})

    # Simulate the runner stopping early due to cancellation.
    cancelled = JobRunResult(
        outcome=JobOutcome.CANCELLED,
        files_verified=1,
        files_copied=1,
        files_skipped=0,
        files_failed=0,
        bytes_copied=1,
    )
    monkeypatch.setattr("aethereal.backup.engine.run_job", lambda *a, **k: cancelled)

    result = engine.run_backup(src, "CARD")

    assert result.job is not None and result.job.outcome is JobOutcome.CANCELLED
    assert result.state is BackupState.SOURCE_SAFE_TO_REMOVE
    row = repo._conn.execute(  # noqa: SLF001
        "SELECT state FROM backup_job WHERE id = ?", (result.job_id,)
    ).fetchone()
    assert row[0] == "BACKUP_CANCELLED"
    # A cancelled job is terminal and must not be re-detected as incomplete (REC-001).
    assert result.job_id not in repo.list_incomplete_jobs()


def test_recover_on_startup_finalizes_and_flags_jobs(tmp_path: Path) -> None:
    engine, repo = _engine(tmp_path)
    store = tmp_path / "Backups" / ".aethereal" / "objects"
    store.mkdir(parents=True, exist_ok=True)

    # Simulate an interrupted job: a non-terminal job row + a valid pending object.
    repo.create_backup_job("20260711-009", state="BACKUP_COPYING")
    data = b"interrupted file"
    identity = content_identity_of_bytes(data)
    final = object_path(store, identity.sha256)
    temp = partial_path(store, identity.sha256)
    iid = repo.upsert_content_identity(identity)
    oid = repo.upsert_content_object_pending(iid, str(final), str(temp))
    session = str(tmp_path / "Backups" / "session" / "IMG.CR3")
    repo.insert_session_entry("20260711-009", oid, session, state="PENDING")
    final.parent.mkdir(parents=True, exist_ok=True)
    temp.write_bytes(data)

    report = engine.recover_on_startup()

    assert report.finalized == 1
    assert repo.has_verified_object(identity)
    assert Path(session).exists()
    # The interrupted job is flagged for recovery.
    state = repo._conn.execute(  # noqa: SLF001
        "SELECT state FROM backup_job WHERE id = ?", ("20260711-009",)
    ).fetchone()[0]
    assert state == "RECOVERY_REQUIRED"
