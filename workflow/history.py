"""History domain types: the AC1 fingerprint rule and the AC2 terminal-state
guard, decoupled from SQL (story 2.6, AD-15).

SOLID-S: this module builds no SQL and does no I/O; `workflow/history_store.py`
is the one Postgres adapter. `normalize_fingerprint` is a pure function so the
AC1 rule ("fingerprint is the sha256 of the normalized fields") is testable
without a database. `HistoryEntry` is the internal, full-row type — it is
never transmitted to an agent (`contracts/evidence.py::HistoryRow` is the
agent-facing shape, AD-6 does not bind this one). `ImportRecord` accepts only
enumerated/structured fields; a free-text key such as `notes` is not a field
of this dataclass, so passing it raises `TypeError` before any row is built.
"""

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from workflow.run_states import RunState

__all__ = [
    "HistoryEntry",
    "HistoryRepoMismatchError",
    "HistoryRowVanishedError",
    "HumanVerdict",
    "ImportRecord",
    "NonTerminalWriteError",
    "TerminalWrite",
    "normalize_fingerprint",
]

_FIELD_SEPARATOR = "\x1f"


def normalize_fingerprint(
    test_id: str, error_type: str, top_stack_frames: Sequence[str]
) -> str:
    """sha256 hex of the stripped fields joined by `\\x1f` (AC1).

    Pure, no I/O: `HistoryStore.write_terminal`/`import_seed`/`lookup` all
    call this same function so the fingerprint is computed identically on
    every path.
    """
    fields = [
        test_id.strip(),
        error_type.strip(),
        *(frame.strip() for frame in top_stack_frames),
    ]
    joined = _FIELD_SEPARATOR.join(fields)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


class HumanVerdict(str, Enum):
    """A human's post-hoc read of a terminal run's outcome."""

    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class HistoryEntry:
    """One persisted `history` row: the internal, full-row type (AD-15).

    Distinct from `contracts.evidence.HistoryRow` (the agent-facing subset);
    this type is never transmitted to an agent.
    """

    row_id: uuid.UUID
    run_id: uuid.UUID
    repo_id: int
    test_id: str
    error_type: str
    top_stack_frames: tuple[str, ...]
    fingerprint: str
    terminal_state: RunState
    human_verdict: HumanVerdict | None
    created_at: datetime


@dataclass(frozen=True)
class ImportRecord:
    """One seed row for `history_import` (AC3): enumerated fields only.

    A free-text key (e.g. `notes`) is not a field here, so constructing this
    with an unexpected keyword raises `TypeError` before any row is written.
    """

    repo_id: int
    test_id: str
    error_type: str
    top_stack_frames: tuple[str, ...]
    terminal_state: RunState
    human_verdict: HumanVerdict | None = None


@dataclass(frozen=True)
class TerminalWrite:
    """The terminal history write to persist (AC1/AC2): a small model instead
    of a long parameter list (AGENTS.md clean code, max 5 parameters)."""

    run_id: uuid.UUID
    repo_id: int
    test_id: str
    error_type: str
    top_stack_frames: tuple[str, ...]
    to_state: RunState
    human_verdict: HumanVerdict | None = None


class NonTerminalWriteError(Exception):
    """`write_terminal` was asked to write a non-terminal `RunState` (AC2).

    Definitive, never retryable (AD-22): writing terminal history for a
    non-terminal run is a caller bug, not a transient fault. Raised before
    any I/O.
    """

    retryable: bool = False

    def __init__(self, run_id: uuid.UUID | None, to_state: RunState) -> None:
        # `run_id` is None for an `import_seed` record: seed rows have no
        # run_id yet when the terminal-state check runs, before any is
        # generated (AC1/AC3 -- rejected before any I/O).
        target = f"run {run_id}" if run_id is not None else "a seed import record"
        super().__init__(
            f"write_terminal refused: {to_state.value!r} is not a terminal "
            f"state for {target}"
        )
        self.run_id = run_id
        self.to_state = to_state


class HistoryRowVanishedError(Exception):
    """The row a `UniqueViolation` implied must exist was not found on re-select.

    Definitive, never retryable (AD-22): the database's own unique
    constraint already proved the row exists, so a missing re-select is a
    data-integrity fault, never a transient condition.
    """

    retryable: bool = False

    def __init__(self, run_id: uuid.UUID) -> None:
        super().__init__(f"history row for run {run_id} vanished after UniqueViolation")
        self.run_id = run_id


class HistoryRepoMismatchError(Exception):
    """`write_terminal` retried for `run_id` with a different `repo_id`.

    Definitive, never retryable (AD-22): a `history` row's `repo_id` is fixed
    at first write (AD-15 tenant scope); a caller supplying a different one
    on retry is a bug, never a transient fault.
    """

    retryable: bool = False

    def __init__(
        self, run_id: uuid.UUID, expected_repo_id: int, actual_repo_id: int
    ) -> None:
        super().__init__(
            f"history row for run {run_id} belongs to repo {actual_repo_id}, "
            f"not {expected_repo_id}"
        )
        self.run_id = run_id
        self.expected_repo_id = expected_repo_id
        self.actual_repo_id = actual_repo_id
