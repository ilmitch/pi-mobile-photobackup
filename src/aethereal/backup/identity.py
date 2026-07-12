"""Content identity: size + SHA-256.

Implements PRD v0.3 FILE-002 (definitive content identity) and the strict streaming
hash of Implementation Plan v0.3 section 12. Identity is content-only: filename, path,
timestamp, and camera metadata are deliberately excluded, so identical bytes under
different names compare equal.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

# Impl §12: initial streaming chunk size (configurable, performance-tested).
DEFAULT_CHUNK_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ContentIdentity:
    """The definitive identity of a file's content: its size and SHA-256 digest.

    Two files share a ``ContentIdentity`` if and only if their bytes are identical.
    """

    size_bytes: int
    sha256: str


def hash_stream(reader: BinaryIO, *, chunk_bytes: int = DEFAULT_CHUNK_BYTES) -> ContentIdentity:
    """Stream ``reader`` in chunks, returning its size and SHA-256 in one pass."""
    if chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be positive")
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = reader.read(chunk_bytes)
        if not chunk:
            break
        size += len(chunk)
        digest.update(chunk)
    return ContentIdentity(size_bytes=size, sha256=digest.hexdigest())


def content_identity_of_path(
    path: Path, *, chunk_bytes: int = DEFAULT_CHUNK_BYTES
) -> ContentIdentity:
    """Compute the content identity of a file on disk by streaming it read-only."""
    with path.open("rb") as reader:
        return hash_stream(reader, chunk_bytes=chunk_bytes)


def content_identity_of_bytes(data: bytes) -> ContentIdentity:
    """Compute the content identity of an in-memory byte string (test/utility helper)."""
    return ContentIdentity(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
