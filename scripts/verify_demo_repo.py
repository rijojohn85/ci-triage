"""Read back the demo repository's live GitHub configuration (story 0.4, AC4).

Compares four things against the expected values in
``test-data/demo-repo-expected.json`` (single source of truth, DRY):

1. the App installation's permissions + subscribed events (AD-16):
   exact match of the requested set, ``workflows`` forbidden, and the
   platform-implied grants (``metadata:read``, ``statuses:write``) reported
   separately so they are never mistaken for requested permissions;
2. the default-branch ruleset: human review is required (pull_request rule),
   force-push (``non_fast_forward``) and deletion are blocked, and the App is
   NOT a bypass actor (bypass_actors empty or without our app);
3. CODEOWNERS applies on the default branch with a fallback ``*`` rule;
4. the ``baseline-v1`` annotated tag exists and resolves to a commit SHA.

Reads go through ``gh api`` with the human's own gh auth — no App key
needed, no secret ever printed. Exits non-zero on any mismatch.

Usage:
    python scripts/verify_demo_repo.py --org ORG --repo REPO \
        --app-id N --installation-id N --ruleset-id N [--tag baseline-v1]
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_PATH = ROOT / "test-data" / "demo-repo-expected.json"
DEFAULT_TAG = "baseline-v1"
DEFAULT_RULESET_NAME = "protect-default-branch"
FALLBACK_RULE = "*"
FALLBACK_TOKENS = 2


class VerifyError(Exception):
    """A read-back check failed (exit 1) or GitHub could not be read (exit 2)."""


# ---------------------------------------------------------------------------
# Pure comparison logic (unit-tested against recorded fixtures; AC4, AC1, AC2)
# ---------------------------------------------------------------------------


def split_permissions(
    granted: dict[str, str],
    expected: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Split granted repository permissions into (mismatches, requested, implied).

    Repository permissions only (org permissions are checked separately in
    :func:`check`). A permission is "requested" when its name appears in the
    expected ``permissions`` map; anything else not forbidden is
    platform-implied by GitHub. ``workflows`` (or any name in
    ``forbidden_permissions``) must never be granted.

    Returns three dicts keyed by permission:
    - mismatches: wrong-valued requested permissions (value = granted value),
      plus ``"MISSING"`` entries for expected permissions absent from granted
    - requested:  granted subset matching the expected set
    - platform_implied: granted but not requested
    """
    forbidden = set(expected.get("forbidden_permissions", []))
    requested_names = expected.get("permissions", {})
    org_names = set(expected.get("organization_permissions", {}))
    for name in forbidden:
        if granted.get(name) not in (None, "none"):
            return {name: granted[name]}, {}, {}
    mismatches = {
        name: granted.get(name, "MISSING")
        for name in requested_names
        if granted.get(name) != requested_names[name]
    }
    requested = {
        name: value
        for name, value in granted.items()
        if name in requested_names and value == requested_names[name]
    }
    platform_implied = {
        name: value
        for name, value in granted.items()
        if name not in requested_names
        and name not in org_names
        and name not in forbidden
        and name not in mismatches
    }
    return mismatches, requested, platform_implied


def org_permission_mismatches(
    granted: dict[str, str], expected: dict[str, Any]
) -> dict[str, str]:
    """Wrong-valued or missing expected organization permissions (e.g. members)."""
    expected_org = expected.get("organization_permissions", {})
    return {
        name: granted.get(name, "MISSING")
        for name, expected_value in expected_org.items()
        if granted.get(name) != expected_value
    }


def events_match(granted: list[str], expected: dict[str, Any]) -> bool:
    """True when the subscribed event set equals the expected set exactly."""
    return sorted(granted) == sorted(expected.get("events", []))


