"""Unit tests for the backup planner, including the R2-2 intra-job dedup fix."""

from __future__ import annotations

from aethereal.backup.classification import FileClassification
from aethereal.backup.identity import content_identity_of_bytes
from aethereal.backup.planner import (
    ClassifiedFile,
    FileAction,
    build_plan,
)

SESSION = "/Backups/2026/2026-07-11/20260711-001_CANON_CARD_01"


def _new(path: str, data: bytes) -> ClassifiedFile:
    ident = content_identity_of_bytes(data)
    return ClassifiedFile(path, ident, ident.size_bytes, FileClassification.NEW)


def test_all_new_distinct_are_copied() -> None:
    plan = build_plan([_new("a.cr3", b"aaaa"), _new("b.cr3", b"bbbbbb")], session_root=SESSION)
    assert plan.new_object_count == 2
    assert plan.new_object_bytes == 4 + 6
    assert plan.largest_new_object_bytes == 6
    assert not plan.blocked
    assert all(f.action is FileAction.COPY_VERIFY_OBJECT_AND_LINK for f in plan.files)


def test_intra_job_duplicate_is_linked_not_copied() -> None:
    # R2-2: two source files with identical content in ONE job.
    dup = b"identical bytes"
    plan = build_plan(
        [_new("DCIM/IMG_1.CR3", dup), _new("DCIM/IMG_2.CR3", dup)], session_root=SESSION
    )
    actions = {f.relative_path: f.action for f in plan.files}
    assert actions["DCIM/IMG_1.CR3"] is FileAction.COPY_VERIFY_OBJECT_AND_LINK
    assert actions["DCIM/IMG_2.CR3"] is FileAction.LINK_NEW_OBJECT_SAME_JOB
    # Content counted once for capacity; the duplicate is tracked separately.
    assert plan.new_object_count == 1
    assert plan.new_object_bytes == len(dup)
    assert plan.intra_job_duplicate_count == 1
    assert not plan.blocked


def test_already_backed_up_is_linked() -> None:
    ident = content_identity_of_bytes(b"known")
    item = ClassifiedFile("a.cr3", ident, ident.size_bytes, FileClassification.ALREADY_BACKED_UP)
    plan = build_plan([item], session_root=SESSION)
    assert plan.files[0].action is FileAction.LINK_EXISTING_VERIFIED_OBJECT
    assert plan.already_backed_up_count == 1
    assert plan.new_object_count == 0


def test_conflict_blocks_job() -> None:
    ident = content_identity_of_bytes(b"x")
    item = ClassifiedFile("a.cr3", ident, ident.size_bytes, FileClassification.POTENTIAL_CONFLICT)
    plan = build_plan([item, _new("b.cr3", b"bb")], session_root=SESSION)
    assert plan.blocked
    assert plan.conflict_count == 1
    assert any(f.action is FileAction.BLOCK_CONFLICT for f in plan.files)


def test_unreadable_blocks_job() -> None:
    item = ClassifiedFile("bad.cr3", None, 0, FileClassification.UNREADABLE)
    plan = build_plan([item], session_root=SESSION)
    assert plan.blocked
    assert plan.unreadable_count == 1
    assert plan.files[0].action is FileAction.BLOCK_UNREADABLE


def test_unsupported_is_skipped_not_blocking() -> None:
    ident = content_identity_of_bytes(b"link-target")
    item = ClassifiedFile("link", ident, ident.size_bytes, FileClassification.UNSUPPORTED)
    plan = build_plan([item, _new("b.cr3", b"bb")], session_root=SESSION)
    actions = {f.relative_path: f.action for f in plan.files}
    assert not plan.blocked
    assert plan.unsupported_count == 1
    assert actions["link"] is FileAction.SKIP_UNSUPPORTED


def test_session_path_is_composed_from_root() -> None:
    plan = build_plan([_new("DCIM/100CANON/IMG.CR3", b"z")], session_root=SESSION)
    assert plan.files[0].session_path == f"{SESSION}/DCIM/100CANON/IMG.CR3"


def test_plan_is_deterministically_ordered() -> None:
    plan = build_plan(
        [_new("z.cr3", b"z"), _new("a.cr3", b"a"), _new("m.cr3", b"m")], session_root=SESSION
    )
    assert [f.relative_path for f in plan.files] == ["a.cr3", "m.cr3", "z.cr3"]
