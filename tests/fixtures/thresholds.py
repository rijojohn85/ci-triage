"""Test-only thresholds: loaded from `thresholds.test.yaml`, never the real
`guardrails/thresholds.yaml`, so recalibrating the real numbers (OQ-2) can
never break a test."""

from pathlib import Path
from typing import Final

from guardrails.confidence import ConfidenceCutoffs
from workflow.thresholds import load_thresholds

FIXTURE_THRESHOLDS_PATH: Final[Path] = (
    Path(__file__).resolve().parent / "thresholds.test.yaml"
)
FIXTURE_CUTOFFS: Final[ConfidenceCutoffs] = load_thresholds(
    FIXTURE_THRESHOLDS_PATH
).confidence
