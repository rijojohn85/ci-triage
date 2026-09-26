"""The pure NULL-aware cost calculator (story 6.2, AD-18).

One rule everywhere (spec "Design Notes"): a missing fact — an unreported
token counter, an unsourced rate — propagates as a NULL cost plus a flag,
never 0 and never dropped. A per-run total is the sum of its parts only
when every part is known; otherwise the total is NULL and the reasons are
listed.

Pure domain only (SOLID-S): no SQL, no I/O. Rates come from a
`PriceTable` (loaded by `monitoring.pricing`); usage comes from
`contracts.usage.ModelUsage`. The orchestrator-side reader that feeds
attempts in lives in `workflow/usage_costs.py`.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from contracts.usage import ModelUsage
from monitoring.pricing import PriceTable, TokenType

__all__ = ["RunCostSummary", "TokenCosts", "cost_of_usage", "summarize_costs"]

_COUNTERS: Final[Mapping[TokenType, Callable[[ModelUsage], int | None]]] = {
    TokenType.INPUT: lambda usage: usage.input_tokens,
    TokenType.OUTPUT: lambda usage: usage.output_tokens,
    TokenType.CACHE_READ: lambda usage: usage.cache_read_input_tokens,
    TokenType.CACHE_WRITE_5M: lambda usage: usage.cache_creation_input_tokens_5m,
    TokenType.CACHE_WRITE_1H: lambda usage: usage.cache_creation_input_tokens_1h,
}


@dataclass(frozen=True)
class TokenCosts:
    """What one model call cost, per token type (AC1).

    A per-type cost is NULL when the counter was unreported, the model is
    unpriced, or the call was Jev-billed (OQ-3) — never a silent 0.
    """

    model: str
    per_type: dict[TokenType, float | None]
    complete: bool
    flags: tuple[str, ...]


@dataclass(frozen=True)
class RunCostSummary:
    """The per-run rollup: totals plus the reasons for any incompleteness."""

    per_type: dict[TokenType, float | None]
    complete: bool
    reasons: tuple[str, ...]


def cost_of_usage(usage: ModelUsage, table: PriceTable, *, jev: bool) -> TokenCosts:
    """Price one attempt's usage; missing facts become NULL + flag (AC2)."""
    if jev:
        return TokenCosts(
            model=usage.model,
            per_type={token_type: None for token_type in TokenType},
            complete=False,
            flags=("jev_unpriced",),
        )
    rates = table.models.get(usage.model)
    if rates is None:
        return TokenCosts(
            model=usage.model,
            per_type={token_type: None for token_type in TokenType},
            complete=False,
            flags=("model_unpriced",),
        )

    per_type: dict[TokenType, float | None] = {}
    flags: list[str] = []
    for token_type in TokenType:
        counter = _COUNTERS[token_type](usage)
        if counter is None:
            per_type[token_type] = None
            flags.append(f"{token_type.value}_unreported")
        else:
            per_type[token_type] = counter * rates.usd_per_mtok[token_type] / 1_000_000
    return TokenCosts(
        model=usage.model,
        per_type=per_type,
        complete=not flags,
        flags=tuple(flags),
    )


def summarize_costs(costs: Iterable[TokenCosts]) -> RunCostSummary:
    """Roll attempts into per-run totals; incomplete parts NULL the total.

    One rule (spec "Design Notes"): the run total is the sum of its parts
    only when every part is known — any incomplete or Jev-billed attempt
    turns every per-type total NULL, with the reasons listed.
    """
    attempts = list(costs)
    reasons = _incompleteness_reasons(attempts)
    per_type: dict[TokenType, float | None] = {}
    if reasons:
        for token_type in TokenType:
            per_type[token_type] = None
    else:
        for token_type in TokenType:
            parts = [attempt.per_type[token_type] for attempt in attempts]
            per_type[token_type] = sum(part for part in parts if part is not None)
    return RunCostSummary(per_type=per_type, complete=not reasons, reasons=reasons)


def _incompleteness_reasons(attempts: list[TokenCosts]) -> tuple[str, ...]:
    """The distinct flags of the incomplete attempts, in first-seen order."""
    reasons: list[str] = []
    for attempt in attempts:
        if attempt.complete:
            continue
        for flag in attempt.flags:
            if flag not in reasons:
                reasons.append(flag)
    return tuple(reasons)
