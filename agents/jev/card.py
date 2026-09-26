"""The agent card: exactly the one catalogue skill, non-streaming (AD-5).

The skill id is from the closed catalogue (`classify-failure`); discovery
(3.9) pins this card by digest, so the card stays minimal and stable.
"""

from a2a.types.a2a_pb2 import AgentCapabilities, AgentCard, AgentSkill

__all__ = ["SKILL_ID", "agent_card"]

SKILL_ID = "classify-failure"


def agent_card() -> AgentCard:
    """The public card served at `/.well-known/agent-card.json` (AD-5)."""
    return AgentCard(
        name="jev-classifier",
        description=(
            "Classifies a distilled CI failure into one of five classes and "
            "screens the log for injection, in one batched model call (AD-11)."
        ),
        version="0.1.0",
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        skills=[
            AgentSkill(
                id=SKILL_ID,
                name=SKILL_ID,
                description=(
                    "Serves JevResult{classification, usage} for one "
                    "EvidencePack; errors carry AgentError{code, message, "
                    "retryable}."
                ),
                tags=[SKILL_ID],
            )
        ],
    )
