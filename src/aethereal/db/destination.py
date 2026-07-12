"""Destination manifest database (the authoritative backup manifest).

Implements PRD v0.3 DB-001/002/003 and Implementation Plan v0.3 section 6. This database
lives on the destination SSD and is authoritative for verification state on that SSD, so
it uses WAL mode with ``synchronous=FULL`` and durably commits verified/PENDING_FINALIZE
transitions before the engine crosses the corresponding filesystem boundary.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from aethereal.common.version import __version__
from aethereal.db.migrations import Migration, apply_migrations

# --- v1 schema (Impl §6, destination manifest) -----------------------------------

_V1_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE source_volume (
        id INTEGER PRIMARY KEY,
        filesystem_serial TEXT,
        volume_label TEXT,
        filesystem_type TEXT,
        capacity_bytes INTEGER,
        partition_start INTEGER,
        partition_size INTEGER,
        device_identifier TEXT,
        device_model TEXT,
        device_serial TEXT,
        logical_name TEXT,
        first_seen_at TEXT,
        last_seen_at TEXT
    )
    """,
    """
    CREATE TABLE source_snapshot (
        id INTEGER PRIMARY KEY,
        source_volume_id INTEGER REFERENCES source_volume(id),
        snapshot_sha256 TEXT NOT NULL,
        created_at TEXT,
        file_count INTEGER,
        total_bytes INTEGER
    )
    """,
    """
    CREATE TABLE backup_job (
        id TEXT PRIMARY KEY,
        created_at TEXT,
        started_at TEXT,
        ended_at TEXT,
        source_volume_id INTEGER REFERENCES source_volume(id),
        source_snapshot_id INTEGER REFERENCES source_snapshot(id),
        destination_uuid TEXT,
        session_path TEXT,
        state TEXT,
        files_discovered INTEGER,
        files_planned INTEGER,
        files_copied INTEGER,
        files_skipped INTEGER,
        files_verified INTEGER,
        files_failed INTEGER,
        planned_bytes INTEGER,
        copied_bytes INTEGER,
        warning_count INTEGER,
        error_count INTEGER
    )
    """,
    """
    CREATE TABLE preflight (
        id INTEGER PRIMARY KEY,
        backup_job_id TEXT REFERENCES backup_job(id),
        created_at TEXT,
        source_file_count INTEGER,
        new_file_count INTEGER,
        already_backed_up_count INTEGER,
        conflict_count INTEGER,
        unreadable_count INTEGER,
        source_bytes INTEGER,
        new_bytes INTEGER,
        destination_free_bytes INTEGER,
        operational_reserve_bytes INTEGER,
        safety_margin_bytes INTEGER,
        required_bytes INTEGER,
        result TEXT
    )
    """,
    """
    CREATE TABLE content_identity (
        id INTEGER PRIMARY KEY,
        size_bytes INTEGER NOT NULL,
        sha256 TEXT NOT NULL,
        created_at TEXT
    )
    """,
    "CREATE UNIQUE INDEX ux_content_identity ON content_identity (size_bytes, sha256)",
    """
    CREATE TABLE source_file (
        id INTEGER PRIMARY KEY,
        source_snapshot_id INTEGER REFERENCES source_snapshot(id),
        relative_path TEXT,
        filename TEXT,
        size_bytes INTEGER,
        mtime_ns INTEGER,
        content_identity_id INTEGER REFERENCES content_identity(id)
    )
    """,
    """
    CREATE TABLE content_object (
        id INTEGER PRIMARY KEY,
        content_identity_id INTEGER REFERENCES content_identity(id),
        object_path TEXT,
        status TEXT,
        pending_temp_path TEXT,
        pending_final_path TEXT,
        verified_at TEXT
    )
    """,
    """
    CREATE TABLE session_entry (
        id INTEGER PRIMARY KEY,
        backup_job_id TEXT REFERENCES backup_job(id),
        source_file_id INTEGER REFERENCES source_file(id),
        content_object_id INTEGER REFERENCES content_object(id),
        session_path TEXT,
        state TEXT,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE copy_operation (
        id INTEGER PRIMARY KEY,
        backup_job_id TEXT REFERENCES backup_job(id),
        source_file_id INTEGER REFERENCES source_file(id),
        content_object_id INTEGER REFERENCES content_object(id),
        started_at TEXT,
        ended_at TEXT,
        bytes_written INTEGER,
        preflight_source_sha256 TEXT,
        copy_stream_sha256 TEXT,
        destination_sha256 TEXT,
        state TEXT,
        attempt_number INTEGER,
        error_code TEXT,
        error_message TEXT
    )
    """,
    """
    CREATE TABLE verification_result (
        id INTEGER PRIMARY KEY,
        copy_operation_id INTEGER REFERENCES copy_operation(id),
        preflight_source_sha256 TEXT,
        copy_stream_sha256 TEXT,
        destination_sha256 TEXT,
        verified_at TEXT,
        result TEXT
    )
    """,
    """
    CREATE TABLE event_log (
        id INTEGER PRIMARY KEY,
        timestamp TEXT,
        severity TEXT,
        component TEXT,
        backup_job_id TEXT,
        event_code TEXT,
        message TEXT,
        details_json TEXT
    )
    """,
)

DESTINATION_MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, name="initial_destination_schema", statements=_V1_STATEMENTS),
)


def open_destination_manifest(
    path: Path | str,
    *,
    application_version: str = __version__,
    synchronous: str = "FULL",
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    """Open (creating if needed) and migrate the destination manifest.

    Uses autocommit mode (``isolation_level=None``) so the migration framework controls
    transactions explicitly, and enables WAL + ``synchronous=FULL`` per DB-002. Set
    ``check_same_thread=False`` when the backup worker thread and the web event loop share
    one connection (WAL permits a concurrent reader with the single writer).
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=check_same_thread)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA synchronous={synchronous}")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn, DESTINATION_MIGRATIONS, application_version=application_version)
    return conn
