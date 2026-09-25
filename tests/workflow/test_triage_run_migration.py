"""Story 2.1 integration tests — real postgres:18 via Docker (AC1+AC2).

Covers the `0001_triage_run` migration: it applies on a fresh database, its
CHECK constraints reject an unknown state, a bad escalation reason and an
AWAITING_APPROVAL row without an escalation reason, and the CHECK value
lists match the Python enums exactly (parity, single source AD-6).

Needs Docker on the host; marked `integration` and excluded from `make
check` (pyproject addopts). Run explicitly:

    .venv/bin/pytest -m integration tests/workflow -q
"""

import re
from pathlib import Path
from typing import Final

import psycopg
import pytest

from contracts.enums import ESCALATION_REASONS, TerminalState
from workflow import migrate
from workflow.run_states import RUN_STATES

pytestmark = pytest.mark.integration

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR: Final[Path] = REPO_ROOT / "deploy" / "migrations"
# Derived, not hardcoded: later stories add migrations (0002, 0003, …) and the
# point of this test is that *every* file applies once and only once.
EXPECTED_MIGRATIONS: Final[int] = len(migrate.read_migrations(MIGRATIONS_DIR))


def applied_once(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return migrate.apply_pending_files(
            migrate.PsycopgMigrationConnection(conn), MIGRATIONS_DIR
        )


def _query(dsn: str, sql: str) -> list[tuple[object, ...]]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return list(cur.fetchall())


def check_defs(dsn: str) -> dict[str, str]:
    rows = _query(
        dsn,
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid = 'triage_run'::regclass",
    )
    return {str(name): str(definition) for name, definition in rows}


def test_0001_migration_applies_and_check_constraints_reject_bad_state_and_missing_reason(
    pg_dsn: str,
) -> None:
    assert applied_once(pg_dsn) == EXPECTED_MIGRATIONS
    assert applied_once(pg_dsn) == 0  # forward-only: never rerun

    good = (
        "INSERT INTO triage_run (run_id, repo_id, workflow_run_id, run_attempt, "
        "state, escalation_reason) VALUES (gen_random_uuid(), 1, 100, 1, "
        "'AWAITING_APPROVAL', 'gate_blocked')"
    )
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(good)  # AD-1: AWAITING_APPROVAL insert with a reason works

    bad_state = good.replace("'AWAITING_APPROVAL'", "'TRANSCENDENT'")
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(bad_state)

    missing_reason = (
        "INSERT INTO triage_run (run_id, repo_id, workflow_run_id, run_attempt, "
        "state) VALUES (gen_random_uuid(), 1, 101, 1, 'AWAITING_APPROVAL')"
    )
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(missing_reason)

    bad_reason = good.replace("'gate_blocked'", "'gate_open'")
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(bad_reason)

    duplicate = (
        "INSERT INTO triage_run (run_id, repo_id, workflow_run_id, run_attempt, "
        "state) VALUES (gen_random_uuid(), 1, 100, 1, 'RECEIVED')"
    )
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.UniqueViolation):
            # same (repo_id, workflow_run_id, run_attempt) identity (AD-17)
            cur.execute(duplicate)


def test_proposal_step_id_is_optional_awaiting_approval_roundtrip(pg_dsn: str) -> None:
    # AC2: proposal_step_id optional — with a value and without, read back.
    assert applied_once(pg_dsn) == EXPECTED_MIGRATIONS
    with_proposal = (
        "INSERT INTO triage_run (run_id, repo_id, workflow_run_id, run_attempt, "
        "state, escalation_reason, proposal_step_id) VALUES (gen_random_uuid(), "
        "2, 200, 1, 'AWAITING_APPROVAL', 'gate_blocked', gen_random_uuid()) "
        "RETURNING proposal_step_id"
    )
    without_proposal = (
        "INSERT INTO triage_run (run_id, repo_id, workflow_run_id, run_attempt, "
        "state, escalation_reason) VALUES (gen_random_uuid(), 2, 201, 1, "
        "'AWAITING_APPROVAL', 'low_confidence')"
    )
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute(with_proposal)
        written = cur.fetchone()
        assert written is not None
        cur.execute(without_proposal)
    stored, none_case = _query(
        pg_dsn,
        "SELECT proposal_step_id FROM triage_run WHERE workflow_run_id = 200",
    ), _query(
        pg_dsn,
        "SELECT proposal_step_id FROM triage_run WHERE workflow_run_id = 201",
    )
    assert stored[0][0] is not None and str(stored[0][0]) == str(written[0])
    assert none_case[0][0] is None


def test_enum_check_constraint_parity(pg_dsn: str) -> None:
    assert applied_once(pg_dsn) == EXPECTED_MIGRATIONS
    constraints = check_defs(pg_dsn)

    state_def = constraints["ck_triage_run_state"]
    listed = set(re.findall(r"'([A-Z_]+)'", state_def))
    assert listed == set(RUN_STATES)

    reason_def = constraints["ck_triage_run_escalation_reason"]
    reasons = set(re.findall(r"'([a-z_]+)'", reason_def))
    assert reasons == set(ESCALATION_REASONS)
    iff_def = constraints["ck_triage_run_escalation_iff_state"]
    assert "AWAITING_APPROVAL" in iff_def and "escalation_reason IS NOT NULL" in iff_def

    # AC2: AWAITING_APPROVAL is non-terminal in the DB — no terminal_state
    # side condition may call it terminal; terminal_state arrives with the
    # payload story, not the state column.
    columns = _query(
        pg_dsn,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'triage_run'",
    )
    names = {str(row[0]) for row in columns}
    assert "state" in names and "escalation_reason" in names
    for terminal in TerminalState:
        assert terminal.value not in names
