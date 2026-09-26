"""The versioned price table and its one loader (story 6.2, AD-18, AD-19).

Rates live only in `monitoring/prices.yaml` — never in code. The loader
mirrors `workflow/thresholds.py`: frozen Pydantic models, sanity checks,
one reader for one YAML file. Every non-Jev model must carry all five
per-token-type rates plus provenance (source URL + retrieved date); the
Jev entry stays NULL + flagged until a sourced rate replaces it (OQ-3).
"""

import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

__all__ = [
    "PRICES_PATH",
    "JevRate",
    "ModelRates",
    "PriceTable",
    "PriceTableError",
    "TokenType",
    "load_prices",
]

PRICES_PATH = Path(__file__).resolve().parent / "prices.yaml"


class TokenType(str, Enum):
    """The five distinct token types (AD-18); each is priced on its own."""

    INPUT = "input"
    OUTPUT = "output"
    CACHE_READ = "cache_read"
    CACHE_WRITE_5M = "cache_write_5m"
    CACHE_WRITE_1H = "cache_write_1h"


class ModelRates(BaseModel):
    """One model's per-type rates plus provenance (AC1, AD-18)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    usd_per_mtok: dict[TokenType, Annotated[float, Field(ge=0)]]
    source_url: str
    retrieved: datetime.date


class JevRate(BaseModel):
    """The Jev (system_one) billing entry: NULL + flagged until sourced (OQ-3).

    The calculator does not read this entry yet: replacing `rate: null`
    with a sourced rate later is a YAML edit plus a small wiring change in
    `monitoring/costs.py` once the billing units are known (AD-19).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rate: float | None = Field(default=None, ge=0)
    flagged: bool
    source_url: str | None = None
    retrieved: datetime.date | None = None


class PriceTable(BaseModel):
    """The whole `monitoring/prices.yaml` table (AD-19 single source)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    table_version: int = Field(ge=1)
    models: dict[str, ModelRates]
    jev: dict[str, JevRate] = {}


class PriceTableError(Exception):
    """The price table is unusable: unversioned, incomplete or unsourced."""


def load_prices(path: Path = PRICES_PATH) -> PriceTable:
    """Read the one price file and refuse anything incomplete or unsourced."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PriceTableError(f"{path}: unreadable price table — {exc}") from exc
    try:
        table = PriceTable.model_validate(raw)
    except ValidationError as exc:
        raise PriceTableError(f"{path}: invalid price table — {exc}") from exc
    _sanity_checks(table, path)
    return table


def _sanity_checks(table: PriceTable, path: Path) -> None:
    """Structural checks beyond the schema: completeness and provenance."""
    for model, rates in table.models.items():
        missing = set(TokenType) - set(rates.usd_per_mtok)
        if missing:
            names = sorted(t.value for t in missing)
            raise PriceTableError(f"{path}: {model} is missing rates for {names}")
        if not rates.source_url:
            raise PriceTableError(f"{path}: {model} needs a source_url")
    for system, entry in table.jev.items():
        if entry.rate is None:
            if not entry.flagged:
                raise PriceTableError(
                    f"{path}: unpriced Jev entry {system!r} must be flagged (OQ-3)"
                )
        else:
            if entry.flagged:
                raise PriceTableError(
                    f"{path}: priced Jev entry {system!r} must not stay flagged"
                )
            if entry.source_url is None or entry.retrieved is None:
                raise PriceTableError(
                    f"{path}: priced Jev entry {system!r} needs a source_url "
                    "and a retrieved date"
                )
