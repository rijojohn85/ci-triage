"""AC tests for `workflow/orchestrator_config.py` (AD-19): lease timings live
only in `config/orchestrator.yaml`, read through one loader (story 1.2)."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from workflow.orchestrator_config import (
    ORCHESTRATOR_CONFIG_PATH,
    OrchestratorConfig,
    load_orchestrator_config,
)


def test_ac1_lease_timings_load_from_the_one_config_file() -> None:
    config = load_orchestrator_config()

    assert isinstance(config, OrchestratorConfig)
    assert config.lease_seconds > 0
    assert config.renew_after_seconds > 0
    # A renew must be due well before the lease expires, or a long step
    # would lose its lease while still running (AD-23).
    assert config.renew_after_seconds < config.lease_seconds


def test_ac1_orchestrator_config_is_frozen() -> None:
    config = load_orchestrator_config()
    with pytest.raises(ValidationError):
        config.lease_seconds = 9  # type: ignore[misc]


def test_ac1_missing_lease_section_raises(tmp_path: Path) -> None:
    broken = tmp_path / "orchestrator.yaml"
    broken.write_text("lease_seconds: 300\n", encoding="utf-8")
    with pytest.raises(KeyError):
        load_orchestrator_config(broken)


def _write(tmp_path: Path, lease_seconds: int, renew_after_seconds: int) -> Path:
    path = tmp_path / "orchestrator.yaml"
    path.write_text(
        "lease:\n"
        f"  lease_seconds: {lease_seconds}\n"
        f"  renew_after_seconds: {renew_after_seconds}\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("lease_seconds", "renew_after_seconds"),
    [
        (0, 0),  # non-positive lease
        (300, 0),  # non-positive renew point
        (300, 300),  # renew at expiry: lease is instantly lost
        (300, 400),  # renew after expiry
    ],
)
def test_ac1_unusable_timings_are_refused_at_load(
    tmp_path: Path, lease_seconds: int, renew_after_seconds: int
) -> None:
    path = _write(tmp_path, lease_seconds, renew_after_seconds)
    with pytest.raises(ValidationError):
        load_orchestrator_config(path)


def test_ac1_real_config_still_declares_both_timings() -> None:
    raw = yaml.safe_load(ORCHESTRATOR_CONFIG_PATH.read_text(encoding="utf-8"))
    assert set(raw["lease"]) == {"lease_seconds", "renew_after_seconds"}


# --- story 2.8 / AC2: the AD-22 transient-retry budget lives in the same file


def test_ac2_retry_budget_loads_from_the_one_config_file() -> None:
    config = load_orchestrator_config()

    assert config.retry.max_attempts == 3, "AD-22: at most three transient attempts"
    assert config.retry.backoff_base_seconds > 0
    assert config.retry.backoff_factor == 2, "the growth factor lives in YAML (AD-19)"


def test_ac2_missing_retry_section_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "orchestrator.yaml"
    path.write_text(
        "lease:\n  lease_seconds: 300\n  renew_after_seconds: 120\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_orchestrator_config(path)


def test_ac2_unusable_retry_budget_is_refused_at_load(tmp_path: Path) -> None:
    path = tmp_path / "orchestrator.yaml"
    path.write_text(
        "lease:\n  lease_seconds: 300\n  renew_after_seconds: 120\n"
        "retry:\n  max_attempts: 0\n  backoff_base_seconds: 0\n"
        "  backoff_factor: 0.5\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_orchestrator_config(path)
