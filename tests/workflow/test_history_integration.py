"""Story 2.6 integration tests — real postgres:18 via Docker (AC1/AC2/AC3).

Covers the `0005_history`/`0006_pr_feedback` migrations (no free-text column
on `history`), the AC2 exactly-once terminal write under a real duplicate,
the AWAITING_APPROVAL refusal writing no row, RT-03 (foreign-repo lookup
returns nothing) and RT-04 (pr_feedback can never become history). Needs
Docker on the host; marked `integration` and excluded from `make check`. Run
explicitly:

    .venv/bin/pytest -m integration tests/workflow/test_history_integration.py -q
"""

import re
import uuid
from itertools import count
from pathlib import Path
from typing import Final

import psycopg
import pytest

from workflow import migrate
from workflow.history import HumanVerdict, NonTerminalWriteError, TerminalWrite
from workflow.history_store import PostgresHistoryStore
from workflow.ids import new_run_id
from workflow.pr_feedback_store import PostgresPRFeedbackStore
from workflow.run_states import TERMINAL_RUN_STATES, RunState

pytestmark = pytest.mark.integration

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR: Final[Path] = REPO_ROOT / "deploy" / "migrations"
REPO_ID = 42
OTHER_REPO_ID = 99
_WORKFLOW_RUN_IDS = count(9001)

EXPECTED_HISTORY_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "row_id",
        "run_id",
        "repo_id",
        "test_id",
        "error_type",
        "top_stack_frames",
        "fingerprint",
        "terminal_state",
        "human_verdict",
        "created_at",
    }
)


