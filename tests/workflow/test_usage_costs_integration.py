"""Story 6.2 integration tests — the cost reader against real Postgres (AC2).

Proves the rollup over story 6.1's real audit rows: migration applies, the
reader reads the attempts 6.1's recorder wrote (NULL counters preserved),
`call:system_one` rows are Jev-billed, an incomplete attempt turns the run
total NULL with reasons, a complete run sums cleanly, and the read is
repo-bound.

Needs Docker on the host; marked `integration` and excluded from `make
check`. Run explicitly:

    .venv/bin/pytest -m integration tests/workflow/test_usage_costs_integration.py -q
"""

import uuid
from itertools import count
from pathlib import Path
from typing import Final

import psycopg
import pytest

from contracts.usage import ModelUsage
from monitoring.pricing import TokenType
from tests.fixtures.prices import FIXTURE_TABLE, FULL_USAGE, HAIKU
from workflow import migrate
from workflow.ids import new_run_id
from workflow.usage_audit import (
    AuditIdentity,
    ModelCallResult,
    PostgresUsageAuditStore,
    audit_model_call,
)
from workflow.usage_costs import PostgresUsageAuditReader, run_cost_summary

pytestmark = pytest.mark.integration

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR: Final[Path] = REPO_ROOT / "deploy" / "migrations"
REPO_ID: Final[int] = 43
_WORKFLOW_RUN_IDS = count(7101)


def migrated(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return migrate.apply_pending_files(
            migrate.PsycopgMigrationConnection(conn), MIGRATIONS_DIR
        )


def insert_run(dsn: str, run_id: uuid.UUID) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO triage_run (run_id, repo_id, workflow_run_id, "
            "run_attempt, state) VALUES (%s, %s, %s, 1, 'RECEIVED')",
            (run_id, REPO_ID, next(_WORKFLOW_RUN_IDS)),
        )


def record(
    dsn: str, run_id: uuid.UUID, step_name: str, attempt: int, usage: ModelUsage | None
) -> None:
    """Write one attempt row through 6.1's real recorder."""
    identity = AuditIdentity(run_id=run_id, repo_id=REPO_ID, task_id=str(run_id))
    audit = audit_model_call(
        PostgresUsageAuditStore(dsn),
        identity,
        step_name=step_name,
        attempt=attempt,
        model=HAIKU,
    )
    audit(lambda: ModelCallResult(value="payload", usage=usage))


def test_ac2_reader_reads_6_1_rows_with_null_counters_preserved(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    record(pg_dsn, run_id, "call:analyze", 1, FULL_USAGE)
    record(pg_dsn, run_id, "call:analyze", 2, ModelUsage(model=HAIKU, input_tokens=10))
    record(pg_dsn, run_id, "call:analyze", 3, None)

    rows = PostgresUsageAuditReader(pg_dsn).read_attempts(REPO_ID, run_id)

    assert [(row.step, row.attempt) for row in rows] == [
        ("call:analyze", 1),
        ("call:analyze", 2),
        ("call:analyze", 3),
    ]
    assert rows[0].usage == FULL_USAGE
    assert rows[1].usage == ModelUsage(model=HAIKU, input_tokens=10), (
        "partial usage keeps its reported counter"
    )
    assert rows[2].usage is None, (
        "all-NULL counters mean the provider reported nothing: usage stays None"
    )


def test_ac2_jev_and_incomplete_rows_turn_the_run_total_null(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    record(pg_dsn, run_id, "call:system_one", 1, FULL_USAGE)
    record(pg_dsn, run_id, "call:analyze", 1, ModelUsage(model=HAIKU, input_tokens=10))

    summary = run_cost_summary(
        PostgresUsageAuditReader(pg_dsn),
        FIXTURE_TABLE,
        repo_id=REPO_ID,
        run_id=run_id,
    )

    assert summary.complete is False
    assert all(total is None for total in summary.per_type.values()), (
        "incomplete parts are never summed into a complete-looking total"
    )
    assert "jev_unpriced" in summary.reasons, "OQ-3: flagged, never estimated"
    assert "output_unreported" in summary.reasons


def test_ac2_complete_run_sums_cleanly_over_real_rows(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    record(pg_dsn, run_id, "call:analyze", 1, FULL_USAGE)
    record(pg_dsn, run_id, "call:analyze", 2, FULL_USAGE)

    summary = run_cost_summary(
        PostgresUsageAuditReader(pg_dsn),
        FIXTURE_TABLE,
        repo_id=REPO_ID,
        run_id=run_id,
    )

    assert summary.complete is True
    assert summary.reasons == ()
    assert summary.per_type[TokenType.INPUT] == pytest.approx(0.0024)  # 2 x 1200 x $1


def test_ac2_reader_is_repo_bound(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    record(pg_dsn, run_id, "call:analyze", 1, FULL_USAGE)

    rows = PostgresUsageAuditReader(pg_dsn).read_attempts(REPO_ID + 1, run_id)

    assert rows == [], "a read for another repo sees nothing (AD-15)"
