"""Appliance-local database (non-authoritative).

Implements PRD v0.3 DB-001 and Implementation Plan v0.3 section 6. This database lives
on the Pi's system storage and holds configuration metadata, source aliases, and
non-authoritative system events. Backup correctness must not depend on it: losing it
must not invalidate verified destination content (verified by FI-REC-009).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from aethereal.common.version import __version__
from aethereal.db.migrations import Migration, apply_migrations

_V1_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE appliance (
        installation_id TEXT PRIMARY KEY,
        created_at TEXT,
        installed_version TEXT,
        last_successful_health_check TEXT
    )
    """,
    """
    CREATE TABLE source_alias (
        id INTEGER PRIMARY KEY,
        observed_identity_json TEXT,
        logical_name TEXT,
        first_seen_at TEXT,
        last_seen_at TEXT
    )
    """,
    """
    CREATE TABLE system_event (
        id INTEGER PRIMARY KEY,
        timestamp TEXT,
        severity TEXT,
        component TEXT,
        event_code TEXT,
        message TEXT,
        details_json TEXT
    )
    """,
)

APPLIANCE_MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, name="initial_appliance_schema", statements=_V1_STATEMENTS),
)


def open_appliance_db(
    path: Path | str, *, application_version: str = __version__
) -> sqlite3.Connection:
    """Open (creating if needed) and migrate the appliance-local database."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn, APPLIANCE_MIGRATIONS, application_version=application_version)
    return conn
