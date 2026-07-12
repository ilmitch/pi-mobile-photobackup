"""End-to-end test of the appliance composition root (config -> stack -> real backup).

Runs the entire appliance off the Pi with injected fakes for the platform, device
enumeration, and mounting, but real hashing / copy / verify / SQLite manifest on the host
filesystem. Proves the whole wiring: insert a card, back it up, see it in history.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi.testclient import TestClient

from aethereal.appliance import build_appliance
from aethereal.common.config import AetherealConfig
from aethereal.linux.devices import BlockDevice
from aethereal.linux.mount import SourceMount
from aethereal.common.platform import FakePlatformOps

REPO_ROOT = Path(__file__).resolve().parents[2]
DEST_UUID = "dest-ssd-uuid"


def _config(tmp_path: Path) -> AetherealConfig:
    with (REPO_ROOT / "config" / "default.yaml").open(encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle)
    backups = tmp_path / "Backups"
    data["destination"]["filesystem_uuid"] = DEST_UUID
    data["destination"]["backup_root"] = str(backups)
    data["destination"]["object_store_root"] = str(backups / ".aethereal" / "objects")
    data["destination"]["manifest_path"] = str(backups / "manifest.sqlite3")
    data["database"]["appliance_path"] = str(tmp_path / "appliance.db")
    data["source"]["mount_root"] = str(tmp_path / "mnt")
    return AetherealConfig.model_validate(data)


class _FakeMount:
    """Mounts a device by pointing at a prepared source directory."""

    def __init__(self, source_dir: Path) -> None:
        self._source_dir = source_dir

    def mount_source_read_only(
        self, device: str, mount_point: Path, *, fstype: str | None
    ) -> SourceMount:
        return SourceMount(device, str(self._source_dir), block_read_only=True, mount_read_only=True)

    def unmount(self, mount_point: Path) -> None:
        return None


def _card() -> BlockDevice:
    return BlockDevice(
        name="sda1", path="/dev/sda1", fstype="exfat", uuid="card-uuid", label="CANON_R6",
        size_bytes=64_000_000_000, read_only=False, mountpoint=None, dev_type="part",
        model=None, serial=None, partuuid=None,
    )


_DEST = BlockDevice(
    name="sdb1", path="/dev/sdb1", fstype="ext4", uuid=DEST_UUID, label="AETHEREAL",
    size_bytes=2_000_000_000_000, read_only=False, mountpoint="/Backups", dev_type="part",
    model=None, serial=None, partuuid=None,
)


def test_appliance_backs_up_an_inserted_card(tmp_path: Path) -> None:
    # A prepared "card" directory that the fake mount exposes read-only.
    card_dir = tmp_path / "card"
    (card_dir / "DCIM" / "100CANON").mkdir(parents=True)
    (card_dir / "DCIM" / "100CANON" / "IMG_1.CR3").write_bytes(b"raw one")
    (card_dir / "DCIM" / "100CANON" / "IMG_2.CR3").write_bytes(b"raw two")

    devices: list[BlockDevice] = [_DEST]
    app = build_appliance(
        _config(tmp_path),
        platform=FakePlatformOps(total_bytes=2_000_000_000_000, free_bytes=2_000_000_000_000),
        device_lister=lambda: list(devices),
        mount_service=_FakeMount(card_dir),
    )

    with TestClient(app) as client:
        # No card yet.
        assert client.get("/api/v1/status").json()["source"] is None
        assert client.get("/api/v1/media").json()["state"] == "NO_SOURCE"

        # Insert the card.
        devices.append(_card())
        source = client.get("/api/v1/source").json()
        assert source["present"] is True
        assert source["logical_name"] == "CANON_R6"

        # Dry run then back up through the appliance.
        dry = client.post("/api/v1/dry-run").json()
        assert dry["outcome"] == "READY"
        assert dry["new_file_count"] == 2

        # TIME-001: the appliance clock starts untrusted; establish trust (phone sync)
        # before a dated backup session can be created.
        assert client.get("/api/v1/system").json()["clock_state"] == "CLOCK_UNTRUSTED"
        assert client.post("/api/v1/time/sync").status_code == 202

        assert client.post("/api/v1/backups").status_code == 202
        deadline_jobs = None
        import time

        for _ in range(200):
            jobs = client.get("/api/v1/backups").json()["jobs"]
            if jobs and jobs[0]["state"] == "BACKUP_COMPLETED":
                deadline_jobs = jobs
                break
            time.sleep(0.02)
        assert deadline_jobs is not None, "backup did not complete"
        assert deadline_jobs[0]["files_copied"] == 2

        # The destination now reports the backed-up content.
        dest = client.get("/api/v1/destination").json()
        assert dest["verified_object_count"] == 2
