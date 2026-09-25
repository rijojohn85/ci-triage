"""Story 1.2 unit tests — leases and fencing (AC1/AC2/AC3, AD-23).

The Postgres boundary is driven through a small Protocol fake (AGENTS.md
"TDD": I/O boundaries tested against Protocol fakes in unit tests; the real
adapter runs in the marked integration tests). No test sleeps: every clock
value is injected.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from workflow.lease_store import PostgresRunLeaseStore
from workflow.leases import (
    CLAIMABLE_RUN_STATES,
    Claim,
    LeaseLost,
    lease_expired,
    new_lease_owner,
    renew_due,
)
from workflow.run_states import TERMINAL_RUN_STATES, RunState

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
LEASE_SECONDS = 300


class FakeTransaction:
    """Records commit/rollback so the short-transaction rule is observable."""

    def __init__(self, connection: "FakeConnection") -> None:
        self._connection = connection

    def __enter__(self) -> "FakeTransaction":
        self._connection.events.append("begin")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> bool:
        self._connection.events.append("rollback" if exc_type else "commit")
        return False


class FakeCursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class FakeConnection:
    """One scripted result per execute; records events and bound parameters."""

    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self.row = row
        self.events: list[str] = []
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> bool:
        return False

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    def execute(
        self, sql: str, params: tuple[object, ...] = ()
    ) -> FakeCursor:
        self.calls.append((sql, params))
        return FakeCursor(self.row)


def store_against(connection: FakeConnection) -> PostgresRunLeaseStore:
    return PostgresRunLeaseStore("postgresql://unused", connect=lambda _dsn: connection)


def bound_list(params: tuple[object, ...]) -> list[object]:
    return next(value for value in params if isinstance(value, list))


class TestClaim:
    def test_ac1_claim_sets_owner_and_expiry_and_returns_claim(self) -> None:
        run_id = uuid.uuid4()
        connection = FakeConnection(row=(run_id,))

        claim = store_against(connection).claim_next(
            now=NOW, lease_seconds=LEASE_SECONDS
        )

        assert claim is not None
        assert claim.run_id == run_id
        assert claim.owner
        assert claim.lease_until == NOW + timedelta(seconds=LEASE_SECONDS)
        assert connection.events == ["begin", "commit"]
        _, params = connection.calls[0]
        assert claim.owner in params
        assert claim.lease_until in params

    def test_ac1_claim_uses_skip_locked_and_short_transaction(self) -> None:
        connection = FakeConnection(row=(uuid.uuid4(),))

        store_against(connection).claim_next(now=NOW, lease_seconds=LEASE_SECONDS)

        sql, _ = connection.calls[0]
        assert "FOR UPDATE SKIP LOCKED" in sql
        assert len(connection.calls) == 1, "one short transaction, no extra round trips"
        assert connection.events == ["begin", "commit"], "commit before any external call"

    def test_ac1_leased_row_skipped_until_expiry(self) -> None:
        # No unleased/expired row: the claim finds nothing and writes nothing.
        connection = FakeConnection(row=None)

        claim = store_against(connection).claim_next(
            now=NOW, lease_seconds=LEASE_SECONDS
        )

        assert claim is None
        sql, _ = connection.calls[0]
        assert "lease_until IS NULL OR lease_until <=" in sql

    def test_ac1_terminal_run_not_claimable(self) -> None:
        # The ten AD-1 non-terminal states, written out so a bad derivation
        # fails here instead of restating the production expression.
        assert CLAIMABLE_RUN_STATES == frozenset(
            {
                RunState.RECEIVED,
                RunState.DISTILLING,
                RunState.CLASSIFYING,
                RunState.ANALYZING,
                RunState.PROPOSING,
                RunState.REVIEWING,
                RunState.GATING,
                RunState.AWAITING_APPROVAL,
                RunState.PR_OPENING,
                RunState.REPORTING,
            }
        )
        for terminal in TERMINAL_RUN_STATES:
            assert terminal not in CLAIMABLE_RUN_STATES

        connection = FakeConnection(row=None)
        store_against(connection).claim_next(now=NOW, lease_seconds=LEASE_SECONDS)
        bound = bound_list(connection.calls[0][1])
        assert set(bound) == {state.value for state in CLAIMABLE_RUN_STATES}

    def test_new_lease_owner_is_unique_per_claim(self) -> None:
        assert new_lease_owner() != new_lease_owner()

    def test_new_lease_owner_names_the_configured_worker(self) -> None:
        owner = new_lease_owner(env={"WORKER_ID": "worker-7"})
        assert owner.startswith("worker-7:")  # identity from config (AD-19)
        assert owner != new_lease_owner(env={"WORKER_ID": "worker-7"})


class TestRenew:
    def test_ac2_renew_extends_expiry_for_owner_only(self) -> None:
        run_id = uuid.uuid4()
        connection = FakeConnection(row=(run_id,))
        claim = Claim(run_id, "owner-a", NOW + timedelta(seconds=LEASE_SECONDS))

        extended = store_against(connection).renew(
            claim, now=NOW, lease_seconds=600
        )

        assert extended is True
        sql, params = connection.calls[0]
        assert "lease_owner = " in sql, "only the current owner may extend"
        assert "lease_until > " in sql, "an expired lease is not renewable"
        assert NOW + timedelta(seconds=600) in params

    def test_ac2_renew_rejected_for_non_owner(self) -> None:
        connection = FakeConnection(row=None)  # UPDATE matched no row
        claim = Claim(uuid.uuid4(), "owner-a", NOW + timedelta(seconds=LEASE_SECONDS))

        assert store_against(connection).renew(
            claim, now=NOW, lease_seconds=600
        ) is False

    def test_ac2_lease_expired_and_renew_due_helpers(self) -> None:
        future = NOW + timedelta(seconds=60)
        past = NOW - timedelta(seconds=60)

        assert lease_expired(None, NOW) is True, "no lease means claimable"
        assert lease_expired(past, NOW) is True
        assert lease_expired(future, NOW) is False

        assert renew_due(future, NOW, renew_after_seconds=120) is True
        assert renew_due(NOW + timedelta(seconds=300), NOW, 120) is False
        assert renew_due(None, NOW, 120) is False, "absent lease is not renewable"
        assert renew_due(past, NOW, 120) is False, "an expired lease is already lost"


class TestGuardedCommit:
    def test_ac3_guarded_commit_rejects_owner_mismatch(self) -> None:
        claim = Claim(uuid.uuid4(), "owner-a", NOW + timedelta(seconds=LEASE_SECONDS))
        connection = FakeConnection(row=("owner-b",))  # the row now belongs to B
        touched: list[object] = []

        with pytest.raises(LeaseLost):
            store_against(connection).guarded_commit(
                claim, lambda conn: touched.append(conn)
            )

        assert touched == [], "stale work must never run"
        assert connection.events == ["begin", "rollback"], "discard rolls back"

    def test_ac3_guarded_commit_by_owner_commits_work_atomically(self) -> None:
        run_id = uuid.uuid4()
        claim = Claim(run_id, "owner-a", NOW + timedelta(seconds=LEASE_SECONDS))
        connection = FakeConnection(row=("owner-a",))

        def work(conn: object) -> str:
            conn.execute(  # type: ignore[attr-defined]
                "UPDATE triage_run SET state = %s WHERE run_id = %s",
                ("DISTILLING", run_id),
            )
            return "committed"

        result = store_against(connection).guarded_commit(claim, work)

        assert result == "committed"
        assert connection.events == ["begin", "commit"]
        assert connection.calls[0][0].startswith("SELECT lease_owner")
        assert "FOR UPDATE" in connection.calls[0][0]
        assert connection.calls[1][0].startswith("UPDATE")

    def test_ac3_lease_lost_is_definitive_not_retryable(self) -> None:
        assert LeaseLost(uuid.uuid4(), "owner").retryable is False  # AD-22
