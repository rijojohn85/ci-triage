"""Story 1.2 integration tests — real postgres:18 via Docker (AC1/AC2/AC3).

Proves the lease rules against the real database: N workers claim distinct
rows at most once, an expired lease is reclaimable, and a stale owner's
guarded commit is discarded while the new owner can progress. Time is
DB-seeded, never a real sleep.

Needs Docker on the host; marked `integration` and excluded from `make
check` (pyproject addopts). Run explicitly:

    .venv/bin/pytest -m integration tests/workflow/test_lease_integration.py -q
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone
from itertools import count
from pathlib import Path
from typing import Final, cast

import psycopg
import pytest

from workflow import migrate
from workflow.ids import new_run_id
from workflow.lease_store import PostgresRunLeaseStore
from workflow.leases import Claim, LeaseLost
from workflow.run_states import RunState
from workflow.transitions import GuardInput, transition

pytestmark = pytest.mark.integration

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR: Final[Path] = REPO_ROOT / "deploy" / "migrations"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
LEASE_SECONDS = 300
WORKERS = 5
ROWS = 12
_WORKFLOW_RUN_IDS = count(1001)


def migrated(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return migrate.apply_pending_files(
            migrate.PsycopgMigrationConnection(conn), MIGRATIONS_DIR
        )


def insert_run(
    dsn: str,
    run_id: uuid.UUID,
    state: RunState = RunState.RECEIVED,
    repo_id: int = 1,
) -> None:
    workflow_run_id = next(_WORKFLOW_RUN_IDS)
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO triage_run (run_id, repo_id, workflow_run_id, "
            "run_attempt, state) VALUES (%s, %s, %s, %s, %s)",
            (run_id, repo_id, workflow_run_id, 1, state.value),
        )


def query(dsn: str, sql: str, params: tuple[object, ...] = ()) -> list[tuple]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def current_state(dsn: str, run_id: uuid.UUID) -> str:
    return str(query(dsn, "SELECT state FROM triage_run WHERE run_id = %s", (run_id,))[0][0])


def expire_lease(dsn: str, run_id: uuid.UUID) -> None:
    """Seed the clock: move `lease_until` just behind the injected `NOW`, so
    claims compare against the same clock the tests pass in (no real sleep)."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE triage_run SET lease_until = %s WHERE run_id = %s",
            (NOW - timedelta(seconds=1), run_id),
        )


def lease_row(dsn: str, run_id: uuid.UUID) -> tuple[str, datetime]:
    owner, until = query(
        dsn, "SELECT lease_owner, lease_until FROM triage_run WHERE run_id = %s",
        (run_id,),
    )[0]
    return str(owner), cast(datetime, until)


