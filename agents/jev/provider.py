"""The `JevProvider` seam (SOLID-D): the Protocols and the typesafe-sdk adapter.

Tests inject fakes; the agent never imports the concrete client outside this
adapter. The adapter is async (the A2A executor runs on the event loop) and
resolves the API key/base URL from the environment per `config/runtime.yaml`'s
key scopes (`TYPESAFE_API_KEY`, an OpenRouter key, base URL from
`TYPESAFE_BASE_URL`). The client is built once — it owns the HTTP connection
pool — and is injected through the same seam in tests.
"""

from collections.abc import Mapping
from typing import Protocol

from typesafe_sdk import AsyncTypeSafeClient
from typesafe_sdk._core.question_types import Question

from contracts.jev import SdkChoiceAnswer, SdkNoulAnswer

__all__ = [
    "JevProvider",
    "SystemOneClient",
    "SystemOneResult",
    "SystemOneUsage",
    "TypeSafeJevProvider",
]


class SystemOneUsage(Protocol):
    """Structural shape of the SDK's `Usage` (AD-18: counters may be None)."""

    @property
    def input_tokens(self) -> int | None: ...

    @property
    def output_tokens(self) -> int | None: ...


class SystemOneResult(Protocol):
    """Structural shape of typesafe-sdk 0.7.1's `SystemOneResponse`."""

    @property
    def model(self) -> str: ...

    @property
    def usage(self) -> SystemOneUsage: ...

    @property
    def choices(self) -> Mapping[str, SdkChoiceAnswer]: ...

    @property
    def nouls(self) -> Mapping[str, SdkNoulAnswer]: ...


class SystemOneClient(Protocol):
    """The SDK client surface the adapter uses (SOLID-I: one method)."""

    async def system_one(
        self,
        state: str,
        questions: Mapping[str, Question],
        *,
        model: str,
        timeout: float,
    ) -> SystemOneResult: ...


class JevProvider(Protocol):
    """The one provider call the classifier makes (AD-11)."""

    async def system_one(
        self,
        state: str,
        questions: Mapping[str, Question],
        *,
        model: str,
        timeout: float,
    ) -> SystemOneResult: ...


class TypeSafeJevProvider:
    """The concrete adapter; the only module that touches the SDK client."""

    def __init__(self, client: SystemOneClient | None = None) -> None:
        self._client: SystemOneClient = (
            client if client is not None else AsyncTypeSafeClient()
        )

    async def system_one(
        self,
        state: str,
        questions: Mapping[str, Question],
        *,
        model: str,
        timeout: float,
    ) -> SystemOneResult:
        """Forward the one call to the client built (or injected) once."""
        return await self._client.system_one(
            state=state, questions=questions, model=model, timeout=timeout
        )
