"""Confidence, caps and the classification-branch cut-off predicates (AD-9).

Pure domain code (stdlib + pydantic + `contracts` only, layer contract):
`ClassConfidence.confidence` is computed — `min(confidence_jev, caps…)` via
`contracts.verdict.effective_confidence`, the rule's one home — never set.
`RouteConfidence` is a separate type so a no-route confidence can never be
fed to a classification-branch predicate by mistake (`below_class_cutoff`
type-checks against `ClassConfidence` and refuses anything else).
"""

from pydantic import BaseModel, ConfigDict, Field

from contracts.citations import JevSignalCitation
from contracts.enums import EscalationReason, FailureClass
from contracts.jev import JevChoice, JevInjectionScreen
from contracts.verdict import Cap, effective_confidence

__all__ = [
    "ClassConfidence",
    "ConfidenceCutoffs",
    "RouteConfidence",
    "apply_injection_screen",
    "below_class_cutoff",
    "class_escalation",
]


class ConfidenceCutoffs(BaseModel):
    """Cut-offs read from `guardrails/thresholds.yaml` (AD-19).

    "Below" means `confidence < cutoff`; a confidence equal to the cutoff is
    not below it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    class_cutoff: float = Field(ge=0.0, le=1.0)
    no_route_cutoff: float = Field(ge=0.0, le=1.0)
    injection_screen_cutoff: float = Field(ge=0.0, le=1.0)
    injection_screen_cap: float = Field(ge=0.0, le=1.0)


class ClassConfidence(BaseModel):
    """One class's confidence (AD-9): `confidence_jev` is frozen once built;
    `confidence` is computed, with no setter or constructor argument."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    failure_class: FailureClass
    confidence_jev: float = Field(ge=0.0, le=1.0)
    caps: tuple[Cap, ...] = ()

    @property
    def confidence(self) -> float:
        """The one min rule (AD-9): reuses `contracts.verdict.effective_confidence`."""
        return effective_confidence(self.confidence_jev, self.caps)

    @classmethod
    def from_jev(cls, choice: JevChoice) -> "ClassConfidence":
        """Build from a Jev `Choice` answer; `probabilities` play no part
        (AD-9: stored in audit only, never read by a decision function)."""
        return cls(failure_class=choice.answer, confidence_jev=choice.confidence)

    def with_cap(self, cap: Cap) -> "ClassConfidence":
        """Add one cap; `confidence_jev` and the existing caps are untouched."""
        return ClassConfidence(
            failure_class=self.failure_class,
            confidence_jev=self.confidence_jev,
            caps=(*self.caps, cap),
        )


class RouteConfidence(BaseModel):
    """Confidence for the (future) no-route escalation check — a type
    distinct from `ClassConfidence` so a classification predicate cannot be
    misapplied to it (AD-9, AD-10 routing stays out of this story)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    confidence: float = Field(ge=0.0, le=1.0)


def apply_injection_screen(
    confidence: ClassConfidence,
    screen: JevInjectionScreen,
    cutoffs: ConfidenceCutoffs,
) -> ClassConfidence:
    """A positive Noul screen (`noul >= cutoff`) adds one cited cap; it never
    escalates on its own (spine: "a positive injection screen adds a cited
    cap; it never blocks on its own")."""
    if screen.noul < cutoffs.injection_screen_cutoff:
        return confidence
    cap = Cap(
        value=cutoffs.injection_screen_cap,
        reason="injection pre-screen flagged this answer",
        citations=(JevSignalCitation(answer="noul"),),
    )
    return confidence.with_cap(cap)


def _require_class_confidence(confidence: ClassConfidence) -> None:
    """Refuse a `RouteConfidence` (or anything else) at runtime, not only by
    the type hint — both classification-branch predicates call this first."""
    if not isinstance(confidence, ClassConfidence):
        raise TypeError(f"expected a ClassConfidence, got {type(confidence).__name__}")


def below_class_cutoff(confidence: ClassConfidence, cutoffs: ConfidenceCutoffs) -> bool:
    """`confidence.confidence < cutoffs.class_cutoff`."""
    _require_class_confidence(confidence)
    return confidence.confidence < cutoffs.class_cutoff


def class_escalation(
    confidence: ClassConfidence,
    cutoffs: ConfidenceCutoffs,
    class_override: FailureClass | None = None,
) -> EscalationReason | None:
    """The classification branch's escalation reason, or `None` (AD-1, AD-9).

    A `class_override` (AD-14) replaces only these two cut-off checks; it
    changes neither `confidence_jev` nor `confidence`.
    """
    _require_class_confidence(confidence)
    if class_override is not None:
        return None
    if confidence.failure_class is FailureClass.UNKNOWN:
        return EscalationReason.UNKNOWN_CLASS
    if below_class_cutoff(confidence, cutoffs):
        return EscalationReason.LOW_CONFIDENCE
    return None
