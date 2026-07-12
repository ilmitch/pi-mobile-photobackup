"""Explicit, versioned SQLite migrations.

Implements the requirement (PRD DB-002, Impl §6) that all schema changes use explicit
migrations and that each database records its schema version, the application version
that last migrated it, and when. Migrations run inside explicit transactions so an
interrupted migration leaves the database at its previous version rather than partially
applied.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class Migration:
    """One ordered schema migration: a version, a name, and its SQL statements."""

    version: int
    name: str
    statements: tuple[str, ...]


_CREATE_SCHEMA_META = """
CREATE TABLE IF NOT EXISTS schema_meta (
    schema_version INTEGER NOT NULL,
    application_version TEXT NOT NULL,
    name TEXT NOT NULL,
    migrated_at TEXT NOT NULL
)
"""


def _ensure_meta(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_SCHEMA_META)


def current_schema_version(conn: sqlite3.Connection) -> int:
    """Return the highest applied schema version, or 0 if none."""
    _ensure_meta(conn)
    row = conn.execute("SELECT MAX(schema_version) FROM schema_meta").fetchone()
    version = row[0]
    return int(version) if version is not None else 0


def apply_migrations(
    conn: sqlite3.Connection,
    migrations: tuple[Migration, ...],
    *,
    application_version: str,
) -> int:
    """Apply every migration newer than the current version; return the final version.

    Migration versions must be unique. Each migration is applied atomically: on error
    the transaction is rolled back and the exception propagates, leaving the schema at
    the last good version.
    """
    ordered = sorted(migrations, key=lambda m: m.version)
    versions = [m.version for m in ordered]
    if len(set(versions)) != len(versions):
        raise ValueError("duplicate migration version detected")

    current = current_schema_version(conn)
    for migration in ordered:
        if migration.version <= current:
            continue
        conn.execute("BEGIN")
        try:
            for statement in migration.statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_meta "
                "(schema_version, application_version, name, migrated_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    migration.version,
                    application_version,
                    migration.name,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        current = migration.version
    return current
