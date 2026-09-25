"""Thresholds reader: the one config file, one loader (AD-19).

Pure config I/O edge, separated from the pure state-machine module
(SOLID-S): values live only in `guardrails/thresholds.yaml` — domain code
never carries a threshold literal.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

__all__ = ["THRESHOLDS_PATH", "ReviewThresholds", "load_thresholds"]

THRESHOLDS_PATH = (
    Path(__file__).resolve().parent.parent / "guardrails" / "thresholds.yaml"
)


class ReviewThresholds(BaseModel):
    """Values read from `guardrails/thresholds.yaml` (AD-19 single source)."""

    model_config = ConfigDict(frozen=True)

    review_max_rounds: int
    workflow_path_glob: str


def load_thresholds(path: Path = THRESHOLDS_PATH) -> ReviewThresholds:
    """Read the one thresholds file; no threshold literal lives in code."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    review = raw["review"]
    return ReviewThresholds(
        review_max_rounds=int(review["max_rounds"]),
        workflow_path_glob=str(raw["workflow_path_glob"]),
    )
