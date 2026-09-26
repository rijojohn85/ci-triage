"""The deterministic risk gate (AD-13, AD-12, AD-21).

Pure domain code (stdlib + pydantic + `contracts` only, layer contract): one
registry entry per AD-13 rule, evaluated over the proposed diff, the base
content of modified files and the Reviewer's objections. The gate returns
`normal | blocked | not_gated` with structured per-rule evidence — no I/O,
no model, no state transitions (the `AWAITING_APPROVAL(gate_blocked)` pause
belongs to the workflow layer). The gate takes no model-asserted risk tier
as input: it recomputes from the diff, so a verdict claiming `normal` can
never override it — override-impossibility is structural.

Content rules (skip/retry/loosening) are line-pattern tripwires over the
added/removed lines — deliberately conservative pattern sets; they are the
deterministic backstop, not a semantic reviewer. Widening one is a
registry-entry edit plus its fixtures.
"""

import difflib
import posixpath
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import PurePosixPath
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from contracts.enums import DiffOperation, ObjectionSeverity, RiskTier
from contracts.objections import Objection
from contracts.verdict import DiffFile, ProposedDiff

__all__ = [
    "ASSERTION_LOOSENED",
    "INFRA_MANIFEST_TOUCHED",
    "PRIOR_CONTENT_MISSING",
    "RETRY_ADDED",
    "REVIEWER_DANGEROUS",
    "RISK_RULES",
    "SECRET_TOUCHED",
    "TEST_DISABLED",
    "TIMEOUT_INCREASED",
    "UNSAFE_PATH",
    "WORKFLOW_FILE_TOUCHED",
    "GateDecision",
    "GateInput",
    "GateReason",
    "RiskGateConfig",
    "RiskRule",
    "evaluate_risk",
]

TEST_DISABLED = "test_disabled"
"""Rule code: a test skipped/xfailed on an added line, or a test file deleted."""

RETRY_ADDED = "retry_added"
"""Rule code: retry machinery on an added line (a pre-existing retry is not new)."""

TIMEOUT_INCREASED = "timeout_increased"
"""Rule code: the largest timeout in the new content exceeds the base's."""

ASSERTION_LOOSENED = "assertion_loosened"
"""Rule code: a strong assertion removed while a weak one on the same
target token was added."""

WORKFLOW_FILE_TOUCHED = "workflow_file_touched"
"""Rule code: a path under the workflow glob is touched (AD-13)."""

SECRET_TOUCHED = "secret_touched"
"""Rule code: a path under a secret glob is touched (AD-13)."""

INFRA_MANIFEST_TOUCHED = "infra_manifest_touched"
"""Rule code: a path under an infra-manifest glob is touched (AD-13)."""

REVIEWER_DANGEROUS = "reviewer_dangerous"
"""Rule code: a `dangerous` Reviewer objection blocks a safe diff too (AD-12)."""

PRIOR_CONTENT_MISSING = "prior_content_missing"
"""Rule code: a modification whose base content was not supplied — fail closed."""

UNSAFE_PATH = "unsafe_path"
"""Rule code: a path that is absolute, escapes the repo (`..` survives
normalising) or names no file — fail closed before any glob is consulted."""


class RiskGateConfig(BaseModel):
    """The gate's configurable values (AD-19): globs built by the caller from
    `guardrails/thresholds.yaml` — guardrails itself does no config I/O."""

    model_config = ConfigDict(frozen=True)

    workflow_path_glob: str = Field(min_length=1)
    secret_path_globs: tuple[str, ...] = Field(min_length=1)
    infra_path_globs: tuple[str, ...] = Field(min_length=1)


class GateReason(BaseModel):
    """One structured rule hit: the rule code, a human-readable message and
    where in the input the hit sits."""

    model_config = ConfigDict(frozen=True)

    rule_code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    location: str = Field(min_length=1)


class GateDecision(BaseModel):
    """The gate's whole answer: the risk tier plus every reason behind it."""

    model_config = ConfigDict(frozen=True)

    risk_tier: RiskTier
    reasons: tuple[GateReason, ...]


