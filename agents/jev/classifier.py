"""The pure classify step (AC1/AC2): delimited log as state, one provider call.

The distilled log travels as delimited untrusted `state`, never inside the
instructions (AD-20). One `system_one` call batches the five-class `Choice`
and the `Noul` injection screen (AD-11); the response maps onto the shared
contracts with the provider-reported usage (unreported counters NULL, AD-18).
SDK errors are typed with the AD-22 retryable split; nothing escapes untyped.
"""

import secrets
from collections.abc import Callable
from typing import Final

from pydantic import ValidationError
from typesafe_sdk import (
    TypeSafeAPIConnectionError,
    TypeSafeAPIResponseValidationError,
    TypeSafeAuthenticationError,
    TypeSafeBadRequestError,
    TypeSafeInternalServerError,
    TypeSafeNotFoundError,
    TypeSafePermissionDeniedError,
    TypeSafeRateLimitError,
    TypeSafeUnprocessableEntityError,
)

from agents.jev.provider import JevProvider, SystemOneResult
from agents.jev.questions import CHOICE_KEY, NOUL_KEY, load_questions
from agents.jev.runtime import JevRuntime
from contracts.errors import AgentError
from contracts.evidence import EvidencePack
from contracts.jev import (
    JevChoice,
    JevClassification,
    JevInjectionScreen,
    JevResult,
)
from contracts.usage import ModelUsage

__all__ = ["ClassifyError", "agent_error", "classify"]

_RETRYABLE_SDK_ERRORS = (
    TypeSafeAPIConnectionError,
    TypeSafeRateLimitError,
    TypeSafeInternalServerError,
)
"""Connection, timeout (its subclass), throttle and 5xx are transient (AD-22)."""

_DEFINITIVE_SDK_ERRORS = (
    TypeSafeAuthenticationError,
    TypeSafeBadRequestError,
    TypeSafeNotFoundError,
    TypeSafePermissionDeniedError,
    TypeSafeUnprocessableEntityError,
    TypeSafeAPIResponseValidationError,
)
"""Auth, bad request, not found, permission, validation and response-shape
refusals will fail the same way again (AD-22)."""


class ClassifyError(Exception):
    """A typed agent failure carrying its `AgentError` payload (AD-22)."""

    def __init__(self, error: AgentError) -> None:
        super().__init__(error.message)
        self.error = error


def agent_error(exc: Exception) -> AgentError:
    """The AD-22 retryable split over the provider's error surface.

    An unexpected non-SDK failure is treated as transient, like the workflow
    transport does — the budget bounds it, then the run fails terminally.
    """
    if isinstance(exc, _RETRYABLE_SDK_ERRORS):
        retryable = True
    elif isinstance(exc, _DEFINITIVE_SDK_ERRORS):
        retryable = False
    else:
        retryable = True
    return AgentError(
        code=type(exc).__name__,
        message=str(exc) or type(exc).__name__,
        retryable=retryable,
    )


_LOG_START_PREFIX: Final[str] = "<<<distilled_log:"
_LOG_END_SUFFIX: Final[str] = ">>>"
_NONCE_BYTES: Final[int] = 16


def _new_nonce() -> str:
    """The default per-call nonce source: a fresh random token."""
    return secrets.token_hex(_NONCE_BYTES)


def _delimited_state(pack: EvidencePack, nonce: str) -> str:
    """The distilled log as one delimited untrusted data section (AD-20).

    The delimiters carry a per-call random nonce, so a collision with log
    text is practically impossible — an injection-looking log line stays
    data and can never close the section early (AC2: a positive screen
    never blocks on its own, so a denial-of-service refusal is wrong too).
    Embedded newlines in a line's text are escaped so every numbered line
    stays exactly one line.
    """
    start = f"{_LOG_START_PREFIX}{nonce}"
    end = f"distilled_log:{nonce}{_LOG_END_SUFFIX}"
    lines = "\n".join(
        f"{line.line_number} {line.text.replace(chr(10), chr(92) + 'n')}"
        for line in pack.distilled_log
    )
    return f"{start}\n{lines}\n{end}"


def _definitive(code: str, message: str) -> ClassifyError:
    """A failure that will happen again unchanged is never retried (AD-22)."""
    return ClassifyError(AgentError(code=code, message=message, retryable=False))


def _result(response: SystemOneResult) -> JevResult:
    """Map one `SystemOneResponse` onto the shared contracts (AD-9, AD-18)."""
    try:
        classification = JevClassification(
            choice=JevChoice.from_sdk(response.choices[CHOICE_KEY]),
            injection_screen=JevInjectionScreen.from_sdk(response.nouls[NOUL_KEY]),
        )
        usage = ModelUsage(
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
    except (
        KeyError,
        ValueError,
        AttributeError,
        TypeError,
        ValidationError,
    ) as error:
        raise _definitive(
            "invalid_classification",
            f"the provider answer is not a Jev answer: {error}",
        ) from error
    return JevResult(classification=classification, usage=usage)


async def classify(
    pack: EvidencePack,
    provider: JevProvider,
    runtime: JevRuntime,
    *,
    new_nonce: Callable[[], str] = _new_nonce,
) -> JevResult:
    """One batched provider call over the delimited log; typed errors only.

    `new_nonce` is the injectable per-call delimiter nonce source (tests
    pin it for determinism; production uses `secrets`).
    """
    try:
        questions = load_questions()
    except ClassifyError:
        raise
    except Exception as error:
        raise _definitive(
            "invalid_configuration", f"the Jev question setup failed: {error}"
        ) from error
    state = _delimited_state(pack, new_nonce())
    try:
        response = await provider.system_one(
            state=state,
            questions=questions.as_mapping(),
            model=runtime.model,
            timeout=runtime.step_timeout,
        )
    except Exception as error:
        raise ClassifyError(agent_error(error)) from error
    return _result(response)
