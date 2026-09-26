"""The pure verdict validator (AD-6, AD-7, AD-8, AD-9, AD-27).

Two validation layers, one issue shape: the committed generated JSON schema
(`guardrails/schemas/TriageVerdict.json`, AD-6 — never hand-edited) catches
shape/enum/pattern violations; the `contracts.TriageVerdict` parse catches
the invariants JSON Schema cannot express (the min rule, suspect blame
kinds). On top of the parsed verdict, the semantic checks run: every citation
resolves against the `ServedEvidence` (AD-7), suspects come only from
`candidate_suspects` (AD-24), `confidence_jev` is this run's Jev number
(AD-9), and blame-free output carries no author attribution (AD-27).

All issues are collected in one pass — never raised past this boundary —
because AD-8's retry/pause policy belongs to the shared step runner (2.8),
which this module must not re-implement.
"""

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

import jsonschema
from pydantic import BaseModel, ConfigDict, ValidationError

from contracts.jev import JevClassification
from contracts.verdict import TriageVerdict
from guardrails.attribution import attribution_location
from guardrails.citation_check import (
    ServedEvidence,
    ValidationIssue,
    check_citations,
)

__all__ = [
    "ClassificationResult",
    "ServedEvidence",
    "ValidationIssue",
    "ValidationResult",
    "validate_classification",
    "validate_verdict",
]

SCHEMA = "schema"
"""Issue code: a JSON-schema or pydantic shape/invariant violation."""

SUSPECT_NOT_CANDIDATE = "suspect_not_candidate"
"""Issue code: a suspect sha outside the served `candidate_suspects` (AD-24)."""

CONFIDENCE_MISMATCH = "confidence_mismatch"
"""Issue code: `confidence_jev` is not this run's Jev `Choice.confidence`
(AD-9 — probabilities are audit-only, never a confidence source)."""

ATTRIBUTION_PRESENT = "attribution_present"
"""Issue code: an `author_login` key inside blame-free output (AD-27)."""

_SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"
_SCHEMA_PATH = _SCHEMAS_DIR / "TriageVerdict.json"
_VERDICT_CHECKER = jsonschema.Draft202012Validator(
    json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
)
_CLASSIFICATION_SCHEMA_PATH = _SCHEMAS_DIR / "JevClassification.json"
_CLASSIFICATION_CHECKER = jsonschema.Draft202012Validator(
    json.loads(_CLASSIFICATION_SCHEMA_PATH.read_text(encoding="utf-8"))
)


class ValidationResult(BaseModel):
    """The validator's whole answer: the parsed verdict (if any) and every issue."""

    model_config = ConfigDict(frozen=True)

    verdict: TriageVerdict | None
    issues: tuple[ValidationIssue, ...]


class ClassificationResult(BaseModel):
    """`validate_classification`'s whole answer (story 2.8, AC1).

    Schema + parse only: the CLASSIFYING payload is Jev's own answer, so there
    are no citations to resolve (AD-7 does not apply) — the two committed
    layers (generated schema + contract parse) are the whole surface.
    """

    model_config = ConfigDict(frozen=True)

    classification: JevClassification | None
    issues: tuple[ValidationIssue, ...]


def validate_verdict(
    payload: object,
    served: ServedEvidence,
    *,
    blame_free: bool,
) -> ValidationResult:
    """Validate one raw agent payload against the evidence served this run.

    `blame_free` is required — the caller must state the AD-27 decision
    explicitly (state arms plus the class cutoff,
    `workflow.attribution.attribution_allowed`); when it is true, any
    `author_login` key at any depth is an issue, collected even when the
    payload also fails schema/parse so the retry feedback shows the leak.
    Unknown/absent run confidence is served blame-free by the caller
    (defensive default).
    """
    issues: list[ValidationIssue] = _schema_issues(payload)
    if blame_free:
        issues.extend(_attribution_issues(payload))
    verdict = _parse(payload, issues)
    if verdict is None:
        return ValidationResult(verdict=None, issues=tuple(issues))
    issues.extend(_citation_issues(verdict, served))
    issues.extend(_suspect_issues(verdict, served))
    issues.extend(_confidence_issues(verdict, served))
    return ValidationResult(verdict=verdict, issues=tuple(issues))


