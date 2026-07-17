"""Preflight orchestrator.

Implements PRD v0.3 sections 16 (mandatory preflight) and 17 (dry run), and Implementation
Plan v0.3 section 13. Chains the portable core: scan the source read-only, strictly hash
every regular file (FILE-004), derive the source snapshot identity (SRC-007), classify each
file (FILE-005/006/007), build the immutable plan with intra-job dedup (R2-2), and compute
destination capacity (PRE-004..007). Produces READY / WARNING / BLOCKED without copying any
content.

OS-specific capacity measurement is taken through the ``PlatformOps`` seam, so this module
runs unchanged on the macOS dev host with a fake.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from aethereal.backup.capacity import (
    DEFAULT_RESERVE_FLOOR_BYTES,
    DEFAULT_SAFETY_MARGIN_MIN_BYTES,
    DEFAULT_SAFETY_MARGIN_PERCENT,
    CapacityAssessment,
    assess_capacity,
)
from aethereal.backup.classification import (
    ClassificationInput,
    FileClassification,
    OccupantLookup,
    VerifiedLookup,
    classify,
)
from aethereal.backup.identity import DEFAULT_CHUNK_BYTES, content_identity_of_path
from aethereal.backup.planner import ClassifiedFile, Plan, build_plan
from aethereal.backup.snapshot import (
    SourceFileRecord,
    SourceSnapshot,
    build_source_snapshot,
    normalize_relative_path,
)
from aethereal.common.platform import PlatformOps


class PreflightOutcome(str, Enum):
    """Terminal preflight outcomes (PRE-002 / DRY-003)."""

    READY = "READY"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """The complete outcome of a preflight/dry-run pass."""

    outcome: PreflightOutcome
    snapshot: SourceSnapshot
    plan: Plan
    capacity: CapacityAssessment
    files_discovered: int
    new_file_count: int
    already_backed_up_count: int
    conflict_count: int
    unreadable_count: int
    unsupported_count: int
    source_bytes_scanned: int
    new_bytes: int
    already_backed_up_bytes: int
    warnings: tuple[str, ...] = field(default_factory=tuple)
    block_reasons: tuple[str, ...] = field(default_factory=tuple)


def _is_media(name: str, media_extensions: frozenset[str]) -> bool:
    """True if ``name`` is a media file selected by the extension whitelist.

    Dotfiles are always rejected: this drops macOS AppleDouble sidecars (``._MVI_1234.MOV``,
    which otherwise share the real file's extension), ``.DS_Store``, and the like. The
    extension is matched case-insensitively, without its leading dot.
    """
    if name.startswith("."):
        return False
    return Path(name).suffix.lower().lstrip(".") in media_extensions


def _scan_source(
    source_root: Path, *, chunk_bytes: int, media_extensions: frozenset[str] = frozenset()
) -> tuple[list[ClassificationInput], list[SourceFileRecord]]:
    """Walk ``source_root`` read-only, hashing regular files and marking others.

    Symlinks and special objects become UNSUPPORTED inputs; files that cannot be read
    become UNREADABLE inputs. Only successfully hashed files contribute snapshot records.

    When ``media_extensions`` is non-empty, only image/video files with those extensions are
    considered (FILE-008): every other file — and every dot-directory such as
    ``.Spotlight-V100``/``.Trashes`` — is skipped entirely, so non-media never gets counted,
    hashed, copied, or able to block a backup. An empty set keeps the faithful full-card
    behaviour (copy every regular file).
    """
    inputs: list[ClassificationInput] = []
    records: list[SourceFileRecord] = []
    filtering = bool(media_extensions)

    for dirpath, dirnames, filenames in os.walk(source_root, followlinks=False):
        if filtering:
            # Prune hidden directories in place so os.walk never descends into system junk
            # (.Spotlight-V100, .Trashes, .fseventsd, ...).
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if filtering and not _is_media(name, media_extensions):
                continue
            full = Path(dirpath) / name
            relative = normalize_relative_path(full.relative_to(source_root).as_posix())
            if full.is_symlink() or not full.is_file():
                inputs.append(ClassificationInput(relative, None, unsupported=True))
                continue
            try:
                identity = content_identity_of_path(full, chunk_bytes=chunk_bytes)
            except OSError:
                inputs.append(ClassificationInput(relative, None, unreadable=True))
                continue
            inputs.append(ClassificationInput(relative, identity))
            records.append(
                SourceFileRecord(
                    relative_path=relative,
                    size_bytes=identity.size_bytes,
                    sha256=identity.sha256,
                )
            )
    return inputs, records


def _to_classified(
    items: Iterable[ClassificationInput], classification_of: dict[str, FileClassification]
) -> list[ClassifiedFile]:
    result: list[ClassifiedFile] = []
    for item in items:
        size = item.identity.size_bytes if item.identity is not None else 0
        result.append(
            ClassifiedFile(
                relative_path=item.relative_path,
                identity=item.identity,
                size_bytes=size,
                classification=classification_of[item.relative_path],
            )
        )
    return result


def run_preflight(
    source_root: Path,
    *,
    session_root: str,
    destination_path: Path | str,
    platform: PlatformOps,
    verified: VerifiedLookup,
    occupant: OccupantLookup | None = None,
    safety_margin_percent: int = DEFAULT_SAFETY_MARGIN_PERCENT,
    safety_margin_min_bytes: int = DEFAULT_SAFETY_MARGIN_MIN_BYTES,
    reserve_floor_bytes: int = DEFAULT_RESERVE_FLOOR_BYTES,
    metadata_estimate_bytes: int = 0,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    media_extensions: frozenset[str] = frozenset(),
) -> PreflightResult:
    """Run a full preflight over ``source_root`` and return the assessed result.

    ``media_extensions`` (lowercase, no leading dot) restricts the scan to image/video
    files (FILE-008); empty keeps the faithful full-card behaviour.
    """
    if not source_root.is_dir():
        raise ValueError(f"source_root is not a directory: {source_root}")

    inputs, records = _scan_source(
        source_root, chunk_bytes=chunk_bytes, media_extensions=media_extensions
    )
    snapshot = build_source_snapshot(records)

    classification_of = {
        item.relative_path: classify(item, verified=verified, occupant=occupant) for item in inputs
    }
    classified = _to_classified(inputs, classification_of)
    plan = build_plan(classified, session_root=session_root)

    usage = platform.disk_usage(destination_path)
    capacity = assess_capacity(
        destination_capacity_bytes=usage.total_bytes,
        available_bytes=usage.free_bytes,
        new_file_bytes=plan.new_object_bytes,
        largest_new_file_bytes=plan.largest_new_object_bytes,
        safety_margin_percent=safety_margin_percent,
        safety_margin_min_bytes=safety_margin_min_bytes,
        reserve_floor_bytes=reserve_floor_bytes,
        metadata_estimate_bytes=metadata_estimate_bytes,
    )

    block_reasons = list(plan.block_reasons)
    if not capacity.sufficient:
        block_reasons.append(
            f"insufficient destination capacity: shortfall {capacity.shortfall_bytes} bytes"
        )

    warnings: list[str] = []
    if plan.unsupported_count:
        warnings.append(f"{plan.unsupported_count} unsupported object(s) skipped")

    blocked = plan.blocked or not capacity.sufficient
    if blocked:
        outcome = PreflightOutcome.BLOCKED
    elif warnings:
        outcome = PreflightOutcome.WARNING
    else:
        outcome = PreflightOutcome.READY

    new_file_count = sum(1 for f in plan.files if f.classification is FileClassification.NEW)
    source_bytes = sum(f.planned_size_bytes for f in plan.files if f.identity is not None)
    already_backed_up_bytes = sum(
        f.planned_size_bytes
        for f in plan.files
        if f.classification is FileClassification.ALREADY_BACKED_UP
    )

    return PreflightResult(
        outcome=outcome,
        snapshot=snapshot,
        plan=plan,
        capacity=capacity,
        files_discovered=len(plan.files),
        new_file_count=new_file_count,
        already_backed_up_count=plan.already_backed_up_count,
        conflict_count=plan.conflict_count,
        unreadable_count=plan.unreadable_count,
        unsupported_count=plan.unsupported_count,
        source_bytes_scanned=source_bytes,
        new_bytes=plan.new_object_bytes,
        already_backed_up_bytes=already_backed_up_bytes,
        warnings=tuple(warnings),
        block_reasons=tuple(block_reasons),
    )
