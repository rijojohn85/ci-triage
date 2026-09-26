"""Shared minimal Postgres connection Protocol + opener (SOLID-I, DRY).

Extracted on the third near-identical occurrence of this connection shape in
`workflow/` (after `step_store.py`'s `StepConnection` and, before this
module existed, `history_store.py`'s `HistoryConnection` and
`pr_feedback_store.py`'s `PRFeedbackConnection`): AGENTS.md DRY "extract on
the third". `history_store.py` and `pr_feedback_store.py` both use this one
Protocol + opener; `step_store.py` is untouched (its lease-guarded commit is
a different, larger surface — out of scope for this extraction).
"""

from types import TracebackType
from typing import Protocol

import psycopg

__all__ = ["Connection", "Cursor", "Transaction", "open_connection"]


class Cursor(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...
    def fetchall(self) -> list[tuple[object, ...]]: ...


class Transaction(Protocol):
    """An explicit transaction block, for a caller that needs one batch to
    commit or roll back atomically (e.g. `HistoryStore.import_seed`)."""

    def __enter__(self) -> object: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> object: ...


class Connection(Protocol):
    """Smallest connection surface the history/pr_feedback adapters need."""

    def __enter__(self) -> "Connection": ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> object: ...
    def execute(self, sql: str, params: tuple[object, ...] = ()) -> Cursor: ...
    def transaction(self) -> Transaction: ...


def open_connection(dsn: str) -> Connection:
    # autocommit: a single statement here is already atomic on its own, a
    # caught UniqueViolation must not abort the connection before a
    # re-select, and an explicit conn.transaction() block still gives a real
    # all-or-nothing transaction where a caller needs one (import_seed).
    return psycopg.connect(dsn, autocommit=True)
