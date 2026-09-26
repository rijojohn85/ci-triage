"""Per-run cost rollup over 6.1's audit rows (story 6.2, AD-18).

The orchestrator computes costs (AD-18): it reads story 6.1's attempt rows
through a small `UsageAuditReader` Protocol (SOLID-I), marks
`call:system_one` rows as Jev-billed (OQ-3 — the `call:` namespace constant
lives once in `workflow/usage_audit.py`), and hands the attempts to the
pure calculator in `monitoring/costs.py`. Nothing is written back: costs
are computed, not stored (no migration).

SOLID-D: the domain math lives in `monitoring`; this module is the I/O
edge (the Postgres adapter) plus the one composition point.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from contracts.usage import ModelUsage
from monitoring.costs import RunCostSummary, TokenCosts, cost_of_usage, summarize_costs
from monitoring.pricing import PriceTable
from workflow.db import Connection, open_connection
from workflow.usage_audit import CALL_STEP_PREFIX

__all__ = [
    "JEV_STEP_NAME",
    "PostgresUsageAuditReader",
    "UsageAttemptRow",
    "UsageAuditReader",
    "run_cost_summary",
]

JEV_STEP_NAME = f"{CALL_STEP_PREFIX}system_one"
"""The Jev (system_one) attempt rows: the `call:` namespace constant from
6.1's recorder, composed — never a duplicated string."""

_SELECT_ATTEMPT_SQL = """
SELECT step, attempt, model, input_tokens, output_tokens,
       cache_read_input_tokens, cache_creation_input_tokens_5m,
       cache_creation_input_tokens_1h
FROM run_step
WHERE repo_id = %s AND run_id = %s AND step LIKE %s AND model IS NOT NULL
ORDER BY step, attempt
"""


@dataclass(frozen=True)
class UsageAttemptRow:
    """One audited attempt as the calculator needs it (AD-18).

    `usage` is None when the provider reported nothing — the counters stay
    NULL, and the calculator flags every type unreported.
    """

    step: str
    attempt: int
    model: str
    usage: ModelUsage | None


class UsageAuditReader(Protocol):
    """The read surface the rollup consumes (SOLID-I)."""

    def read_attempts(
        self, repo_id: int, run_id: uuid.UUID
    ) -> list[UsageAttemptRow]: ...


def run_cost_summary(
    reader: UsageAuditReader,
    table: PriceTable,
    *,
    repo_id: int,
    run_id: uuid.UUID,
) -> RunCostSummary:
    """Compute one run's cost summary from its audit rows (AD-18).

    `call:system_one` rows are Jev-billed (OQ-3): their cost is NULL and
    flagged, whatever the counters say. Any incomplete part turns the whole
    run total NULL with the reasons listed (spec "Design Notes").
    """
    rows = reader.read_attempts(repo_id, run_id)
    costs: list[TokenCosts] = []
    for row in rows:
        usage = row.usage if row.usage is not None else ModelUsage(model=row.model)
        costs.append(cost_of_usage(usage, table, jev=row.step == JEV_STEP_NAME))
    return summarize_costs(costs)


class PostgresUsageAuditReader:
    """I/O adapter: repo-bound read of a run's `call:` attempt rows (AD-15).

    `connect` is injectable so unit tests can drive the SQL through a fake
    connection; the real thing reads story 6.1's rows as they were written.
    """

    def __init__(
        self,
        dsn: str,
        connect: Callable[[str], Connection] | None = None,
    ) -> None:
        self._dsn = dsn
        self._connect: Callable[[str], Connection] = connect or open_connection

    def read_attempts(self, repo_id: int, run_id: uuid.UUID) -> list[UsageAttemptRow]:
        with self._connect(self._dsn) as conn:
            rows = conn.execute(
                _SELECT_ATTEMPT_SQL,
                (repo_id, run_id, f"{CALL_STEP_PREFIX}%"),
            ).fetchall()
        return [_row_to_attempt(row) for row in rows]


def _row_to_attempt(row: "tuple[object, ...]") -> UsageAttemptRow:
    """One `run_step` audit row → the calculator's input (AD-18).

    All five counter columns NULL means the provider reported nothing:
    `usage` stays None, honouring 6.1's `ModelCallAttempt.usage` contract.
    """
    model = cast(str, row[2])
    counters = tuple(cast("int | None", column) for column in row[3:8])
    usage = (
        None
        if all(counter is None for counter in counters)
        else ModelUsage(
            model=model,
            input_tokens=counters[0],
            output_tokens=counters[1],
            cache_read_input_tokens=counters[2],
            cache_creation_input_tokens_5m=counters[3],
            cache_creation_input_tokens_1h=counters[4],
        )
    )
    return UsageAttemptRow(
        step=cast(str, row[0]),
        attempt=cast(int, row[1]),
        model=model,
        usage=usage,
    )
