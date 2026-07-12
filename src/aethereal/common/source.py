"""Neutral source-reference type shared by the media manager and the web layer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourceRef:
    """A source presented to the appliance: the mounted card root and a logical name."""

    root: Path
    logical_name: str
