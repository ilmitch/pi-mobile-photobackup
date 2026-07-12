"""Query helpers over the destination manifest.

Provides the FILE-005 dedup lookup — whether a given content identity already has a
VERIFIED canonical object on this destination — plus content-identity upsert. Keeping
these behind a small repository lets the pure classification/planner logic depend on
callables rather than on SQLite directly.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from aethereal.backup.identity import ContentIdentity


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class PendingObject:
    """A content object left in PENDING_FINALIZE by an interrupted job (REC-004)."""

    object_id: int
    content_identity_id: int
    size_bytes: int
    sha256: str
    temp_path: str | None
    final_path: str | None


class ManifestRepository:
    """Thin data-access layer over an open destination-manifest connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert_content_identity(self, identity: ContentIdentity) -> int:
        """Return the row id for ``identity``, inserting it if new (idempotent)."""
        self._conn.execute(
            "INSERT OR IGNORE INTO content_identity (size_bytes, sha256, created_at) "
            "VALUES (?, ?, ?)",
            (identity.size_bytes, identity.sha256, _now()),
        )
        row = self._conn.execute(
            "SELECT id FROM content_identity WHERE size_bytes = ? AND sha256 = ?",
            (identity.size_bytes, identity.sha256),
        ).fetchone()
        return int(row[0])

    def content_identity_id(self, identity: ContentIdentity) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM content_identity WHERE size_bytes = ? AND sha256 = ?",
            (identity.size_bytes, identity.sha256),
        ).fetchone()
        return int(row[0]) if row is not None else None

    def has_verified_object(self, identity: ContentIdentity) -> bool:
        """FILE-005: does a VERIFIED canonical object exist for this content identity?"""
        row = self._conn.execute(
            "SELECT 1 FROM content_object o "
            "JOIN content_identity c ON o.content_identity_id = c.id "
            "WHERE c.size_bytes = ? AND c.sha256 = ? AND o.status = 'VERIFIED' LIMIT 1",
            (identity.size_bytes, identity.sha256),
        ).fetchone()
        return row is not None

    def verified_object_path(self, identity: ContentIdentity) -> str | None:
        row = self._conn.execute(
            "SELECT o.object_path FROM content_object o "
            "JOIN content_identity c ON o.content_identity_id = c.id "
            "WHERE c.size_bytes = ? AND c.sha256 = ? AND o.status = 'VERIFIED' LIMIT 1",
            (identity.size_bytes, identity.sha256),
        ).fetchone()
        return str(row[0]) if row is not None else None

    def insert_content_object(
        self,
        content_identity_id: int,
        object_path: str,
        status: str,
        *,
        verified_at: str | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO content_object "
            "(content_identity_id, object_path, status, verified_at) VALUES (?, ?, ?, ?)",
            (content_identity_id, object_path, status, verified_at),
        )
        return int(cur.lastrowid or 0)

    def _content_object_id(self, content_identity_id: int) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM content_object WHERE content_identity_id = ? LIMIT 1",
            (content_identity_id,),
        ).fetchone()
        return int(row[0]) if row is not None else None

    def upsert_content_object_pending(
        self, content_identity_id: int, object_path: str, temp_path: str
    ) -> int:
        """Record (or move) a content object into PENDING_FINALIZE with its temp/final paths."""
        existing = self._content_object_id(content_identity_id)
        if existing is not None:
            self._conn.execute(
                "UPDATE content_object SET status = 'PENDING_FINALIZE', object_path = ?, "
                "pending_temp_path = ?, pending_final_path = ? WHERE id = ?",
                (object_path, temp_path, object_path, existing),
            )
            return existing
        cur = self._conn.execute(
            "INSERT INTO content_object "
            "(content_identity_id, object_path, status, pending_temp_path, pending_final_path) "
            "VALUES (?, ?, 'PENDING_FINALIZE', ?, ?)",
            (content_identity_id, object_path, temp_path, object_path),
        )
        return int(cur.lastrowid or 0)

    def mark_content_object_verified(self, content_identity_id: int, object_path: str) -> int:
        """Transition (or create) the content object as VERIFIED and clear pending paths."""
        existing = self._content_object_id(content_identity_id)
        if existing is not None:
            self._conn.execute(
                "UPDATE content_object SET status = 'VERIFIED', object_path = ?, "
                "verified_at = ?, pending_temp_path = NULL, pending_final_path = NULL "
                "WHERE id = ?",
                (object_path, _now(), existing),
            )
            return existing
        return self.insert_content_object(
            content_identity_id, object_path, "VERIFIED", verified_at=_now()
        )

    def create_backup_job(
        self, backup_job_id: str, *, state: str, session_path: str | None = None
    ) -> None:
        """Insert a minimal backup_job row (satisfies session_entry's foreign key)."""
        self._conn.execute(
            "INSERT INTO backup_job (id, created_at, started_at, state, session_path) "
            "VALUES (?, ?, ?, ?, ?)",
            (backup_job_id, _now(), _now(), state, session_path),
        )

    def count_jobs_for_date(self, id_prefix: str) -> int:
        """Count backup jobs whose id starts with ``id_prefix`` (e.g. ``20260711-``)."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM backup_job WHERE id LIKE ?", (f"{id_prefix}%",)
        ).fetchone()
        return int(row[0])

    def set_backup_job_state(self, backup_job_id: str, state: str) -> None:
        self._conn.execute(
            "UPDATE backup_job SET state = ? WHERE id = ?", (state, backup_job_id)
        )

    _JOB_COLUMNS = (
        "id",
        "created_at",
        "started_at",
        "ended_at",
        "state",
        "session_path",
        "files_copied",
        "files_skipped",
        "files_failed",
        "files_verified",
        "copied_bytes",
    )

    def _job_row_to_dict(self, row: tuple[object, ...]) -> dict[str, object]:
        return dict(zip(self._JOB_COLUMNS, row, strict=True))

    def list_backup_jobs(self) -> list[dict[str, object]]:
        cols = ", ".join(self._JOB_COLUMNS)
        rows = self._conn.execute(
            f"SELECT {cols} FROM backup_job ORDER BY created_at DESC"
        ).fetchall()
        return [self._job_row_to_dict(r) for r in rows]

    def get_backup_job(self, backup_job_id: str) -> dict[str, object] | None:
        cols = ", ".join(self._JOB_COLUMNS)
        row = self._conn.execute(
            f"SELECT {cols} FROM backup_job WHERE id = ?", (backup_job_id,)
        ).fetchone()
        return self._job_row_to_dict(row) if row is not None else None

    def destination_totals(self) -> tuple[int, int]:
        """Return (verified_object_count, total_backed_up_bytes) for the destination."""
        row = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(c.size_bytes), 0) "
            "FROM content_object o JOIN content_identity c ON o.content_identity_id = c.id "
            "WHERE o.status = 'VERIFIED'"
        ).fetchone()
        return int(row[0]), int(row[1])

    def list_incomplete_jobs(self) -> list[str]:
        """Return job ids left in a non-terminal state by an interruption (REC-001)."""
        rows = self._conn.execute(
            "SELECT id FROM backup_job WHERE state IN "
            "('BACKUP_COPYING', 'BACKUP_VERIFYING', 'BACKUP_CANCELLING')"
        ).fetchall()
        return [str(r[0]) for r in rows]

    def finish_backup_job(
        self,
        backup_job_id: str,
        *,
        state: str,
        files_copied: int,
        files_skipped: int,
        files_failed: int,
        files_verified: int,
        copied_bytes: int,
    ) -> None:
        self._conn.execute(
            "UPDATE backup_job SET state = ?, ended_at = ?, files_copied = ?, "
            "files_skipped = ?, files_failed = ?, files_verified = ?, copied_bytes = ? "
            "WHERE id = ?",
            (
                state,
                _now(),
                files_copied,
                files_skipped,
                files_failed,
                files_verified,
                copied_bytes,
                backup_job_id,
            ),
        )

    def insert_session_entry(
        self,
        backup_job_id: str,
        content_object_id: int,
        session_path: str,
        *,
        source_file_id: int | None = None,
        state: str = "VERIFIED",
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO session_entry "
            "(backup_job_id, source_file_id, content_object_id, session_path, state, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (backup_job_id, source_file_id, content_object_id, session_path, state, _now()),
        )
        return int(cur.lastrowid or 0)

    def finalize_session_entry(
        self, backup_job_id: str, content_object_id: int, session_path: str
    ) -> int:
        """Promote a PENDING session entry to VERIFIED, or insert one if absent."""
        row = self._conn.execute(
            "SELECT id FROM session_entry WHERE backup_job_id = ? AND session_path = ? LIMIT 1",
            (backup_job_id, session_path),
        ).fetchone()
        if row is not None:
            self._conn.execute(
                "UPDATE session_entry SET state = 'VERIFIED', content_object_id = ? WHERE id = ?",
                (content_object_id, int(row[0])),
            )
            return int(row[0])
        return self.insert_session_entry(
            backup_job_id, content_object_id, session_path, state="VERIFIED"
        )

    # --- recovery / reconciliation (REC-002/004) ---

    def list_pending_finalize(self) -> list[PendingObject]:
        rows = self._conn.execute(
            "SELECT o.id, o.content_identity_id, c.size_bytes, c.sha256, "
            "o.pending_temp_path, o.pending_final_path "
            "FROM content_object o JOIN content_identity c ON o.content_identity_id = c.id "
            "WHERE o.status = 'PENDING_FINALIZE'"
        ).fetchall()
        return [
            PendingObject(
                object_id=int(r[0]),
                content_identity_id=int(r[1]),
                size_bytes=int(r[2]),
                sha256=str(r[3]),
                temp_path=r[4],
                final_path=r[5],
            )
            for r in rows
        ]

    def pending_session_entries(self, content_object_id: int) -> list[tuple[int, str, str]]:
        rows = self._conn.execute(
            "SELECT id, backup_job_id, session_path FROM session_entry "
            "WHERE content_object_id = ? AND state = 'PENDING'",
            (content_object_id,),
        ).fetchall()
        return [(int(r[0]), str(r[1]), str(r[2])) for r in rows]

    def finalize_session_entry_by_id(self, entry_id: int) -> None:
        self._conn.execute(
            "UPDATE session_entry SET state = 'VERIFIED' WHERE id = ?", (entry_id,)
        )

    def discard_pending_object(self, content_object_id: int) -> None:
        """Delete an unrecoverable pending object and its pending session entries."""
        self._conn.execute(
            "DELETE FROM session_entry WHERE content_object_id = ? AND state = 'PENDING'",
            (content_object_id,),
        )
        self._conn.execute("DELETE FROM content_object WHERE id = ?", (content_object_id,))
