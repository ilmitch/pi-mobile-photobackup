"""Canonical content-object path helpers.

Implements the content-addressed store layout of PRD v0.3 DST-005: objects live under
``<root>/<aa>/<bb>/<sha256>`` where ``aa``/``bb`` are the first two byte-pairs of the
digest. In-flight copies use the configured partial suffix (COPY-001).
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_PARTIAL_SUFFIX = ".aethereal-partial"


def object_relative_path(sha256: str) -> str:
    """Return the sharded relative path ``aa/bb/<sha256>`` for a digest."""
    if len(sha256) < 4:
        raise ValueError("sha256 digest too short")
    return f"{sha256[:2]}/{sha256[2:4]}/{sha256}"


def object_path(object_store_root: Path | str, sha256: str) -> Path:
    """Return the absolute canonical object path for ``sha256``."""
    return Path(object_store_root) / object_relative_path(sha256)


def partial_path(
    object_store_root: Path | str, sha256: str, *, suffix: str = DEFAULT_PARTIAL_SUFFIX
) -> Path:
    """Return the absolute temporary (partial) object path for ``sha256``."""
    return object_path(object_store_root, sha256).with_name(f"{sha256}{suffix}")
