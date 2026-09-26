"""Test-only thresholds: loaded from `thresholds.test.yaml`, never the real
`guardrails/thresholds.yaml`, so recalibrating the real numbers (OQ-2) can
never break a test."""

from pathlib import Path
from typing import Final

from guardrails.confidence import ConfidenceCutoffs
from workflow.thresholds import DistillerLimits, Thresholds, load_thresholds

FIXTURE_THRESHOLDS_PATH: Final[Path] = (
    Path(__file__).resolve().parent / "thresholds.test.yaml"
)
_FIXTURE_THRESHOLDS = load_thresholds(FIXTURE_THRESHOLDS_PATH)
FIXTURE_THRESHOLDS: Final[Thresholds] = _FIXTURE_THRESHOLDS
FIXTURE_CUTOFFS: Final[ConfidenceCutoffs] = _FIXTURE_THRESHOLDS.confidence
FIXTURE_DISTILLER_LIMITS: Final[DistillerLimits] = _FIXTURE_THRESHOLDS.distiller
