"""Unit tests for source snapshot identity (Verification Plan v0.3 UT-004, SRC-007)."""

from __future__ import annotations

import pytest

from aethereal.backup.snapshot import (
    SourceFileRecord,
    build_canonical_manifest,
    build_source_snapshot,
    normalize_relative_path,
)


def _rec(path: str, size: int, sha: str) -> SourceFileRecord:
    return SourceFileRecord(relative_path=path, size_bytes=size, sha256=sha)


def test_snapshot_is_order_independent() -> None:
    a = [
        _rec("DCIM/100CANON/IMG_2.CR3", 20, "bb"),
        _rec("DCIM/100CANON/IMG_1.CR3", 10, "aa"),
    ]
    b = list(reversed(a))
    assert build_source_snapshot(a).snapshot_sha256 == build_source_snapshot(b).snapshot_sha256


def test_identical_manifest_identical_snapshot() -> None:
    recs = [_rec("a.txt", 1, "11"), _rec("b/c.txt", 2, "22")]
    assert build_source_snapshot(recs) == build_source_snapshot(list(recs))


def test_path_change_changes_snapshot() -> None:
    base = [_rec("DCIM/IMG_1.CR3", 10, "aa")]
    moved = [_rec("DCIM/IMG_2.CR3", 10, "aa")]
    assert build_source_snapshot(base).snapshot_sha256 != build_source_snapshot(moved).snapshot_sha256


def test_size_change_changes_snapshot() -> None:
    base = [_rec("a.txt", 10, "aa")]
    bigger = [_rec("a.txt", 11, "aa")]
    assert build_source_snapshot(base).snapshot_sha256 != build_source_snapshot(bigger).snapshot_sha256


def test_content_hash_change_changes_snapshot() -> None:
    base = [_rec("a.txt", 10, "aa")]
    changed = [_rec("a.txt", 10, "ab")]
    assert build_source_snapshot(base).snapshot_sha256 != build_source_snapshot(changed).snapshot_sha256


def test_snapshot_counts_and_totals() -> None:
    snap = build_source_snapshot([_rec("a", 10, "aa"), _rec("b", 25, "bb")])
    assert snap.file_count == 2
    assert snap.total_bytes == 35


def test_manifest_records_are_newline_terminated() -> None:
    manifest = build_canonical_manifest([_rec("a", 1, "aa"), _rec("b", 2, "bb")])
    assert manifest.count(b"\n") == 2


def test_delimiter_forgery_does_not_collide() -> None:
    # Two distinct file sets must not produce the same manifest via crafted fields.
    one = build_canonical_manifest([_rec("a", 1, "aa"), _rec("b", 2, "bb")])
    two = build_canonical_manifest([_rec("a", 1, "aa\x00b\x002\x00bb"), _rec("b", 2, "bb")])
    # sha values here are synthetic; the point is the encodings differ.
    assert one != two


# --- path normalization ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("./DCIM/IMG.CR3", "DCIM/IMG.CR3"),
        ("DCIM/IMG.CR3/", "DCIM/IMG.CR3"),
        ("DCIM\\100CANON\\IMG.CR3", "DCIM/100CANON/IMG.CR3"),
        ("a//b", "a/b"),
    ],
)
def test_normalize_relative_path(raw: str, expected: str) -> None:
    assert normalize_relative_path(raw) == expected


def test_normalize_rejects_absolute() -> None:
    with pytest.raises(ValueError):
        normalize_relative_path("/etc/passwd")


def test_normalize_rejects_parent_traversal() -> None:
    with pytest.raises(ValueError):
        normalize_relative_path("../secrets")
