"""Story 6.2 unit tests — the versioned price table and its one loader (AC1/AC2).

The shipped `monitoring/prices.yaml` is loaded and checked for versioning,
per-type rates and provenance; the loader's refusals are driven through
inline YAML fixtures in `tmp_path`, never the real file (mirrors
`tests/workflow/test_thresholds.py`).
"""

import datetime
from pathlib import Path

import pytest

from monitoring.pricing import (
    PRICES_PATH,
    JevRate,
    PriceTableError,
    TokenType,
    load_prices,
)

CLAUDE_SOURCE_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
CLAUDE_RETRIEVED = datetime.date(2026, 9, 26)
HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-5"
TOKEN_TYPES = frozenset(TokenType)


def test_ac1_price_table_is_versioned_with_provenance() -> None:
    table = load_prices()

    assert table.table_version >= 1, "the table is versioned"
    assert HAIKU in table.models and SONNET in table.models, (
        "both allowed Claude models are priced"
    )
    for model, rates in table.models.items():
        assert set(rates.usd_per_mtok) == TOKEN_TYPES, (
            f"{model}: all five token types are priced distinctly"
        )
        assert rates.source_url, f"{model}: rate source URL is recorded"
        assert rates.retrieved is not None, f"{model}: retrieved date is recorded"


def test_ac2_claude_rates_are_sourced_with_url_and_date() -> None:
    table = load_prices()

    for model in (HAIKU, SONNET):
        rates = table.models[model]
        assert rates.source_url == CLAUDE_SOURCE_URL, model
        assert rates.retrieved == CLAUDE_RETRIEVED, model

    haiku = table.models[HAIKU]
    assert haiku.usd_per_mtok[TokenType.INPUT] == pytest.approx(1.0)
    assert haiku.usd_per_mtok[TokenType.OUTPUT] == pytest.approx(5.0)
    assert haiku.usd_per_mtok[TokenType.CACHE_READ] == pytest.approx(0.10)
    assert haiku.usd_per_mtok[TokenType.CACHE_WRITE_5M] == pytest.approx(1.25)
    assert haiku.usd_per_mtok[TokenType.CACHE_WRITE_1H] == pytest.approx(2.0)

    sonnet = table.models[SONNET]
    assert sonnet.usd_per_mtok[TokenType.INPUT] == pytest.approx(2.0)
    assert sonnet.usd_per_mtok[TokenType.OUTPUT] == pytest.approx(10.0)
    assert sonnet.usd_per_mtok[TokenType.CACHE_READ] == pytest.approx(0.20)
    assert sonnet.usd_per_mtok[TokenType.CACHE_WRITE_5M] == pytest.approx(2.50)
    assert sonnet.usd_per_mtok[TokenType.CACHE_WRITE_1H] == pytest.approx(4.0)


def test_ac2_jev_rate_is_null_and_flagged() -> None:
    table = load_prices()

    (system_one,) = table.jev.values()
    assert system_one.rate is None, (
        "OQ-3: the Jev rate is unresolved — no estimate is substituted"
    )
    assert system_one.flagged, "the unpriced Jev entry is visibly flagged"


def test_ac2_loader_refuses_an_unsourced_claude_model(tmp_path: Path) -> None:
    unsourced = tmp_path / "prices.yaml"
    unsourced.write_text(
        "\n".join(
            [
                "table_version: 1",
                "models:",
                f"  {HAIKU}:",
                "    usd_per_mtok:",
                "      input: 1.0",
                "      output: 5.0",
                "      cache_read: 0.1",
                "      cache_write_5m: 1.25",
                "      cache_write_1h: 2.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PriceTableError):
        load_prices(unsourced)


def test_ac2_loader_refuses_an_incomplete_rate_set(tmp_path: Path) -> None:
    incomplete = tmp_path / "prices.yaml"
    incomplete.write_text(
        "\n".join(
            [
                "table_version: 1",
                "models:",
                f"  {HAIKU}:",
                "    usd_per_mtok:",
                "      input: 1.0",
                "      output: 5.0",
                f"    source_url: {CLAUDE_SOURCE_URL}",
                "    retrieved: 2026-09-26",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PriceTableError):
        load_prices(incomplete)


def test_ac2_loader_refuses_a_priced_jev_entry_that_stays_flagged(
    tmp_path: Path,
) -> None:
    contradictory = tmp_path / "prices.yaml"
    contradictory.write_text(
        "\n".join(
            [
                "table_version: 1",
                "models: {}",
                "jev:",
                "  system_one:",
                "    rate: 0.5",
                "    flagged: true",
                f"    source_url: {CLAUDE_SOURCE_URL}",
                "    retrieved: 2026-09-26",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PriceTableError):
        load_prices(contradictory)


def test_ac2_loader_refuses_a_negative_rate(tmp_path: Path) -> None:
    negative = tmp_path / "prices.yaml"
    negative.write_text(
        "\n".join(
            [
                "table_version: 1",
                "models:",
                f"  {HAIKU}:",
                "    usd_per_mtok:",
                "      input: -1.0",
                "      output: 5.0",
                "      cache_read: 0.1",
                "      cache_write_5m: 1.25",
                "      cache_write_1h: 2.0",
                f"    source_url: {CLAUDE_SOURCE_URL}",
                "    retrieved: 2026-09-26",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PriceTableError):
        load_prices(negative)


def test_ac2_loader_refuses_an_unversioned_table(tmp_path: Path) -> None:
    unversioned = tmp_path / "prices.yaml"
    unversioned.write_text("models: {}\n", encoding="utf-8")

    with pytest.raises(PriceTableError):
        load_prices(unversioned)


def test_ac1_price_models_are_frozen() -> None:
    table = load_prices()

    with pytest.raises((TypeError, ValueError)):
        table.models[HAIKU].source_url = "https://elsewhere.example"  # type: ignore[misc]
    with pytest.raises((TypeError, ValueError)):
        table.jev["system_one"].flagged = False  # type: ignore[misc]


def test_ac1_default_path_is_the_one_price_table() -> None:
    assert PRICES_PATH.name == "prices.yaml"
    assert PRICES_PATH.parent.name == "monitoring"


def test_ac2_jev_rate_model_keeps_the_null_semantics() -> None:
    # The Jev entry is data (AD-19): a later sourced rate is a YAML edit,
    # so the model must accept a rate once provenance exists.
    sourced = JevRate(
        rate=0.5,
        flagged=False,
        source_url="https://example.com/pricing",
        retrieved=datetime.date(2026, 9, 26),
    )
    assert sourced.rate == pytest.approx(0.5)
    assert JevRate(rate=None, flagged=True).rate is None
