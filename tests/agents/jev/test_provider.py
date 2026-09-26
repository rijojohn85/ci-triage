"""The real adapter's one coverage: a stub client records what is forwarded.

`TypeSafeJevProvider` is the only module that touches the SDK client; the
stub rides the `SystemOneClient` seam (SOLID-D) — no real model, no network.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from agents.jev.provider import TypeSafeJevProvider

STATE = "the delimited state"
MODEL = "typesafe/jev-1.13"
TIMEOUT = 60.0
EXPECTED_CALLS = 2


@dataclass
class RecordingClient:
    """A `SystemOneClient` stub that records each call's arguments."""

    calls: list[dict[str, Any]] = field(default_factory=list)

    async def system_one(
        self,
        state: str,
        questions: Mapping[str, Any],
        *,
        model: str,
        timeout: float,
    ) -> Any:
        self.calls.append(
            {"state": state, "questions": questions, "model": model, "timeout": timeout}
        )
        return "sentinel"


def test_adapter_forwards_the_call_unchanged_to_one_client() -> None:
    client = RecordingClient()
    provider = TypeSafeJevProvider(client)
    questions: Mapping[str, Any] = {"choice": object(), "noul": object()}

    asyncio.run(
        provider.system_one(
            state=STATE, questions=questions, model=MODEL, timeout=TIMEOUT
        )
    )
    asyncio.run(
        provider.system_one(
            state=STATE, questions=questions, model=MODEL, timeout=TIMEOUT
        )
    )

    assert len(client.calls) == EXPECTED_CALLS, "the client is built once and reused"
    for call in client.calls:
        assert call["state"] == STATE
        assert call["questions"] is questions
        assert call["model"] == MODEL
        assert call["timeout"] == TIMEOUT
