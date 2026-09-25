"""Step domain types and the resume view: the AD-2 vocabulary (no SQL).

One `run_step` records what a step produced; the same lease-guarded
transaction (story 1.2's `RunLeaseStore.guarded_commit`) moves
`triage_run.state`. If the lease changed owner, or the move is not in story
2.1's transition table, nothing is written (AD-23, AD-1). Resume reads the
current state and the names of completed steps so a reclaimed worker skips
finished work instead of paying for it twice (AD-2).

SOLID-S: the domain lives here and builds no SQL. `StepRecorder` is the small
interface a worker loop consumes (SOLID-I); the Postgres implementation is
`workflow/step_store.py`. Retries (2.8), audit/cost (6.1/6.2) and evidence
packs (2.7) live elsewhere. No model/token/cost fields here (AD-18). Every
persisted query binds `repo_id` (AD-15).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol

from workflow.leases import Claim
from workflow.run_states import RunState
from workflow.transitions import GuardInput

__all__ = [
    "ResumeView",
    "StepCommit",
    "StepRecord",
    "StepRecorder",
    "StepStatus",
]


class StepStatus(str, Enum):
    """`run_step.status`: a finished step, or a failed attempt of its own.

    Mirrors the migration's CHECK list exactly. A failed attempt is a step,
    never a silent skip (AD-22).
    """

    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class StepRecord:
    """One persisted `run_step` row (AD-2). `output` is JSON-serializable."""

    step_id: uuid.UUID
    run_id: uuid.UUID
    repo_id: int
    step: str
    attempt: int
    status: StepStatus
    output: object
    created_at: datetime


@dataclass(frozen=True)
class StepCommit:
    """The step outcome to persist together with its run-state move (AD-2).

    A small model instead of a long parameter list (AGENTS.md clean code):
    `step` + `to_state` are required; a first completed attempt with no output
    is the common case.
    """

    step: str
    to_state: RunState
    attempt: int = 1
    status: StepStatus = StepStatus.COMPLETED
    output: object = None
    guards: GuardInput = field(default_factory=GuardInput)


@dataclass(frozen=True)
class ResumeView:
    """What a reclaiming worker needs: the current state and finished steps."""

    state: RunState
    completed_steps: frozenset[str]

    def is_completed(self, step: str) -> bool:
        """True when `step` already ran and must not run again (AD-2)."""
        return step in self.completed_steps


class StepRecorder(Protocol):
    """The persistence surface a worker loop consumes (AD-2)."""

    def record(self, claim: Claim, repo_id: int, commit: StepCommit) -> StepRecord: ...

    def resume(self, run_id: uuid.UUID, repo_id: int) -> ResumeView | None: ...
