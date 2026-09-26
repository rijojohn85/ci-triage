"""The one Postgres adapter for `history` (story 2.6, AC1/AC2/AC3, AD-15).

SOLID-S: the domain words live in `workflow/history.py`; this module builds
the SQL. The connection Protocol + opener are shared with
`workflow/pr_feedback_store.py` via `workflow/db.py` (DRY). No lease/`Claim`
is needed here (see the spec's Design Notes): `CLAIMABLE_RUN_STATES` already
excludes `TERMINAL_RUN_STATES`, so a terminal write has no competing writer
to guard against — the `uq_history_run_id` unique constraint alone gives
AC2's idempotency. `connect` is injectable so unit tests drive the SQL
through a fake connection; the real adapter runs in the marked integration
tests.

Every `history` query binds `repo_id` (AD-15), except the one internal
re-select after a caught `UniqueViolation`: it must find the row by
`run_id` alone so a `repo_id` mismatch between the retry and the original
write can be detected and raised, rather than silently reading nothing.
"""

import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Protocol, cast

import psycopg

from workflow.db import Connection, open_connection
from workflow.history import (
    HistoryEntry,
    HistoryRepoMismatchError,
    HistoryRowVanishedError,
    HumanVerdict,
    ImportRecord,
    NonTerminalWriteError,
    TerminalWrite,
    normalize_fingerprint,
)
from workflow.ids import new_run_id
from workflow.run_states import TERMINAL_RUN_STATES, RunState

__all__ = ["HistoryStore", "PostgresHistoryStore"]

_INSERT_SQL = """
INSERT INTO history (
    row_id, run_id, repo_id, test_id, error_type, top_stack_frames,
    fingerprint, terminal_state, human_verdict
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING row_id, created_at
"""

# Deliberately not repo-scoped: this is the post-UniqueViolation recovery
# read, which must find the row by run_id alone so a repo_id mismatch is
# detected and raised (HistoryRepoMismatchError), not silently missed.
_SELECT_BY_RUN_ID_SQL = """
SELECT row_id, run_id, repo_id, test_id, error_type, top_stack_frames,
       fingerprint, terminal_state, human_verdict, created_at
FROM history
WHERE run_id = %s
"""

_LOOKUP_SQL = """
SELECT row_id, run_id, repo_id, test_id, error_type, top_stack_frames,
       fingerprint, terminal_state, human_verdict, created_at
FROM history
WHERE repo_id = %s AND fingerprint = %s
"""


def _entry_from_row(row: tuple[object, ...]) -> HistoryEntry:
    return HistoryEntry(
        row_id=cast(uuid.UUID, row[0]),
        run_id=cast(uuid.UUID, row[1]),
        repo_id=cast(int, row[2]),
        test_id=str(row[3]),
        error_type=str(row[4]),
        top_stack_frames=tuple(row[5]),  # type: ignore[arg-type]
        fingerprint=str(row[6]),
        terminal_state=RunState(str(row[7])),
        human_verdict=HumanVerdict(str(row[8])) if row[8] is not None else None,
        created_at=cast(datetime, row[9]),
    )


class HistoryStore(Protocol):
    """The persistence surface the orchestrator's finalize path consumes."""

    def write_terminal(self, write: TerminalWrite) -> HistoryEntry: ...

    def import_seed(self, records: Sequence[ImportRecord]) -> list[uuid.UUID]: ...

    def lookup(self, repo_id: int, fingerprint: str) -> list[HistoryEntry]: ...


class PostgresHistoryStore:
    """I/O adapter: exactly-once terminal write, seed import, repo-scoped lookup."""

    def __init__(
        self,
        dsn: str,
        connect: Callable[[str], Connection] | None = None,
    ) -> None:
        self._dsn = dsn
        self._connect: Callable[[str], Connection] = connect or open_connection

    def write_terminal(self, write: TerminalWrite) -> HistoryEntry:
        if write.to_state not in TERMINAL_RUN_STATES:
            # AC2: refused before any I/O — a non-terminal write is a caller
            # bug, not a transient fault (AD-22).
            raise NonTerminalWriteError(write.run_id, write.to_state)

        frames = tuple(write.top_stack_frames)
        fingerprint = normalize_fingerprint(write.test_id, write.error_type, frames)
        row_id = new_run_id()
        verdict = write.human_verdict

        with self._connect(self._dsn) as conn:
            try:
                inserted = conn.execute(
                    _INSERT_SQL,
                    (
                        row_id,
                        write.run_id,
                        write.repo_id,
                        write.test_id,
                        write.error_type,
                        list(frames),
                        fingerprint,
                        write.to_state.value,
                        verdict.value if verdict is not None else None,
                    ),
                ).fetchone()
            except psycopg.errors.UniqueViolation:
                # A duplicate write_terminal for the same run_id is a no-op:
                # return the existing row, never raise (AC2, AD-2 spirit).
                inserted = None
            if inserted is not None:
                return HistoryEntry(
                    row_id=row_id,
                    run_id=write.run_id,
                    repo_id=write.repo_id,
                    test_id=write.test_id,
                    error_type=write.error_type,
                    top_stack_frames=frames,
                    fingerprint=fingerprint,
                    terminal_state=write.to_state,
                    human_verdict=verdict,
                    created_at=cast(datetime, inserted[1]),
                )
            existing = conn.execute(_SELECT_BY_RUN_ID_SQL, (write.run_id,)).fetchone()
            if existing is None:
                raise HistoryRowVanishedError(write.run_id)
            entry = _entry_from_row(existing)
            if entry.repo_id != write.repo_id:
                # AD-15: the row's tenant is fixed at first write; a retry
                # under a different repo_id is a caller bug, never silently
                # ignored.
                raise HistoryRepoMismatchError(
                    write.run_id, write.repo_id, entry.repo_id
                )
            return entry

    def import_seed(self, records: Sequence[ImportRecord]) -> list[uuid.UUID]:
        for record in records:
            if record.terminal_state not in TERMINAL_RUN_STATES:
                # AC1/AC3: refused before any I/O, same guard as
                # write_terminal — a seed row has no run_id yet.
                raise NonTerminalWriteError(None, record.terminal_state)

        row_ids: list[uuid.UUID] = []
        with self._connect(self._dsn) as conn, conn.transaction():
            for record in records:
                # Seed history has no real triage_run behind it; a fresh
                # run_id keeps the column NOT NULL and uniform for both
                # writers (see the spec's Design Notes).
                run_id = new_run_id()
                row_id = new_run_id()
                fingerprint = normalize_fingerprint(
                    record.test_id, record.error_type, record.top_stack_frames
                )
                conn.execute(
                    _INSERT_SQL,
                    (
                        row_id,
                        run_id,
                        record.repo_id,
                        record.test_id,
                        record.error_type,
                        list(record.top_stack_frames),
                        fingerprint,
                        record.terminal_state.value,
                        record.human_verdict.value
                        if record.human_verdict is not None
                        else None,
                    ),
                )
                row_ids.append(row_id)
        return row_ids

    def lookup(self, repo_id: int, fingerprint: str) -> list[HistoryEntry]:
        with self._connect(self._dsn) as conn:
            rows = conn.execute(_LOOKUP_SQL, (repo_id, fingerprint)).fetchall()
        return [_entry_from_row(row) for row in rows]
