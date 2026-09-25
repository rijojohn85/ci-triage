"""Worker lease timings: the one config file, one loader (AD-19, AD-23).

Pure config I/O edge, separated from the lease decision logic (SOLID-S):
`lease_seconds` and `renew_after_seconds` live only in
`config/orchestrator.yaml` — domain code never carries a timing literal.
Mirrors `workflow/thresholds.py`.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

__all__ = [
    "ORCHESTRATOR_CONFIG_PATH",
    "OrchestratorConfig",
    "load_orchestrator_config",
]

ORCHESTRATOR_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "orchestrator.yaml"
)


class OrchestratorConfig(BaseModel):
    """Values read from `config/orchestrator.yaml` (AD-19 single source).

    A lease must last a positive time and the renew point must come before
    the lease ends, or a long step would lose the run while it is still
    working (AD-23). A file that breaks either rule is refused at load.
    """

    model_config = ConfigDict(frozen=True)

    lease_seconds: int
    renew_after_seconds: int

    @model_validator(mode="after")
    def _timings_are_usable(self) -> "OrchestratorConfig":
        if self.lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if self.renew_after_seconds <= 0:
            raise ValueError("renew_after_seconds must be positive")
        if self.renew_after_seconds >= self.lease_seconds:
            raise ValueError("renew_after_seconds must be smaller than lease_seconds")
        return self


def load_orchestrator_config(
    path: Path = ORCHESTRATOR_CONFIG_PATH,
) -> OrchestratorConfig:
    """Read the one orchestrator config file; no timing literal lives in code."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return OrchestratorConfig.model_validate(raw["lease"])