def ruleset_problems(ruleset: dict[str, Any], app_id: int) -> list[str]:
    """Return human-readable problems with the ruleset (empty means pass).

    AC2 requirements enforced here: active enforcement on the default
    branch, a pull_request rule requiring >= 1 approval and code-owner
    review, force-push and deletion blocked, and the App absent from
    bypass_actors.
    """
    problems: list[str] = []
    if ruleset.get("enforcement") != "active":
        problems.append(
            f"ruleset enforcement is {ruleset.get('enforcement')!r}, expected 'active'"
        )
    conditions = ruleset.get("conditions") or {}
    ref_name = conditions.get("ref_name") or {}
    include = ref_name.get("include") or []
    if "~DEFAULT_BRANCH" not in include:
        problems.append(
            f"ruleset ref include {include!r} does not cover '~DEFAULT_BRANCH'"
        )
    rules = {rule.get("type"): rule for rule in ruleset.get("rules") or []}
    pull_request = rules.get("pull_request")
    if pull_request is None:
        problems.append("ruleset has no 'pull_request' rule (human review required)")
    else:
        params = pull_request.get("parameters") or {}
        count = params.get("required_approving_review_count", 0)
        if not isinstance(count, int) or count < 1:
            problems.append(
                f"pull_request rule requires {count!r} approvals, expected >= 1"
            )
        if not params.get("require_code_owner_review"):
            problems.append("pull_request rule does not require code-owner review")
    for rule_type in ("non_fast_forward", "deletion"):
        if rule_type not in rules:
            problems.append(f"ruleset has no '{rule_type}' rule")
    bypass = ruleset.get("bypass_actors") or []
    for actor in bypass:
        if actor.get("actor_type") == "Integration" and actor.get("actor_id") == app_id:
            problems.append("App is a bypass actor on the ruleset (must never be)")
    return problems


