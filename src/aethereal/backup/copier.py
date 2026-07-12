"""Copy, three-way verify, and crash-recoverable finalize for one content object.

Implements PRD v0.3 COPY-001..005 and VER-001..005, and Implementation Plan v0.3
section 15. For a NEW content object:

  copy source -> partial (computing copy-stream hash H2)
  -> fsync -> evict cache -> reopen -> destination hash H3
  -> require H1 == H2 == H3
  -> durable PENDING_FINALIZE -> atomic rename -> fsync dir
  -> session hardlink -> fsync dir -> mark VERIFIED

The durable ``PENDING_FINALIZE`` record is written *before* the rename so the
rename-before-commit window is reconcilable (VER-004). ``H1`` is the strict preflight
hash; ``H2`` catches an unstable source read; ``H3`` proves the bytes landed on the
device. Filesystem durability (fsync/rename/hardlink) uses the stdlib directly so tests
exercise real behavior; only cache eviction goes through the ``PlatformOps`` seam.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from aethereal.backup.identity import DEFAULT_CHUNK_BYTES, ContentIdentity, hash_stream
from aethereal.backup.object_store import DEFAULT_PARTIAL_SUFFIX, object_path, partial_path
from aethereal.common.platform import PlatformOps


class CopyOutcome(str, Enum):
    """Terminal outcome of a copy+verify+finalize for one object."""

    VERIFIED = "VERIFIED"
    SOURCE_UNSTABLE = "SOURCE_UNSTABLE"  # H2 != H1: source read disagreed with preflight
    DESTINATION_MISMATCH = "DESTINATION_MISMATCH"  # H3 != H1: written bytes disagree
    FAILED = "FAILED"  # retries exhausted


class SessionPathConflict(Exception):
    """Raised when a session path is occupied by a different inode (FILE-007/COPY-002)."""


class FinalizeJournal(Protocol):
    """Durable record of the finalize step (implemented by the destination manifest)."""

    def record_pending_finalize(
        self, identity: ContentIdentity, *, temp_path: str, final_path: str, session_path: str
    ) -> None: ...

    def mark_verified(
        self, identity: ContentIdentity, *, object_path: str, session_path: str
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class CopyResult:
    """Outcome and evidence for a single planned file."""

    outcome: CopyOutcome
    object_path: str
    session_path: str
    expected_sha256: str
    copy_stream_sha256: str | None
    destination_sha256: str | None
    bytes_written: int
    attempts: int


class _AttemptResult(str, Enum):
    OK = "OK"
    SOURCE_UNSTABLE = "SOURCE_UNSTABLE"
    DESTINATION_MISMATCH = "DESTINATION_MISMATCH"


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _copy_and_verify_once(
    source_path: Path,
    partial: Path,
    expected: ContentIdentity,
    *,
    platform: PlatformOps,
    chunk_bytes: int,
) -> tuple[_AttemptResult, str, str | None, int]:
    """One copy attempt. Returns (result, H2, H3, bytes). Removes the partial on failure."""
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.unlink(missing_ok=True)

    digest = hashlib.sha256()
    size = 0
    with source_path.open("rb") as src, partial.open("xb") as dst:
        while True:
            chunk = src.read(chunk_bytes)
            if not chunk:
                break
            digest.update(chunk)
            dst.write(chunk)
            size += len(chunk)
        dst.flush()
        os.fsync(dst.fileno())
    h2 = digest.hexdigest()

    # H2 vs H1: did the source read agree with the strict preflight hash? (COPY-004)
    if size != expected.size_bytes or h2 != expected.sha256:
        partial.unlink(missing_ok=True)
        return (_AttemptResult.SOURCE_UNSTABLE, h2, None, size)

    # H3: drop cache, reopen, and hash what actually landed on the device (COPY-005).
    with partial.open("rb") as reader:
        platform.evict_cache(reader.fileno(), 0, size)
        h3 = hash_stream(reader, chunk_bytes=chunk_bytes).sha256

    if h3 != expected.sha256:
        partial.unlink(missing_ok=True)
        return (_AttemptResult.DESTINATION_MISMATCH, h2, h3, size)

    return (_AttemptResult.OK, h2, h3, size)


def _link_into_session(final: Path, session_path: str, *, allow_existing: bool = True) -> None:
    """Hardlink ``final`` into the session tree, then fsync the session directory."""
    session = Path(session_path)
    session.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(final, session)
    except FileExistsError:
        if not allow_existing or session.stat().st_ino != final.stat().st_ino:
            raise SessionPathConflict(session_path) from None
    _fsync_dir(session.parent)


def place_session_link(final: Path, session_path: str) -> None:
    """Public helper for recovery: (idempotently) hardlink ``final`` into the session."""
    _link_into_session(final, session_path)


def link_verified_object(
    object_store_root: Path | str,
    identity: ContentIdentity,
    session_path: str,
    journal: FinalizeJournal,
) -> CopyResult:
    """Link an already-verified canonical object into the session (no copy).

    Used for ALREADY_BACKED_UP and R2-2 LINK_NEW_OBJECT_SAME_JOB actions.
    """
    final = object_path(object_store_root, identity.sha256)
    if not final.exists():
        raise FileNotFoundError(f"canonical object missing for link: {final}")
    _link_into_session(final, session_path)
    journal.mark_verified(identity, object_path=str(final), session_path=session_path)
    return CopyResult(
        outcome=CopyOutcome.VERIFIED,
        object_path=str(final),
        session_path=session_path,
        expected_sha256=identity.sha256,
        copy_stream_sha256=None,
        destination_sha256=None,
        bytes_written=0,
        attempts=0,
    )


def copy_verify_finalize(
    source_path: Path,
    expected: ContentIdentity,
    *,
    object_store_root: Path | str,
    session_path: str,
    journal: FinalizeJournal,
    platform: PlatformOps,
    retries: int = 2,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    partial_suffix: str = DEFAULT_PARTIAL_SUFFIX,
) -> CopyResult:
    """Copy a NEW object, three-way verify, and finalize durably with retries (VER-005)."""
    final = object_path(object_store_root, expected.sha256)
    partial = partial_path(object_store_root, expected.sha256, suffix=partial_suffix)

    # If the canonical object already exists and is intact, just link (dedup/recovery).
    if final.exists():
        return link_verified_object(object_store_root, expected, session_path, journal)

    last = _AttemptResult.SOURCE_UNSTABLE
    h2: str | None = None
    h3: str | None = None
    attempts = 0

    for _ in range(retries + 1):
        attempts += 1
        result, h2, h3, size = _copy_and_verify_once(
            source_path, partial, expected, platform=platform, chunk_bytes=chunk_bytes
        )
        if result is _AttemptResult.OK:
            # Durable PENDING_FINALIZE before the rename (VER-004 crash-window guard).
            journal.record_pending_finalize(
                expected,
                temp_path=str(partial),
                final_path=str(final),
                session_path=session_path,
            )
            os.replace(partial, final)
            _fsync_dir(final.parent)
            _link_into_session(final, session_path)
            journal.mark_verified(expected, object_path=str(final), session_path=session_path)
            return CopyResult(
                outcome=CopyOutcome.VERIFIED,
                object_path=str(final),
                session_path=session_path,
                expected_sha256=expected.sha256,
                copy_stream_sha256=h2,
                destination_sha256=h3,
                bytes_written=size,
                attempts=attempts,
            )
        last = result

    partial.unlink(missing_ok=True)
    failed_outcome = (
        CopyOutcome.SOURCE_UNSTABLE
        if last is _AttemptResult.SOURCE_UNSTABLE
        else CopyOutcome.DESTINATION_MISMATCH
    )
    return CopyResult(
        outcome=failed_outcome,
        object_path=str(final),
        session_path=session_path,
        expected_sha256=expected.sha256,
        copy_stream_sha256=h2,
        destination_sha256=h3,
        bytes_written=0,
        attempts=attempts,
    )