class GateInput(BaseModel):
    """Everything the gate may look at — and nothing else (AD-21): the diff,
    the base content of modified files, the Reviewer's objections and the
    config. No model-asserted risk tier and no quarantine: the gate
    recomputes from the diff alone."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    diff: ProposedDiff | None
    config: RiskGateConfig
    prior_contents: Mapping[str, str] = Field(default_factory=dict)
    objections: tuple[Objection, ...] = ()


_SKIP_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"pytest\.mark\.(?:skip|skipif|xfail)|pytest\.skip\("
    r"|pytest\.xfail\(|pytest\.importorskip\(|unittest\.skip"
    r"|unittest\.SkipTest|self\.skipTest\("
    r"|\bmark\.(?:skip|skipif|xfail)\b|pytest\.skip\.Exception"
)
"""Skip/disable spellings: the pytest markers and runtime calls, unittest's
decorator and `SkipTest`, `self.skipTest(`, the bare `mark.*` forms (after
`from pytest import mark`) and `pytest.skip.Exception`. `skip` inside an
unrelated identifier (`skip_header_rows`) never matches — the patterns are
anchored to the real call/marker shapes."""
_RETRY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b[a-z_]*(?:retry|retries|rerun|reruns)\b"
    r"|\bon_exception\b|@backoff\.|\bflaky\b|\bstamina\b|\btenacity\b"
)
"""Case-insensitive, word-bounded on the stem so `max_retries=` inside a
call is caught too: retry/retries/rerun(s), retry=, .on_exception, @backoff,
flaky, stamina, tenacity. A retry that already existed is not a new one —
only added lines are scanned."""
_TIMEOUT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b[a-z_]*timeout[a-z_]*\s*[=:]\s*([0-9][0-9_]*(?:\.[0-9]+)?)"
    r"|timeout\(\s*([0-9][0-9_]*(?:\.[0-9]+)?)\s*\)"
)
"""Case-insensitive: any `…timeout…` key with a numeric value (assignment,
keyword argument or mapping entry), plus the `timeout(N)` call/marker form.
Values may be floats or use digit separators; they are compared numerically."""
_STRONG_ASSERTION: Final[re.Pattern[str]] = re.compile(
    r"""assertEqual\(([\w.\[\]"']+)\s*,|assert\s+([\w.\[\]"']+)\s*=="""
)
_WEAK_ASSERTION: Final[re.Pattern[str]] = re.compile(
    r"""assertIn\(([\w.\[\]"']+)\s*,|assert\s+([\w.\[\]"']+)\s+in\b"""
    r"""|assertTrue\(([\w.\[\]"']+)|assertIsNotNone\(([\w.\[\]"']+)"""
    r"""|assert\s+([\w.\[\]"']+)\s*==\s*pytest\.approx"""
)
_ASSERTION_LINE: Final[re.Pattern[str]] = re.compile(
    r"\bassert\b|self\.assert\w+\(|\bassert\w+\("
)
"""The loosening rule's target token accepts dotted and subscripted names
(`resp.status`, `data["k"]`), and the weak set covers assertTrue /
assertIsNotNone / a `pytest.approx` comparison — weaker checks on the same
target. The line pattern is the deletion arm: a test file with net fewer
assertion lines than its base is a loosening too (AD-13)."""
_TEST_FILE_GLOBS: Final[tuple[str, ...]] = ("test_*.py", "*_test.py", "conftest.py")
# Rule constant, not a tunable (AD-19): what counts as a test file IS the rule.


def _canonical_path(path: str) -> str:
    """The one path normalisation, applied before ANY path rule: backslashes
    become separators, `.` segments and a leading `./` collapse — so
    `./.github/workflows/ci.yml`, `src/../.github/workflows/ci.yml` and
    `.github\\workflows\\ci.yml` all meet the globs in their canonical form."""
    return posixpath.normpath(path.replace("\\", "/"))


def _is_unsafe_path(canonical: str) -> bool:
    """A path is unsafe when it is absolute, still carries `..` after
    normalising, or names no file at all — fail closed (AD-13)."""
    parts = PurePosixPath(canonical).parts
    return canonical.startswith("/") or ".." in parts or canonical in ("", ".")


def _glob_match(path: str, glob: str) -> bool:
    """Case-insensitive fnmatch: `Secrets/` and `DOCKERFILE` must not evade
    a path rule by case alone."""
    return fnmatch(path.lower(), glob.lower())


def _is_test_path(path: str) -> bool:
    """A test file is one whose basename matches the test-file globs — the
    directory a test lives in must not matter."""
    return any(_glob_match(PurePosixPath(path).name, glob) for glob in _TEST_FILE_GLOBS)


def _changed_lines(prior: str, new: str, added: bool) -> list[str]:
    """The added (or removed) lines of one modification, via `difflib` so a
    relocated line surfaces as a remove+add pair instead of silence."""
    prior_lines = prior.splitlines()
    new_lines = new.splitlines()
    matcher = difflib.SequenceMatcher(a=prior_lines, b=new_lines, autojunk=False)
    lines: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if added and tag in ("insert", "replace"):
            lines.extend(new_lines[j1:j2])
        elif not added and tag in ("delete", "replace"):
            lines.extend(prior_lines[i1:i2])
    return lines


def _added_lines(file: DiffFile, prior_contents: Mapping[str, str]) -> list[str]:
    """The lines a diff adds: all of them for a new file, the difflib-added
    ones for a modification, none for a deletion — or when the base is
    missing (`prior_content_missing` covers that file)."""
    if file.op is DiffOperation.DELETE:
        return []
    if file.op is DiffOperation.ADD:
        return file.new_content.splitlines()
    prior = prior_contents.get(_canonical_path(file.path))
    if prior is None:
        return []
    return _changed_lines(prior, file.new_content, added=True)


def _removed_lines(file: DiffFile, prior_contents: Mapping[str, str]) -> list[str]:
    """The base lines a modification drops (difflib, so a relocation shows
    up on both sides); nothing without the base content."""
    if file.op is not DiffOperation.MODIFY:
        return []
    prior = prior_contents.get(_canonical_path(file.path))
    if prior is None:
        return []
    return _changed_lines(prior, file.new_content, added=False)


def _timeout_values(text: str) -> list[float]:
    return [float(first or second) for first, second in _TIMEOUT_PATTERN.findall(text)]


def _assertion_tokens(lines: Sequence[str], pattern: re.Pattern[str]) -> set[str]:
    return {
        group
        for groups in pattern.findall("\n".join(lines))
        for group in groups
        if group
    }


def _added_line_hits(
    gate: GateInput,
    pattern: re.Pattern[str],
    code: str,
    message_for: Callable[[str, str], str],
) -> tuple[GateReason, ...]:
    """One reason per file for the first added line matching `pattern`."""
    if gate.diff is None:
        return ()
    reasons: list[GateReason] = []
    for file in gate.diff.files:
        for line in _added_lines(file, gate.prior_contents):
            if pattern.search(line):
                reasons.append(
                    GateReason(
                        rule_code=code,
                        message=message_for(file.path, line),
                        location=file.path,
                    )
                )
                break
    return tuple(reasons)


def _skip_message(path: str, line: str) -> str:
    return f"test skipped or xfailed: {line.strip()!r} in {path}"


def _retry_message(path: str, line: str) -> str:
    return f"retry machinery added: {line.strip()!r} in {path}"


def _check_test_disabled(gate: GateInput) -> tuple[GateReason, ...]:
    """Skip/xfail markers on added lines, or a deleted test file (AD-13)."""
    if gate.diff is None:
        return ()
    deletions = tuple(
        GateReason(
            rule_code=TEST_DISABLED,
            message=f"test file deleted: {file.path}",
            location=file.path,
        )
        for file in gate.diff.files
        if file.op is DiffOperation.DELETE and _is_test_path(_canonical_path(file.path))
    )
    return deletions + _added_line_hits(
        gate, _SKIP_PATTERN, TEST_DISABLED, _skip_message
    )


def _check_retry_added(gate: GateInput) -> tuple[GateReason, ...]:
    """Retry machinery on an added line (AD-13)."""
    return _added_line_hits(gate, _RETRY_PATTERN, RETRY_ADDED, _retry_message)


def _check_timeout_increased(gate: GateInput) -> tuple[GateReason, ...]:
    """Per-line timeout comparison over the changed lines (AD-13): a timeout
    raised above the value it replaced, a brand-new timeout on an added line,
    or any timeout in a newly added file — each blocks. A file-wide max
    comparison would let a bump hide behind a larger unchanged timeout; the
    difflib-derived changed lines keep that closed. A missing base is
    `prior_content_missing`'s job."""
    if gate.diff is None:
        return ()
    reasons: list[GateReason] = []
    for file in gate.diff.files:
        if file.op is DiffOperation.ADD:
            added = _timeout_values(file.new_content)
            if added:
                reasons.append(
                    GateReason(
                        rule_code=TIMEOUT_INCREASED,
                        message=(f"new file introduces a timeout ({max(added)})"),
                        location=file.path,
                    )
                )
            continue
        if file.op is not DiffOperation.MODIFY:
            continue
        prior = gate.prior_contents.get(_canonical_path(file.path))
        if prior is None:
            continue
        removed = _timeout_values("\n".join(_removed_lines(file, gate.prior_contents)))
        added = _timeout_values("\n".join(_added_lines(file, gate.prior_contents)))
        if added and (not removed or max(added) > max(removed)):
            reasons.append(
                GateReason(
                    rule_code=TIMEOUT_INCREASED,
                    message=(
                        f"timeout raised from {max(removed, default=0)} to {max(added)}"
                    ),
                    location=file.path,
                )
            )
    return tuple(reasons)


def _check_assertion_loosened(gate: GateInput) -> tuple[GateReason, ...]:
    """A strong assertion removed while a weak one on the same target token
    was added (AD-13): `assertEqual(tok,` → `assertIn(tok,`,
    `assert tok ==` → `assert tok in`/`assertTrue(tok`/`assertIsNotNone(tok`/
    `assert tok == pytest.approx` — the token may be dotted or subscripted.
    A test file whose changed lines hold net fewer assertion lines than its
    base is a deletion, and blocks too."""
    if gate.diff is None:
        return ()
    reasons: list[GateReason] = []
    for file in gate.diff.files:
        removed_lines = _removed_lines(file, gate.prior_contents)
        added_lines = _added_lines(file, gate.prior_contents)
        removed = _assertion_tokens(removed_lines, _STRONG_ASSERTION)
        added = _assertion_tokens(added_lines, _WEAK_ASSERTION)
        reasons.extend(
            GateReason(
                rule_code=ASSERTION_LOOSENED,
                message=f"assertion on {token!r} loosened",
                location=file.path,
            )
            for token in sorted(removed & added)
        )
        removed_count = sum(1 for line in removed_lines if _ASSERTION_LINE.search(line))
        added_count = sum(1 for line in added_lines if _ASSERTION_LINE.search(line))
        if removed_count > added_count:
            reasons.append(
                GateReason(
                    rule_code=ASSERTION_LOOSENED,
                    message=(
                        f"assertion lines removed without a replacement "
                        f"({removed_count} removed, {added_count} added)"
                    ),
                    location=file.path,
                )
            )
    return tuple(reasons)


def _touched_paths(
    gate: GateInput,
    globs: Sequence[str],
    code: str,
    verb: str,
) -> tuple[GateReason, ...]:
    """One reason per file whose path matches any of the globs."""
    if gate.diff is None:
        return ()
    return tuple(
        GateReason(rule_code=code, message=f"{verb}: {file.path}", location=file.path)
        for file in gate.diff.files
        if any(_glob_match(_canonical_path(file.path), glob) for glob in globs)
    )


def _check_workflow_file_touched(gate: GateInput) -> tuple[GateReason, ...]:
    return _touched_paths(
        gate,
        (gate.config.workflow_path_glob,),
        WORKFLOW_FILE_TOUCHED,
        "workflow file touched",
    )


def _check_secret_touched(gate: GateInput) -> tuple[GateReason, ...]:
    return _touched_paths(
        gate, gate.config.secret_path_globs, SECRET_TOUCHED, "secret file touched"
    )


def _check_infra_manifest_touched(gate: GateInput) -> tuple[GateReason, ...]:
    return _touched_paths(
        gate,
        gate.config.infra_path_globs,
        INFRA_MANIFEST_TOUCHED,
        "infra manifest touched",
    )


def _check_reviewer_dangerous(gate: GateInput) -> tuple[GateReason, ...]:
    """A `dangerous` Reviewer objection blocks a safe diff too (AD-12)."""
    return tuple(
        GateReason(
            rule_code=REVIEWER_DANGEROUS,
            message=f"dangerous objection: {objection.category}: {objection.claim}",
            location=f"objections[{index}]",
        )
        for index, objection in enumerate(gate.objections)
        if objection.severity is ObjectionSeverity.DANGEROUS
    )


def _check_unsafe_path(gate: GateInput) -> tuple[GateReason, ...]:
    """Absolute, repo-escaping or empty paths fail closed before any glob is
    consulted (AD-13): normalisation cannot be tricked into a protected path,
    and a path that names no file is refused outright."""
    if gate.diff is None:
        return ()
    return tuple(
        GateReason(
            rule_code=UNSAFE_PATH,
            message=(
                f"path is absolute, escapes the repo, or names no file: {file.path}"
            ),
            location=file.path,
        )
        for file in gate.diff.files
        if _is_unsafe_path(_canonical_path(file.path))
    )


def _check_prior_content_missing(gate: GateInput) -> tuple[GateReason, ...]:
    """Fail closed (AD-13): a modification whose base content the caller did
    not supply blocks — and so does a path replaced by a DELETE + ADD pair,
    which no comparison rule can see — so gating is never silently skipped."""
    if gate.diff is None:
        return ()
    delete_paths = {
        file.path for file in gate.diff.files if file.op is DiffOperation.DELETE
    }
    add_paths = {file.path for file in gate.diff.files if file.op is DiffOperation.ADD}
    return tuple(
        GateReason(
            rule_code=PRIOR_CONTENT_MISSING,
            message=(
                f"modified file has no base content to compare against: {file.path}"
            ),
            location=file.path,
        )
        for file in gate.diff.files
        if file.op is DiffOperation.MODIFY
        and _canonical_path(file.path)
        not in {_canonical_path(path) for path in gate.prior_contents}
    ) + tuple(
        GateReason(
            rule_code=PRIOR_CONTENT_MISSING,
            message=(
                "path replaced by a delete and an add in one diff, base "
                f"comparison impossible: {path}"
            ),
            location=path,
        )
        for path in sorted(delete_paths & add_paths)
    )


@dataclass(frozen=True)
class RiskRule:
    """One AD-13 rule: a code plus its pure check (SOLID-O — the registry is
    the extension point; a new rule is a new entry, never a new if/elif)."""

    code: str
    check: Callable[[GateInput], tuple[GateReason, ...]]


RISK_RULES: Final[tuple[RiskRule, ...]] = (
    RiskRule(code=UNSAFE_PATH, check=_check_unsafe_path),
    RiskRule(code=TEST_DISABLED, check=_check_test_disabled),
    RiskRule(code=RETRY_ADDED, check=_check_retry_added),
    RiskRule(code=TIMEOUT_INCREASED, check=_check_timeout_increased),
    RiskRule(code=ASSERTION_LOOSENED, check=_check_assertion_loosened),
    RiskRule(code=WORKFLOW_FILE_TOUCHED, check=_check_workflow_file_touched),
    RiskRule(code=SECRET_TOUCHED, check=_check_secret_touched),
    RiskRule(code=INFRA_MANIFEST_TOUCHED, check=_check_infra_manifest_touched),
    RiskRule(code=REVIEWER_DANGEROUS, check=_check_reviewer_dangerous),
    RiskRule(code=PRIOR_CONTENT_MISSING, check=_check_prior_content_missing),
)


def evaluate_risk(gate: GateInput) -> GateDecision:
    """The one gate entry point: no diff → `not_gated`; any rule hit →
    `blocked` with ALL reasons collected; otherwise `normal`. Deterministic
    and pure — no GitHub, Postgres, HTTP or model call (AD-13)."""
    if gate.diff is None:
        return GateDecision(risk_tier=RiskTier.NOT_GATED, reasons=())
    reasons = tuple(reason for rule in RISK_RULES for reason in rule.check(gate))
    if reasons:
        return GateDecision(risk_tier=RiskTier.BLOCKED, reasons=reasons)
    return GateDecision(risk_tier=RiskTier.NORMAL, reasons=())
