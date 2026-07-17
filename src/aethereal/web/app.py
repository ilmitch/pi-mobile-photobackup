"""Local web application over the backup engine.

Implements the API surface of Implementation Plan v0.3 section 20 and PRD WEB-001..008:
a REST API for status/history/control plus a reconnecting WebSocket event stream
(WEB-003). The engine is the authoritative owner of backup state; this layer only reads
snapshots and requests actions. A backup runs on a single-slot worker so the event loop
stays responsive and a client disconnect never stops the backup (§7, NET-003).

Auth (SEC-002) is a minimal shared-token guard here; full single-user session auth is a
separate step.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import psutil
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from aethereal.backup.engine import BackupEngine
from aethereal.backup.state_machine import BackupState
from aethereal.common.events import Event, EventBus
from aethereal.common.source import SourceRef
from aethereal.db.manifest_repo import ManifestRepository
from aethereal.led.controller import led_state_for
from aethereal.linux.media import MediaManager
from aethereal.watch.service import WatchService

SourceProvider = Callable[[], "SourceRef | None"]


class MediaSelectRequest(BaseModel):
    """Body for choosing the active source when several cards are present (SRC-008)."""

    uuid: str


class TimeSyncRequest(BaseModel):
    """Body for phone time sync (TIME-003): the browser's current wall-clock time."""

    browser_time: datetime | None = None


class NoSourceError(Exception):
    """Raised when an action needs a source but none is present."""


class BackupService:
    """Runs at most one backup at a time on a background worker (single active source)."""

    def __init__(self, engine: BackupEngine, source_provider: SourceProvider) -> None:
        self._engine = engine
        self._source = source_provider
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="backup")
        self._future: Future[object] | None = None
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        return self._future is not None and not self._future.done()

    def start(self) -> bool:
        """Start a backup of the current source. Returns False if one is already running."""
        with self._lock:
            if self.is_running():
                return False
            source = self._source()
            if source is None:
                raise NoSourceError
            if self._engine.state is not BackupState.IDLE:
                self._engine.reset()
            self._future = self._executor.submit(
                self._engine.run_backup, source.root, source.logical_name
            )
            return True

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def _metric(read: Callable[[], float]) -> float | None:
    """Read a host telemetry value, or None if the host does not permit it (WEB-008).

    Host metrics are best-effort: on restricted hosts (sandboxes, some containers)
    ``psutil`` can raise, and a missing metric must never fail the status endpoint.
    """
    try:
        return read()
    except Exception:
        return None


def _event_json(event: Event) -> dict[str, object]:
    return {
        "sequence": event.sequence,
        "timestamp": event.timestamp.isoformat(),
        "type": event.type.value,
        "severity": event.severity.value,
        "component": event.component,
        "message": event.message,
        "backup_job_id": event.backup_job_id,
        "details": dict(event.details),
    }


