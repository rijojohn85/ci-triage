"""Story 2.8 integration tests — real postgres:18 via Docker (AC1/AC2/AC3).

Proves the runner's persistence facts against the real database: every
attempt is its own `run_step` row, a second invalid output pauses with
`escalation_reason = validation_failed`, an exhausted transient budget ends
`FAILED` with terminal history written once, and a stale owner's commit is
refused by the lease guard (AD-23).

The transports are the same fakes the unit tests use (real specialist
integration is story 2.9); the stores are the real Postgres adapters. Needs
Docker on the host; marked `integration` and excluded from `make check`.

    .venv/bin/pytest -m integration tests/workflow/test_step_runner_integration.py -q
"""

import json
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from itertools import count
from pathlib import Path
from typing import Final

import psycopg
import pytest

from contracts.enums import EscalationReason
from contracts.usage import ModelUsage
from guardrails.citation_check import ValidationIssue
from tests.workflow.test_step_runner import (
    FakeAudit,
    FakeTransport,
    VALID_PAYLOAD,
    config,
    issue_list,
    transient,
)
from workflow import migrate
from workflow.history import TerminalWrite
from workflow.history_store import PostgresHistoryStore
from workflow.ids import new_run_id
from workflow.lease_store import PostgresRunLeaseStore
from workflow.leases import Claim, LeaseLost
from workflow.run_states import RunState
from workflow.step_runner import PostgresAttemptRecorder, StepContext, run_step
from workflow.step_store import PostgresStepRecorder
from workflow.usage_audit import PostgresUsageAuditStore

pytestmark = pytest.mark.integration

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR: Final[Path] = REPO_ROOT / "deploy" / "migrations"
REPO_ID = 42
_WORKFLOW_RUN_IDS = count(6001)
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
MODEL = "claude-haiku-4-5-20251001"
ISSUE = ValidationIssue(code="schema", message="bad shape", location="choice")


