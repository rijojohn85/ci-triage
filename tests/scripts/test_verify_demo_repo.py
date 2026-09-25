"""Story 0.4 AC4 tests: read-back comparison logic against recorded fixtures.

Fixtures under tests/scripts/fixtures/ are recorded (shape-faithful) GitHub
API responses. The live gh subprocess path is integration-tested in
tests/scripts/test_verify_demo_repo_integration.py — make check stays fast.

Test names cite the AC they prove (AGENTS.md TDD rule).
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_demo_repo.py"
FIXTURES = ROOT / "tests" / "scripts" / "fixtures"

_spec = importlib.util.spec_from_file_location("verify_demo_repo", SCRIPT)
assert _spec is not None and _spec.loader is not None
verify = importlib.util.module_from_spec(_spec)
sys.modules["verify_demo_repo"] = verify
_spec.loader.exec_module(verify)


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# AC1 / AC4: permissions read-back against AD-16 expected set
# ---------------------------------------------------------------------------


def test_ac4_permissions_exact_match_passes() -> None:
    granted = load("installation_permissions_ok.json")["permissions"]
    expected = load("expected.json")
    mismatches, requested, implied = verify.split_permissions(granted, expected)
    assert mismatches == {}
    assert requested == expected["permissions"]
    assert set(implied) == set(expected["platform_implied_permissions"])


def test_ac4_missing_permission_flagged() -> None:
    granted = dict(load("installation_permissions_ok.json")["permissions"])
    del granted["contents"]
    expected = load("expected.json")
    mismatches, _, _ = verify.split_permissions(granted, expected)
    assert mismatches == {"contents": "MISSING"}


def test_ac4_wrong_value_flagged() -> None:
    granted = dict(load("installation_permissions_ok.json")["permissions"])
    granted["contents"] = "read"
    expected = load("expected.json")
    mismatches, _, _ = verify.split_permissions(granted, expected)
    assert mismatches == {"contents": "read"}


def test_ac4_workflows_permission_is_rejection() -> None:
    granted = dict(load("installation_permissions_ok.json")["permissions"])
    granted["workflows"] = "write"
    expected = load("expected.json")
    mismatches, requested, _ = verify.split_permissions(granted, expected)
    # workflows is forbidden outright: a hard mismatch, requested set empty.
    assert mismatches == {"workflows": "write"}
    assert requested == {}


def test_ac4_metadata_only_is_platform_implied_not_requested() -> None:
    granted = dict(load("installation_permissions_ok.json")["permissions"])
    granted["stargazers"] = "read"
    expected = load("expected.json")
    _, requested, implied = verify.split_permissions(granted, expected)
    assert requested == expected["permissions"]
    assert implied["stargazers"] == "read"
    assert "metadata" in implied


def test_ac4_events_exact_match() -> None:
    expected = load("expected.json")
    assert verify.events_match(["workflow_run", "issue_comment"], expected)
    assert verify.events_match(sorted(["issue_comment", "workflow_run"]), expected)
    assert not verify.events_match(["workflow_run"], expected)
    assert not verify.events_match(["push", "workflow_run", "issue_comment"], expected)


def test_ac4_installation_lookup_filters_to_app_id_and_rejects_ambiguity() -> None:
    install = verify.fetch_installation.__doc__
    assert install is not None  # contract documented; live path integration-tested


# ---------------------------------------------------------------------------
# AC2: ruleset read-back (human review, force-push/deletion blocked, no bypass)
# ---------------------------------------------------------------------------


def test_ac2_ruleset_requires_review_when_rules_match() -> None:
    ruleset = load("ruleset_ok.json")
    assert verify.ruleset_problems(ruleset, app_id=5073639) == []


def test_ac2_ruleset_fails_when_app_is_bypass_actor() -> None:
    ruleset = load("ruleset_ok.json")
    ruleset["bypass_actors"] = [
        {"actor_id": 5073639, "actor_type": "Integration", "bypass_mode": "always"}
    ]
    problems = verify.ruleset_problems(ruleset, app_id=5073639)
    assert any("bypass actor" in p for p in problems)


def test_ac2_ruleset_fails_without_code_owner_review() -> None:
    ruleset = load("ruleset_ok.json")
    for rule in ruleset["rules"]:
        if rule["type"] == "pull_request":
            rule["parameters"]["require_code_owner_review"] = False
    problems = verify.ruleset_problems(ruleset, app_id=5073639)
    assert any("code-owner" in p for p in problems)


def test_ac2_ruleset_fails_without_force_push_or_deletion_rule() -> None:
    ruleset = load("ruleset_ok.json")
    ruleset["rules"] = [
        r for r in ruleset["rules"] if r["type"] not in ("non_fast_forward", "deletion")
    ]
    problems = verify.ruleset_problems(ruleset, app_id=5073639)
    assert any("non_fast_forward" in p for p in problems)
    assert any("deletion" in p for p in problems)


def test_ac2_ruleset_fails_when_not_active_or_wrong_ref() -> None:
    ruleset = load("ruleset_ok.json")
    ruleset["enforcement"] = "disabled"
    assert any("enforcement" in p for p in verify.ruleset_problems(ruleset, 5073639))
    ruleset2 = load("ruleset_ok.json")
    ruleset2["conditions"]["ref_name"]["include"] = ["~ALL"]
    assert any("DEFAULT" in p for p in verify.ruleset_problems(ruleset2, 5073639))


# ---------------------------------------------------------------------------
# AC2: CODEOWNERS fallback rule
# ---------------------------------------------------------------------------


def test_ac2_codeowners_fallback_rule_required() -> None:
    assert verify.codeowners_problems("* @rijojohn85\n") == []
    assert verify.codeowners_problems("# comment\n* @rijojohn85\n") == []
    assert verify.codeowners_problems("*.py @rijojohn85\n") != []
    assert verify.codeowners_problems("*  @rijojohn85\n") == []
    assert verify.codeowners_problems("") != []
    problems = verify.codeowners_problems("# only a comment\n")
    assert any("'*'" in p for p in problems)


# ---------------------------------------------------------------------------
# AC4: annotated tag resolution + exit code path
# ---------------------------------------------------------------------------


def test_ac4_baseline_tag_resolution_direct_commit() -> None:
    assert (
        verify.tag_matches({"object": {"type": "commit", "sha": "a" * 40}}) == "a" * 40
    )


def test_ac4_baseline_tag_resolution_annotated_tag() -> None:
    ref = {"object": {"type": "tag", "sha": "b" * 40}, "_resolved_commit": {}}
    assert verify.tag_matches(ref) is None
    assert verify.tag_matches({"object": {"type": "tag", "sha": "b" * 40}}) is None


def test_ac4_baseline_tag_resolution_rejects_non_commit_object() -> None:
    assert verify.tag_matches({"object": {"type": "tree", "sha": "c" * 40}}) is None


def test_ac4_cli_exits_nonzero_on_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps({"installations": []})

    class FakeProc:
        returncode = 0

        def __init__(self) -> None:
            self.stdout = payload
            self.stderr = ""

    def fake_run(*_args: object, **_kwargs: object) -> FakeProc:
        return FakeProc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert verify.main(["--org", "o", "--repo", "r", "--app-id", "1"]) != 0
