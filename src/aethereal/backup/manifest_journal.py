"""Durable finalize journal backed by the destination manifest.

Implements the copier's ``FinalizeJournal`` protocol over ``ManifestRepository`` for a
single backup job (PRD DB-004/DB-005, VER-004). ``record_pending_finalize`` durably
records the PENDING_FINALIZE content object before the rename; ``mark_verified`` promotes
it to VERIFIED and adds the session entry.
"""

from __future__ import annotations

from aethereal.backup.identity import ContentIdentity
from aethereal.db.manifest_repo import ManifestRepository


class JobManifestJournal:
    """Finalize journal scoped to one ``backup_job_id``."""

    def __init__(self, repo: ManifestRepository, backup_job_id: str) -> None:
        self._repo = repo
        self._job_id = backup_job_id

    def record_pending_finalize(
        self,
        identity: ContentIdentity,
        *,
        temp_path: str,
        final_path: str,
        session_path: str,
    ) -> None:
        identity_id = self._repo.upsert_content_identity(identity)
        object_id = self._repo.upsert_content_object_pending(identity_id, final_path, temp_path)
        # A PENDING session entry records the intended hardlink target so recovery can
        # complete it after a crash in the finalize window (REC-004).
        self._repo.insert_session_entry(self._job_id, object_id, session_path, state="PENDING")

    def mark_verified(
        self, identity: ContentIdentity, *, object_path: str, session_path: str
    ) -> None:
        identity_id = self._repo.upsert_content_identity(identity)
        object_id = self._repo.mark_content_object_verified(identity_id, object_path)
        self._repo.finalize_session_entry(self._job_id, object_id, session_path)