def migrated(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return migrate.apply_pending_files(
            migrate.PsycopgMigrationConnection(conn), MIGRATIONS_DIR
        )


def insert_run(
    dsn: str,
    run_id: uuid.UUID,
    state: RunState = RunState.CLASSIFYING,
    repo_id: int = REPO_ID,
) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO triage_run (run_id, repo_id, workflow_run_id, "
            "run_attempt, state) VALUES (%s, %s, %s, %s, %s)",
            (run_id, repo_id, next(_WORKFLOW_RUN_IDS), 1, state.value),
        )


def query(dsn: str, sql: str, params: tuple[object, ...] = ()) -> list[tuple]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def current_state(dsn: str, run_id: uuid.UUID) -> str:
    return str(
        query(dsn, "SELECT state FROM triage_run WHERE run_id = %s", (run_id,))[0][0]
    )


def escalation_reason(dsn: str, run_id: uuid.UUID) -> str | None:
    value = query(
        dsn, "SELECT escalation_reason FROM triage_run WHERE run_id = %s", (run_id,)
    )[0][0]
    return None if value is None else str(value)


def step_rows(dsn: str, run_id: uuid.UUID) -> list[tuple]:
    return query(
        dsn,
        "SELECT step, attempt, status, output FROM run_step "
        "WHERE run_id = %s ORDER BY attempt, step",
        (run_id,),
    )


def history_rows(dsn: str, run_id: uuid.UUID) -> list[tuple]:
    return query(dsn, "SELECT terminal_state FROM history WHERE run_id = %s", (run_id,))


def context_for(dsn: str, run_id: uuid.UUID, claim: Claim) -> StepContext:
    return StepContext(
        claim=claim,
        repo_id=REPO_ID,
        request={"skill": "classify"},
        to_state=RunState.ANALYZING,
        terminal=TerminalWrite(
            run_id=run_id,
            repo_id=REPO_ID,
            test_id="tests/test_x.py",
            error_type="AssertionError",
            top_stack_frames=("app.py:10",),
            to_state=RunState.FAILED,
        ),
    )


def runner_stores(dsn: str) -> tuple:
    return (
        PostgresStepRecorder(dsn),
        PostgresAttemptRecorder(dsn),
        PostgresHistoryStore(dsn),
        PostgresUsageAuditStore(dsn),
    )


def run(
    dsn: str,
    run_id: uuid.UUID,
    transport: FakeTransport,
    *,
    claim: Claim,
    validate: object = issue_list,
) -> object:
    recorder, attempts, history, audit = runner_stores(dsn)
    return run_step(
        context_for(dsn, run_id, claim),
        "classify",
        transport,
        validate,  # type: ignore[arg-type]
        recorder,
        attempts,
        history,
        audit,
        lambda _seconds: None,
        config(),
    )


def test_ac1_second_invalid_output_pauses_with_escalation_reason(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    claim = PostgresRunLeaseStore(pg_dsn).claim_next(lease_seconds=300)
    assert claim is not None

    outcome = run(
        pg_dsn,
        run_id,
        FakeTransport({"bad": 1}, {"bad": 2}),
        claim=claim,
    )

    assert type(outcome).__name__ == "StepPaused"
    assert current_state(pg_dsn, run_id) == RunState.AWAITING_APPROVAL.value
    assert escalation_reason(pg_dsn, run_id) == (
        EscalationReason.VALIDATION_FAILED.value
    )
    rows = step_rows(pg_dsn, run_id)
    assert [(row[0], row[1], row[2]) for row in rows] == [
        ("call:classify", 1, "completed"),
        ("classify", 1, "failed"),
        ("call:classify", 2, "completed"),
        ("classify", 2, "failed"),
    ], "each attempt is its own run_step row (AD-2, AD-22)"


def test_ac2_exhausted_transient_budget_fails_with_history_once(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    claim = PostgresRunLeaseStore(pg_dsn).claim_next(lease_seconds=300)
    assert claim is not None

    outcome = run(
        pg_dsn,
        run_id,
        FakeTransport(transient(), transient(), transient()),
        claim=claim,
    )

    assert type(outcome).__name__ == "StepFailed"
    assert current_state(pg_dsn, run_id) == RunState.FAILED.value
    rows = step_rows(pg_dsn, run_id)
    assert [(row[0], row[1], row[2]) for row in rows] == [
        ("call:classify", 1, "failed"),
        ("classify", 1, "failed"),
        ("call:classify", 2, "failed"),
        ("classify", 2, "failed"),
        ("call:classify", 3, "failed"),
        ("classify", 3, "failed"),
    ], "every attempt (plain + audited) is its own row"
    assert len(history_rows(pg_dsn, run_id)) == 1, "terminal history written once"


def test_ac2_re_run_after_residue_rows_continues_the_numbering(pg_dsn: str) -> None:
    """A reclaimed worker re-runs a step whose earlier owner left failed
    attempt and `call:` audit rows: numbering continues at last+1 per
    namespace, so the `(run_id, step, attempt)` identity never collides."""
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO run_step (step_id, run_id, repo_id, step, attempt, "
            "status, output) VALUES (gen_random_uuid(), %s, %s, 'classify', 1, "
            "'failed', %s::jsonb)",
            (run_id, REPO_ID, json.dumps({"error": "earlier owner died"})),
        )
        cur.execute(
            "INSERT INTO run_step (step_id, run_id, repo_id, step, attempt, "
            "status, output, model, outcome) VALUES (gen_random_uuid(), %s, %s, "
            "'call:classify', 1, 'failed', NULL, %s, 'error')",
            (run_id, REPO_ID, MODEL),
        )
    claim = PostgresRunLeaseStore(pg_dsn).claim_next(lease_seconds=300)
    assert claim is not None

    outcome = run(pg_dsn, run_id, FakeTransport(VALID_PAYLOAD), claim=claim)

    assert type(outcome).__name__ == "StepCommitted"
    assert current_state(pg_dsn, run_id) == RunState.ANALYZING.value
    rows = step_rows(pg_dsn, run_id)
    assert [(row[0], row[1], row[2]) for row in rows] == [
        ("call:classify", 1, "failed"),
        ("classify", 1, "failed"),
        ("call:classify", 2, "completed"),
        ("classify", 2, "completed"),
    ], "both namespaces continue at last+1; no identity collision (AD-2)"


def test_ac3_validated_output_and_state_commit_atomically(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    claim = PostgresRunLeaseStore(pg_dsn).claim_next(lease_seconds=300)
    assert claim is not None

    transport = FakeTransport(VALID_PAYLOAD)
    transport.usage = ModelUsage(model=MODEL, input_tokens=12)
    outcome = run(pg_dsn, run_id, transport, claim=claim)

    assert type(outcome).__name__ == "StepCommitted"
    assert current_state(pg_dsn, run_id) == RunState.ANALYZING.value
    rows = step_rows(pg_dsn, run_id)
    assert [(row[0], row[1], row[2]) for row in rows] == [
        ("call:classify", 1, "completed"),
        ("classify", 1, "completed"),
    ]
    assert rows[1][3] == VALID_PAYLOAD, "the validated output is the committed output"
    audit_rows = query(
        pg_dsn,
        "SELECT model, input_tokens, output_tokens FROM run_step "
        "WHERE run_id = %s AND step = 'call:classify'",
        (run_id,),
    )
    assert audit_rows == [(MODEL, 12, None)], "usage counters: reported + NULL (AD-18)"


def test_ac3_stale_owner_result_cannot_commit(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_run(pg_dsn, run_id)
    store = PostgresRunLeaseStore(pg_dsn)
    stale = store.claim_next(lease_seconds=300)
    assert stale is not None
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE triage_run SET lease_until = now() - interval '1 second' "
            "WHERE run_id = %s",
            (run_id,),
        )
    fresh = store.claim_next(lease_seconds=300)
    assert fresh is not None and fresh.owner != stale.owner

    with pytest.raises(LeaseLost):
        run(pg_dsn, run_id, FakeTransport(VALID_PAYLOAD), claim=stale)

    assert current_state(pg_dsn, run_id) == RunState.CLASSIFYING.value, (
        "the fenced commit moved nothing (AD-23)"
    )
    rows = step_rows(pg_dsn, run_id)
    assert [row[0] for row in rows] == ["call:classify"], (
        "no step row from the stale owner; the audited call attempt remains "
        "(bookkeeping, not a state move — AD-18, AD-23)"
    )
    assert rows[0][2] == "completed"
