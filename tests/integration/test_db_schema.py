"""Integration tests for the SQLite schemas and migration framework (Impl §6, DB-002)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from aethereal.db.appliance import open_appliance_db
from aethereal.db.destination import open_destination_manifest
from aethereal.db.migrations import Migration, apply_migrations, current_schema_version


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def test_destination_manifest_has_all_tables(tmp_path: Path) -> None:
    conn = open_destination_manifest(tmp_path / "manifest.sqlite3")
    try:
        tables = _table_names(conn)
        expected = {
            "schema_meta",
            "source_volume",
            "source_snapshot",
            "backup_job",
            "preflight",
            "source_file",
            "content_identity",
            "content_object",
            "session_entry",
            "copy_operation",
            "verification_result",
            "event_log",
        }
        assert expected <= tables
        assert current_schema_version(conn) == 1
    finally:
        conn.close()


def test_destination_uses_wal_and_synchronous_full(tmp_path: Path) -> None:
    conn = open_destination_manifest(tmp_path / "manifest.sqlite3")
    try:
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
        assert journal.lower() == "wal"
        assert synchronous == 2  # 2 == FULL
    finally:
        conn.close()


def test_content_identity_unique_index_enforced(tmp_path: Path) -> None:
    conn = open_destination_manifest(tmp_path / "manifest.sqlite3")
    try:
        conn.execute("INSERT INTO content_identity (size_bytes, sha256) VALUES (?, ?)", (10, "abc"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO content_identity (size_bytes, sha256) VALUES (?, ?)",
                (10, "abc"),
            )
        # Same hash, different size is a distinct identity and must be allowed.
        conn.execute("INSERT INTO content_identity (size_bytes, sha256) VALUES (?, ?)", (11, "abc"))
    finally:
        conn.close()


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "manifest.sqlite3"
    conn = open_destination_manifest(path)
    conn.close()
    # Reopening applies no new migrations and keeps the version stable.
    conn = open_destination_manifest(path)
    try:
        assert current_schema_version(conn) == 1
        rows = conn.execute("SELECT COUNT(*) FROM schema_meta").fetchone()[0]
        assert rows == 1  # exactly one migration recorded, not re-applied
    finally:
        conn.close()


def test_appliance_db_has_tables(tmp_path: Path) -> None:
    conn = open_appliance_db(tmp_path / "appliance.db")
    try:
        assert {"schema_meta", "appliance", "source_alias", "system_event"} <= _table_names(conn)
        assert current_schema_version(conn) == 1
    finally:
        conn.close()


def test_duplicate_migration_versions_rejected(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    dupes = (
        Migration(version=1, name="a", statements=("CREATE TABLE a (x)",)),
        Migration(version=1, name="b", statements=("CREATE TABLE b (x)",)),
    )
    with pytest.raises(ValueError):
        apply_migrations(conn, dupes, application_version="test")


def test_failed_migration_rolls_back(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    bad = (
        Migration(
            version=1,
            name="bad",
            statements=("CREATE TABLE ok (x)", "THIS IS NOT SQL"),
        ),
    )
    with pytest.raises(sqlite3.OperationalError):
        apply_migrations(conn, bad, application_version="test")
    # The whole migration rolled back: no version recorded and table not present.
    assert current_schema_version(conn) == 0
    tables = _table_names(conn)
    assert "ok" not in tables
