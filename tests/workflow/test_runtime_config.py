"""Story 2.8 tests for `workflow/runtime_config.py` (AC3, AD-19).

Model IDs and per-skill `step_timeout` live only in `config/runtime.yaml`,
read through this one loader — never a literal in code (AD-19).
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from workflow.runtime_config import (
    RUNTIME_CONFIG_PATH,
    RuntimeConfig,
    load_runtime_config,
)


def test_ac3_per_skill_timeouts_load_from_the_one_config_file() -> None:
    config = load_runtime_config()

    assert isinstance(config, RuntimeConfig)
    assert config.for_skill("classify").step_timeout == 60
    assert config.for_skill("analyze").step_timeout == 120
    assert config.for_skill("propose").step_timeout == 180
    assert config.for_skill("review").step_timeout == 180


def test_ac3_per_skill_model_ids_load_from_the_one_config_file() -> None:
    config = load_runtime_config()

    assert config.for_skill("classify").model == "typesafe/jev-1.13"
    assert config.for_skill("analyze").model == "claude-haiku-4-5-20251001"
    assert config.for_skill("propose").model == "claude-sonnet-5"
    assert config.for_skill("review").model == "claude-sonnet-5"


def test_ac3_runtime_config_is_frozen() -> None:
    config = load_runtime_config()

    with pytest.raises(ValidationError):
        config.analyzer.step_timeout = 1  # type: ignore[misc]


def test_ac3_unknown_skill_is_refused() -> None:
    config = load_runtime_config()

    with pytest.raises(ValueError):
        config.for_skill("distill")


def test_ac3_non_positive_timeout_is_refused_at_load(tmp_path: Path) -> None:
    path = tmp_path / "runtime.yaml"
    path.write_text(
        "jev:\n  model: typesafe/jev-1.13\n  step_timeout: 0\n"
        "analyzer:\n  model: m\n  step_timeout: 1\n"
        "proposer:\n  model: m\n  step_timeout: 1\n"
        "reviewer:\n  model: m\n  step_timeout: 1\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_runtime_config(path)


def test_ac3_real_config_declares_all_four_skills() -> None:
    raw = yaml.safe_load(RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))

    assert set(raw) == {"jev", "analyzer", "proposer", "reviewer"}
    for key in ("analyzer", "proposer", "reviewer"):
        assert set(raw[key]) == {"model", "step_timeout"}
    # jev also pins its serve host/port (story 3.1, AD-19).
    assert set(raw["jev"]) == {"model", "step_timeout", "host", "port"}
