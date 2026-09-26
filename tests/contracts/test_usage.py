"""Story 6.1 contract tests — `ModelUsage` (AC1, AD-18).

The AD-18 rule as a type: a counter the provider did not report is NULL,
never 0. The model is a frozen, extra-forbid Pydantic model following the
`contracts/evidence.py` pattern.
"""

import pytest
from pydantic import ValidationError

from contracts.usage import ModelUsage

MODEL = "claude-haiku-4-5-20251001"


def test_ac1_unreported_counters_stay_null() -> None:
    usage = ModelUsage(model=MODEL)

    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert usage.cache_read_input_tokens is None
    assert usage.cache_creation_input_tokens_5m is None
    assert usage.cache_creation_input_tokens_1h is None


def test_ac1_usage_round_trips_through_json() -> None:
    full = ModelUsage(
        model=MODEL,
        input_tokens=1200,
        output_tokens=340,
        cache_read_input_tokens=512,
        cache_creation_input_tokens_5m=64,
        cache_creation_input_tokens_1h=128,
    )

    restored = ModelUsage.model_validate(full.model_dump(mode="json"))

    assert restored == full


def test_ac1_reported_zero_is_kept_not_nulled() -> None:
    # NULL means "not reported"; a provider-reported 0 is a real value (AD-18).
    usage = ModelUsage(model=MODEL, cache_creation_input_tokens_1h=0)

    assert usage.cache_creation_input_tokens_1h == 0


def test_ac1_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError) as exc:
        ModelUsage.model_validate({"model": MODEL, "input_tokens": 5, "cost_usd": 0.01})

    assert "extra_forbid" in str(exc.value) or "Extra inputs" in str(exc.value)


def test_ac1_negative_counter_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelUsage(model=MODEL, input_tokens=-1)


def test_ac1_usage_is_frozen() -> None:
    usage = ModelUsage(model=MODEL, input_tokens=5)

    with pytest.raises(ValidationError):
        usage.input_tokens = 6  # type: ignore[misc]