def validate_classification(payload: object) -> ClassificationResult:
    """Validate one raw CLASSIFYING payload: schema + parse only (story 2.8).

    Same two-layer pattern as `validate_verdict`, same issue shape — the
    committed generated `JevClassification.json` (AD-6) catches shape/enum
    violations; the `contracts.JevClassification` parse catches the invariants
    JSON Schema cannot express. Issues are collected, never raised: AD-8's
    retry/pause policy belongs to the shared step runner (2.8).
    """
    issues: list[ValidationIssue] = [
        ValidationIssue(
            code=SCHEMA,
            message=error.message,
            location=_format_path(error.absolute_path),
        )
        for error in _CLASSIFICATION_CHECKER.iter_errors(payload)
    ]
    classification = _parse_classification(payload, issues)
    return ClassificationResult(classification=classification, issues=tuple(issues))


def _parse_classification(
    payload: object,
    issues: list[ValidationIssue],
) -> JevClassification | None:
    """Parse with the contract so model invariants surface as the same issues."""
    if not isinstance(payload, Mapping):
        return None  # the schema layer already reported the type violation
    try:
        return JevClassification.model_validate(dict(payload))
    except ValidationError as error:
        issues.extend(
            ValidationIssue(
                code=SCHEMA,
                message=str(item["msg"]),
                location=_format_path(item["loc"]),
            )
            for item in error.errors()
        )
        return None


def _schema_issues(payload: object) -> list[ValidationIssue]:
    """The committed generated schema is the validation surface (AD-6)."""
    return [
        ValidationIssue(
            code=SCHEMA,
            message=error.message,
            location=_format_path(error.absolute_path),
        )
        for error in _VERDICT_CHECKER.iter_errors(payload)
    ]


def _parse(
    payload: object,
    issues: list[ValidationIssue],
) -> TriageVerdict | None:
    """Parse with the contract so model invariants surface as the same issues."""
    if not isinstance(payload, Mapping):
        return None  # the schema layer already reported the type violation
    try:
        return TriageVerdict.model_validate(dict(payload))
    except ValidationError as error:
        issues.extend(
            ValidationIssue(
                code=SCHEMA,
                message=str(item["msg"]),
                location=_format_path(item["loc"]),
            )
            for item in error.errors()
        )
        return None


def _citation_issues(
    verdict: TriageVerdict,
    served: ServedEvidence,
) -> list[ValidationIssue]:
    """Every citation surface: top level, each cap and the quarantine."""
    issues = check_citations(verdict.citations, served, "citations")
    for index, cap in enumerate(verdict.caps):
        base = f"caps[{index}].citations"
        issues.extend(check_citations(cap.citations, served, base))
    if verdict.quarantine is not None:
        issues.extend(
            check_citations(
                verdict.quarantine.citations, served, "quarantine.citations"
            )
        )
    return issues


def _suspect_issues(
    verdict: TriageVerdict,
    served: ServedEvidence,
) -> list[ValidationIssue]:
    """Suspects only from `candidate_suspects` (AD-24); blame kinds are the
    parse layer's job (`contracts.verdict.Suspect`)."""
    issues: list[ValidationIssue] = []
    candidates = {suspect.sha for suspect in served.pack.candidate_suspects}
    for index, suspect in enumerate(verdict.suspects):
        if suspect.sha not in candidates:
            issues.append(
                ValidationIssue(
                    code=SUSPECT_NOT_CANDIDATE,
                    message=(
                        f"suspect sha {suspect.sha} is not in the served "
                        "candidate_suspects"
                    ),
                    location=f"suspects[{index}]",
                )
            )
        issues.extend(
            check_citations(suspect.citations, served, f"suspects[{index}].citations")
        )
    return issues


def _confidence_issues(
    verdict: TriageVerdict,
    served: ServedEvidence,
) -> list[ValidationIssue]:
    """`confidence_jev` is this run's Jev `Choice.confidence` (AD-9)."""
    jev_confidence = served.jev.choice.confidence
    if verdict.confidence_jev == jev_confidence:
        return []
    return [
        ValidationIssue(
            code=CONFIDENCE_MISMATCH,
            message=(
                f"confidence_jev {verdict.confidence_jev} is not this run's Jev "
                f"Choice confidence {jev_confidence}; probabilities are audit-only"
            ),
            location="confidence_jev",
        )
    ]


def _attribution_issues(payload: object) -> list[ValidationIssue]:
    """Blame-free output carries no author attribution at any depth (AD-27)."""
    location = attribution_location(payload)
    if location is None:
        return []
    return [
        ValidationIssue(
            code=ATTRIBUTION_PRESENT,
            message="author_login is present in blame-free output (AD-27)",
            location=location,
        )
    ]


def _format_path(path: Iterable[str | int]) -> str:
    """One location spelling everywhere: `suspects[0].citations[0]`; the root
    (a whole-payload error) is the empty string."""
    formatted = ""
    for element in path:
        formatted += f"[{element}]" if isinstance(element, int) else f".{element}"
    return formatted.lstrip(".")
