"""Unit tests for the job runner (PRD section 33 completion definition)."""

from __future__ import annotations

from pathlib import Path

import pytest

from aethereal.backup.classification import FileClassification
from aethereal.backup.identity import ContentIdentity, content_identity_of_bytes
from aethereal.backup.planner import ClassifiedFile, build_plan
from aethereal.backup.runner import CancellationToken, JobOutcome, run_job
from aethereal.common.platform import FakePlatformOps

PLATFORM = FakePlatformOps(total_bytes=1_000_000_000_000, free_bytes=1_000_000_000_000)


class RecordingJournal:
    def __init__(self) -> None:
        self.pending = 0
        self.verified = 0

    def record_pending_finalize(
        self, identity: ContentIdentity, *, temp_path: str, final_path: str, session_path: str
    ) -> None:
        self.pending += 1

    def mark_verified(
        self, identity: ContentIdentity, *, object_path: str, session_path: str
    ) -> None:
        self.verified += 1


def _new(root: Path, rel: str, data: bytes) -> ClassifiedFile:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    ident = content_identity_of_bytes(data)
    return ClassifiedFile(rel, ident, ident.size_bytes, FileClassification.NEW)


def test_completed_job_copies_and_links(tmp_path: Path) -> None:
    source = tmp_path / "source"
    dup = b"identical"
    items = [
        _new(source, "a.cr3", b"aaaa"),
        _new(source, "b.cr3", b"bbbbbb"),
        _new(source, "c.cr3", dup),
        _new(source, "d.cr3", dup),  # intra-job duplicate of c
    ]
    plan = build_plan(items, session_root=str(tmp_path / "session"))
    result = run_job(
        plan,
        source_root=source,
        object_store_root=tmp_path / "objects",
        journal=RecordingJournal(),
        platform=PLATFORM,
    )
    assert result.outcome is JobOutcome.COMPLETED
    assert result.files_copied == 3  # a, b, c (d is a link)
    assert result.files_verified == 4  # all four end up verified
    assert result.files_failed == 0


def test_blocked_plan_refused(tmp_path: Path) -> None:
    source = tmp_path / "source"
    ident = content_identity_of_bytes(b"x")
    blocked = ClassifiedFile("bad", ident, 1, FileClassification.UNREADABLE)
    plan = build_plan([blocked], session_root=str(tmp_path / "session"))
    assert plan.blocked
    with pytest.raises(ValueError):
        run_job(
            plan,
            source_root=source,
            object_store_root=tmp_path / "objects",
            journal=RecordingJournal(),
            platform=PLATFORM,
        )


def test_precancelled_job_copies_nothing(tmp_path: Path) -> None:
    source = tmp_path / "source"
    items = [_new(source, "a.cr3", b"aaaa"), _new(source, "b.cr3", b"bbbb")]
    plan = build_plan(items, session_root=str(tmp_path / "session"))
    token = CancellationToken()
    token.cancel()
    result = run_job(
        plan,
        source_root=source,
        object_store_root=tmp_path / "objects",
        journal=RecordingJournal(),
        platform=PLATFORM,
        cancel_token=token,
    )
    assert result.outcome is JobOutcome.CANCELLED
    assert result.files_verified == 0


def test_cancel_after_first_file_preserves_verified(tmp_path: Path) -> None:
    source = tmp_path / "source"
    items = [
        _new(source, "a.cr3", b"aaaa"),
        _new(source, "b.cr3", b"bbbb"),
        _new(source, "c.cr3", b"cccc"),
    ]
    plan = build_plan(items, session_root=str(tmp_path / "session"))
    token = CancellationToken()

    # Cancel as soon as the first file has been processed.
    def on_progress(done: int, total: int, rel: str) -> None:
        if done == 1:
            token.cancel()

    result = run_job(
        plan,
        source_root=source,
        object_store_root=tmp_path / "objects",
        journal=RecordingJournal(),
        platform=PLATFORM,
        cancel_token=token,
        on_progress=on_progress,
    )
    assert result.outcome is JobOutcome.CANCELLED
    assert result.files_verified == 1  # first file preserved, rest not scheduled
    assert result.files_copied == 1


def test_missing_source_file_is_a_failure_not_a_crash(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    ident = content_identity_of_bytes(b"phantom")
    # A NEW file whose source path does not actually exist on disk.
    ghost = ClassifiedFile("ghost.cr3", ident, ident.size_bytes, FileClassification.NEW)
    plan = build_plan([ghost], session_root=str(tmp_path / "session"))
    result = run_job(
        plan,
        source_root=source,
        object_store_root=tmp_path / "objects",
        journal=RecordingJournal(),
        platform=PLATFORM,
    )
    assert result.outcome is JobOutcome.FAILED
    assert result.files_failed == 1
