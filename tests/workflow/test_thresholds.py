"""AC tests for `workflow/thresholds.py`'s rename and confidence section
(AD-19, story 2.2): one loader, the confidence cutoffs read from
`guardrails/thresholds.yaml`; tests read the fixture copy, never the real
file (spec-2.2 Boundaries & Constraints)."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from guardrails.confidence import ConfidenceCutoffs
from tests.fixtures.thresholds import FIXTURE_THRESHOLDS_PATH
from workflow.thresholds import (
    THRESHOLDS_PATH,
    DistillerLimits,
    Thresholds,
    load_thresholds,
)

FIXTURE = FIXTURE_THRESHOLDS_PATH


def test_ac3_thresholds_loads_confidence_cutoffs_from_the_fixture() -> None:
    thresholds = load_thresholds(FIXTURE)
    assert isinstance(thresholds, Thresholds)
    assert thresholds.review_max_rounds == 2
    assert thresholds.workflow_path_glob == ".github/workflows/**"
    assert isinstance(thresholds.confidence, ConfidenceCutoffs)
    assert thresholds.confidence.class_cutoff == 0.75
    assert thresholds.confidence.no_route_cutoff == 0.6
    assert thresholds.confidence.injection_screen_cutoff == 0.5
    assert thresholds.confidence.injection_screen_cap == 0.5


def test_ac3_distiller_max_bytes_loads_from_fixture() -> None:
    thresholds = load_thresholds(FIXTURE)
    assert isinstance(thresholds.distiller, DistillerLimits)
    assert thresholds.distiller.max_bytes == 4096


def test_ac3_thresholds_is_frozen() -> None:
    thresholds = load_thresholds(FIXTURE)
    with pytest.raises(ValidationError):
        thresholds.review_max_rounds = 9  # type: ignore[misc]


def test_ac3_unknown_confidence_key_raises(tmp_path: Path) -> None:
    misspelled = tmp_path / "thresholds.yaml"
    misspelled.write_text(
        FIXTURE.read_text(encoding="utf-8").replace("class_cutoff", "class_cuttoff"),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_thresholds(misspelled)


def _key_paths(node: object) -> set[tuple[str, ...]]:
    """Recursive key paths of a nested mapping; values are not compared."""
    if not isinstance(node, dict):
        return set()
    paths: set[tuple[str, ...]] = set()
    for key, value in node.items():
        paths.add((key,))
        paths.update((key, *sub) for sub in _key_paths(value))
    return paths


def test_ac3_fixture_and_real_thresholds_have_the_same_keys() -> None:
    real = yaml.safe_load(THRESHOLDS_PATH.read_text(encoding="utf-8"))
    fixture = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    assert _key_paths(real) == _key_paths(fixture)
