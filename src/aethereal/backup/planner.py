"""Immutable backup plan construction.

Implements Implementation Plan v0.3 section 14 (backup planning) and PRD DST-007
(complete snapshot view via hardlinks). Extends the plan to handle the intra-job
duplicate-content case identified in review finding R2-2: when two source files on the
same card share content, only the first copies the canonical object; the rest link to
it, so the second instance never collides on the object path.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from aethereal.backup.classification import FileClassification
from aethereal.backup.identity import ContentIdentity


class FileAction(str, Enum):
    """What the copy engine will do for a planned file.

    ``LINK_NEW_OBJECT_SAME_JOB`` (R2-2) links to a canonical object produced by another
    NEW file *in the same job*, rather than copying identical content twice.
    """

    COPY_VERIFY_OBJECT_AND_LINK = "COPY_VERIFY_OBJECT_AND_LINK"
    LINK_EXISTING_VERIFIED_OBJECT = "LINK_EXISTING_VERIFIED_OBJECT"
    LINK_NEW_OBJECT_SAME_JOB = "LINK_NEW_OBJECT_SAME_JOB"
    SKIP_UNSUPPORTED = "SKIP_UNSUPPORTED"
    BLOCK_CONFLICT = "BLOCK_CONFLICT"
    BLOCK_UNREADABLE = "BLOCK_UNREADABLE"


@dataclass(frozen=True, slots=True)
class ClassifiedFile:
    """A classified source file entering the planner."""

    relative_path: str
    identity: ContentIdentity | None
    size_bytes: int
    classification: FileClassification


@dataclass(frozen=True, slots=True)
class PlannedFile:
    """One immutable entry of the backup plan."""

    relative_path: str
    session_path: str
    identity: ContentIdentity | None
    classification: FileClassification
    action: FileAction
    planned_size_bytes: int


@dataclass(frozen=True, slots=True)
class Plan:
    """The complete immutable plan for a backup job."""

    files: tuple[PlannedFile, ...]
    new_object_bytes: int
    new_object_count: int
    already_backed_up_count: int
    intra_job_duplicate_count: int
    conflict_count: int
    unreadable_count: int
    unsupported_count: int
    largest_new_object_bytes: int
    blocked: bool
    block_reasons: tuple[str, ...] = field(default_factory=tuple)


def _session_path(session_root: str, relative_path: str) -> str:
    return f"{session_root.rstrip('/')}/{relative_path}"


def build_plan(items: Iterable[ClassifiedFile], *, session_root: str) -> Plan:
    """Build the immutable plan, deduplicating identical NEW content within the job.

    Files are processed in normalized relative-path order for determinism. A POTENTIAL_
    CONFLICT or UNREADABLE file blocks the whole job (FILE-007 default policy; unreadable
    is blocking in v1).
    """
    ordered = sorted(items, key=lambda f: f.relative_path)

    planned: list[PlannedFile] = []
    seen_new: set[ContentIdentity] = set()
    new_object_bytes = 0
    new_object_count = 0
    already = 0
    intra_dupes = 0
    conflicts = 0
    unreadable = 0
    unsupported = 0
    largest_new = 0
    block_reasons: list[str] = []

    for item in ordered:
        session_path = _session_path(session_root, item.relative_path)
        cls = item.classification

        if cls is FileClassification.UNREADABLE:
            action = FileAction.BLOCK_UNREADABLE
            unreadable += 1
            block_reasons.append(f"unreadable: {item.relative_path}")
        elif cls is FileClassification.POTENTIAL_CONFLICT:
            action = FileAction.BLOCK_CONFLICT
            conflicts += 1
            block_reasons.append(f"conflict: {item.relative_path}")
        elif cls is FileClassification.ALREADY_BACKED_UP:
            action = FileAction.LINK_EXISTING_VERIFIED_OBJECT
            already += 1
        elif cls is FileClassification.NEW:
            assert item.identity is not None  # NEW always carries an identity
            if item.identity in seen_new:
                # R2-2: duplicate content already scheduled to be copied in this job.
                action = FileAction.LINK_NEW_OBJECT_SAME_JOB
                intra_dupes += 1
            else:
                seen_new.add(item.identity)
                action = FileAction.COPY_VERIFY_OBJECT_AND_LINK
                new_object_count += 1
                new_object_bytes += item.size_bytes
                largest_new = max(largest_new, item.size_bytes)
        else:  # UNSUPPORTED (FILE-001): symlinks/special objects are skipped, not blocking
            action = FileAction.SKIP_UNSUPPORTED
            unsupported += 1

        planned.append(
            PlannedFile(
                relative_path=item.relative_path,
                session_path=session_path,
                identity=item.identity,
                classification=cls,
                action=action,
                planned_size_bytes=item.size_bytes,
            )
        )

    blocked = bool(conflicts or unreadable)
    return Plan(
        files=tuple(planned),
        new_object_bytes=new_object_bytes,
        new_object_count=new_object_count,
        already_backed_up_count=already,
        intra_job_duplicate_count=intra_dupes,
        conflict_count=conflicts,
        unreadable_count=unreadable,
        unsupported_count=unsupported,
        largest_new_object_bytes=largest_new,
        blocked=blocked,
        block_reasons=tuple(block_reasons),
    )
