"""The pure classify step (AC1/AC2): delimited log as state, one provider call.

The distilled log travels as delimited untrusted `state`, never inside the
instructions (AD-20). One `system_one` call batches the five-class `Choice`
and the `Noul` injection screen (AD-11); the response maps onto the shared
contracts with the provider-reported usage (unreported counters NULL, AD-18).
SDK errors are typed with the AD-22 retryable split; nothing escapes untyped.
"""

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

__all__ = ["LOG_END", "LOG_START", "ClassifyError", "agent_error", "classify"]

LOG_START = "<<<distilled_log"
LOG_END = "distilled_log>>>"

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


def _delimited_state(pack: EvidencePack) -> str:
    """The distilled log as one delimited untrusted data section (AD-20).

    Fails closed when a log line carries a delimiter literal: the section
    would close early and the rest of the log would leak into the model's
    instructions.
    """
    for line in pack.distilled_log:
        if LOG_START in line.text or LOG_END in line.text:
            raise _definitive(
                "log_delimiter_collision",
                f"distilled log line {line.line_number} carries a section "
                "delimiter; refusing to serve it as untrusted state (AD-20)",
            )
    lines = "\n".join(f"{line.line_number} {line.text}" for line in pack.distilled_log)
    return f"{LOG_START}\n{lines}\n{LOG_END}"


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
    pack: EvidencePack, provider: JevProvider, runtime: JevRuntime
) -> JevResult:
    """One batched provider call over the delimited log; typed errors only."""
    try:
        questions = load_questions()
        state = _delimited_state(pack)
    except ClassifyError:
        raise
    except Exception as error:
        raise _definitive(
            "invalid_configuration", f"the Jev question setup failed: {error}"
        ) from error
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
