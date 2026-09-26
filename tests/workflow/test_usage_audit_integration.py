"""Story 6.1 integration tests — real postgres:18 via Docker (AC1/AC2/AC3).

Proves the audit fact against the real database: migration 0007 applies and
adds only the audit columns, an attempt row carries the model and its token
counters with NULLs preserved, a failed attempt keeps returned usage, the
`(run_id, step, attempt)` unique identity refuses a duplicate attempt, and
an audit row never moves `triage_run.state` (AD-23).

Needs Docker on the host; marked `integration` and excluded from `make
check`. Run explicitly:

    .venv/bin/pytest -m integration tests/workflow/test_usage_audit_integration.py -q
"""

import uuid
from itertools import count
from pathlib import Path
from typing import Final

import psycopg
import pytest

from contracts.usage import ModelUsage
from tests.workflow.column_sets import EXPECTED_RUN_STEP_COLUMNS
from workflow import migrate
from workflow.ids import new_run_id
from workflow.steps import DuplicateStepError
from workflow.usage_audit import (
    AuditIdentity,
    ModelCallError,
    ModelCallResult,
    PostgresUsageAuditStore,
    audit_model_call,
)

pytestmark = pytest.mark.integration

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR: Final[Path] = REPO_ROOT / "deploy" / "migrations"
REPO_ID: Final[int] = 42
MODEL: Final[str] = "claude-haiku-4-5-20251001"
_WORKFLOW_RUN_IDS = count(7001)

FULL_USAGE = ModelUsage(
    model=MODEL,
    input_tokens=1200,
    output_tokens=340,
    cache_read_input_tokens=512,
    cache_creation_input_tokens_5m=64,
    cache_creation_input_tokens_1h=128,
)

AUDIT_ROW_SQL = (
    "SELECT step, attempt, status, model, input_tokens, output_tokens, "
    "cache_read_input_tokens, cache_creation_input_tokens_5m, "
    "cache_creation_input_tokens_1h, outcome FROM run_step WHERE run_id = %s"
)


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


def query(dsn: str, sql: str, params: tuple[object, ...] = ()) -> list[tuple]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def audit_for(dsn: str, run_id: uuid.UUID) -> object:
    """The wrapper bound to one run's identity and the real Postgres store."""
    identity = AuditIdentity(run_id=run_id, repo_id=REPO_ID, task_id=str(run_id))
    return audit_model_call(
        PostgresUsageAuditStore(dsn),
        identity,
        step_name="call:system_one",
        attempt=1,
        model=MODEL,
    )


def test_ac1_usage_fixture_becomes_row_with_all_counters(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)

    audit_for(pg_dsn, run_id)(
        lambda: ModelCallResult(value="payload", usage=FULL_USAGE)
    )

    (row,) = query(pg_dsn, AUDIT_ROW_SQL, (run_id,))
    assert row == (
        "call:system_one",
        1,
        "completed",
        MODEL,
        1200,
        340,
        512,
        64,
        128,
        "verdict",
    )


def test_ac1_unreported_counters_are_null_not_zero(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    partial = ModelUsage(model=MODEL, input_tokens=10)

    audit_for(pg_dsn, run_id)(lambda: ModelCallResult(value="p", usage=partial))

    (row,) = query(pg_dsn, AUDIT_ROW_SQL, (run_id,))
    assert row[4] == 10, "the reported counter is stored"
    assert row[5] is None and row[6] is None and row[7] is None and row[8] is None, (
        "unreported counters are NULL, never 0 (AD-18)"
    )


def test_ac2_failed_attempt_persists_returned_usage(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)

    def failed_with_usage() -> ModelCallResult[str]:
        raise ModelCallError("usage returned, then failed", usage=FULL_USAGE)

    with pytest.raises(ModelCallError):
        audit_for(pg_dsn, run_id)(failed_with_usage)

    (row,) = query(pg_dsn, AUDIT_ROW_SQL, (run_id,))
    assert (row[2], row[9]) == ("failed", "error")
    assert (row[4], row[5], row[6], row[7], row[8]) == (1200, 340, 512, 64, 128)


def test_ac2_duplicate_attempt_raises_the_ad2_backstop(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    audit = audit_for(pg_dsn, run_id)
    audit(lambda: ModelCallResult(value="first"))

    with pytest.raises(DuplicateStepError):
        audit(lambda: ModelCallResult(value="second"))

    (row,) = query(pg_dsn, AUDIT_ROW_SQL, (run_id,))
    assert row[0] == "call:system_one" and row[2] == "completed", (
        "only the first attempt's row exists"
    )
    count_rows = query(
        pg_dsn, "SELECT count(*) FROM run_step WHERE run_id = %s", (run_id,)
    )
    assert count_rows[0][0] == 1


def test_ac2_audit_rows_never_move_run_state(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    audit = audit_for(pg_dsn, run_id)

    audit(lambda: ModelCallResult(value="payload", usage=FULL_USAGE))

    def failed_with_usage() -> ModelCallResult[str]:
        raise ModelCallError("usage returned, then failed", usage=FULL_USAGE)

    # A second attempt number records the failure row too.
    identity = AuditIdentity(run_id=run_id, repo_id=REPO_ID, task_id=str(run_id))
    failing = audit_model_call(
        PostgresUsageAuditStore(pg_dsn),
        identity,
        step_name="call:system_one",
        attempt=2,
        model=MODEL,
    )
    with pytest.raises(ModelCallError):
        failing(failed_with_usage)

    state = query(pg_dsn, "SELECT state FROM triage_run WHERE run_id = %s", (run_id,))
    assert state == [("RECEIVED",)], "audit rows never move run state (AD-23)"


def test_ac3_migration_adds_only_the_audit_columns(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0

    columns = query(
        pg_dsn,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'run_step'",
    )
    names = {str(row[0]) for row in columns}
    assert names == EXPECTED_RUN_STEP_COLUMNS, "only this story's audit fields"
    for forbidden in ("cost", "price", "evidence"):
        assert not any(forbidden in name for name in names), forbidden

    nullable = {
        str(row[0])
        for row in query(
            pg_dsn,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'run_step' AND is_nullable = 'YES'",
        )
    }
    assert {
        "model",
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens_5m",
        "cache_creation_input_tokens_1h",
        "outcome",
    } <= nullable, "every audit column is NULLable (AD-18)"


def test_ac3_outcome_stays_a_closed_enum(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)

    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO run_step (step_id, run_id, repo_id, step, attempt, "
                "status, model, outcome) "
                "VALUES (gen_random_uuid(), %s, %s, 'call:x', 1, 'failed', %s, "
                "'rate_limited')",
                (run_id, REPO_ID, MODEL),
            )


def test_ac3_0007_migration_applies_forward_only(pg_dsn: str) -> None:
    expected = len(migrate.read_migrations(MIGRATIONS_DIR))
    assert migrated(pg_dsn) == expected
    assert migrated(pg_dsn) == 0, "forward-only: never rerun (AD-25)"
