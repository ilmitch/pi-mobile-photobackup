"""Authoritative backup job state machine.

Implements PRD v0.3 section 20 (Backup Job States) and Implementation Plan v0.3
section 7 (Authoritative State Machine). ``backupd`` is the sole authority for these
states; the web UI and LED controller only consume them.

The transition map is encoded explicitly and validated on every transition, so an
illegal state change raises rather than silently corrupting job state.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum


class BackupState(str, Enum):
    """Every state a backup job may occupy.

    Values mirror the PRD names so they can be persisted and shown verbatim.
    """

    IDLE = "IDLE"

    SOURCE_DETECTED = "SOURCE_DETECTED"
    MULTIPLE_SOURCES_DETECTED = "MULTIPLE_SOURCES_DETECTED"
    SOURCE_MOUNTING = "SOURCE_MOUNTING"
    SOURCE_PROTECTION_FAILURE = "SOURCE_PROTECTION_FAILURE"
    SOURCE_READY = "SOURCE_READY"

    PREFLIGHT_SCANNING = "PREFLIGHT_SCANNING"
    PREFLIGHT_HASHING = "PREFLIGHT_HASHING"
    PREFLIGHT_COMPARING = "PREFLIGHT_COMPARING"
    PREFLIGHT_CAPACITY_CHECK = "PREFLIGHT_CAPACITY_CHECK"
    PREFLIGHT_READY = "PREFLIGHT_READY"
    PREFLIGHT_WARNING = "PREFLIGHT_WARNING"
    PREFLIGHT_BLOCKED = "PREFLIGHT_BLOCKED"

    BACKUP_QUEUED = "BACKUP_QUEUED"
    BACKUP_COPYING = "BACKUP_COPYING"
    BACKUP_CANCELLING = "BACKUP_CANCELLING"
    BACKUP_VERIFYING = "BACKUP_VERIFYING"

    BACKUP_COMPLETED = "BACKUP_COMPLETED"
    BACKUP_COMPLETED_WITH_WARNINGS = "BACKUP_COMPLETED_WITH_WARNINGS"
    BACKUP_CANCELLED = "BACKUP_CANCELLED"
    BACKUP_FAILED = "BACKUP_FAILED"

    SOURCE_SAFE_TO_REMOVE = "SOURCE_SAFE_TO_REMOVE"

    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    RECOVERING = "RECOVERING"


# Allowed outbound transitions, transcribed from Implementation Plan v0.3 section 7.
# A state absent as a key, or with an empty set, has no defined outbound transition.
_ALLOWED: dict[BackupState, frozenset[BackupState]] = {
    BackupState.IDLE: frozenset(
        {BackupState.SOURCE_DETECTED, BackupState.MULTIPLE_SOURCES_DETECTED}
    ),
    BackupState.SOURCE_DETECTED: frozenset(
        {
            BackupState.SOURCE_MOUNTING,
            BackupState.SOURCE_PROTECTION_FAILURE,
            BackupState.BACKUP_FAILED,
        }
    ),
    BackupState.MULTIPLE_SOURCES_DETECTED: frozenset(
        {BackupState.SOURCE_DETECTED, BackupState.IDLE}
    ),
    BackupState.SOURCE_MOUNTING: frozenset(
        {
            BackupState.SOURCE_READY,
            BackupState.SOURCE_PROTECTION_FAILURE,
            BackupState.BACKUP_FAILED,
        }
    ),
    BackupState.SOURCE_PROTECTION_FAILURE: frozenset(
        {BackupState.SOURCE_DETECTED, BackupState.IDLE}
    ),
    BackupState.SOURCE_READY: frozenset({BackupState.PREFLIGHT_SCANNING}),
    BackupState.PREFLIGHT_SCANNING: frozenset(
        {
            BackupState.PREFLIGHT_HASHING,
            BackupState.PREFLIGHT_BLOCKED,
            BackupState.BACKUP_FAILED,
        }
    ),
    BackupState.PREFLIGHT_HASHING: frozenset(
        {
            BackupState.PREFLIGHT_COMPARING,
            BackupState.PREFLIGHT_BLOCKED,
            BackupState.BACKUP_FAILED,
        }
    ),
    BackupState.PREFLIGHT_COMPARING: frozenset({BackupState.PREFLIGHT_CAPACITY_CHECK}),
    BackupState.PREFLIGHT_CAPACITY_CHECK: frozenset(
        {
            BackupState.PREFLIGHT_READY,
            BackupState.PREFLIGHT_WARNING,
            BackupState.PREFLIGHT_BLOCKED,
        }
    ),
    BackupState.PREFLIGHT_READY: frozenset({BackupState.BACKUP_QUEUED}),
    BackupState.PREFLIGHT_WARNING: frozenset(
        {BackupState.BACKUP_QUEUED, BackupState.PREFLIGHT_BLOCKED}
    ),
    # A blocked preflight must be able to rescan (after the user frees space or swaps the
    # SSD) or be abandoned. PRE-008 forbids *overriding* a capacity block, not rescanning.
    # See Implementation Plan v0.3 section 7.
    BackupState.PREFLIGHT_BLOCKED: frozenset({BackupState.PREFLIGHT_SCANNING, BackupState.IDLE}),
    BackupState.BACKUP_QUEUED: frozenset(
        {BackupState.BACKUP_COPYING, BackupState.BACKUP_CANCELLED}
    ),
    BackupState.BACKUP_COPYING: frozenset(
        {
            BackupState.BACKUP_VERIFYING,
            BackupState.BACKUP_CANCELLING,
            BackupState.RECOVERY_REQUIRED,
            BackupState.BACKUP_FAILED,
        }
    ),
    BackupState.BACKUP_VERIFYING: frozenset(
        {
            BackupState.BACKUP_COPYING,
            BackupState.BACKUP_COMPLETED,
            BackupState.BACKUP_COMPLETED_WITH_WARNINGS,
            BackupState.BACKUP_CANCELLING,
            BackupState.RECOVERY_REQUIRED,
            BackupState.BACKUP_FAILED,
        }
    ),
    BackupState.BACKUP_CANCELLING: frozenset(
        {BackupState.BACKUP_CANCELLED, BackupState.RECOVERY_REQUIRED}
    ),
    BackupState.BACKUP_COMPLETED: frozenset({BackupState.SOURCE_SAFE_TO_REMOVE}),
    BackupState.BACKUP_COMPLETED_WITH_WARNINGS: frozenset({BackupState.SOURCE_SAFE_TO_REMOVE}),
    BackupState.BACKUP_CANCELLED: frozenset(
        {BackupState.SOURCE_SAFE_TO_REMOVE, BackupState.PREFLIGHT_SCANNING}
    ),
    BackupState.RECOVERY_REQUIRED: frozenset({BackupState.RECOVERING}),
    BackupState.RECOVERING: frozenset(
        {
            BackupState.PREFLIGHT_SCANNING,
            BackupState.BACKUP_COPYING,
            BackupState.BACKUP_VERIFYING,
            BackupState.BACKUP_COMPLETED,
            BackupState.BACKUP_FAILED,
        }
    ),
    BackupState.SOURCE_SAFE_TO_REMOVE: frozenset({BackupState.IDLE}),
    # A failed job must be recoverable: retry through a fresh preflight (PRE-001 /
    # WEB-004), enter reconciliation, or be abandoned cleanly. See Implementation
    # Plan v0.3 section 7.
    BackupState.BACKUP_FAILED: frozenset(
        {
            BackupState.PREFLIGHT_SCANNING,
            BackupState.RECOVERY_REQUIRED,
            BackupState.SOURCE_SAFE_TO_REMOVE,
        }
    ),
}


class InvalidTransition(Exception):
    """Raised when a state transition is not permitted by the transition map."""

    def __init__(self, source: BackupState, target: BackupState) -> None:
        self.source = source
        self.target = target
        super().__init__(f"illegal backup state transition: {source.value} -> {target.value}")


def allowed_targets(source: BackupState) -> frozenset[BackupState]:
    """Return the set of states reachable from ``source`` in a single transition."""
    return _ALLOWED.get(source, frozenset())


def can_transition(source: BackupState, target: BackupState) -> bool:
    """Return whether ``source -> target`` is a permitted single transition."""
    return target in allowed_targets(source)


# Hook invoked after a validated transition. The persistence/event layer (Impl §7
# steps 2-4: persist, record event, publish) plugs in here without this module
# depending on the database or event bus.
TransitionHook = Callable[[BackupState, BackupState], None]


class JobStateMachine:
    """Tracks the current state of a single backup job and guards its transitions.

    Per Implementation Plan v0.3 section 7, every transition validates first, then
    (via ``on_transition``) persists, records an event, and publishes. A rejected
    transition never mutates state and never fires the hook.
    """

    def __init__(
        self,
        initial: BackupState = BackupState.IDLE,
        *,
        on_transition: TransitionHook | None = None,
    ) -> None:
        self._state = initial
        self._on_transition = on_transition

    @property
    def state(self) -> BackupState:
        return self._state

    def can_transition_to(self, target: BackupState) -> bool:
        return can_transition(self._state, target)

    def transition(self, target: BackupState) -> BackupState:
        """Validate and apply a transition to ``target``.

        Raises ``InvalidTransition`` (leaving state unchanged) if the move is not
        permitted. On success, applies the new state and invokes ``on_transition``.
        """
        source = self._state
        if not can_transition(source, target):
            raise InvalidTransition(source, target)
        self._state = target
        if self._on_transition is not None:
            self._on_transition(source, target)
        return target
