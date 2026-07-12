"""Local development server for the web layer.

Serves the FastAPI app on 127.0.0.1:8011 so you can drive a backup from a browser on the
Mac (no Raspberry Pi required).

    # Demo mode: a throwaway temp card with a few fake files
    uv run python scripts/dev_server.py

    # Real data: point at an actual folder (or a mounted SD card) and an APFS destination
    uv run python scripts/dev_server.py \
        --source "/Volumes/CANON_R6" --dest ~/AetherealBackups --name CANON_CARD_01

Notes for real-data testing on macOS:
  * The app only ever READS the source; it never writes to it. Use an SD card lock switch
    for hardware write-protection, or copy files to a folder and point --source there.
  * The destination must be APFS (Mac disk or an APFS external SSD). Session snapshots use
    hardlinks, which exFAT/FAT do not support.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path

import uvicorn

from aethereal.backup.engine import BackupEngine
from aethereal.common.events import EventBus
from aethereal.common.platform import FakePlatformOps, LocalPlatformOps, PlatformOps
from aethereal.db.destination import open_destination_manifest
from aethereal.common.source import SourceRef
from aethereal.db.manifest_repo import ManifestRepository
from aethereal.web.app import create_app


def _make_engine(
    backup_root: Path,
    *,
    platform: PlatformOps,
    safety_margin_min_bytes: int | None = None,
    reserve_floor_bytes: int | None = None,
) -> tuple[BackupEngine, ManifestRepository, EventBus]:
    backup_root.mkdir(parents=True, exist_ok=True)
    conn = open_destination_manifest(
        backup_root / "manifest.sqlite3", check_same_thread=False
    )
    repo = ManifestRepository(conn)
    bus = EventBus()
    extra: dict[str, int] = {}
    if safety_margin_min_bytes is not None:
        extra["safety_margin_min_bytes"] = safety_margin_min_bytes
    if reserve_floor_bytes is not None:
        extra["reserve_floor_bytes"] = reserve_floor_bytes
    engine = BackupEngine(
        repo=repo,
        object_store_root=backup_root / ".aethereal" / "objects",
        backup_root=backup_root,
        platform=platform,
        event_bus=bus,
        **extra,
    )
    return engine, repo, bus


def build_real_app(source_root: Path, backup_root: Path, logical_name: str) -> object:
    engine, repo, bus = _make_engine(backup_root, platform=LocalPlatformOps())
    source = SourceRef(root=source_root, logical_name=logical_name)
    return create_app(
        engine=engine, repo=repo, source_provider=lambda: source, event_bus=bus
    )


def build_demo_app() -> tuple[object, Path]:
    """A realistic fake 256 MB card so the two-color source bar is meaningful.

    Six 15 MB files; four are pre-backed-up before serving, so a dry run reveals a
    green (already backed up) / amber (needs backup) split.
    """
    work = Path(tempfile.mkdtemp(prefix="aethereal-dev-"))
    card = work / "card"
    rel_files = [f"DCIM/100CANON/IMG_80{i:02d}.CR3" for i in range(6)]
    for rel in rel_files:
        p = card / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(os.urandom(15_000_000))

    # Fake 256 MB card whose "used" (90 MB) matches the six files' total.
    platform = FakePlatformOps(total_bytes=256_000_000, free_bytes=166_000_000)
    engine, repo, bus = _make_engine(
        work / "Backups",
        platform=platform,
        safety_margin_min_bytes=10_000_000,
        reserve_floor_bytes=8_000_000,
    )

    # Pre-back-up the first four files (a previous session) so they show as already saved.
    partial = work / "partial"
    for rel in rel_files[:4]:
        dst = partial / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(card / rel, dst)
    engine.run_backup(partial, "DEMO_CARD_01")
    engine.reset()

    source = SourceRef(root=card, logical_name="DEMO_CARD_01")
    app = create_app(
        engine=engine, repo=repo, source_provider=lambda: source, event_bus=bus
    )
    return app, work


def main() -> None:
    parser = argparse.ArgumentParser(description="Aethereal dev server")
    parser.add_argument("--source", type=Path, help="source folder or mounted card")
    parser.add_argument("--dest", type=Path, help="destination backup root (APFS)")
    parser.add_argument("--name", default="DEV_CARD_01", help="logical source name")
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()

    if args.source is not None:
        if args.dest is None:
            parser.error("--dest is required when --source is given")
        print(f"[dev_server] source: {args.source}")
        print(f"[dev_server] dest:   {args.dest}")
        app: object = build_real_app(args.source, args.dest, args.name)
    else:
        app, work = build_demo_app()
        print(f"[dev_server] demo mode, workdir: {work}")

    print(f"[dev_server] http://127.0.0.1:{args.port}  (docs at /docs)")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
