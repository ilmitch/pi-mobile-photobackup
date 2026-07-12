"""Integration tests for the preflight orchestrator (PRE-001..007, DRY-002/003).

Runs against a real temp source directory on the host with a fake platform for capacity,
so the whole chain (scan -> hash -> snapshot -> classify -> plan -> capacity) is exercised
on macOS.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aethereal.backup.identity import ContentIdentity, content_identity_of_bytes
from aethereal.backup.planner import FileAction
from aethereal.backup.preflight import PreflightOutcome, run_preflight
from aethereal.common.platform import FakePlatformOps

SESSION = "/Backups/2026/2026-07-11/20260711-001_CANON_CARD_01"
TB = 1_000_000_000_000


def _never_verified(_: ContentIdentity) -> bool:
    return False


def _make_source(tmp_path: Path, files: dict[str, bytes]) -> Path:
    root = tmp_path / "source"
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def test_ready_with_new_files(tmp_path: Path) -> None:
    root = _make_source(
        tmp_path, {"DCIM/100CANON/IMG_1.CR3": b"aaaa", "DCIM/100CANON/IMG_2.CR3": b"bbbbbb"}
    )
    result = run_preflight(
        root,
        session_root=SESSION,
        destination_path=tmp_path,
        platform=FakePlatformOps(total_bytes=1 * TB, free_bytes=1 * TB),
        verified=_never_verified,
    )
    assert result.outcome is PreflightOutcome.READY
    assert result.files_discovered == 2
    assert result.new_file_count == 2
    assert result.new_bytes == 10
    assert result.source_bytes_scanned == 10
    assert result.snapshot.file_count == 2
    assert result.snapshot.snapshot_sha256  # deterministic non-empty digest


def test_blocked_on_insufficient_capacity(tmp_path: Path) -> None:
    root = _make_source(tmp_path, {"big.mp4": b"x" * 1000})
    result = run_preflight(
        root,
        session_root=SESSION,
        destination_path=tmp_path,
        # Free space far below required (reserve floor + 10 GB margin dominate).
        platform=FakePlatformOps(total_bytes=1 * TB, free_bytes=1000),
        verified=_never_verified,
    )
    assert result.outcome is PreflightOutcome.BLOCKED
    assert any("insufficient destination capacity" in r for r in result.block_reasons)


def test_already_backed_up_files_are_not_new(tmp_path: Path) -> None:
    known = content_identity_of_bytes(b"known content")
    root = _make_source(tmp_path, {"a.cr3": b"known content", "b.cr3": b"new content"})

    def verified(identity: ContentIdentity) -> bool:
        return identity == known

    result = run_preflight(
        root,
        session_root=SESSION,
        destination_path=tmp_path,
        platform=FakePlatformOps(total_bytes=1 * TB, free_bytes=1 * TB),
        verified=verified,
    )
    assert result.already_backed_up_count == 1
    assert result.new_file_count == 1


def test_intra_job_duplicate_counted_once(tmp_path: Path) -> None:
    dup = b"identical drone frame"
    root = _make_source(tmp_path, {"DCIM/IMG_1.CR3": dup, "DCIM/IMG_2.CR3": dup})
    result = run_preflight(
        root,
        session_root=SESSION,
        destination_path=tmp_path,
        platform=FakePlatformOps(total_bytes=1 * TB, free_bytes=1 * TB),
        verified=_never_verified,
    )
    assert result.plan.new_object_count == 1
    assert result.plan.intra_job_duplicate_count == 1
    assert result.new_bytes == len(dup)
    actions = {f.relative_path: f.action for f in result.plan.files}
    assert actions["DCIM/IMG_2.CR3"] is FileAction.LINK_NEW_OBJECT_SAME_JOB


def test_symlink_is_unsupported_and_warns(tmp_path: Path) -> None:
    root = _make_source(tmp_path, {"real.cr3": b"data"})
    (root / "link.cr3").symlink_to(root / "real.cr3")
    result = run_preflight(
        root,
        session_root=SESSION,
        destination_path=tmp_path,
        platform=FakePlatformOps(total_bytes=1 * TB, free_bytes=1 * TB),
        verified=_never_verified,
    )
    assert result.unsupported_count == 1
    assert result.outcome is PreflightOutcome.WARNING


def test_unreadable_file_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _make_source(tmp_path, {"ok.cr3": b"fine", "bad.cr3": b"unreadable"})

    from aethereal.backup.identity import content_identity_of_path as real

    def flaky(path: Path, *, chunk_bytes: int) -> ContentIdentity:
        if path.name == "bad.cr3":
            raise OSError("simulated read error")
        return real(path, chunk_bytes=chunk_bytes)

    monkeypatch.setattr("aethereal.backup.preflight.content_identity_of_path", flaky)

    result = run_preflight(
        root,
        session_root=SESSION,
        destination_path=tmp_path,
        platform=FakePlatformOps(total_bytes=1 * TB, free_bytes=1 * TB),
        verified=_never_verified,
    )
    assert result.outcome is PreflightOutcome.BLOCKED
    assert result.unreadable_count == 1
    assert any("unreadable" in r for r in result.block_reasons)


def test_missing_source_root_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        run_preflight(
            tmp_path / "does-not-exist",
            session_root=SESSION,
            destination_path=tmp_path,
            platform=FakePlatformOps(total_bytes=1 * TB, free_bytes=1 * TB),
            verified=_never_verified,
        )
