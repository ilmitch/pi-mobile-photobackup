"""Unit tests for the backup state machine.

Covers Verification Plan v0.2 UT-001 (allowed/rejected transitions) and UT-006
(complete transition-map coverage for the states added in v0.3).
"""

from __future__ import annotations

import pytest

from aethereal.backup.state_machine import (
    _ALLOWED,
    BackupState,
    InvalidTransition,
    JobStateMachine,
    allowed_targets,
    can_transition,
)


def test_every_declared_transition_is_accepted() -> None:
    """Each transition in the map executes and updates state (UT-006)."""
    for source, targets in _ALLOWED.items():
        for target in targets:
            machine = JobStateMachine(initial=source)
            assert machine.can_transition_to(target)
            assert machine.transition(target) is target
            assert machine.state is target


@pytest.mark.parametrize(
    ("source", "target"),
    [
        # Representative illegal moves (UT-001).
        (BackupState.IDLE, BackupState.BACKUP_COMPLETED),
        (BackupState.PREFLIGHT_BLOCKED, BackupState.BACKUP_COPYING),
        (BackupState.BACKUP_QUEUED, BackupState.BACKUP_VERIFYING),
        (BackupState.BACKUP_COMPLETED, BackupState.IDLE),
        (BackupState.SOURCE_READY, BackupState.BACKUP_COPYING),
    ],
)
def test_illegal_transition_raises_and_preserves_state(
    source: BackupState, target: BackupState
) -> None:
    machine = JobStateMachine(initial=source)
    with pytest.raises(InvalidTransition):
        machine.transition(target)
    assert machine.state is source


def test_rejected_transition_does_not_fire_hook() -> None:
    calls: list[tuple[BackupState, BackupState]] = []
    machine = JobStateMachine(
        initial=BackupState.IDLE,
        on_transition=lambda s, t: calls.append((s, t)),
    )
    with pytest.raises(InvalidTransition):
        machine.transition(BackupState.BACKUP_COMPLETED)
    assert calls == []


def test_accepted_transition_fires_hook_once() -> None:
    calls: list[tuple[BackupState, BackupState]] = []
    machine = JobStateMachine(
        initial=BackupState.IDLE,
        on_transition=lambda s, t: calls.append((s, t)),
    )
    machine.transition(BackupState.SOURCE_DETECTED)
    assert calls == [(BackupState.IDLE, BackupState.SOURCE_DETECTED)]


@pytest.mark.parametrize(
    ("source", "target"),
    [
        # v0.3-added states must be wired in (UT-006).
        (BackupState.IDLE, BackupState.MULTIPLE_SOURCES_DETECTED),
        (BackupState.SOURCE_MOUNTING, BackupState.SOURCE_PROTECTION_FAILURE),
        (BackupState.BACKUP_CANCELLING, BackupState.BACKUP_CANCELLED),
        (BackupState.RECOVERY_REQUIRED, BackupState.RECOVERING),
        (BackupState.BACKUP_COMPLETED, BackupState.SOURCE_SAFE_TO_REMOVE),
    ],
)
def test_v03_states_are_reachable(source: BackupState, target: BackupState) -> None:
    assert can_transition(source, target)


def test_happy_path_full_backup_sequence() -> None:
    """A nominal successful backup walks end to end without an illegal move."""
    machine = JobStateMachine(initial=BackupState.IDLE)
    path = [
        BackupState.SOURCE_DETECTED,
        BackupState.SOURCE_MOUNTING,
        BackupState.SOURCE_READY,
        BackupState.PREFLIGHT_SCANNING,
        BackupState.PREFLIGHT_HASHING,
        BackupState.PREFLIGHT_COMPARING,
        BackupState.PREFLIGHT_CAPACITY_CHECK,
        BackupState.PREFLIGHT_READY,
        BackupState.BACKUP_QUEUED,
        BackupState.BACKUP_COPYING,
        BackupState.BACKUP_VERIFYING,
        BackupState.BACKUP_COMPLETED,
        BackupState.SOURCE_SAFE_TO_REMOVE,
        BackupState.IDLE,
    ]
    for target in path:
        machine.transition(target)
    assert machine.state is BackupState.IDLE


def test_backup_failed_is_recoverable() -> None:
    """A failed job can retry, reconcile, or be abandoned cleanly (Impl §7)."""
    assert allowed_targets(BackupState.BACKUP_FAILED) == frozenset(
        {
            BackupState.PREFLIGHT_SCANNING,
            BackupState.RECOVERY_REQUIRED,
            BackupState.SOURCE_SAFE_TO_REMOVE,
        }
    )
