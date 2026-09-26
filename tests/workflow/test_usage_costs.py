"""Story 6.2 unit tests — the per-run cost rollup over 6.1's audit rows (AC2).

The Postgres boundary is driven through a `UsageAuditReader` Protocol fake,
no database touched here (mirrors `tests/workflow/test_usage_audit.py`);
the real adapter runs in the marked integration tests
(`tests/workflow/test_usage_costs_integration.py`).
"""

import uuid

import pytest

from contracts.usage import ModelUsage
from monitoring.pricing import TokenType
from tests.fixtures.prices import FIXTURE_TABLE, FULL_USAGE, HAIKU
from workflow.usage_costs import (
    JEV_STEP_NAME,
    PostgresUsageAuditReader,
    UsageAttemptRow,
    run_cost_summary,
)

RUN_ID = uuid.UUID("018f6a2c-0000-7000-8000-000000000002")
REPO_ID = 7
UNPRICED = "claude-opus-9"


class FakeUsageAuditReader:
    """Protocol fake: returns the rows it was given and records the ask."""

    def __init__(self, rows: list[UsageAttemptRow]) -> None:
        self.rows = rows
        self.requested: list[tuple[int, uuid.UUID]] = []

    def read_attempts(self, repo_id: int, run_id: uuid.UUID) -> list[UsageAttemptRow]:
        self.requested.append((repo_id, run_id))
        return self.rows


def attempt_row(
    step: str, attempt: int, usage: ModelUsage | None, model: str = HAIKU
) -> UsageAttemptRow:
    return UsageAttemptRow(step=step, attempt=attempt, model=model, usage=usage)


def test_ac2_system_one_rows_are_jev_billed() -> None:
    reader = FakeUsageAuditReader([attempt_row(JEV_STEP_NAME, 1, FULL_USAGE)])

    summary = run_cost_summary(reader, FIXTURE_TABLE, repo_id=REPO_ID, run_id=RUN_ID)

    assert reader.requested == [(REPO_ID, RUN_ID)], "the read is repo-bound"
    assert summary.complete is False
    assert summary.reasons == ("jev_unpriced",), "OQ-3: flagged, never estimated"
    assert all(total is None for total in summary.per_type.values()), (
        "a Jev-billed call prices to NULL, never a silent 0"
    )


def test_ac2_non_jev_rows_are_priced_from_the_table() -> None:
    reader = FakeUsageAuditReader([attempt_row("call:analyze", 1, FULL_USAGE)])

    summary = run_cost_summary(reader, FIXTURE_TABLE, repo_id=REPO_ID, run_id=RUN_ID)

    assert summary.complete is True
    assert summary.reasons == ()
    assert summary.per_type[TokenType.INPUT] == pytest.approx(0.0012)  # 1200 x $1/MTok
    assert summary.per_type[TokenType.OUTPUT] == pytest.approx(0.0017)  # 340 x $5/MTok


def test_ac2_unpriced_model_row_is_flagged_through_the_rollup() -> None:
    # Row model and usage model agree (6.1 writes both from one attempt).
    reader = FakeUsageAuditReader(
        [
            attempt_row(
                "call:analyze",
                1,
                ModelUsage(model=UNPRICED, input_tokens=1200),
                model=UNPRICED,
            )
        ]
    )

    summary = run_cost_summary(reader, FIXTURE_TABLE, repo_id=REPO_ID, run_id=RUN_ID)

    assert summary.complete is False
    assert summary.reasons == ("model_unpriced",), (
        "AD-18: an unpriced model yields a NULL cost, flagged"
    )
    assert all(total is None for total in summary.per_type.values())


def test_ac2_run_rollup_flags_incomplete_usage() -> None:
    reader = FakeUsageAuditReader(
        [
            attempt_row("call:analyze", 1, FULL_USAGE),
            # The provider reported only input tokens on the retry.
            attempt_row("call:analyze", 2, ModelUsage(model=HAIKU, input_tokens=10)),
            # Usage lost entirely: nothing was reported at all.
            attempt_row("call:analyze", 3, None),
        ]
    )

    summary = run_cost_summary(reader, FIXTURE_TABLE, repo_id=REPO_ID, run_id=RUN_ID)

    assert summary.complete is False
    assert all(total is None for total in summary.per_type.values()), (
        "incomplete parts are never summed into a complete-looking total"
    )
    assert "output_unreported" in summary.reasons
    assert "input_unreported" in summary.reasons, "a lost usage row flags too"


def test_ac2_rollup_of_a_run_without_attempts_is_complete_at_zero() -> None:
    reader = FakeUsageAuditReader([])

    summary = run_cost_summary(reader, FIXTURE_TABLE, repo_id=REPO_ID, run_id=RUN_ID)

    assert summary.complete is True
    assert summary.reasons == ()


class FakeCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchone(self) -> tuple[object, ...] | None:
        return None

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class FakeConnection:
    """Records SQL and bound params; answers with the given rows."""

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._rows = rows

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        tb: object,
    ) -> bool:
        return False

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> FakeCursor:
        self.calls.append((sql, params))
        return FakeCursor(self._rows)


def test_ac2_adapter_reads_audit_rows_with_null_counters_preserved() -> None:
    connection = FakeConnection(
        [
            ("call:analyze", 1, HAIKU, 1200, 340, 512, 64, 128),
            ("call:system_one", 1, HAIKU, None, None, None, None, None),
        ]
    )
    reader = PostgresUsageAuditReader(
        "postgresql://unused", connect=lambda _dsn: connection
    )

    rows = reader.read_attempts(REPO_ID, RUN_ID)

    assert rows[0].usage == FULL_USAGE
    assert rows[1].usage is None, (
        "all-NULL counters mean the provider reported nothing: usage stays None"
    )
    sql, params = connection.calls[0]
    assert "FROM run_step" in sql
    assert params[0] == REPO_ID and params[1] == RUN_ID
    assert params[2] == "call:%", "only attempt rows in the call: namespace"


def test_ac2_adapter_returns_no_rows_for_another_repo() -> None:
    connection = FakeConnection([])
    reader = PostgresUsageAuditReader(
        "postgresql://unused", connect=lambda _dsn: connection
    )

    rows = reader.read_attempts(REPO_ID + 1, RUN_ID)

    assert rows == []
