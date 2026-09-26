"""The Jev agent's one-key reader of `config/runtime.yaml` (AD-19).

Model id and `step_timeout` live only in the YAML; no model id or timing
literal lives in code. The agents layer may not import `workflow/` (spine
layer table), so this is the jev-key counterpart of
`workflow.runtime_config`'s full loader — the values stay single-sourced in
the one file.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "RUNTIME_CONFIG_PATH",
    "JevRuntime",
    "RuntimeConfigError",
    "load_jev_runtime",
]

RUNTIME_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "runtime.yaml"
)


class RuntimeConfigError(ValueError):
    """The runtime config file carries no usable `jev` settings (AD-19)."""


class JevRuntime(BaseModel):
    """The pinned Jev model id, its per-skill `step_timeout` and the serve
    host/port (AD-19).

    A non-positive timeout or port is refused at load (a step that never
    times out would hold a lease forever, AD-23).
    """

    model_config = ConfigDict(frozen=True)

    model: str = Field(min_length=1)
    step_timeout: int = Field(gt=0)
    host: str = Field(default="0.0.0.0", min_length=1)
    port: int = Field(default=8080, gt=0)


def load_jev_runtime(path: Path = RUNTIME_CONFIG_PATH) -> JevRuntime:
    """Read the `jev` key of the one runtime config file.

    A missing or empty `jev` key is a config error, not a raw KeyError — the
    failure names the file and the rule (AD-19).
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    settings = raw.get("jev") if isinstance(raw, dict) else None
    if not isinstance(settings, dict):
        raise RuntimeConfigError(f"{path} carries no 'jev' settings (AD-19)")
    return JevRuntime.model_validate(settings)
