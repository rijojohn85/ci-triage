"""Live read-back against the demo repository (story 0.4, AC4) — integration.

Runs the real `gh api` path of scripts/verify_demo_repo.py against
rijojohn85-dev/triage-demo-py. Explicitly marked `integration` so
`make check` stays offline; run with `.venv/bin/pytest -m integration`
or `make test-integration`. Requires `gh` auth as the installing account.
"""

import pytest

import tests.scripts.test_verify_demo_repo as unit  # reuse the loaded module

ORG = "rijojohn85-dev"
APP_ID = 5073639
RULESET_ID = 23997553
TAG = "baseline-v1"
EXPECTED_COMMIT = "fe2a35d0ec762e899b3e94b0bc2b38bb3aac8277"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        unit.verify.EXPECTED_PATH.exists() is False,
        reason="test-data/demo-repo-expected.json missing",
    ),
]


def test_ac4_live_read_back_passes_against_demo_repo() -> None:
    exit_code = unit.verify.main(
        [
            "--org",
            ORG,
            "--repo",
            "triage-demo-py",
            "--app-id",
            str(APP_ID),
            "--ruleset-id",
            str(RULESET_ID),
            "--tag",
            TAG,
        ]
    )
    assert exit_code == 0


def test_ac4_live_baseline_tag_resolves_to_recorded_commit() -> None:
    assert unit.verify.fetch_tag_commit(ORG, "triage-demo-py", TAG) == EXPECTED_COMMIT
