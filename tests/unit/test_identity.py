"""Unit tests for content identity (Verification Plan v0.3 UT-004, FILE-002)."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from aethereal.backup.identity import (
    ContentIdentity,
    content_identity_of_bytes,
    content_identity_of_path,
    hash_stream,
)


def test_identity_matches_hashlib() -> None:
    data = b"IMG_8421 raw bytes" * 1000
    identity = content_identity_of_bytes(data)
    assert identity.size_bytes == len(data)
    assert identity.sha256 == hashlib.sha256(data).hexdigest()


def test_same_bytes_same_identity() -> None:
    data = b"identical content"
    assert content_identity_of_bytes(data) == content_identity_of_bytes(data)


def test_different_content_different_identity() -> None:
    # Same size, different content -> different identity (UT-004 / FILE-002).
    a = content_identity_of_bytes(b"AAAA")
    b = content_identity_of_bytes(b"BBBB")
    assert a.size_bytes == b.size_bytes
    assert a != b


def test_identity_is_content_only_not_filename(tmp_path: Path) -> None:
    # Different filenames, identical bytes -> same content identity.
    data = b"same photo bytes"
    p1 = tmp_path / "IMG_0001.CR3"
    p2 = tmp_path / "DCIM/100CANON/IMG_9999.CR3"
    p2.parent.mkdir(parents=True)
    p1.write_bytes(data)
    p2.write_bytes(data)
    assert content_identity_of_path(p1) == content_identity_of_path(p2)


def test_streaming_matches_single_shot_across_chunk_boundaries() -> None:
    data = bytes(range(256)) * 5000  # ~1.25 MB, crosses small chunk sizes
    whole = content_identity_of_bytes(data)
    streamed = hash_stream(io.BytesIO(data), chunk_bytes=7)  # deliberately tiny chunks
    assert streamed == whole


def test_empty_file_identity() -> None:
    identity = content_identity_of_bytes(b"")
    assert identity.size_bytes == 0
    assert identity.sha256 == hashlib.sha256(b"").hexdigest()


def test_zero_chunk_size_rejected() -> None:
    with pytest.raises(ValueError):
        hash_stream(io.BytesIO(b"x"), chunk_bytes=0)


def test_content_identity_is_hashable_and_frozen() -> None:
    identity = ContentIdentity(size_bytes=3, sha256="abc")
    assert identity in {identity}
    with pytest.raises(AttributeError):
        identity.size_bytes = 4  # type: ignore[misc]
