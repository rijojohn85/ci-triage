"""Story 1.1 integration tests: real postgres:18 via Docker (AC2/AC3, AD-17/AD-25).

Marked `integration` and excluded from `make check` (pyproject addopts);
run explicitly:

    .venv/bin/pytest -m integration tests/security -q

The disposable `pg_dsn` fixture is reused from `tests/workflow/conftest.py`
(no duplication); each test gets a fresh postgres:18.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from gateway.events import RunIdentity
from gateway.store import IntakeOutcome, PostgresIntakeStore
from tests.workflow.conftest import pg_dsn  # noqa: F401 — pytest fixture re-export

from workflow import migrate

REPO_MIGRATIONS = migrate.DEFAULT_MIGRATIONS_DIR

pytestmark = pytest.mark.integration


def apply_migrations(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        migrate.apply_pending_files(migrate.PsycopgMigrationConnection(conn), REPO_MIGRATIONS)


def query(dsn: str, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


class TestWebhookDeliveryMigration:
    def test_0002_webhook_delivery_applies_and_replay_is_noop(self, pg_dsn: str) -> None:
        apply_migrations(pg_dsn)
        tables = {
            str(row[0])
            for row in query(
                pg_dsn,
                "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'",
            )
        }
        assert "webhook_delivery" in tables

        store = PostgresIntakeStore(pg_dsn)
        identity = RunIdentity(installation_id=1, repo_id=10, workflow_run_id=20, run_attempt=1)
        first = store.record_and_enqueue("delivery-1", identity, uuid.uuid4())
        assert first.outcome is IntakeOutcome.ENQUEUED

        replay = store.record_and_enqueue("delivery-1", identity, uuid.uuid4())
        assert replay.outcome is IntakeOutcome.DELIVERY_REPLAY
        assert replay.run_id == first.run_id, "a replay echoes the existing run id"

        same_identity_new_delivery = store.record_and_enqueue(
            "delivery-2", identity, uuid.uuid4()
        )
        assert same_identity_new_delivery.outcome is IntakeOutcome.RUN_DUPLICATE
        assert same_identity_new_delivery.run_id == first.run_id, (
            "a duplicate identity echoes the existing run id"
        )

        assert query(pg_dsn, "SELECT state FROM triage_run") == [("RECEIVED",)]
        assert query(pg_dsn, "SELECT count(*) FROM webhook_delivery") == [(2,)]

    def test_ac2_queue_count_matches_accepted(self, pg_dsn: str) -> None:
        apply_migrations(pg_dsn)
        store = PostgresIntakeStore(pg_dsn)
        for index in range(3):
            result = store.record_and_enqueue(
                f"queue-{index}",
                RunIdentity(1, 10, 100 + index, 1),
                uuid.uuid4(),
            )
            assert result.outcome is IntakeOutcome.ENQUEUED
        assert store.queue_depth(10) == 3
        with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO triage_run "
                "(run_id, repo_id, workflow_run_id, run_attempt, state) "
                "VALUES (gen_random_uuid(), 10, 999, 1, 'DONE_PR')"
            )
        assert store.queue_depth(10) == 3, "a terminal run is not in the queue"
        assert store.queue_depth(11) == 0

    def test_ac2_concurrent_duplicates_create_one_run(self, pg_dsn: str) -> None:
        apply_migrations(pg_dsn)
        store = PostgresIntakeStore(pg_dsn)
        identity = RunIdentity(installation_id=1, repo_id=10, workflow_run_id=555, run_attempt=1)

        def submit(index: int) -> IntakeOutcome:
            return store.record_and_enqueue(
                f"concurrent-{index}", identity, uuid.uuid4()
            ).outcome

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(submit, range(8)))

        assert outcomes.count(IntakeOutcome.ENQUEUED) == 1
        assert query(pg_dsn, "SELECT count(*) FROM triage_run") == [(1,)]
