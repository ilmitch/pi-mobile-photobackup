"""Source snapshot identity.

Implements PRD v0.3 SRC-007 and Implementation Plan v0.3 section 12. Every completed
strict preflight derives a deterministic snapshot identity from a canonical, ordered
manifest of (relative path, size, SHA-256) for every regular source file. The snapshot
identity — not the observed FAT/exFAT volume serial — authorises interrupted-job
recovery, so a different card with a colliding serial but different content is rejected.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True, slots=True)
class SourceFileRecord:
    """One regular source file's contribution to the snapshot manifest."""

    relative_path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """The deterministic identity of a complete source scan."""

    snapshot_sha256: str
    file_count: int
    total_bytes: int


def normalize_relative_path(relative_path: str) -> str:
    """Return a canonical POSIX form: forward slashes, no leading ``./``, no trailing ``/``.

    Rejects absolute paths and ``..`` components so a manifest cannot reference outside
    the source root.
    """
    pure = PurePosixPath(relative_path.replace("\\", "/"))
    if pure.is_absolute():
        raise ValueError(f"relative_path must not be absolute: {relative_path!r}")
    parts = [p for p in pure.parts if p != "."]
    if any(p == ".." for p in parts):
        raise ValueError(f"relative_path must not contain '..': {relative_path!r}")
    return "/".join(parts)


def _encode_record(record: SourceFileRecord) -> bytes:
    """Encode one record injection-safely.

    NUL separates fields and newline separates records; neither can appear in a valid
    FAT/exFAT filename, so distinct manifests cannot collide through delimiter forgery.
    """
    if record.size_bytes < 0:
        raise ValueError("size_bytes must be non-negative")
    path = normalize_relative_path(record.relative_path)
    return b"\x00".join(
        (path.encode("utf-8"), str(record.size_bytes).encode("ascii"), record.sha256.encode("ascii"))
    ) + b"\n"


def build_canonical_manifest(records: Iterable[SourceFileRecord]) -> bytes:
    """Serialise ``records`` into the canonical manifest byte string.

    Records are sorted by normalized relative path (Unicode code-point order) so the
    output is independent of filesystem walk order and host locale.
    """
    normalized = sorted(records, key=lambda r: normalize_relative_path(r.relative_path))
    return b"".join(_encode_record(r) for r in normalized)


def build_source_snapshot(records: Iterable[SourceFileRecord]) -> SourceSnapshot:
    """Compute the SRC-007 source snapshot identity from the file records."""
    materialized = list(records)
    manifest = build_canonical_manifest(materialized)
    return SourceSnapshot(
        snapshot_sha256=hashlib.sha256(manifest).hexdigest(),
        file_count=len(materialized),
        total_bytes=sum(r.size_bytes for r in materialized),
    )
