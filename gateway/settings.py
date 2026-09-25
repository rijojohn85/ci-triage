"""Gateway settings and load limits (AD-16 secrets, AD-19 limits).

Secrets and the DSN come from the environment (AD-16 names unchanged);
numeric limits come only from `config/gateway.yaml` (AD-19) through one
loader, mirroring `workflow/thresholds.py`.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

__all__ = [
    "GATEWAY_CONFIG_PATH",
    "GatewayLimits",
    "GatewaySettings",
    "load_gateway_limits",
]

GATEWAY_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "gateway.yaml"

_SECRET_ENV = "GITHUB_WEBHOOK_SECRET"
_INSTALLATION_ENV = "GITHUB_APP_INSTALLATION_ID"
_DATABASE_ENV = "DATABASE_URL"
_SEPARATOR = ","


@dataclass(frozen=True)
class GatewaySettings:
    """Environment-sourced gateway settings (names fixed by AD-16)."""

    webhook_secrets: tuple[str, ...]
    allowed_installation_ids: frozenset[int]
    database_url: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "GatewaySettings":
        source = os.environ if env is None else env
        return cls(
            webhook_secrets=_split_secrets(source.get(_SECRET_ENV, "")),
            allowed_installation_ids=frozenset(
                _parse_int_list(source.get(_INSTALLATION_ENV, ""), _INSTALLATION_ENV)
            ),
            database_url=source.get(_DATABASE_ENV, ""),
        )


class GatewayLimits(BaseModel):
    """Values read from `config/gateway.yaml` (AD-19 single source)."""

    model_config = ConfigDict(frozen=True)

    rate_limit_per_installation: int
    rate_limit_window_seconds: int
    max_queue_depth_per_repo: int
    max_body_bytes: int


def load_gateway_limits(path: Path = GATEWAY_CONFIG_PATH) -> GatewayLimits:
    """Read the one gateway config file; no limit literal lives in code."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return GatewayLimits.model_validate(raw["limits"])


def _split_secrets(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(_SEPARATOR) if part.strip())


def _parse_int_list(raw: str, name: str) -> list[int]:
    values: list[int] = []
    for part in raw.split(_SEPARATOR):
        candidate = part.strip()
        if not candidate:
            continue
        if not candidate.isdigit():
            raise ValueError(f"{name} must be a comma-separated list of integers")
        values.append(int(candidate))
    return values
