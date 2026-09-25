"""Accepted GitHub events and the run identity they carry (AD-17).

Acceptance is a registry, not an if/elif chain: a new accepted event is a
new tuple entry. Parsing is minimal and defensive — a signed but
unexpected or malformed payload is ignored, never a 500.
"""

from collections.abc import Mapping
from dataclasses import dataclass

__all__ = [
    "ACCEPTED_EVENTS",
    "DELIVERY_HEADER",
    "EVENT_HEADER",
    "RunIdentity",
    "installation_id",
    "is_accepted_event",
    "parse_run_identity",
]

EVENT_HEADER = "X-GitHub-Event"
DELIVERY_HEADER = "X-GitHub-Delivery"

# (event name, action, conclusion) accepted for enqueue. `issue_comment`
# (the SHOULD `/triage` command) and every other conclusion are absent.
ACCEPTED_EVENTS: frozenset[tuple[str, str, str]] = frozenset(
    {("workflow_run", "completed", "failure")}
)


@dataclass(frozen=True)
class RunIdentity:
    """The unique run key: one `triage_run` per (repo, run, attempt) (AD-17)."""

    installation_id: int
    repo_id: int
    workflow_run_id: int
    run_attempt: int


def is_accepted_event(event_name: str, payload: Mapping[str, object]) -> bool:
    action = _str_field(payload, "action")
    workflow_run = _mapping_field(payload, "workflow_run")
    if action is None or workflow_run is None:
        return False
    conclusion = _str_field(workflow_run, "conclusion")
    if conclusion is None:
        return False
    return (event_name, action, conclusion) in ACCEPTED_EVENTS


def installation_id(payload: Mapping[str, object]) -> int | None:
    installation = _mapping_field(payload, "installation")
    return None if installation is None else _int_field(installation, "id")


def parse_run_identity(payload: Mapping[str, object]) -> RunIdentity | None:
    installation = _mapping_field(payload, "installation")
    repository = _mapping_field(payload, "repository")
    workflow_run = _mapping_field(payload, "workflow_run")
    if installation is None or repository is None or workflow_run is None:
        return None
    installation_value = _int_field(installation, "id")
    repo_id = _int_field(repository, "id")
    workflow_run_id = _int_field(workflow_run, "id")
    run_attempt = _int_field(workflow_run, "run_attempt")
    if (
        installation_value is None
        or repo_id is None
        or workflow_run_id is None
        or run_attempt is None
    ):
        return None
    return RunIdentity(
        installation_id=installation_value,
        repo_id=repo_id,
        workflow_run_id=workflow_run_id,
        run_attempt=run_attempt,
    )


def _mapping_field(
    source: Mapping[str, object], key: str
) -> Mapping[str, object] | None:
    value = source.get(key)
    return value if isinstance(value, Mapping) else None


def _str_field(source: Mapping[str, object], key: str) -> str | None:
    value = source.get(key)
    return value if isinstance(value, str) else None


def _int_field(source: Mapping[str, object], key: str) -> int | None:
    value = source.get(key)
    if isinstance(value, bool):  # bool is an int subclass; GitHub sends numbers
        return None
    return value if isinstance(value, int) else None
