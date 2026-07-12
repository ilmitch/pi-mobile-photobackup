"""Interrupted-backup recovery.

Implements PRD v0.3 REC-001..006 and Implementation Plan v0.3 section 17. On startup the
engine reconciles every ``PENDING_FINALIZE`` content object against the filesystem:

- If a candidate object (final, else temp) exists and rehashes to the expected content
  identity, finalize it — rename temp into place if needed, (re)create the pending
  session hardlinks, and mark VERIFIED. This covers the rename-before-commit and
  rename-after crash windows (FI-REC-005/006).
- Otherwise the candidate is unprovable: discard it and let the file be recopied
  (REC-003). SQLite is never trusted as proof of file existence, and the filesystem is
  never trusted as proof of verification (REC-002).

Finally, any stray ``*.aethereal-partial`` object with no pending record is an orphan and
is removed (REC-003).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from aethereal.backup.copier import _fsync_dir, place_session_link
from aethereal.backup.identity import DEFAULT_CHUNK_BYTES, ContentIdentity, content_identity_of_path
from aethereal.backup.object_store import DEFAULT_PARTIAL_SUFFIX, object_path
from aethereal.db.manifest_repo import ManifestRepository


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    """Summary of a reconciliation pass."""

    finalized: int
    discarded: int
    orphan_partials_removed: int


def _remove_orphan_partials(object_store_root: Path) -> int:
    if not object_store_root.exists():
        return 0
    removed = 0
    for partial in object_store_root.rglob(f"*{DEFAULT_PARTIAL_SUFFIX}"):
        partial.unlink(missing_ok=True)
        removed += 1
    return removed


def recover_destination(
    repo: ManifestRepository,
    *,
    object_store_root: Path | str,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
) -> RecoveryReport:
    """Reconcile all interrupted PENDING_FINALIZE objects and clean orphan partials."""
    root = Path(object_store_root)
    finalized = 0
    discarded = 0

    for pending in repo.list_pending_finalize():
        expected = ContentIdentity(size_bytes=pending.size_bytes, sha256=pending.sha256)
        final = (
            Path(pending.final_path)
            if pending.final_path
            else object_path(root, pending.sha256)
        )
        temp = Path(pending.temp_path) if pending.temp_path else None

        if final.exists():
            candidate: Path | None = final
        elif temp is not None and temp.exists():
            candidate = temp
        else:
            candidate = None

        if candidate is not None and content_identity_of_path(candidate, chunk_bytes=chunk_bytes) == expected:
            if candidate is not final:
                os.replace(candidate, final)
                _fsync_dir(final.parent)
            for entry_id, _job_id, session_path in repo.pending_session_entries(pending.object_id):
                place_session_link(final, session_path)
                repo.finalize_session_entry_by_id(entry_id)
            repo.mark_content_object_verified(pending.content_identity_id, str(final))
            finalized += 1
        else:
            # Unprovable: remove any partial/corrupt candidates and schedule recopy.
            if temp is not None:
                temp.unlink(missing_ok=True)
            if final.exists():
                final.unlink(missing_ok=True)
            repo.discard_pending_object(pending.object_id)
            discarded += 1

    orphans = _remove_orphan_partials(root)
    return RecoveryReport(
        finalized=finalized, discarded=discarded, orphan_partials_removed=orphans
    )
