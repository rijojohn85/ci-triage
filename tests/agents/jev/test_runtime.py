"""AC1: model id and timeout come only from `config/runtime.yaml` (AD-19).

The agents layer may not import `workflow/` (spine layer table), so this is
the jev-key reader of the same file the workflow's full loader reads — the
values stay single-sourced in the YAML.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.jev.runtime import RuntimeConfigError, load_jev_runtime

PINNED_STEP_TIMEOUT = 60


def test_ac1_model_and_timeout_from_runtime_yaml() -> None:
    runtime = load_jev_runtime()

    assert runtime.model == "typesafe/jev-1.13", "the pinned Jev model id (AD-19)"
    assert runtime.step_timeout == PINNED_STEP_TIMEOUT


def test_ac1_non_positive_timeout_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "runtime.yaml"
    path.write_text("jev:\n  model: typesafe/jev-1.13\n  step_timeout: 0\n")

    with pytest.raises(ValidationError):
        load_jev_runtime(path)


def test_ac1_missing_or_empty_jev_key_is_a_typed_config_error(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.yaml"
    missing.write_text("analyzer:\n  model: x\n  step_timeout: 1\n")
    empty = tmp_path / "empty.yaml"
    empty.write_text("jev:\n")

    with pytest.raises(RuntimeConfigError) as missing_error:
        load_jev_runtime(missing)
    with pytest.raises(RuntimeConfigError):
        load_jev_runtime(empty)

    assert "jev" in str(missing_error.value)