def create_app(
    *,
    engine: BackupEngine,
    repo: ManifestRepository,
    source_provider: SourceProvider,
    event_bus: EventBus | None = None,
    api_token: str | None = None,
    media_manager: MediaManager | None = None,
    watch: WatchService | None = None,
) -> FastAPI:
    service = BackupService(engine, source_provider)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        service.shutdown()

    app = FastAPI(title="Aethereal Mobile Backup", version="1", lifespan=lifespan)
    index_html = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return index_html

    async def require_auth(authorization: str = Header(default="")) -> None:
        if api_token is not None and authorization != f"Bearer {api_token}":
            raise HTTPException(status_code=401, detail="authentication required")

    def _source_payload() -> dict[str, object] | None:
        source = source_provider()
        if source is None:
            return None
        return {"root": str(source.root), "logical_name": source.logical_name}

    @app.get("/api/v1/status")
    async def status() -> dict[str, object]:
        return {
            "state": engine.state.value,
            "led_state": led_state_for(engine.state).value,
            "backup_running": service.is_running(),
            "last_event_sequence": event_bus.last_sequence if event_bus else 0,
            "source": _source_payload(),
        }

    @app.get("/api/v1/source")
    async def source() -> dict[str, object]:
        src = source_provider()
        if src is None:
            return {"present": False}
        present = Path(src.root).exists()
        if present:
            usage = engine.filesystem_usage(src.root)
            total, free = usage.total_bytes, usage.free_bytes
        else:
            total = free = 0
        return {
            "present": True,
            "logical_name": src.logical_name,
            "root": str(src.root),
            "total_bytes": total,
            "free_bytes": free,
            "used_bytes": total - free,
            # Backed-up bytes as of the last scan (None until a dry run / backup).
            "backed_up_bytes": engine.last_source_scan(src.root),
        }

    @app.get("/api/v1/media")
    async def media() -> dict[str, object]:
        if media_manager is None:
            return {"managed": False, "state": "UNMANAGED", "candidates": []}
        return {
            "managed": True,
            "state": media_manager.state().value,
            "candidates": [
                {
                    "uuid": c.uuid,
                    "name": c.name,
                    "label": c.label,
                    "fstype": c.fstype,
                    "size_bytes": c.size_bytes,
                }
                for c in media_manager.source_candidates()
            ],
        }

    @app.post("/api/v1/media/select", status_code=202)
    async def media_select(
        body: MediaSelectRequest, _auth: None = Depends(require_auth)
    ) -> dict[str, object]:
        if media_manager is None:
            raise HTTPException(status_code=409, detail="media selection not available")
        media_manager.select(body.uuid)
        return {"selected": body.uuid}

    @app.get("/api/v1/destination")
    async def destination() -> dict[str, object]:
        status = engine.destination_status()
        used = status.total_bytes - status.free_bytes
        return {
            "backup_root": status.backup_root,
            "present": status.present,
            "total_bytes": status.total_bytes,
            "free_bytes": status.free_bytes,
            "used_bytes": used,
            "verified_object_count": status.verified_object_count,
            "backed_up_bytes": status.backed_up_bytes,
        }

    @app.get("/api/v1/system")
    async def system() -> dict[str, object]:
        boot = _metric(psutil.boot_time)
        status: dict[str, object] = {
            "uptime_seconds": (time.time() - boot) if boot is not None else None,
            "cpu_percent": _metric(lambda: psutil.cpu_percent(interval=None)),
            "memory_percent": _metric(lambda: psutil.virtual_memory().percent),
            "engine_state": engine.state.value,
            "backup_running": service.is_running(),
        }
        if watch is not None:
            health = watch.snapshot()
            status.update(
                {
                    "cpu_temperature_celsius": health.telemetry.cpu_temperature_celsius,
                    "undervoltage": health.telemetry.undervoltage,
                    "storage_free_bytes": health.telemetry.storage_free_bytes,
                    "storage_total_bytes": health.telemetry.storage_total_bytes,
                    "clock_state": health.clock_state.value,
                    "warnings": [
                        {"kind": w.kind.value, "message": w.message} for w in health.warnings
                    ],
                }
            )
        return status

    @app.get("/api/v1/backups")
    async def backups() -> dict[str, object]:
        return {"jobs": repo.list_backup_jobs()}

    @app.get("/api/v1/backups/{job_id}")
    async def backup_detail(job_id: str) -> dict[str, object]:
        job = repo.get_backup_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.post("/api/v1/dry-run")
    async def dry_run(_auth: None = Depends(require_auth)) -> dict[str, object]:
        if service.is_running():
            raise HTTPException(status_code=409, detail="a backup is running")
        source = source_provider()
        if source is None:
            raise HTTPException(status_code=409, detail="no source media present")
        result = await asyncio.to_thread(engine.dry_run, source.root, source.logical_name)
        return {
            "outcome": result.outcome.value,
            "files_discovered": result.files_discovered,
            "new_file_count": result.new_file_count,
            "already_backed_up_count": result.already_backed_up_count,
            "conflict_count": result.conflict_count,
            "unreadable_count": result.unreadable_count,
            "new_bytes": result.new_bytes,
            "required_bytes": result.capacity.required_bytes,
            "available_bytes": result.capacity.available_bytes,
            "shortfall_bytes": result.capacity.shortfall_bytes,
            "source_snapshot": result.snapshot.snapshot_sha256,
            "block_reasons": list(result.block_reasons),
            # FILE-008: what the media whitelist left behind, so nothing drops silently.
            "skipped_non_media_count": result.skipped_non_media_count,
            "skipped_extensions": list(result.skipped_extensions),
            "skipped_hidden_count": result.skipped_hidden_count,
        }

    @app.post("/api/v1/backups", status_code=202)
    async def start_backup(_auth: None = Depends(require_auth)) -> dict[str, object]:
        try:
            started = service.start()
        except NoSourceError:
            raise HTTPException(status_code=409, detail="no source media present") from None
        if not started:
            raise HTTPException(status_code=409, detail="a backup is already running")
        return {"accepted": True, "state": engine.state.value}

    @app.post("/api/v1/backups/{job_id}/cancel", status_code=202)
    async def cancel_backup(job_id: str, _auth: None = Depends(require_auth)) -> dict[str, object]:
        if not engine.request_cancellation():
            raise HTTPException(status_code=409, detail="no active backup to cancel")
        return {"requested": True, "job_id": job_id}

    @app.post("/api/v1/time/sync", status_code=202)
    async def time_sync(
        body: TimeSyncRequest | None = None, _auth: None = Depends(require_auth)
    ) -> dict[str, object]:
        # TIME-003: the phone establishes trusted time; with a browser timestamp the OS
        # clock is set from it (so dated sessions are correct without an RTC).
        if watch is None:
            raise HTTPException(status_code=409, detail="clock management not available")
        browser_time = body.browser_time if body is not None else None
        state = watch.sync_from_phone(browser_time)
        return {"clock_state": state.value}

    @app.post("/api/v1/system/shutdown", status_code=202)
    async def shutdown(_auth: None = Depends(require_auth)) -> dict[str, object]:
        try:
            engine.power_off()
        except NotImplementedError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from None
        return {"shutting_down": True}

    @app.post("/api/v1/system/reboot", status_code=202)
    async def reboot(_auth: None = Depends(require_auth)) -> dict[str, object]:
        try:
            engine.reboot()
        except NotImplementedError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from None
        return {"rebooting": True}

    @app.websocket("/api/v1/events")
    async def events_ws(websocket: WebSocket, since: int = 0) -> None:
        await websocket.accept()
        if event_bus is None:
            await websocket.close()
            return

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Event] = asyncio.Queue()

        def on_event(event: Event) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        unsubscribe = event_bus.subscribe(on_event)
        try:
            # Replay any gap since the client's last-seen sequence (WEB-003 reconnect).
            backlog = event_bus.events_since(since)
            highest = since
            for event in backlog:
                await websocket.send_json(_event_json(event))
                highest = max(highest, event.sequence)
            while True:
                event = await queue.get()
                if event.sequence <= highest:
                    continue  # already delivered via backlog
                await websocket.send_json(_event_json(event))
        except WebSocketDisconnect:
            pass
        finally:
            unsubscribe()

    app.state.service = service
    return app
