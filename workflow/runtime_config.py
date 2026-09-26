"""Per-skill runtime settings: the one `config/runtime.yaml` loader (AD-19).

Model IDs and per-skill `step_timeout` live only in the YAML file — domain
code never carries a model id or a timing literal. Mirrors
`workflow/orchestrator_config.py` and `workflow/thresholds.py` (one file, one
loader, frozen values).

The runner's skill names (`classify`/`analyze`/`propose`/`review`) map onto
the YAML's agent keys (`jev`/`analyzer`/`proposer`/`reviewer`); the mapping is
the module's one vocabulary table (SOLID-O: a new skill is a new entry, not a
new branch).
"""

from pathlib import Path
from typing import cast

import yaml
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "RUNTIME_CONFIG_PATH",
    "SKILL_RUNTIME_KEYS",
    "RuntimeConfig",
    "SkillRuntime",
    "load_runtime_config",
]

RUNTIME_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "runtime.yaml"

SKILL_RUNTIME_KEYS: dict[str, str] = {
    "classify": "jev",
    "analyze": "analyzer",
    "propose": "proposer",
    "review": "reviewer",
}
"""The runner's skill names onto the YAML's agent keys (SOLID-O: a new skill
is a new entry, not a new branch)."""


class SkillRuntime(BaseModel):
    """One agent's pinned model id and its per-skill `step_timeout` (AD-19).

    The YAML key is `step_timeout`; a non-positive timeout is refused at load
    (a step that never times out would hold a lease forever, AD-23).
    """

    model_config = ConfigDict(frozen=True)

    model: str = Field(min_length=1)
    step_timeout: int = Field(gt=0)


class RuntimeConfig(BaseModel):
    """All four agents' runtime settings, frozen once loaded (AD-19)."""

    model_config = ConfigDict(frozen=True)

    jev: SkillRuntime
    analyzer: SkillRuntime
    proposer: SkillRuntime
    reviewer: SkillRuntime

    def for_skill(self, skill: str) -> SkillRuntime:
        """The runtime settings for one runner skill name (story 2.8)."""
        try:
            key = SKILL_RUNTIME_KEYS[skill]
        except KeyError:
            raise ValueError(f"unknown skill {skill!r}") from None
        return cast(SkillRuntime, getattr(self, key))


def load_runtime_config(path: Path = RUNTIME_CONFIG_PATH) -> RuntimeConfig:
    """Read the one runtime config file; no model id or timeout lives in code."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return RuntimeConfig.model_validate(raw)