def test_ac1_n_workers_claim_distinct_rows_at_most_once(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_ids = [new_run_id() for _ in range(ROWS)]
    for run_id in run_ids:
        insert_run(pg_dsn, run_id)

    store = PostgresRunLeaseStore(pg_dsn)
    claimed: list[uuid.UUID] = []
    lock = threading.Lock()
    barrier = threading.Barrier(WORKERS)

    def worker() -> None:
        barrier.wait()
        while True:
            claim = store.claim_next(now=NOW, lease_seconds=LEASE_SECONDS)
            if claim is None:
                return
            with lock:
                claimed.append(claim.run_id)

    threads = [threading.Thread(target=worker) for _ in range(WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Drain any row a worker happened to skip while it was locked (AC1 cap).
    while (claim := store.claim_next(now=NOW, lease_seconds=LEASE_SECONDS)) is not None:
        claimed.append(claim.run_id)

    assert sorted(claimed) == sorted(run_ids), "every row claimed exactly once"
    assert len(set(claimed)) == ROWS, "no row claimed twice (at most once)"
    owners = query(pg_dsn, "SELECT lease_owner FROM triage_run")
    assert all(row[0] for row in owners), "each claim commits an owner before returning"


def test_ac2_expired_row_reclaimable_by_other_worker(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)

    first = PostgresRunLeaseStore(pg_dsn).claim_next(
        now=NOW, lease_seconds=LEASE_SECONDS
    )
    assert first is not None and first.run_id == run_id

    expire_lease(pg_dsn, run_id)
    second = PostgresRunLeaseStore(pg_dsn).claim_next(
        now=NOW, lease_seconds=LEASE_SECONDS
    )

    assert second is not None and second.run_id == run_id
    assert second.owner != first.owner, "the new worker becomes the owner"
    owner, until = lease_row(pg_dsn, run_id)
    assert owner == second.owner
    assert until > NOW, "reclaimed lease is live again"


def test_ac2_renew_extends_only_the_owners_live_lease(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    store = PostgresRunLeaseStore(pg_dsn)
    claim = store.claim_next(now=NOW, lease_seconds=LEASE_SECONDS)
    assert claim is not None
    _, seeded = lease_row(pg_dsn, run_id)

    later = NOW + timedelta(seconds=60)
    assert store.renew(claim, now=later, lease_seconds=600) is True
    _, renewed = lease_row(pg_dsn, run_id)
    assert renewed == later + timedelta(seconds=600)
    assert renewed > seeded

    impostor = Claim(run_id, "not-the-owner", renewed)
    assert store.renew(impostor, now=later, lease_seconds=900) is False
    _, unchanged = lease_row(pg_dsn, run_id)
    assert unchanged == renewed, "a non-owner leaves the lease untouched"

    expire_lease(pg_dsn, run_id)
    assert store.renew(claim, now=later, lease_seconds=600) is False, (
        "an already-expired lease is not renewable"
    )


def test_ac3_stale_owner_discarded_without_state_or_output(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("CREATE TABLE lease_probe (id integer)")

    a = PostgresRunLeaseStore(pg_dsn)
    b = PostgresRunLeaseStore(pg_dsn)
    claim_a = a.claim_next(now=NOW, lease_seconds=LEASE_SECONDS)
    assert claim_a is not None
    expire_lease(pg_dsn, run_id)
    claim_b = b.claim_next(now=NOW, lease_seconds=LEASE_SECONDS)
    assert claim_b is not None and claim_b.owner != claim_a.owner

    def a_stale_work(conn: object) -> None:
        conn.execute(  # type: ignore[attr-defined]
            "INSERT INTO lease_probe (id) VALUES (1)"
        )
        conn.execute(  # type: ignore[attr-defined]
            "UPDATE triage_run SET state = %s WHERE run_id = %s",
            (RunState.FAILED.value, run_id),
        )

    with pytest.raises(LeaseLost):
        a.guarded_commit(claim_a, a_stale_work)

    assert current_state(pg_dsn, run_id) == RunState.RECEIVED.value
    assert query(pg_dsn, "SELECT count(*) FROM lease_probe")[0][0] == 0


def test_ac3_two_worker_fencing_and_b_recovers(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    a = PostgresRunLeaseStore(pg_dsn)
    b = PostgresRunLeaseStore(pg_dsn)

    claim_a = a.claim_next(now=NOW, lease_seconds=LEASE_SECONDS)
    assert claim_a is not None and claim_a.run_id == run_id

    # Worker A's lease expires (DB-seeded, deterministic, no sleep).
    expire_lease(pg_dsn, run_id)
    claim_b = b.claim_next(now=NOW, lease_seconds=LEASE_SECONDS)
    assert claim_b is not None and claim_b.run_id == run_id
    assert claim_b.owner != claim_a.owner

    def b_progress(conn: object) -> None:
        row = transition(RunState.RECEIVED, RunState.DISTILLING, GuardInput())
        conn.execute(  # type: ignore[attr-defined]
            "UPDATE triage_run SET state = %s WHERE run_id = %s",
            (row.to_state.value, run_id),
        )

    b.guarded_commit(claim_b, b_progress)
    assert current_state(pg_dsn, run_id) == RunState.DISTILLING.value

    def a_stale(conn: object) -> None:
        conn.execute(  # type: ignore[attr-defined]
            "UPDATE triage_run SET state = %s WHERE run_id = %s",
            (RunState.FAILED.value, run_id),
        )

    with pytest.raises(LeaseLost):
        a.guarded_commit(claim_a, a_stale)
    assert current_state(pg_dsn, run_id) == RunState.DISTILLING.value, (
        "worker A cannot overwrite worker B's committed progress"
    )


def test_ac3_guarded_commit_by_current_owner_persists_work(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    store = PostgresRunLeaseStore(pg_dsn)
    claim = store.claim_next(now=NOW, lease_seconds=LEASE_SECONDS)
    assert claim is not None

    def work(conn: object) -> str:
        conn.execute(  # type: ignore[attr-defined]
            "UPDATE triage_run SET state = %s WHERE run_id = %s",
            (RunState.DISTILLING.value, run_id),
        )
        return "ok"

    assert store.guarded_commit(claim, work) == "ok"
    assert current_state(pg_dsn, run_id) == RunState.DISTILLING.value


def test_0003_migration_adds_lease_columns_and_claim_index(pg_dsn: str) -> None:
    expected = len(migrate.read_migrations(MIGRATIONS_DIR))
    assert migrated(pg_dsn) == expected

    names = {
        str(name): (str(data_type), str(is_nullable))
        for name, data_type, is_nullable in query(
            pg_dsn,
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'triage_run' AND column_name IN "
            "('lease_owner', 'lease_until')",
        )
    }
    assert names == {
        "lease_owner": ("text", "YES"),
        "lease_until": ("timestamp with time zone", "YES"),
    }

    index_defs = [
        str(row[0])
        for row in query(
            pg_dsn,
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'triage_run'",
        )
    ]
    assert any("lease_until" in definition for definition in index_defs), (
        "the claim needs an index on lease_until (AD-23)"
    )


def test_0003_claim_index_is_named_and_covers_lease_until(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    definitions = [
        str(row[0])
        for row in query(
            pg_dsn,
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'triage_run' AND indexname = 'ix_triage_run_lease_until'",
        )
    ]
    assert len(definitions) == 1
    assert "(lease_until)" in definitions[0]
