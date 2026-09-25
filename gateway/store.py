"""Intake persistence: delivery dedupe + idempotent run insert (AD-17).

`IntakeStore` is the small Protocol the app depends on (SOLID-I); the
Postgres adapter runs one transaction — the delivery row first (a replay
is a no-op), then the `triage_run(RECEIVED)` insert keyed on the unique
run identity. The gateway writes no other state.
"""

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

import psycopg

from gateway.events import RunIdentity
from workflow.run_states import RunState

__all__ = ["IntakeOutcome", "IntakeResult", "IntakeStore", "PostgresIntakeStore"]

_INSERT_DELIVERY_SQL = """
INSERT INTO webhook_delivery (delivery_id, repo_id, workflow_run_id, run_attempt)
VALUES (%s, %s, %s, %s)
ON CONFLICT (delivery_id) DO NOTHING
RETURNING delivery_id
"""
_INSERT_RUN_SQL = """
INSERT INTO triage_run (run_id, repo_id, workflow_run_id, run_attempt, state)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (repo_id, workflow_run_id, run_attempt) DO NOTHING
RETURNING run_id
"""
_QUEUE_DEPTH_SQL = "SELECT count(*) FROM triage_run WHERE repo_id = %s AND state = %s"
_SELECT_RUN_ID_SQL = """
SELECT run_id FROM triage_run
WHERE repo_id = %s AND workflow_run_id = %s AND run_attempt = %s
"""


class IntakeOutcome(str, Enum):
    """What the enqueue did: first accept, replay, or duplicate identity."""

    ENQUEUED = "enqueued"
    DELIVERY_REPLAY = "delivery_replay"
    RUN_DUPLICATE = "run_duplicate"


@dataclass(frozen=True)
class IntakeResult:
    outcome: IntakeOutcome
    run_id: uuid.UUID | None = None


class IntakeStore(Protocol):
    """The app's whole persistence surface (no god-repository)."""

    def queue_depth(self, repo_id: int) -> int: ...

    def record_and_enqueue(
        self, delivery_id: str, identity: RunIdentity, run_id: uuid.UUID
    ) -> IntakeResult: ...


class PostgresIntakeStore:
    """I/O adapter; one connection per call keeps it safe under threads."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def queue_depth(self, repo_id: int) -> int:
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cursor:
            cursor.execute(_QUEUE_DEPTH_SQL, (repo_id, RunState.RECEIVED.value))
            row = cursor.fetchone()
        return int(row[0]) if row is not None else 0

    def record_and_enqueue(
        self, delivery_id: str, identity: RunIdentity, run_id: uuid.UUID
    ) -> IntakeResult:
        with psycopg.connect(self._dsn) as conn, conn.transaction():
            delivery = conn.execute(
                _INSERT_DELIVERY_SQL,
                (
                    delivery_id,
                    identity.repo_id,
                    identity.workflow_run_id,
                    identity.run_attempt,
                ),
            ).fetchone()
            if delivery is None:
                return IntakeResult(
                    IntakeOutcome.DELIVERY_REPLAY,
                    _existing_run_id(conn, identity),
                )
            inserted = conn.execute(
                _INSERT_RUN_SQL,
                (
                    run_id,
                    identity.repo_id,
                    identity.workflow_run_id,
                    identity.run_attempt,
                    RunState.RECEIVED.value,
                ),
            ).fetchone()
            if inserted is None:
                return IntakeResult(
                    IntakeOutcome.RUN_DUPLICATE,
                    _existing_run_id(conn, identity),
                )
            return IntakeResult(IntakeOutcome.ENQUEUED, run_id)


def _existing_run_id(
    conn: "psycopg.Connection[psycopg.rows.TupleRow]",
    identity: RunIdentity,
) -> uuid.UUID | None:
    row = conn.execute(
        _SELECT_RUN_ID_SQL,
        (identity.repo_id, identity.workflow_run_id, identity.run_attempt),
    ).fetchone()
    if row is None:
        return None
    value = row[0]
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
