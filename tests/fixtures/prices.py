"""Test-only price table: an inline `PriceTable` with known rates, never the
real `monitoring/prices.yaml`, so repricing the real table (a YAML edit)
can never break a test (mirrors `tests/fixtures/thresholds.py`)."""

import datetime
from typing import Final

from contracts.usage import ModelUsage
from monitoring.pricing import JevRate, ModelRates, PriceTable, TokenType

HAIKU: Final[str] = "claude-haiku-4-5-20251001"

FIXTURE_TABLE: Final[PriceTable] = PriceTable(
    table_version=1,
    models={
        HAIKU: ModelRates(
            usd_per_mtok={
                TokenType.INPUT: 1.0,
                TokenType.OUTPUT: 5.0,
                TokenType.CACHE_READ: 0.10,
                TokenType.CACHE_WRITE_5M: 1.25,
                TokenType.CACHE_WRITE_1H: 2.0,
            },
            source_url="https://example.com/pricing",
            retrieved=datetime.date(2026, 9, 26),
        )
    },
    jev={"system_one": JevRate(rate=None, flagged=True)},
)

FULL_USAGE: Final[ModelUsage] = ModelUsage(
    model=HAIKU,
    input_tokens=1200,
    output_tokens=340,
    cache_read_input_tokens=512,
    cache_creation_input_tokens_5m=64,
    cache_creation_input_tokens_1h=128,
)
