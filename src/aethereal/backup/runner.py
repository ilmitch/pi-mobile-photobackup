"""Backup job runner.

Executes an immutable ``Plan`` (Implementation Plan v0.3 section 14) file by file,
dispatching each action to the copy/verify/finalize engine or the hardlink path, and
tallies the job result per the completion definition (PRD v0.3 section 33): a job is only
COMPLETED when every planned file is verified and none failed.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from aethereal.backup.copier import (
    CopyOutcome,
    FinalizeJournal,
    SessionPathConflict,
    copy_verify_finalize,
    link_verified_object,
)
from aethereal.backup.identity import DEFAULT_CHUNK_BYTES
from aethereal.backup.planner import FileAction, Plan
from aethereal.common.platform import PlatformOps


class JobOutcome(str, Enum):
    """Terminal job outcomes (PRD sections 31, 33)."""

    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class CancellationToken:
    """Thread-safe cooperative cancellation flag (JOB-001)."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True, slots=True)
class JobRunResult:
    """Aggregate result of executing a plan."""

    outcome: JobOutcome
    files_verified: int
    files_copied: int
    files_skipped: int
    files_failed: int
    bytes_copied: int
    failures: tuple[str, ...] = field(default_factory=tuple)


# Progress callback: (files_done, files_total, bytes_done, bytes_total,
# relative_path_just_processed). Bytes track planned sizes so the UI can show a byte-based
# bar (smoother than file count when sizes vary, e.g. large video among small photos).
ProgressCallback = Callable[[int, int, int, int, str], None]


def run_job(
    plan: Plan,
    *,
    source_root: Path,
    object_store_root: Path | str,
    journal: FinalizeJournal,
    platform: PlatformOps,
    retries: int = 2,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    on_progress: ProgressCallback | None = None,
    cancel_token: CancellationToken | None = None,
) -> JobRunResult:
    """Execute ``plan`` and return the aggregate result.

    ``on_progress`` is called once per planned file with (files_done, files_total,
    bytes_done, bytes_total, relative_path). If ``cancel_token`` is set between files,
    scheduling stops after the current file finishes (JOB-001); already-verified files are
    preserved and the outcome is CANCELLED. Raises ``ValueError`` if the plan is blocked — a
    blocked plan must never run.
    """
    if plan.blocked:
        raise ValueError("cannot run a blocked plan")

    total = len(plan.files)
    total_bytes = sum(f.planned_size_bytes for f in plan.files)
    done = 0
    bytes_done = 0
    cancelled = False

    verified = copied = skipped = failed = 0
    bytes_copied = 0
    failures: list[str] = []

    for planned in plan.files:
        # Cooperative cancellation boundary: stop scheduling before the next file.
        if cancel_token is not None and cancel_token.cancelled:
            cancelled = True
            break

        action = planned.action

        if action is FileAction.COPY_VERIFY_OBJECT_AND_LINK:
            assert planned.identity is not None
            try:
                result = copy_verify_finalize(
                    source_root / planned.relative_path,
                    planned.identity,
                    object_store_root=object_store_root,
                    session_path=planned.session_path,
                    journal=journal,
                    platform=platform,
                    retries=retries,
                    chunk_bytes=chunk_bytes,
                )
            except OSError as exc:  # e.g. source removed mid-copy (REC-007)
                failed += 1
                failures.append(f"{planned.relative_path}: source error: {exc}")
                continue
            if result.outcome is CopyOutcome.VERIFIED:
                verified += 1
                copied += 1
                bytes_copied += result.bytes_written
            else:
                failed += 1
                failures.append(f"{planned.relative_path}: {result.outcome.value}")

        elif action in (
            FileAction.LINK_EXISTING_VERIFIED_OBJECT,
            FileAction.LINK_NEW_OBJECT_SAME_JOB,
        ):
            assert planned.identity is not None
            try:
                link_verified_object(
                    object_store_root, planned.identity, planned.session_path, journal
                )
                verified += 1
                if action is FileAction.LINK_EXISTING_VERIFIED_OBJECT:
                    skipped += 1
            except (FileNotFoundError, SessionPathConflict) as exc:
                failed += 1
                failures.append(f"{planned.relative_path}: link failed: {exc}")

        elif action is FileAction.SKIP_UNSUPPORTED:
            pass

        else:  # BLOCK_* — unreachable because a blocked plan is rejected above
            failed += 1
            failures.append(f"{planned.relative_path}: unexpected blocking action")

        done += 1
        bytes_done += planned.planned_size_bytes
        if on_progress is not None:
            on_progress(done, total, bytes_done, total_bytes, planned.relative_path)

    if cancelled:
        outcome = JobOutcome.CANCELLED
    elif failed:
        outcome = JobOutcome.FAILED
    elif plan.unsupported_count:
        outcome = JobOutcome.COMPLETED_WITH_WARNINGS
    else:
        outcome = JobOutcome.COMPLETED

    return JobRunResult(
        outcome=outcome,
        files_verified=verified,
        files_copied=copied,
        files_skipped=skipped,
        files_failed=failed,
        bytes_copied=bytes_copied,
        failures=tuple(failures),
    )
