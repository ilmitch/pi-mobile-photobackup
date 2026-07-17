"""Appliance composition root.

Assembles the full stack from an :class:`AetherealConfig`: the destination manifest, the
backup engine (with startup recovery), the media manager (source detection + read-only
mounting), and the web application. Platform, device enumeration, and mounting are
injectable so the whole appliance can be integration-tested off the Pi with fakes; the
defaults are the real Linux implementations.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

from aethereal.backup.engine import BackupEngine
from aethereal.common.config import AetherealConfig
from aethereal.common.events import EventBus
from aethereal.common.platform import LocalPlatformOps, PlatformOps
from aethereal.db.appliance import open_appliance_db
from aethereal.db.destination import open_destination_manifest
from aethereal.db.manifest_repo import ManifestRepository
from aethereal.linux.devices import BlockDevice
from aethereal.linux.media import MediaManager, MountService
from aethereal.watch.service import WatchService
from aethereal.web.app import create_app


def build_appliance(
    config: AetherealConfig,
    *,
    platform: PlatformOps | None = None,
    event_bus: EventBus | None = None,
    api_token: str | None = None,
    device_lister: Callable[[], list[BlockDevice]] | None = None,
    mount_service: MountService | None = None,
) -> FastAPI:
    """Build the appliance FastAPI app wired to a real (or injected) platform."""
    platform = platform or LocalPlatformOps()
    bus = event_bus or EventBus()

    conn = open_destination_manifest(config.destination.manifest_path, check_same_thread=False)
    repo = ManifestRepository(conn)
    appliance_conn = open_appliance_db(config.database.appliance_path)

    watch = WatchService(
        thermal_warning_celsius=config.thermal.warning_celsius,
        storage_critical_bytes=config.system_storage.critical_free_bytes,
        set_system_time=platform.set_system_time,
    )

    engine = BackupEngine(
        repo=repo,
        object_store_root=config.destination.object_store_root,
        backup_root=config.destination.backup_root,
        platform=platform,
        event_bus=bus,
        safety_margin_percent=config.destination.safety_margin_percent,
        safety_margin_min_bytes=config.destination.safety_margin_min_bytes,
        retries=config.backup.verification_retries,
        chunk_bytes=config.backup.io_chunk_bytes,
        media_extensions=tuple(config.backup.media_extensions),
        # TIME-001: block dated sessions until the clock is trusted (RTC/phone/network).
        is_clock_trusted=(lambda: watch.clock.is_trusted)
        if config.time.require_trusted_clock
        else None,
    )
    # Reconcile any job interrupted before this start (REC-001).
    engine.recover_on_startup()

    manager_kwargs: dict[str, object] = {}
    if device_lister is not None:
        manager_kwargs["device_lister"] = device_lister
    if mount_service is not None:
        manager_kwargs["mount_service"] = mount_service
    manager = MediaManager(
        destination_uuid=config.destination.filesystem_uuid,
        source_mount_root=config.source.mount_root,
        supported_filesystems=tuple(config.source.supported_filesystems),
        **manager_kwargs,  # type: ignore[arg-type]
    )

    app = create_app(
        engine=engine,
        repo=repo,
        source_provider=manager.current_source,
        event_bus=bus,
        api_token=api_token,
        media_manager=manager,
        watch=watch,
    )
    # Keep long-lived handles reachable (and available to tests).
    app.state.engine = engine
    app.state.repo = repo
    app.state.media_manager = manager
    app.state.watch = watch
    app.state.appliance_db = appliance_conn
    return app
