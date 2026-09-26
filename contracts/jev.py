"""Jev classification result (AD-9, AD-11): one `system_one` call's answers.

Frozen, closed models mirror typesafe_sdk 0.7.1's `ChoiceAnswer`/`NoulAnswer`
(checked in the installed source: `ChoiceAnswer{type,choice,confidence,
probabilities}`, `NoulAnswer{type,noul}`, both frozen pydantic). `contracts/`
never imports the SDK package itself (layer contract): `from_sdk` accepts a
structural `Protocol` instead, so any object with the right attributes
converts, not only the installed SDK's class.
"""

from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field

from contracts.enums import FailureClass
from contracts.usage import ModelUsage

__all__ = [
    "JevChoice",
    "JevClassification",
    "JevInjectionScreen",
    "JevResult",
    "SdkChoiceAnswer",
    "SdkNoulAnswer",
]


class SdkChoiceAnswer(Protocol):
    """Structural shape of typesafe_sdk 0.7.1's `ChoiceAnswer`."""

    choice: str
    confidence: float
    probabilities: dict[str, float]


class SdkNoulAnswer(Protocol):
    """Structural shape of typesafe_sdk 0.7.1's `NoulAnswer`."""

    noul: float


class JevChoice(BaseModel):
    """The 5-class `Choice` answer: `confidence_jev`'s source (AD-9, AD-11).

    Frozen once built (AD-9): nothing downstream may mutate the Jev number.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: FailureClass
    confidence: float = Field(ge=0.0, le=1.0)
    probabilities: dict[FailureClass, Annotated[float, Field(ge=0.0, le=1.0)]]
    """Stored in audit only (AD-9); never read by a decision function."""

    @classmethod
    def from_sdk(cls, answer: SdkChoiceAnswer) -> "JevChoice":
        """Convert one SDK `ChoiceAnswer` into the frozen contract (AD-9)."""
        return cls(
            answer=FailureClass(answer.choice),
            confidence=answer.confidence,
            probabilities={
                FailureClass(choice): probability
                for choice, probability in answer.probabilities.items()
            },
        )


class JevInjectionScreen(BaseModel):
    """The injection pre-screen `Noul` answer (spine "One Jev call" rule):
    a probability, not a boolean — `guardrails.confidence` turns it into a
    cited cap above its cutoff.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    noul: float = Field(ge=0.0, le=1.0)

    @classmethod
    def from_sdk(cls, answer: SdkNoulAnswer) -> "JevInjectionScreen":
        """Convert one SDK `NoulAnswer` into the frozen contract."""
        return cls(noul=answer.noul)


class JevClassification(BaseModel):
    """One Jev `system_one` call: the class choice plus the injection screen
    (spine: one call carries both the 5-class `Choice` and the `Noul`
    pre-screen)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    choice: JevChoice
    injection_screen: JevInjectionScreen


class JevResult(BaseModel):
    """What the Jev agent serves for one `classify-failure` call (story 3.1).

    The classification plus the provider-reported usage (AD-18): the
    orchestrator/harness owns the accounting, so the agent only reports what
    the provider reported — unreported counters stay NULL, never 0.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    classification: JevClassification
    usage: ModelUsage
