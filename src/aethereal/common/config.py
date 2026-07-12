"""Typed appliance configuration.

Implements the configuration model of Implementation Plan v0.3 section 5. Validation
encodes the v1 correctness profile as type constraints, so a config that violates it
(non-ext4 destination, an unsupported source filesystem, a non-FULL destination sync
mode, and so on) fails to load rather than silently degrading. Per Impl §5, invalid
critical configuration must prevent ``backupd`` from reaching READY.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")  # reject unknown keys (surface typos)


class DeviceConfig(_Base):
    hostname: str


class NetworkConfig(_Base):
    ssid: str
    static_ip: str
    interface: str


class DestinationConfig(_Base):
    filesystem_uuid: str
    # DST-004: the v1 correctness profile requires ext4.
    required_filesystem: Literal["ext4"]
    backup_root: str
    object_store_root: str
    manifest_path: str
    safety_margin_percent: int = Field(ge=0, le=100)
    safety_margin_min_bytes: int = Field(ge=0)


class SourceConfig(_Base):
    mount_root: str
    # FILE-001A: v1 supports only FAT32 (vfat) and exFAT sources.
    supported_filesystems: list[Literal["vfat", "exfat"]] = Field(min_length=1)
    block_device_read_only: bool
    read_only_mount: bool


class BackupConfig(_Base):
    partial_suffix: str
    # VER-002: SHA-256 is the v1 verification algorithm.
    hash_algorithm: Literal["sha256"]
    verification_retries: int = Field(ge=0)
    single_active_source: bool
    # FILE-004: v1 always hashes fresh; no mtime shortcut.
    strict_source_hashing: bool
    io_worker_count: int = Field(ge=1)
    io_chunk_bytes: int = Field(gt=0)
    destination_cache_evict: bool
    direct_io_verify: bool


class DatabaseConfig(_Base):
    appliance_path: str
    destination_wal: bool
    # DB-002: the destination manifest uses synchronous=FULL for the correctness profile.
    destination_synchronous: Literal["FULL"]


class LoggingConfig(_Base):
    path: str
    retention_days: int = Field(ge=0)


class ThermalConfig(_Base):
    warning_celsius: int = Field(gt=0)


class TimeConfig(_Base):
    require_trusted_clock: bool
    rtc_profile: str
    allow_phone_sync: bool
    max_clock_skew_seconds: int = Field(ge=0)


class SystemStorageConfig(_Base):
    critical_free_bytes: int = Field(ge=0)


class AetherealConfig(_Base):
    """The complete validated appliance configuration."""

    device: DeviceConfig
    network: NetworkConfig
    destination: DestinationConfig
    source: SourceConfig
    backup: BackupConfig
    database: DatabaseConfig
    logging: LoggingConfig
    thermal: ThermalConfig
    time: TimeConfig
    system_storage: SystemStorageConfig


def load_config(path: Path) -> AetherealConfig:
    """Load and validate configuration from a YAML file.

    Raises ``pydantic.ValidationError`` if the content violates the schema, or
    ``ValueError`` if the file is not a YAML mapping.
    """
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"config root must be a mapping, got {type(raw).__name__}")
    return AetherealConfig.model_validate(raw)
