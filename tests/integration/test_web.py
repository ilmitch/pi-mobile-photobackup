"""Integration tests for the FastAPI web layer (WEB-001..008, §20 API)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aethereal.backup.engine import BackupEngine
from aethereal.common.events import EventBus, EventSeverity, EventType
from aethereal.common.platform import DiskUsage, FakePlatformOps, PlatformOps
from aethereal.db.destination import open_destination_manifest
from aethereal.common.source import SourceRef
from aethereal.db.manifest_repo import ManifestRepository
from aethereal.web.app import create_app

BIG = FakePlatformOps(total_bytes=1_000_000_000_000, free_bytes=1_000_000_000_000)
FIXED_CLOCK = lambda: datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)  # noqa: E731


class RecordingPlatform:
    """A platform double that records power actions (or refuses them)."""

    def __init__(self, *, supports_power: bool = True) -> None:
        self.supports_power = supports_power
        self.calls: list[str] = []

    def disk_usage(self, path: Path | str) -> DiskUsage:  # noqa: ARG002
        return DiskUsage(total_bytes=1_000_000_000_000, free_bytes=1_000_000_000_000)

    def evict_cache(self, fd: int, offset: int, length: int) -> None:  # noqa: ARG002
        return None

    def power_off(self) -> None:
        if not self.supports_power:
            raise NotImplementedError("power control is not available on darwin")
        self.calls.append("power_off")

    def reboot(self) -> None:
        if not self.supports_power:
            raise NotImplementedError("power control is not available on darwin")
        self.calls.append("reboot")


def _build(
    tmp_path: Path,
    *,
    source: SourceRef | None,
    bus: EventBus | None = None,
    token: str | None = None,
    platform: PlatformOps | None = None,
) -> FastAPI:
    conn = open_destination_manifest(
        tmp_path / "Backups" / "manifest.sqlite3", check_same_thread=False
    )
    repo = ManifestRepository(conn)
    engine = BackupEngine(
        repo=repo,
        object_store_root=tmp_path / "Backups" / ".aethereal" / "objects",
        backup_root=tmp_path / "Backups",
        platform=platform or BIG,
        event_bus=bus,
        clock=FIXED_CLOCK,
    )
    app = create_app(
        engine=engine,
        repo=repo,
        source_provider=lambda: source,
        event_bus=bus,
        api_token=token,
    )
    return app


def _source(tmp_path: Path, files: dict[str, bytes]) -> SourceRef:
    root = tmp_path / "card"
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return SourceRef(root=root, logical_name="CANON_CARD_01")


def _wait_idle(client: TestClient, timeout: float = 5.0) -> dict[str, object]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status: dict[str, object] = client.get("/api/v1/status").json()
        if not status["backup_running"]:
            return status
        time.sleep(0.02)
    raise AssertionError("backup did not finish in time")


def test_index_page_served(tmp_path: Path) -> None:
    app = _build(tmp_path, source=_source(tmp_path, {"a.cr3": b"a"}))
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Aethereal Backup" in resp.text


def test_status_and_system(tmp_path: Path) -> None:
    app = _build(tmp_path, source=_source(tmp_path, {"a.cr3": b"a"}))
    with TestClient(app) as client:
        status = client.get("/api/v1/status").json()
        assert status["state"] == "IDLE"
        assert status["backup_running"] is False
        assert status["source"]["logical_name"] == "CANON_CARD_01"

        system = client.get("/api/v1/system").json()
        assert "uptime_seconds" in system
        assert system["engine_state"] == "IDLE"


def test_system_endpoint_survives_blocked_telemetry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reproduce a restricted host (e.g. sandbox) where psutil calls are denied.
    def denied(*_args: object, **_kwargs: object) -> float:
        raise PermissionError("telemetry not permitted")

    monkeypatch.setattr("aethereal.web.app.psutil.boot_time", denied)
    monkeypatch.setattr("aethereal.web.app.psutil.cpu_percent", denied)
    monkeypatch.setattr("aethereal.web.app.psutil.virtual_memory", denied)

    app = _build(tmp_path, source=_source(tmp_path, {"a.cr3": b"a"}))
    with TestClient(app) as client:
        resp = client.get("/api/v1/system")
        assert resp.status_code == 200  # never 500 on blocked telemetry
        body = resp.json()
        assert body["uptime_seconds"] is None
        assert body["cpu_percent"] is None
        assert body["engine_state"] == "IDLE"


def test_source_endpoint(tmp_path: Path) -> None:
    app = _build(tmp_path, source=_source(tmp_path, {"a.cr3": b"a"}))
    with TestClient(app) as client:
        s = client.get("/api/v1/source").json()
        assert s["present"] is True
        assert s["logical_name"] == "CANON_CARD_01"
        assert s["total_bytes"] == BIG.total_bytes
        assert s["used_bytes"] == BIG.total_bytes - BIG.free_bytes


def test_source_endpoint_no_card(tmp_path: Path) -> None:
    app = _build(tmp_path, source=None)
    with TestClient(app) as client:
        assert client.get("/api/v1/source").json() == {"present": False}


def test_source_backed_up_bytes_tracks_scans(tmp_path: Path) -> None:
    app = _build(tmp_path, source=_source(tmp_path, {"a.cr3": b"a"}))
    with TestClient(app) as client:
        # Unscanned: no breakdown yet.
        assert client.get("/api/v1/source").json()["backed_up_bytes"] is None
        # Dry run of a fresh card: scanned but nothing backed up yet -> 0.
        client.post("/api/v1/dry-run")
        assert client.get("/api/v1/source").json()["backed_up_bytes"] == 0
        # After a backup: all scanned content is now backed up (1 byte).
        client.post("/api/v1/backups")
        _wait_idle(client)
        assert client.get("/api/v1/source").json()["backed_up_bytes"] == 1


def test_destination_endpoint(tmp_path: Path) -> None:
    app = _build(tmp_path, source=_source(tmp_path, {"a.cr3": b"a"}))
    with TestClient(app) as client:
        # Before any backup: destination present, nothing stored yet.
        d = client.get("/api/v1/destination").json()
        assert d["present"] is True
        assert d["verified_object_count"] == 0
        assert d["total_bytes"] == BIG.total_bytes

        client.post("/api/v1/backups")
        _wait_idle(client)

        d2 = client.get("/api/v1/destination").json()
        assert d2["verified_object_count"] == 1
        assert d2["backed_up_bytes"] == 1


def test_dry_run(tmp_path: Path) -> None:
    app = _build(tmp_path, source=_source(tmp_path, {"a.cr3": b"aaaa", "b.cr3": b"bbbbbb"}))
    with TestClient(app) as client:
        body = client.post("/api/v1/dry-run").json()
        assert body["outcome"] == "READY"
        assert body["new_file_count"] == 2
        assert body["new_bytes"] == 10
        # A dry run must not create a job.
        assert client.get("/api/v1/backups").json()["jobs"] == []


def test_start_backup_runs_and_appears_in_history(tmp_path: Path) -> None:
    app = _build(tmp_path, source=_source(tmp_path, {"DCIM/IMG.CR3": b"photo"}))
    with TestClient(app) as client:
        resp = client.post("/api/v1/backups")
        assert resp.status_code == 202
        assert resp.json()["accepted"] is True

        _wait_idle(client)

        jobs = client.get("/api/v1/backups").json()["jobs"]
        assert len(jobs) == 1
        assert jobs[0]["state"] == "BACKUP_COMPLETED"
        assert jobs[0]["files_copied"] == 1

        detail = client.get(f"/api/v1/backups/{jobs[0]['id']}").json()
        assert detail["id"] == jobs[0]["id"]


def test_backup_detail_404(tmp_path: Path) -> None:
    app = _build(tmp_path, source=_source(tmp_path, {"a.cr3": b"a"}))
    with TestClient(app) as client:
        assert client.get("/api/v1/backups/nope").status_code == 404


def test_shutdown_and_reboot_invoke_platform(tmp_path: Path) -> None:
    platform = RecordingPlatform(supports_power=True)
    app = _build(tmp_path, source=_source(tmp_path, {"a.cr3": b"a"}), platform=platform)
    with TestClient(app) as client:
        assert client.post("/api/v1/system/shutdown").status_code == 202
        assert client.post("/api/v1/system/reboot").status_code == 202
    assert platform.calls == ["power_off", "reboot"]


def test_shutdown_refused_returns_501(tmp_path: Path) -> None:
    platform = RecordingPlatform(supports_power=False)  # like macOS
    app = _build(tmp_path, source=_source(tmp_path, {"a.cr3": b"a"}), platform=platform)
    with TestClient(app) as client:
        assert client.post("/api/v1/system/shutdown").status_code == 501
        assert client.post("/api/v1/system/reboot").status_code == 501


def test_system_actions_require_auth_when_token_set(tmp_path: Path) -> None:
    app = _build(tmp_path, source=_source(tmp_path, {"a.cr3": b"a"}), token="secret")
    with TestClient(app) as client:
        assert client.post("/api/v1/system/shutdown").status_code == 401


def test_cancel_with_no_active_backup_409(tmp_path: Path) -> None:
    app = _build(tmp_path, source=_source(tmp_path, {"a.cr3": b"a"}))
    with TestClient(app) as client:
        assert client.post("/api/v1/backups/anything/cancel").status_code == 409


def test_no_source_blocks_actions(tmp_path: Path) -> None:
    app = _build(tmp_path, source=None)
    with TestClient(app) as client:
        assert client.post("/api/v1/dry-run").status_code == 409
        assert client.post("/api/v1/backups").status_code == 409


def test_auth_required_when_token_set(tmp_path: Path) -> None:
    app = _build(tmp_path, source=_source(tmp_path, {"a.cr3": b"a"}), token="secret")
    with TestClient(app) as client:
        assert client.post("/api/v1/backups").status_code == 401
        ok = client.post("/api/v1/backups", headers={"Authorization": "Bearer secret"})
        assert ok.status_code == 202
        _wait_idle(client)


def test_websocket_replays_backlog(tmp_path: Path) -> None:
    bus = EventBus()
    app = _build(tmp_path, source=_source(tmp_path, {"a.cr3": b"a"}), bus=bus)
    bus.publish(EventType.SOURCE_DETECTED, EventSeverity.INFO, "media", "card in")
    bus.publish(EventType.PREFLIGHT_STARTED, EventSeverity.INFO, "preflight", "scanning")
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/events?since=0") as ws:
            first = ws.receive_json()
            second = ws.receive_json()
            assert first["type"] == "SOURCE_DETECTED"
            assert second["type"] == "PREFLIGHT_STARTED"
            assert second["sequence"] == 2
