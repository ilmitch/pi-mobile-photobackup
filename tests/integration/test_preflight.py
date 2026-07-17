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


def test_media_filter_keeps_only_images_and_video(tmp_path: Path) -> None:
    # A realistic card: real media, a camera management file, an unlisted extension, and the
    # macOS junk a card picks up on a Mac (an AppleDouble sidecar sharing the .MOV extension,
    # plus a dot-directory of Spotlight index files).
    root = _make_source(
        tmp_path,
        {
            "DCIM/100CANON/MVI_1234.MOV": b"video-bytes",
            "DCIM/100CANON/IMG_1234.CR3": b"raw-bytes",
            "DCIM/100CANON/IMG_1234.JPG": b"jpg-bytes",
            "DCIM/CANONMSC/M100CANON.CTG": b"canon-db",  # not a media extension
            "DCIM/100CANON/._MVI_1234.MOV": b"appledouble",  # dotfile, .MOV extension
            ".Spotlight-V100/store.db": b"spotlight-junk",  # dot-directory
            ".DS_Store": b"finder-junk",
        },
    )
    media = frozenset(("jpg", "cr3", "mov"))
    result = run_preflight(
        root,
        session_root=SESSION,
        destination_path=tmp_path,
        platform=FakePlatformOps(total_bytes=1 * TB, free_bytes=1 * TB),
        verified=_never_verified,
        media_extensions=media,
    )
    kept = {f.relative_path for f in result.plan.files}
    assert kept == {
        "DCIM/100CANON/MVI_1234.MOV",
        "DCIM/100CANON/IMG_1234.CR3",
        "DCIM/100CANON/IMG_1234.JPG",
    }
    # The AppleDouble ._*.MOV must not sneak in on its extension, and nothing is left to
    # block or warn: the junk is skipped outright, not classified UNREADABLE/UNSUPPORTED.
    assert result.files_discovered == 3
    assert result.unsupported_count == 0
    assert result.unreadable_count == 0
    assert result.snapshot.file_count == 3
    assert result.outcome is PreflightOutcome.READY
    # Skip telemetry: the unlisted .ctg is a visible non-media skip; the AppleDouble ._*.MOV,
    # .DS_Store, and Spotlight store.db are hidden junk counted apart (never alarming).
    assert result.skipped_non_media_count == 1
    assert result.skipped_extensions == ("ctg",)
    assert result.skipped_hidden_count == 3


def test_media_filter_off_reports_no_skips(tmp_path: Path) -> None:
    root = _make_source(tmp_path, {"IMG_1.CR3": b"raw", "notes.txt": b"text"})
    result = run_preflight(
        root,
        session_root=SESSION,
        destination_path=tmp_path,
        platform=FakePlatformOps(total_bytes=1 * TB, free_bytes=1 * TB),
        verified=_never_verified,
    )
    assert result.skipped_non_media_count == 0
    assert result.skipped_extensions == ()
    assert result.skipped_hidden_count == 0


def test_empty_media_filter_is_faithful(tmp_path: Path) -> None:
    # No filter -> every regular file is scanned, including hidden ones (back-compat).
    root = _make_source(
        tmp_path, {"IMG_1.CR3": b"raw", ".DS_Store": b"junk", "notes.txt": b"text"}
    )
    result = run_preflight(
        root,
        session_root=SESSION,
        destination_path=tmp_path,
        platform=FakePlatformOps(total_bytes=1 * TB, free_bytes=1 * TB),
        verified=_never_verified,
    )
    assert result.files_discovered == 3


def test_missing_source_root_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        run_preflight(
            tmp_path / "does-not-exist",
            session_root=SESSION,
            destination_path=tmp_path,
            platform=FakePlatformOps(total_bytes=1 * TB, free_bytes=1 * TB),
            verified=_never_verified,
        )
