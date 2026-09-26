"""Thresholds reader: the one config file, one loader (AD-19).

Pure config I/O edge, separated from the pure state-machine module
(SOLID-S): values live only in `guardrails/thresholds.yaml` — domain code
never carries a threshold literal.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, PositiveInt

from guardrails.confidence import ConfidenceCutoffs

__all__ = [
    "THRESHOLDS_PATH",
    "DistillerLimits",
    "Thresholds",
    "load_thresholds",
]

THRESHOLDS_PATH = (
    Path(__file__).resolve().parent.parent / "guardrails" / "thresholds.yaml"
)


class DistillerLimits(BaseModel):
    """The distilled-log byte bound (AD-19, AD-20): the most evidence text the
    distiller may keep, so a huge raw log can never reach a model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_bytes: PositiveInt


class EvidenceLimits(BaseModel):
    """Bounds on the evidence pack (AD-19, AD-20): the distilled-log byte cap
    plus the most history rows served, so a chronically recurring failure
    cannot grow every agent's context without limit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    distiller: DistillerLimits
    max_history_rows: PositiveInt


class Thresholds(BaseModel):
    """Values read from `guardrails/thresholds.yaml` (AD-19 single source)."""

    model_config = ConfigDict(frozen=True)

    review_max_rounds: int
    workflow_path_glob: str
    confidence: ConfidenceCutoffs
    distiller: DistillerLimits
    evidence: EvidenceLimits


def load_thresholds(path: Path = THRESHOLDS_PATH) -> Thresholds:
    """Read the one thresholds file; no threshold literal lives in code."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    review = raw["review"]
    distiller = DistillerLimits.model_validate(raw["distiller"])
    return Thresholds(
        review_max_rounds=int(review["max_rounds"]),
        workflow_path_glob=str(raw["workflow_path_glob"]),
        confidence=ConfidenceCutoffs.model_validate(raw["confidence"]),
        distiller=distiller,
        evidence=EvidenceLimits(distiller=distiller, **raw["evidence"]),
    )