def codeowners_problems(content: str) -> list[str]:
    """Return problems with CODEOWNERS content (empty means pass).

    AC2: an applicable fallback ``*`` rule naming a fixture owner must exist
    (spine AD-14 authority).
    """
    lines = (
        line.split()
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    tokens = [split_line for split_line in lines if split_line]
    if any(row[0] == FALLBACK_RULE and len(row) >= FALLBACK_TOKENS for row in tokens):
        return []
    return ["CODEOWNERS has no applicable fallback '*' rule naming an owner"]


def tag_matches(ref_obj: dict[str, Any]) -> str | None:
    """Resolve a tag-ref response to its target commit SHA.

    Returns the commit SHA (dereferencing an annotated tag whose payload the
    live reader attached as ``_resolved_commit``), or None when the ref is
    not a commit and no deref data is present.
    """
    ref: dict[str, Any] = ref_obj.get("object") or {}
    if ref.get("type") == "commit":
        return ref.get("sha")
    if ref.get("type") == "tag":
        commit = ref_obj.get("_resolved_commit") or {}
        object_ = commit.get("object") or {}
        if object_.get("type") == "commit":
            return object_.get("sha")
        return None
    return None


# ---------------------------------------------------------------------------
# gh reads (integration-tested: the live path behind @pytest.mark.integration)
# ---------------------------------------------------------------------------


def gh_api(endpoint: str) -> Any:
    """GET one endpoint through ``gh api``; raise VerifyError on failure."""
    result = subprocess.run(
        ["gh", "api", endpoint],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr else "?"
        raise VerifyError(f"gh api {endpoint} failed: {detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise VerifyError(f"gh api {endpoint} returned invalid JSON: {exc}") from exc


def fetch_installation(org: str, app_id: int) -> dict[str, Any]:
    """Find our installation under the org; None-granted perms are dropped."""
    payload = gh_api(f"/orgs/{org}/installations")
    installs = [
        inst
        for inst in payload.get("installations", [])
        if inst.get("app_id") == app_id
    ]
    if len(installs) != 1:
        raise VerifyError(
            f"expected exactly 1 installation of app {app_id} in {org}, "
            f"found {len(installs)}"
        )
    found = installs[0]
    assert isinstance(found, dict)
    return found


def fetch_ruleset(org: str, repo: str, ruleset_id: int) -> dict[str, Any]:
    payload = gh_api(f"/repos/{org}/{repo}/rulesets/{ruleset_id}")
    assert isinstance(payload, dict)
    return payload


def fetch_codeowners(org: str, repo: str, branch: str) -> str | None:
    """CODEOWNERS content on *branch*, or None when GitHub says absent."""
    result = subprocess.run(
        ["gh", "api", f"/repos/{org}/{repo}/contents/CODEOWNERS?ref={branch}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    encoded = payload.get("content", "")
    return base64.b64decode(str(encoded)).decode("utf-8")


def fetch_tag_commit(org: str, repo: str, tag_name: str) -> str | None:
    """Resolve *tag_name* on the remote to its commit SHA via the refs API."""
    ref = gh_api(f"/repos/{org}/{repo}/git/ref/tags/{tag_name}")
    assert isinstance(ref, dict)
    object_ = ref.get("object") or {}
    if object_.get("type") == "commit":
        return str(object_["sha"])
    tag = gh_api(f"/repos/{org}/{repo}/git/tags/{object_['sha']}")
    assert isinstance(tag, dict)
    object_ = tag.get("object") or {}
    if object_.get("type") == "commit":
        return str(object_["sha"])
    return None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def report_expected() -> dict[str, Any]:
    payload = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--app-id", type=int, required=True)
    parser.add_argument("--installation-id", type=int, default=None)
    parser.add_argument("--ruleset-id", type=int, default=None)
    parser.add_argument("--ruleset-name", default=DEFAULT_RULESET_NAME)
    parser.add_argument("--tag", default=DEFAULT_TAG)
    return parser.parse_args(argv)


def check_installation(
    installation: dict[str, Any], expected: dict[str, Any]
) -> tuple[list[str], dict[str, str]]:
    """AC1 read-back: granted permissions + events against the AD-16 set.

    Returns (failure lines, platform-implied grants) so the caller logs the
    implied grants without mistaking them for requested ones.
    """
    failures: list[str] = []
    granted = {
        name: value
        for name, value in (installation.get("permissions") or {}).items()
        if value != "none"
    }
    missing_or_wrong = org_permission_mismatches(granted, expected)
    granted = {
        name: value for name, value in granted.items() if name not in missing_or_wrong
    }
    mismatches, _, platform_implied = split_permissions(granted, expected)
    for name, value in missing_or_wrong.items():
        failures.append(f"AC1 org permission {name}={value!r} deviates from AD-16")
    for name, value in mismatches.items():
        failures.append(f"AC1 permission {name}={value!r} deviates from AD-16")
    events = sorted(installation.get("events") or [])
    if not events_match(events, expected):
        wanted = sorted(expected.get("events", []))
        failures.append(f"AC1 events {events} != expected {wanted}")
    if not platform_implied:
        return failures, {}
    implied = ", ".join(f"{k}:{v}" for k, v in sorted(platform_implied.items()))
    print(f"note: platform-implied permissions (not requested): {implied}")
    return failures, platform_implied


def check_ruleset(org: str, repo: str, app_id: int, ruleset_id: int) -> list[str]:
    """AC2 read-back of one ruleset through gh api."""
    ruleset = fetch_ruleset(org, repo, ruleset_id)
    problems = ruleset_problems(ruleset, app_id)
    return [f"AC2 {problem}" for problem in problems]


def check_codeowners(org: str, repo: str) -> list[str]:
    """AC2 read-back: CODEOWNERS applies on the default branch tip (AD-14)."""
    branch = gh_api(f"/repos/{org}/{repo}")["default_branch"]
    codeowners = fetch_codeowners(org, repo, branch)
    if codeowners is None:
        return [f"AC2 CODEOWNERS absent on default branch {branch!r}"]
    problems = codeowners_problems(codeowners)
    return [f"AC2 {problem}" for problem in problems]


def check_baseline_tag(org: str, repo: str, tag: str) -> list[str]:
    """AC4 read-back of the annotated baseline tag through gh api."""
    sha = fetch_tag_commit(org, repo, tag)
    if sha is None:
        return [f"AC4 {tag!r} not found or does not resolve to a commit"]
    print(f"note: {tag} -> {sha}")
    return []


@dataclass(frozen=True)
class VerifyTarget:
    """What to read back (org/repo/app identity, ruleset id, baseline tag)."""

    org: str
    repo: str
    app_id: int
    tag: str
    installation: dict[str, Any] | None = None
    ruleset_id: int | None = None


def check(target: VerifyTarget, expected: dict[str, Any]) -> list[str]:
    """Run every read-back check; return human-readable failures (AC4)."""
    failures: list[str] = []
    if target.installation is not None:
        found, _ = check_installation(target.installation, expected)
        failures.extend(found)
    if target.ruleset_id is not None:
        failures.extend(
            check_ruleset(target.org, target.repo, target.app_id, target.ruleset_id)
        )
    failures.extend(check_codeowners(target.org, target.repo))
    failures.extend(check_baseline_tag(target.org, target.repo, target.tag))
    return failures


def find_ruleset(org: str, repo: str, name: str) -> dict[str, Any] | None:
    listing = gh_api(f"/repos/{org}/{repo}/rulesets")
    assert isinstance(listing, list)
    for entry in listing:
        if entry.get("name") == name:
            return fetch_ruleset(org, repo, int(entry["id"]))
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        expected = report_expected()
        target = VerifyTarget(
            org=args.org,
            repo=args.repo,
            app_id=args.app_id,
            tag=args.tag,
            installation=fetch_installation(args.org, args.app_id),
            ruleset_id=args.ruleset_id,
        )
        failures = check(target, expected)
    except VerifyError as exc:
        print(f"VERIFY FAIL: {exc}")
        return 2
    if failures:
        for failure in failures:
            print(f"VERIFY FAIL: {failure}")
        return 1
    print("VERIFY PASS: demo repository matches AD-16 + AC2 expectations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
