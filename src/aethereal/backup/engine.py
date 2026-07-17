"""The backup engine — the authoritative orchestrator (``backupd`` core).

Ties the portable pieces into a job lifecycle: it owns the ``JobStateMachine``, generates
job ids and session paths (DST-006/009), runs preflight and the job runner, updates the
manifest, reconciles interrupted jobs on startup (REC-001), and publishes state/events.

Source-mount and destination validation are OS-specific and performed by the Linux
service layer before ``run_backup`` is called; this class stays portable and testable.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from aethereal.backup.capacity import (
    DEFAULT_RESERVE_FLOOR_BYTES,
    DEFAULT_SAFETY_MARGIN_MIN_BYTES,
    DEFAULT_SAFETY_MARGIN_PERCENT,
)
from aethereal.backup.identity import DEFAULT_CHUNK_BYTES
from aethereal.backup.manifest_journal import JobManifestJournal
from aethereal.backup.preflight import PreflightOutcome, PreflightResult, run_preflight
from aethereal.backup.recovery import RecoveryReport, recover_destination
from aethereal.backup.runner import (
    CancellationToken,
    JobOutcome,
    JobRunResult,
    run_job,
)
from aethereal.backup.state_machine import BackupState, JobStateMachine
from aethereal.common.events import EventBus, EventSeverity, EventType
from aethereal.common.platform import DiskUsage, PlatformOps
from aethereal.db.manifest_repo import ManifestRepository

_RESET_ROUTES: dict[BackupState, tuple[BackupState, ...]] = {
    BackupState.IDLE: (),
    BackupState.SOURCE_SAFE_TO_REMOVE: (BackupState.IDLE,),
    BackupState.PREFLIGHT_BLOCKED: (BackupState.IDLE,),
    BackupState.BACKUP_FAILED: (BackupState.SOURCE_SAFE_TO_REMOVE, BackupState.IDLE),
    BackupState.BACKUP_CANCELLED: (BackupState.SOURCE_SAFE_TO_REMOVE, BackupState.IDLE),
}

_JOB_OUTCOME_TO_STATE = {
    JobOutcome.COMPLETED: BackupState.BACKUP_COMPLETED,
    JobOutcome.COMPLETED_WITH_WARNINGS: BackupState.BACKUP_COMPLETED_WITH_WARNINGS,
    JobOutcome.FAILED: BackupState.BACKUP_FAILED,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name) or "SOURCE"


@dataclass(frozen=True, slots=True)
class EngineResult:
    """Outcome of an engine ``run_backup`` call."""

    state: BackupState
    preflight_outcome: PreflightOutcome
    preflight: PreflightResult
    job: JobRunResult | None
    job_id: str | None


@dataclass(frozen=True, slots=True)
class DestinationStatus:
    """Current destination filesystem and manifest summary (WEB-002/WEB-008)."""

    backup_root: str
    present: bool
    total_bytes: int
    free_bytes: int
    verified_object_count: int
    backed_up_bytes: int


class BackupEngine:
    """Authoritative owner of backup state and the job lifecycle."""

    def __init__(
        self,
        *,
        repo: ManifestRepository,
        object_store_root: Path | str,
        backup_root: Path | str,
        platform: PlatformOps,
        event_bus: EventBus | None = None,
        clock: Callable[[], datetime] = _utc_now,
        safety_margin_percent: int = DEFAULT_SAFETY_MARGIN_PERCENT,
        safety_margin_min_bytes: int = DEFAULT_SAFETY_MARGIN_MIN_BYTES,
        reserve_floor_bytes: int = DEFAULT_RESERVE_FLOOR_BYTES,
        retries: int = 2,
        chunk_bytes: int = DEFAULT_CHUNK_BYTES,
        is_clock_trusted: Callable[[], bool] | None = None,
        media_extensions: tuple[str, ...] = (),
    ) -> None:
        self._repo = repo
        self._object_store_root = Path(object_store_root)
        self._backup_root = Path(backup_root)
        self._platform = platform
        self._bus = event_bus
        self._clock = clock
        self._safety_margin_percent = safety_margin_percent
        self._safety_margin_min_bytes = safety_margin_min_bytes
        self._reserve_floor_bytes = reserve_floor_bytes
        self._retries = retries
        self._chunk_bytes = chunk_bytes
        # FILE-008: restrict the scan to these image/video extensions (lowercase, no dot).
        # Empty keeps the faithful full-card backup.
        self._media_extensions = frozenset(
            ext.lower().lstrip(".") for ext in media_extensions if ext
        )
        # TIME-001: a dated backup session may only be created when the clock is trusted.
        self._is_clock_trusted = is_clock_trusted or (lambda: True)
        self._sm = JobStateMachine(on_transition=self._on_transition)
        self._cancel_token: CancellationToken | None = None
        # Cache of the most recent scan: (source_root, bytes_already_backed_up). Used by
        # the UI source bar; None until a dry run or backup has hashed the card.
        self._last_scan: tuple[str, int] | None = None

    def last_source_scan(self, source_root: Path | str) -> int | None:
        """Backed-up bytes for ``source_root`` as of the last scan, or None if unscanned."""
        if self._last_scan is not None and self._last_scan[0] == str(source_root):
            return self._last_scan[1]
        return None

    @property
    def state(self) -> BackupState:
        return self._sm.state

    def filesystem_usage(self, path: Path | str) -> DiskUsage:
        """Total/free bytes for the filesystem containing ``path`` (via the platform)."""
        return self._platform.disk_usage(path)

    def power_off(self) -> None:
        """Shut the device down (WEB-004), via the platform seam."""
        self._platform.power_off()

    def reboot(self) -> None:
        """Reboot the device (WEB-004), via the platform seam."""
        self._platform.reboot()

    def destination_status(self) -> DestinationStatus:
        """Summarise the configured destination: capacity plus what it already holds."""
        present = self._backup_root.exists()
        if present:
            usage = self._platform.disk_usage(self._backup_root)
            total, free = usage.total_bytes, usage.free_bytes
        else:
            total = free = 0
        verified_count, backed_up_bytes = self._repo.destination_totals()
        return DestinationStatus(
            backup_root=str(self._backup_root),
            present=present,
            total_bytes=total,
            free_bytes=free,
            verified_object_count=verified_count,
            backed_up_bytes=backed_up_bytes,
        )

    def request_cancellation(self) -> bool:
        """Request that the active backup stop safely (JOB-001). Thread-safe.

        Returns True if a backup was active to cancel, False otherwise.
        """
        token = self._cancel_token
        if token is None:
            return False
        token.cancel()
        return True

    def _on_transition(self, source: BackupState, target: BackupState) -> None:
        if self._bus is not None:
            self._bus.publish(
                EventType.SYSTEM_STATE_CHANGED,
                EventSeverity.INFO,
                "backupd",
                f"{source.value} -> {target.value}",
                details={"from": source.value, "to": target.value},
            )

    def _emit(
        self, event_type: EventType, severity: EventSeverity, message: str, **details: object
    ) -> None:
        if self._bus is not None:
            self._bus.publish(event_type, severity, "backupd", message, details=details)

    def _generate_job_id(self, now: datetime) -> str:
        prefix = f"{now.strftime('%Y%m%d')}-"
        sequence = self._repo.count_jobs_for_date(prefix) + 1
        return f"{prefix}{sequence:03d}"

    def _session_root(self, now: datetime, job_id: str, logical_source_name: str) -> str:
        year = now.strftime("%Y")
        day = now.strftime("%Y-%m-%d")
        folder = f"{job_id}_{_sanitize(logical_source_name)}"
        return str(self._backup_root / year / day / folder)

    def _run_preflight(self, source_root: Path, session_root: str) -> PreflightResult:
        return run_preflight(
            source_root,
            session_root=session_root,
            destination_path=self._backup_root,
            platform=self._platform,
            verified=self._repo.has_verified_object,
            safety_margin_percent=self._safety_margin_percent,
            safety_margin_min_bytes=self._safety_margin_min_bytes,
            reserve_floor_bytes=self._reserve_floor_bytes,
            chunk_bytes=self._chunk_bytes,
            media_extensions=self._media_extensions,
        )

    def recover_on_startup(self) -> RecoveryReport:
        """Reconcile interrupted objects and flag non-terminal jobs (REC-001)."""
        self._emit(EventType.RECOVERY_STARTED, EventSeverity.INFO, "startup recovery")
        report = recover_destination(
            self._repo, object_store_root=self._object_store_root, chunk_bytes=self._chunk_bytes
        )
        for job_id in self._repo.list_incomplete_jobs():
            self._repo.set_backup_job_state(job_id, BackupState.RECOVERY_REQUIRED.value)
        self._emit(
            EventType.RECOVERY_COMPLETED,
            EventSeverity.INFO,
            "startup recovery complete",
            finalized=report.finalized,
            discarded=report.discarded,
            orphan_partials_removed=report.orphan_partials_removed,
        )
        return report

    def dry_run(self, source_root: Path, logical_source_name: str) -> PreflightResult:
        """Compute preflight without touching job state or copying content (DRY-001/003)."""
        self._emit(EventType.PREFLIGHT_STARTED, EventSeverity.INFO, "dry run")
        now = self._clock()
        job_id = self._generate_job_id(now)
        session_root = self._session_root(now, job_id, logical_source_name)
        result = self._run_preflight(source_root, session_root)
        self._last_scan = (str(source_root), result.already_backed_up_bytes)
        self._emit(
            EventType.PREFLIGHT_COMPLETED,
            EventSeverity.INFO,
            "dry run complete",
            outcome=result.outcome.value,
        )
        return result

    def reset(self) -> None:
        """Return to IDLE from a resting state (post-completion, blocked, or failed)."""
        route = _RESET_ROUTES.get(self._sm.state)
        if route is None:
            raise ValueError(f"cannot reset from {self._sm.state.value}")
        for target in route:
            self._sm.transition(target)

    def run_backup(self, source_root: Path, logical_source_name: str) -> EngineResult:
        """Run a full preflight and, if ready, execute the backup to completion."""
        now = self._clock()
        self._sm.transition(BackupState.SOURCE_DETECTED)
        self._sm.transition(BackupState.SOURCE_MOUNTING)
        self._sm.transition(BackupState.SOURCE_READY)

        self._sm.transition(BackupState.PREFLIGHT_SCANNING)
        self._emit(EventType.PREFLIGHT_STARTED, EventSeverity.INFO, "preflight")
        job_id = self._generate_job_id(now)
        session_root = self._session_root(now, job_id, logical_source_name)
        self._sm.transition(BackupState.PREFLIGHT_HASHING)
        self._sm.transition(BackupState.PREFLIGHT_COMPARING)
        self._sm.transition(BackupState.PREFLIGHT_CAPACITY_CHECK)
        preflight = self._run_preflight(source_root, session_root)
        self._last_scan = (str(source_root), preflight.already_backed_up_bytes)
        clock_trusted = self._is_clock_trusted()

        if preflight.outcome is PreflightOutcome.BLOCKED or not clock_trusted:
            self._sm.transition(BackupState.PREFLIGHT_BLOCKED)
            reasons = list(preflight.block_reasons)
            if not clock_trusted:
                reasons.append(
                    "wall-clock time is untrusted; a dated backup session cannot be "
                    "created (TIME-001)"
                )
            self._emit(
                EventType.PREFLIGHT_COMPLETED,
                EventSeverity.WARNING,
                "preflight blocked",
                reasons=reasons,
            )
            return EngineResult(self._sm.state, PreflightOutcome.BLOCKED, preflight, None, None)

        if preflight.outcome is PreflightOutcome.WARNING:
            self._sm.transition(BackupState.PREFLIGHT_WARNING)
        else:
            self._sm.transition(BackupState.PREFLIGHT_READY)
        self._emit(EventType.PREFLIGHT_COMPLETED, EventSeverity.INFO, "preflight ready")

        self._sm.transition(BackupState.BACKUP_QUEUED)
        self._repo.create_backup_job(
            job_id, state=BackupState.BACKUP_COPYING.value, session_path=session_root
        )
        self._sm.transition(BackupState.BACKUP_COPYING)
        self._emit(EventType.BACKUP_STARTED, EventSeverity.INFO, "backup started", job_id=job_id)

        def _on_progress(done: int, total: int, relative_path: str) -> None:
            self._emit(
                EventType.BACKUP_PROGRESS,
                EventSeverity.INFO,
                "backup progress",
                job_id=job_id,
                done=done,
                total=total,
                current_file=relative_path,
            )

        token = CancellationToken()
        self._cancel_token = token
        journal = JobManifestJournal(self._repo, job_id)
        try:
            job = run_job(
                preflight.plan,
                source_root=source_root,
                object_store_root=self._object_store_root,
                journal=journal,
                platform=self._platform,
                retries=self._retries,
                chunk_bytes=self._chunk_bytes,
                on_progress=_on_progress if self._bus is not None else None,
                cancel_token=token,
            )
        finally:
            self._cancel_token = None

        if job.outcome is JobOutcome.CANCELLED:
            self._finish_job_row(job_id, BackupState.BACKUP_CANCELLED, job)
            self._sm.transition(BackupState.BACKUP_CANCELLING)
            self._sm.transition(BackupState.BACKUP_CANCELLED)
            self._emit(
                EventType.BACKUP_CANCELLED,
                EventSeverity.WARNING,
                "backup cancelled",
                job_id=job_id,
            )
            self._sm.transition(BackupState.SOURCE_SAFE_TO_REMOVE)
            return EngineResult(self._sm.state, preflight.outcome, preflight, job, job_id)

        self._sm.transition(BackupState.BACKUP_VERIFYING)
        final_state = _JOB_OUTCOME_TO_STATE[job.outcome]
        self._sm.transition(final_state)
        self._finish_job_row(job_id, final_state, job)

        if job.outcome is JobOutcome.FAILED:
            self._emit(
                EventType.BACKUP_FAILED,
                EventSeverity.ERROR,
                "backup failed",
                job_id=job_id,
                failures=list(job.failures),
            )
        else:
            self._emit(
                EventType.BACKUP_COMPLETED,
                EventSeverity.INFO,
                "backup completed",
                job_id=job_id,
                outcome=job.outcome.value,
            )
            # All scanned content is now backed up: reflect that in the source bar.
            self._last_scan = (str(source_root), preflight.source_bytes_scanned)
            self._sm.transition(BackupState.SOURCE_SAFE_TO_REMOVE)

        return EngineResult(self._sm.state, preflight.outcome, preflight, job, job_id)

    def _finish_job_row(self, job_id: str, state: BackupState, job: JobRunResult) -> None:
        self._repo.finish_backup_job(
            job_id,
            state=state.value,
            files_copied=job.files_copied,
            files_skipped=job.files_skipped,
            files_failed=job.files_failed,
            files_verified=job.files_verified,
            copied_bytes=job.bytes_copied,
        )
