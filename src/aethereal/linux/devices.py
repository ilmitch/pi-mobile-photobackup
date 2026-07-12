"""Enumerate and identify block devices via ``lsblk``.

Implements source/destination identity collection (PRD SRC-005, DST-001) and Implementation
Plan v0.3 section 8. ``lsblk --json`` gives a stable, parseable inventory without needing a
udev daemon, so it works in the Linux dev container as well as on the Pi. The JSON parser is
pure and unit-testable on any host; only :func:`list_block_devices` runs the Linux command.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

# Columns requested from lsblk. SIZE is in bytes (``--bytes``); RO is a boolean.
_LSBLK_COLUMNS = "NAME,PATH,FSTYPE,UUID,LABEL,SIZE,RO,MOUNTPOINT,TYPE,MODEL,SERIAL,PARTUUID"


@dataclass(frozen=True, slots=True)
class BlockDevice:
    """A block device or partition and its identity (SRC-005)."""

    name: str
    path: str | None
    fstype: str | None
    uuid: str | None
    label: str | None
    size_bytes: int | None
    read_only: bool
    mountpoint: str | None
    dev_type: str | None  # "disk", "part", "loop", ...
    model: str | None
    serial: str | None
    partuuid: str | None
    children: tuple[BlockDevice, ...] = field(default_factory=tuple)

    def flatten(self) -> list[BlockDevice]:
        """This device followed by all descendant partitions, depth-first."""
        result = [self]
        for child in self.children:
            result.extend(child.flatten())
        return result


def _as_bool(value: object) -> bool:
    # lsblk emits RO as a JSON bool on modern util-linux, or "0"/"1" on older versions.
    if isinstance(value, bool):
        return value
    return str(value) in {"1", "true", "True"}


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _device_from_node(node: Mapping[str, object]) -> BlockDevice:
    children_nodes = node.get("children")
    children: tuple[BlockDevice, ...] = ()
    if isinstance(children_nodes, list):
        children = tuple(
            _device_from_node(c) for c in children_nodes if isinstance(c, Mapping)
        )

    def _str(key: str) -> str | None:
        value = node.get(key)
        return str(value) if value is not None else None

    return BlockDevice(
        name=str(node.get("name", "")),
        path=_str("path"),
        fstype=_str("fstype"),
        uuid=_str("uuid"),
        label=_str("label"),
        size_bytes=_as_int(node.get("size")),
        read_only=_as_bool(node.get("ro")),
        mountpoint=_str("mountpoint"),
        dev_type=_str("type"),
        model=_str("model"),
        serial=_str("serial"),
        partuuid=_str("partuuid"),
        children=children,
    )


def parse_lsblk_json(data: Mapping[str, object]) -> list[BlockDevice]:
    """Parse the object returned by ``lsblk --json`` into :class:`BlockDevice` trees."""
    devices = data.get("blockdevices")
    if not isinstance(devices, list):
        return []
    return [_device_from_node(node) for node in devices if isinstance(node, Mapping)]


def _blkid_probe(path: str) -> dict[str, str]:
    """Probe a device directly with ``blkid`` (works without a running udevd)."""
    try:
        output = subprocess.run(
            ["blkid", "-o", "export", path],
            check=True, capture_output=True, text=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}
    result: dict[str, str] = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def _enrich(device: BlockDevice) -> BlockDevice:
    """Fill in UUID/FSTYPE/LABEL from blkid when lsblk (via udev) did not provide them.

    lsblk sources these from the udev database, which is empty in containers and can lag on
    hotplug; blkid reads the on-disk superblock directly. Enrichment is best-effort.
    """
    uuid, fstype, label = device.uuid, device.fstype, device.label
    if device.path is not None and (uuid is None or fstype is None):
        probe = _blkid_probe(device.path)
        uuid = uuid or probe.get("UUID")
        fstype = fstype or probe.get("TYPE")
        label = label or probe.get("LABEL")
    children = tuple(_enrich(child) for child in device.children)
    return replace(device, uuid=uuid, fstype=fstype, label=label, children=children)


def list_block_devices() -> list[BlockDevice]:
    """Enumerate block devices on the host, enriching identity via blkid (Linux only)."""
    if sys.platform != "linux":
        raise NotImplementedError(f"block-device enumeration requires Linux, not {sys.platform}")
    output = subprocess.run(
        ["lsblk", "--json", "--bytes", "--output", _LSBLK_COLUMNS],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [_enrich(device) for device in parse_lsblk_json(json.loads(output))]


def flatten_devices(devices: list[BlockDevice]) -> list[BlockDevice]:
    """Flatten a list of device trees into every device and partition."""
    result: list[BlockDevice] = []
    for device in devices:
        result.extend(device.flatten())
    return result


def find_by_uuid(devices: list[BlockDevice], uuid: str) -> list[BlockDevice]:
    """Return all filesystems (across the trees) whose UUID matches ``uuid``."""
    return [d for d in flatten_devices(devices) if d.uuid is not None and d.uuid == uuid]
