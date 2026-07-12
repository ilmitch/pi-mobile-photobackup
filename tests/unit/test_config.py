"""Unit tests for appliance configuration loading and validation (Impl §5)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from aethereal.common.config import AetherealConfig, load_config

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "default.yaml"


def _default_dict() -> dict[str, Any]:
    with DEFAULT_CONFIG.open("r", encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle)
    return data


def test_default_config_loads() -> None:
    config = load_config(DEFAULT_CONFIG)
    assert isinstance(config, AetherealConfig)
    assert config.device.hostname == "backup.local"
    assert config.destination.required_filesystem == "ext4"
    assert config.destination.safety_margin_min_bytes == 10_000_000_000
    assert config.source.supported_filesystems == ["vfat", "exfat"]
    assert config.backup.io_chunk_bytes == 8 * 1024 * 1024
    assert config.database.destination_synchronous == "FULL"


def test_default_config_is_complete_and_forbids_extra_keys() -> None:
    data = _default_dict()
    data["unexpected_section"] = {"x": 1}
    with pytest.raises(ValidationError):
        AetherealConfig.model_validate(data)


def test_non_ext4_destination_rejected() -> None:
    data = _default_dict()
    data["destination"]["required_filesystem"] = "exfat"
    with pytest.raises(ValidationError):
        AetherealConfig.model_validate(data)


def test_unsupported_source_filesystem_rejected() -> None:
    data = _default_dict()
    data["source"]["supported_filesystems"] = ["ntfs"]
    with pytest.raises(ValidationError):
        AetherealConfig.model_validate(data)


def test_safety_margin_percent_out_of_range_rejected() -> None:
    data = _default_dict()
    data["destination"]["safety_margin_percent"] = 150
    with pytest.raises(ValidationError):
        AetherealConfig.model_validate(data)


def test_non_full_destination_sync_rejected() -> None:
    data = _default_dict()
    data["database"]["destination_synchronous"] = "NORMAL"
    with pytest.raises(ValidationError):
        AetherealConfig.model_validate(data)


def test_zero_io_worker_count_rejected() -> None:
    data = _default_dict()
    data["backup"]["io_worker_count"] = 0
    with pytest.raises(ValidationError):
        AetherealConfig.model_validate(data)


def test_missing_section_rejected() -> None:
    data = _default_dict()
    del data["thermal"]
    with pytest.raises(ValidationError):
        AetherealConfig.model_validate(data)


def test_non_mapping_root_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(bad)


def test_config_defaults_feed_capacity_math() -> None:
    # The config's safety-margin settings are exactly what the capacity module expects.
    from aethereal.backup.capacity import (
        DEFAULT_SAFETY_MARGIN_MIN_BYTES,
        DEFAULT_SAFETY_MARGIN_PERCENT,
    )

    config = load_config(DEFAULT_CONFIG)
    assert config.destination.safety_margin_percent == DEFAULT_SAFETY_MARGIN_PERCENT
    assert config.destination.safety_margin_min_bytes == DEFAULT_SAFETY_MARGIN_MIN_BYTES


def test_frozen_default_dict_helper_isolation() -> None:
    # Guard: mutating one loaded dict must not leak into another (test hygiene).
    a = _default_dict()
    b = _default_dict()
    a["device"]["hostname"] = "mutated"
    assert b["device"]["hostname"] == "backup.local"
    assert copy.deepcopy(a) is not a
