"""Story 3.1 integration smoke: ONE real `system_one` call (F15).

Makes a single live call through `TypeSafeJevProvider` with the pinned
model and timeout from `config/runtime.yaml` (AD-19) and asserts a valid
`JevResult` with usage. Marked `integration` and skipped without
`TYPESAFE_API_KEY`; run explicitly:

    TYPESAFE_API_KEY=... .venv/bin/pytest -m integration tests/agents/jev/test_integration.py -q
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from jsonschema import validate as schema_validate

from agents.jev.classifier import classify
from agents.jev.provider import TypeSafeJevProvider
from agents.jev.runtime import load_jev_runtime
from contracts.evidence import DistilledLogLine, EvidencePack
from contracts.jev import JevResult

pytestmark = pytest.mark.integration

SCHEMA: Any = json.loads(
    (
        Path(__file__).resolve().parents[3] / "guardrails" / "schemas" / "JevResult.json"
    ).read_text(encoding="utf-8")
)


@pytest.mark.skipif(
    not os.environ.get("TYPESAFE_API_KEY"), reason="no TYPESAFE_API_KEY"
)
def test_ac1_real_system_one_call_returns_valid_jev_result() -> None:
    runtime = load_jev_runtime()
    pack = EvidencePack(
        repo_id="integration/repo",
        last_green="0" * 40,
        distilled_log=[
            DistilledLogLine(
                line_number=1,
                text="FAILED tests/test_checkout.py::test_total - assert 512 == 500",
            ),
            DistilledLogLine(
                line_number=2,
                text="PASSED tests/test_checkout.py::test_total (retry 1)",
            ),
        ],
        commits=[],
        candidate_suspects=[],
        history_rows=[],
        metrics={},
    )

    result = asyncio.run(classify(pack, TypeSafeJevProvider(), runtime))

    assert isinstance(result, JevResult)
    schema_validate(result.model_dump(mode="json"), SCHEMA)
    # The provider reports its own (dated) snapshot of the pinned model (AD-18).
    assert result.usage.model.startswith(runtime.model), "usage names the pinned model"
    assert result.classification.choice.answer.value in {
        "code",
        "flaky",
        "infra",
        "external",
        "unknown",
    }
    assert 0.0 <= result.classification.choice.confidence <= 1.0
    assert 0.0 <= result.classification.injection_screen.noul <= 1.0
