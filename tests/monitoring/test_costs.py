"""Story 6.2 unit tests — the pure NULL-aware cost calculator (AC1/AC2).

`monitoring/costs.py` is pure: no I/O, no database, no clock. The price
table is the shared inline fixture with known rates
(`tests/fixtures/prices.py`) so the arithmetic per token type is checked
independently of the shipped `monitoring/prices.yaml` (which
`tests/monitoring/test_pricing.py` verifies).
"""

import pytest

from contracts.usage import ModelUsage
from monitoring.costs import RunCostSummary, TokenCosts, cost_of_usage, summarize_costs
from monitoring.pricing import TokenType
from tests.fixtures.prices import FIXTURE_TABLE, FULL_USAGE, HAIKU

UNPRICED = "claude-opus-9"


def test_ac1_each_token_type_is_priced_distinctly() -> None:
    costs = cost_of_usage(FULL_USAGE, FIXTURE_TABLE, jev=False)

    assert costs.per_type[TokenType.INPUT] == pytest.approx(0.0012)  # 1200 x $1/MTok
    assert costs.per_type[TokenType.OUTPUT] == pytest.approx(0.0017)  # 340 x $5/MTok
    assert costs.per_type[TokenType.CACHE_READ] == pytest.approx(
        0.0000512
    )  # 512 x $0.10/MTok
    assert costs.per_type[TokenType.CACHE_WRITE_5M] == pytest.approx(
        0.00008
    )  # 64 x $1.25/MTok
    assert costs.per_type[TokenType.CACHE_WRITE_1H] == pytest.approx(
        0.000256
    )  # 128 x $2/MTok
    assert costs.complete is True
    assert costs.flags == ()


def test_ac1_cache_write_tiers_stay_distinct() -> None:
    usage = ModelUsage(
        model=HAIKU,
        input_tokens=0,
        output_tokens=0,
        cache_read_input_tokens=0,
        cache_creation_input_tokens_5m=100,
        cache_creation_input_tokens_1h=100,
    )

    costs = cost_of_usage(usage, FIXTURE_TABLE, jev=False)

    assert costs.per_type[TokenType.CACHE_WRITE_5M] == pytest.approx(
        100 * 1.25 / 1_000_000
    )
    assert costs.per_type[TokenType.CACHE_WRITE_1H] == pytest.approx(
        100 * 2.0 / 1_000_000
    )
    five_m = costs.per_type[TokenType.CACHE_WRITE_5M]
    one_h = costs.per_type[TokenType.CACHE_WRITE_1H]
    assert five_m < one_h, "the 5m and 1h write tiers are priced at their own rates"
    # A reported 0 is a real value: it prices to 0 and stays complete.
    assert costs.per_type[TokenType.INPUT] == pytest.approx(0.0)
    assert costs.complete is True


def test_ac2_unreported_counter_yields_null_cost_not_zero() -> None:
    partial = ModelUsage(model=HAIKU, input_tokens=1200)

    costs = cost_of_usage(partial, FIXTURE_TABLE, jev=False)

    assert costs.per_type[TokenType.INPUT] == pytest.approx(0.0012), (
        "the reported type is still priced"
    )
    assert costs.per_type[TokenType.OUTPUT] is None, "NULL, never a silent 0"
    assert costs.per_type[TokenType.CACHE_READ] is None
    assert costs.per_type[TokenType.CACHE_WRITE_5M] is None
    assert costs.per_type[TokenType.CACHE_WRITE_1H] is None
    assert costs.complete is False
    assert costs.flags == (
        "output_unreported",
        "cache_read_unreported",
        "cache_write_5m_unreported",
        "cache_write_1h_unreported",
    )


def test_ac2_jev_call_cost_is_null_and_flagged() -> None:
    costs = cost_of_usage(FULL_USAGE, FIXTURE_TABLE, jev=True)

    assert all(costs.per_type[token_type] is None for token_type in TokenType), (
        "OQ-3: the Jev rate is unresolved — no estimate, no zero"
    )
    assert costs.complete is False
    assert costs.flags == ("jev_unpriced",)


def test_ac2_unpriced_model_yields_null_cost_and_flag() -> None:
    usage = ModelUsage(model=UNPRICED, input_tokens=10)

    costs = cost_of_usage(usage, FIXTURE_TABLE, jev=False)

    assert all(costs.per_type[token_type] is None for token_type in TokenType), (
        "AD-18: an unpriced model yields a NULL cost, flagged"
    )
    assert costs.complete is False
    assert costs.flags == ("model_unpriced",)


def test_ac2_run_total_with_incomplete_parts_is_null_and_flagged() -> None:
    complete = cost_of_usage(FULL_USAGE, FIXTURE_TABLE, jev=False)
    partial = ModelUsage(model=HAIKU, input_tokens=10)
    incomplete = cost_of_usage(partial, FIXTURE_TABLE, jev=False)

    summary = summarize_costs([complete, incomplete])

    assert all(summary.per_type[token_type] is None for token_type in TokenType), (
        "a total is the sum of its parts only when every part is known"
    )
    assert summary.complete is False
    assert "output_unreported" in summary.reasons, "the reasons are listed"


def test_ac2_complete_run_total_sums_cleanly() -> None:
    first = cost_of_usage(FULL_USAGE, FIXTURE_TABLE, jev=False)
    second = cost_of_usage(FULL_USAGE, FIXTURE_TABLE, jev=False)

    summary = summarize_costs([first, second])

    assert summary.per_type[TokenType.INPUT] == pytest.approx(0.0024)
    assert summary.per_type[TokenType.OUTPUT] == pytest.approx(0.0034)
    assert summary.complete is True
    assert summary.reasons == ()


def test_ac2_run_with_no_attempts_is_complete_at_zero() -> None:
    summary = summarize_costs([])

    assert summary.complete is True
    assert all(
        summary.per_type[token_type] == pytest.approx(0.0) for token_type in TokenType
    )
    assert summary.reasons == ()


def test_ac1_cost_values_are_frozen() -> None:
    costs = cost_of_usage(FULL_USAGE, FIXTURE_TABLE, jev=False)
    summary = summarize_costs([costs])

    assert isinstance(costs, TokenCosts)
    assert isinstance(summary, RunCostSummary)
    with pytest.raises((TypeError, ValueError, AttributeError)):
        costs.complete = True  # type: ignore[misc]
    with pytest.raises((TypeError, ValueError, AttributeError)):
        summary.complete = False  # type: ignore[misc]
