"""Postgres adapter for worker leases (AD-23): the only place lease SQL lives.

SOLID-S: the policy is in `workflow/leases.py`; this module builds the SQL and
owns the psycopg connection. `PostgresRunLeaseStore` structurally implements
the `RunLeaseStore` protocol, and its `connect` is injectable so the SQL
contract is unit-tested against a Protocol fake (the real Postgres path runs
in the marked integration tests).
"""

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TypeVar

import psycopg

from workflow.leases import (
    CLAIMABLE_RUN_STATES,
    Claim,
    LeaseConnection,
    LeaseLost,
    new_lease_owner,
)

__all__ = ["PostgresRunLeaseStore"]

_CLAIM_SQL = """
UPDATE triage_run
SET lease_owner = %s, lease_until = %s, updated_at = now()
WHERE run_id = (
    SELECT run_id
    FROM triage_run
    WHERE state = ANY(%s)
      AND (lease_until IS NULL OR lease_until <= %s)
    ORDER BY run_id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING run_id
"""

_RENEW_SQL = """
UPDATE triage_run
SET lease_until = %s, updated_at = now()
WHERE run_id = %s AND lease_owner = %s AND lease_until > %s
RETURNING run_id
"""

_LOCK_OWNER_SQL = "SELECT lease_owner FROM triage_run WHERE run_id = %s FOR UPDATE"

T = TypeVar("T")


def _as_uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _open_connection(dsn: str) -> LeaseConnection:
    return psycopg.connect(dsn)


class PostgresRunLeaseStore:
    """I/O adapter; one short connection per call keeps it thread-safe."""

    def __init__(
        self, dsn: str, connect: Callable[[str], LeaseConnection] | None = None
    ) -> None:
        self._dsn = dsn
        self._connect: Callable[[str], LeaseConnection] = connect or _open_connection

    def claim_next(self, *, now: datetime, lease_seconds: int) -> Claim | None:
        owner = new_lease_owner()
        lease_until = now + timedelta(seconds=lease_seconds)
        with self._connect(self._dsn) as conn, conn.transaction():
            row = conn.execute(
                _CLAIM_SQL,
                (
                    owner,
                    lease_until,
                    [state.value for state in CLAIMABLE_RUN_STATES],
                    now,
                ),
            ).fetchone()
        if row is None:
            return None
        return Claim(_as_uuid(row[0]), owner, lease_until)

    def renew(self, claim: Claim, *, now: datetime, lease_seconds: int) -> bool:
        lease_until = now + timedelta(seconds=lease_seconds)
        with self._connect(self._dsn) as conn, conn.transaction():
            row = conn.execute(
                _RENEW_SQL, (lease_until, claim.run_id, claim.owner, now)
            ).fetchone()
        return row is not None

    def guarded_commit(self, claim: Claim, work: Callable[[LeaseConnection], T]) -> T:
        # The owner re-check and the work commit in one transaction: a
        # mismatch rolls the work back with it (AD-2, AD-23).
        with self._connect(self._dsn) as conn, conn.transaction():
            row = conn.execute(_LOCK_OWNER_SQL, (claim.run_id,)).fetchone()
            if row is None or row[0] != claim.owner:
                raise LeaseLost(claim.run_id, claim.owner)
            return work(conn)
