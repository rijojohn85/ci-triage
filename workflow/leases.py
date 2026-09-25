"""Worker leases and fencing: the pure AD-23 policy (no SQL, no psycopg).

Domain decision logic only (SOLID-S: persistence lives in
`workflow/lease_store.py`): the claimable-state set, the expiry predicates,
the owner token and the small interfaces a worker loop depends on.

The three rules this encodes:

- **Claim** takes a non-terminal run whose lease is absent or expired and
  stamps a new owner and expiry; the SQL that does it lives in the adapter.
- **Renew** extends only the current owner's live lease; a non-owner or an
  already-expired lease is refused definitively (AD-22), never a transient
  retry.
- **Guarded commit** re-checks `lease_owner` under a lock in the one
  transaction that writes a step's output and its state transition; on a
  mismatch it rolls back and raises `LeaseLost` (AD-2, AD-23).

`RunLeaseStore` is the small per-consumer Protocol (AGENTS.md; SOLID-I): unit
tests fake it, the Postgres adapter is the only implementation. Claimable
states derive from `TERMINAL_RUN_STATES` minus the human-wait states, never a
hand-listed set (SOLID-O). Timings come from `config/orchestrator.yaml`
(AD-19); `now` is injected so no test sleeps.
"""

import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol, TypeVar

from workflow.run_states import RUN_STATES, TERMINAL_RUN_STATES, RunState

__all__ = [
    "CLAIMABLE_RUN_STATES",
    "HUMAN_WAIT_STATES",
    "Claim",
    "LeaseConnection",
    "LeaseLost",
    "RunLeaseStore",
    "lease_expired",
    "new_lease_owner",
    "renew_due",
]

_WORKER_ID_ENV = "WORKER_ID"

# AD-1 (spine line 438): a run waits in AWAITING_APPROVAL indefinitely for a
# human; there is no worker work to do while it is paused, so a worker must not
# claim it. The approval handler moves it out through a guarded transition
# (AD-4/AD-14); once it leaves this state it becomes claimable again.
HUMAN_WAIT_STATES: frozenset[RunState] = frozenset({RunState.AWAITING_APPROVAL})

# SOLID-O: the claimable set is *derived* from the state machine. A future
# state change (or terminal addition) flows through with no edit here; a paused
# run is not claimable (see `HUMAN_WAIT_STATES`), so N workers never spin on
# runs that are waiting on a person.
CLAIMABLE_RUN_STATES: frozenset[RunState] = (
    frozenset(RUN_STATES) - TERMINAL_RUN_STATES - HUMAN_WAIT_STATES
)

T = TypeVar("T")


class LeaseLost(Exception):  # noqa: N818 — spine AD-23 names the domain error
    """The caller is no longer the run's lease owner.

    Definitive, never retryable (AD-22): the work was claimed by another
    worker, so re-running it would duplicate or corrupt the run.
    """

    retryable: bool = False

    def __init__(self, run_id: uuid.UUID, owner: str) -> None:
        super().__init__(
            f"lease lost for run {run_id}: owner {owner!r} is no longer current"
        )
        self.run_id = run_id
        self.owner = owner


@dataclass(frozen=True)
class Claim:
    """A worker's right to run one `triage_run` until `lease_until`."""

    run_id: uuid.UUID
    owner: str
    lease_until: datetime


class LeaseCursor(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...


class LeaseTransaction(Protocol):
    """The transaction context a lease connection opens (mirrors psycopg)."""

    def __enter__(self) -> object: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> object: ...


class LeaseConnection(Protocol):
    """Smallest connection surface the lease adapter needs (SOLID-I)."""

    def __enter__(self) -> "LeaseConnection": ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> object: ...
    def transaction(self) -> LeaseTransaction: ...
    def execute(self, sql: str, params: tuple[object, ...] = ()) -> LeaseCursor: ...


class RunLeaseStore(Protocol):
    """The whole persistence surface a worker loop needs (AD-23).

    Lease validity is the database's decision, so no clock is passed in: the
    adapter anchors and compares `lease_until` with the database's `now()`, and
    `lease_seconds` is the only timing input (from config).
    """

    def claim_next(self, *, lease_seconds: int) -> Claim | None: ...

    def renew(self, claim: Claim, *, lease_seconds: int) -> bool: ...

    def guarded_commit(
        self, claim: Claim, work: Callable[[LeaseConnection], T]
    ) -> T: ...


def new_lease_owner(env: Mapping[str, str] | None = None) -> str:
    """One factory for a lease owner token (DRY; AD-19, AD-23).

    The configured `WORKER_ID` (env/config, never a literal in code) names the
    worker; a random token makes each claim unique, so a restarted worker can
    never be mistaken for its predecessor.
    """
    source = os.environ if env is None else env
    worker = source.get(_WORKER_ID_ENV, "").strip()
    token = uuid.uuid4().hex
    return f"{worker}:{token}" if worker else token


def lease_expired(lease_until: datetime | None, now: datetime) -> bool:
    """True when a row has no lease or its lease is over (so it is claimable)."""
    return lease_until is None or lease_until <= now


def renew_due(
    lease_until: datetime | None, now: datetime, renew_after_seconds: int
) -> bool:
    """True when a live lease is close enough to expiry that a long step must
    renew it. An absent or already-expired lease is not renewable (AD-22)."""
    if lease_until is None:
        return False
    return (
        lease_until > now and (lease_until - now).total_seconds() <= renew_after_seconds
    )