def migrated(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return migrate.apply_pending_files(
            migrate.PsycopgMigrationConnection(conn), MIGRATIONS_DIR
        )


def insert_triage_run(dsn: str, run_id: uuid.UUID, repo_id: int = REPO_ID) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO triage_run (run_id, repo_id, workflow_run_id, "
            "run_attempt, state) VALUES (%s, %s, %s, %s, %s)",
            (run_id, repo_id, next(_WORKFLOW_RUN_IDS), 1, RunState.FAILED.value),
        )


def query(dsn: str, sql: str, params: tuple[object, ...] = ()) -> list[tuple]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def check_defs(dsn: str, table: str) -> dict[str, str]:
    rows = query(
        dsn,
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        f"WHERE conrelid = '{table}'::regclass",
    )
    return {str(name): str(definition) for name, definition in rows}


def test_ac1_migration_history_has_no_free_text_column(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0

    columns = query(
        pg_dsn,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'history'",
    )
    names = {str(row[0]) for row in columns}
    assert names == EXPECTED_HISTORY_COLUMNS
    for forbidden in ("notes", "narrative", "free_text", "description", "comment"):
        assert not any(forbidden in name for name in names), forbidden


def test_ac2_duplicate_finalize_writes_one_row(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_triage_run(pg_dsn, run_id)
    store = PostgresHistoryStore(pg_dsn)

    write = TerminalWrite(
        run_id=run_id,
        repo_id=REPO_ID,
        test_id="tests/test_x.py::test_y",
        error_type="AssertionError",
        top_stack_frames=("frame_a", "frame_b"),
        to_state=RunState.FAILED,
    )
    first = store.write_terminal(write)
    second = store.write_terminal(write)

    assert second.row_id == first.row_id
    rows = query(pg_dsn, "SELECT row_id FROM history WHERE run_id = %s", (run_id,))
    assert len(rows) == 1


def test_ac2_human_verdict_stored_and_rejected_has_reason(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_triage_run(pg_dsn, run_id)
    store = PostgresHistoryStore(pg_dsn)

    store.write_terminal(
        TerminalWrite(
            run_id=run_id,
            repo_id=REPO_ID,
            test_id="tests/test_x.py::test_y",
            error_type="AssertionError",
            top_stack_frames=("frame_a",),
            to_state=RunState.REJECTED_BY_HUMAN,
            human_verdict=HumanVerdict.REJECTED,
        )
    )

    stored = query(
        pg_dsn, "SELECT human_verdict FROM history WHERE run_id = %s", (run_id,)
    )
    assert stored[0][0] == HumanVerdict.REJECTED.value


def test_ac2_awaiting_approval_writes_no_history_row(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_triage_run(pg_dsn, run_id)
    store = PostgresHistoryStore(pg_dsn)

    with pytest.raises(NonTerminalWriteError):
        store.write_terminal(
            TerminalWrite(
                run_id=run_id,
                repo_id=REPO_ID,
                test_id="tests/test_x.py::test_y",
                error_type="AssertionError",
                top_stack_frames=("frame_a",),
                to_state=RunState.AWAITING_APPROVAL,
            )
        )

    rows = query(pg_dsn, "SELECT row_id FROM history WHERE run_id = %s", (run_id,))
    assert rows == []


def test_ac3_rt03_foreign_repo_lookup_returns_nothing(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_triage_run(pg_dsn, run_id, repo_id=REPO_ID)
    store = PostgresHistoryStore(pg_dsn)

    entry = store.write_terminal(
        TerminalWrite(
            run_id=run_id,
            repo_id=REPO_ID,
            test_id="tests/test_x.py::test_y",
            error_type="AssertionError",
            top_stack_frames=("frame_a",),
            to_state=RunState.FAILED,
        )
    )

    own_repo = store.lookup(REPO_ID, entry.fingerprint)
    foreign_repo = store.lookup(OTHER_REPO_ID, entry.fingerprint)

    assert len(own_repo) == 1 and own_repo[0].row_id == entry.row_id
    assert foreign_repo == [], "another tenant's row must never surface (AD-15)"


def test_ac1_check_constraint_matches_terminal_run_states(pg_dsn: str) -> None:
    # ck_history_terminal_state duplicates TERMINAL_RUN_STATES with nothing
    # tying them together in code; this parity test is that tie, mirroring
    # tests/workflow/test_triage_run_migration.py::test_enum_check_constraint_parity.
    assert migrated(pg_dsn) > 0
    constraints = check_defs(pg_dsn, "history")

    state_def = constraints["ck_history_terminal_state"]
    listed = set(re.findall(r"'([A-Z_]+)'", state_def))
    assert listed == {state.value for state in TERMINAL_RUN_STATES}


def test_ac3_rt03_pr_feedback_foreign_repo_lookup_returns_nothing(pg_dsn: str) -> None:
    # pr_feedback's own RT-03 equivalent: list_for_run scoped to one repo_id
    # must never surface another tenant's feedback rows (AD-15).
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_triage_run(pg_dsn, run_id, repo_id=REPO_ID)
    feedback_store = PostgresPRFeedbackStore(pg_dsn)

    feedback_store.write(
        run_id,
        REPO_ID,
        pr_number=21,
        feedback_text="looks fine to me",
        author_login="a-human-reviewer",
    )

    own_repo = feedback_store.list_for_run(REPO_ID, run_id)
    foreign_repo = feedback_store.list_for_run(OTHER_REPO_ID, run_id)

    assert len(own_repo) == 1
    assert foreign_repo == [], (
        "another tenant's pr_feedback row must never surface (AD-15)"
    )


def test_ac3_rt04_pr_feedback_never_becomes_history(pg_dsn: str) -> None:
    assert migrated(pg_dsn) > 0
    run_id = new_run_id()
    insert_triage_run(pg_dsn, run_id)
    feedback_store = PostgresPRFeedbackStore(pg_dsn)

    feedback_store.write(
        run_id,
        REPO_ID,
        pr_number=17,
        feedback_text="this diff looks wrong, please redo it",
        author_login="a-human-reviewer",
    )

    listed = feedback_store.list_for_run(REPO_ID, run_id)
    assert len(listed) == 1
    assert listed[0].feedback_text == "this diff looks wrong, please redo it"

    history_rows = query(
        pg_dsn, "SELECT row_id FROM history WHERE run_id = %s", (run_id,)
    )
    assert history_rows == [], "pr_feedback write must never touch history"


def test_ac1_migrations_apply_and_pr_feedback_fk_enforced(pg_dsn: str) -> None:
    expected = len(migrate.read_migrations(MIGRATIONS_DIR))
    assert migrated(pg_dsn) == expected
    assert migrated(pg_dsn) == 0, "forward-only: never rerun (AD-25)"

    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute(
                "INSERT INTO pr_feedback (feedback_id, run_id, repo_id, "
                "pr_number, feedback_text, author_login) VALUES "
                "(gen_random_uuid(), gen_random_uuid(), %s, 1, 'x', 'y')",
                (REPO_ID,),
            )
