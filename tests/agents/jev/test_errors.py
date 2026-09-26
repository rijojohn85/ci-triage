"""AC2: the AD-22 retryable split over the typesafe-sdk 0.7.1 error surface.

Parametrized over the installed SDK's error types (checked in the installed
source `typesafe_sdk/_core/errors.py`): connection/timeout/rate-limit/5xx are
retryable; auth/bad-request/not-found/permission/unprocessable/response-
validation are definitive. Nothing escapes untyped (AD-22).
"""

import asyncio
from typing import Any

import httpx2
import pytest
from typesafe_sdk import (
    TypeSafeAPIConnectionError,
    TypeSafeAPIResponseValidationError,
    TypeSafeAPITimeoutError,
    TypeSafeAuthenticationError,
    TypeSafeBadRequestError,
    TypeSafeInternalServerError,
    TypeSafeNotFoundError,
    TypeSafePermissionDeniedError,
    TypeSafeRateLimitError,
    TypeSafeUnprocessableEntityError,
)

from agents.jev.classifier import ClassifyError, agent_error, classify
from tests.agents.jev.test_classifier import (
    RUNTIME,
    FakeProvider,
    evidence_pack,
)

HEADERS: Any = httpx2.Headers()


def api_error(error_type: type[Exception]) -> Exception:
    """One fixture instance per SDK error type."""
    if error_type is TypeSafeAPITimeoutError:
        return TypeSafeAPITimeoutError(float(RUNTIME.step_timeout))
    if error_type is TypeSafeAPIResponseValidationError:
        return TypeSafeAPIResponseValidationError(200, {}, HEADERS, "answers.choice")
    if error_type is TypeSafeAPIConnectionError:
        return TypeSafeAPIConnectionError("connection reset")
    return error_type(
        500 if error_type is TypeSafeInternalServerError else 400, {}, HEADERS
    )


RETRYABLE_ERRORS = (
    TypeSafeAPIConnectionError,
    TypeSafeAPITimeoutError,
    TypeSafeRateLimitError,
    TypeSafeInternalServerError,
)

DEFINITIVE_ERRORS = (
    TypeSafeAuthenticationError,
    TypeSafeBadRequestError,
    TypeSafeNotFoundError,
    TypeSafePermissionDeniedError,
    TypeSafeUnprocessableEntityError,
    TypeSafeAPIResponseValidationError,
)


@pytest.mark.parametrize("error_type", RETRYABLE_ERRORS)
def test_ac2_retryable_sdk_errors_map_to_retryable_agent_error(
    error_type: type[Exception],
) -> None:
    error = agent_error(api_error(error_type))

    assert error.retryable is True
    assert error.code
    assert error.message


@pytest.mark.parametrize("error_type", DEFINITIVE_ERRORS)
def test_ac2_definitive_sdk_errors_map_to_non_retryable_agent_error(
    error_type: type[Exception],
) -> None:
    error = agent_error(api_error(error_type))

    assert error.retryable is False
    assert error.code
    assert error.message


def test_ac2_unexpected_provider_failure_is_transient() -> None:
    """Nothing escapes the AD-22 split untyped: an unexpected failure is
    treated as transient, like the workflow transport does (AD-22)."""
    error = agent_error(RuntimeError("boom"))

    assert error.retryable is True


def test_ac2_provider_error_surfaces_as_classify_error() -> None:
    provider = FakeProvider(error=TypeSafeRateLimitError(429, {}, HEADERS))

    with pytest.raises(ClassifyError) as exc:
        asyncio.run(classify(evidence_pack(), provider, RUNTIME))

    assert exc.value.error.retryable is True
    assert exc.value.error.code == "TypeSafeRateLimitError"
    assert len(provider.calls) == 1
