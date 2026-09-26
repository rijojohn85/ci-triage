"""The real adapter's coverage: a stub client records what is forwarded.

`TypeSafeJevProvider` is the only module that touches the SDK client; the
stub rides the `SystemOneClient` seam (SOLID-D) — no real model, no network.
F9 (AD-18): the SDK's own retry layer is disabled — client built with
`RetryPolicy(max_retries=0)` and every call carries the same override — so
the workflow's step runner is the ONLY retry layer, and a 503 surfaces as
one attempt and a retryable `AgentError`.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx2
import pytest
from typesafe_sdk import (
    AsyncTypeSafeClient,
    Noul,
    RetryPolicy,
    TypeSafeInternalServerError,
)

import agents.jev.provider as provider_module
from agents.jev.provider import TypeSafeJevProvider

STATE = "the delimited state"
MODEL = "typesafe/jev-1.13"
TIMEOUT = 60.0
EXPECTED_CALLS = 2
NO_RETRIES = 0


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
        retry: Any = None,
    ) -> Any:
        self.calls.append(
            {
                "state": state,
                "questions": questions,
                "model": model,
                "timeout": timeout,
                "retry": retry,
            }
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


def test_adapter_builds_the_client_with_sdk_retries_disabled() -> None:
    built: list[dict[str, Any]] = []

    class RecordingConstructor:
        def __init__(self, **kwargs: Any) -> None:
            built.append(kwargs)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(provider_module, "AsyncTypeSafeClient", RecordingConstructor)
    try:
        TypeSafeJevProvider()
    finally:
        monkeypatch.undo()

    assert built == [{"retry": RetryPolicy(max_retries=NO_RETRIES)}], (
        "the SDK retry layer is disabled at construction (AD-18)"
    )


def test_adapter_passes_retries_disabled_on_every_call() -> None:
    client = RecordingClient()
    provider = TypeSafeJevProvider(client)

    asyncio.run(
        provider.system_one(
            state=STATE, questions={"choice": object()}, model=MODEL, timeout=TIMEOUT
        )
    )

    assert client.calls[0]["retry"] == RetryPolicy(max_retries=NO_RETRIES), (
        "the per-call override keeps the SDK retry layer off (AD-18)"
    )


class FiftyThreeTransport(httpx2.AsyncBaseTransport):
    """A fake transport answering 503, counting the requests it sees."""

    def __init__(self) -> None:
        self.requests = 0

    async def handle_async_request(self, request: Any) -> httpx2.Response:
        self.requests += 1
        return httpx2.Response(503)


def test_real_client_with_disabled_retries_calls_503_exactly_once() -> None:
    transport = FiftyThreeTransport()
    provider = TypeSafeJevProvider(
        AsyncTypeSafeClient(api_key="test-key", transport=transport)
    )

    with pytest.raises(TypeSafeInternalServerError):
        asyncio.run(
            provider.system_one(
                state=STATE,
                questions={"noul": Noul(instructions="screen")},
                model=MODEL,
                timeout=TIMEOUT,
            )
        )

    assert transport.requests == 1, (
        "the step runner is the only retry layer: one attempt, no SDK retries"
    )
