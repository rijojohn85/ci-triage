"""`pr_feedback` domain type: post-terminal human feedback on an opened PR
(story 2.6, AC3/RT-04, AD-15).

Kept in its own module/table pair from `history.py`/`history_store.py` on
purpose (SOLID-S): `feedback_text` is free text by design, and free text must
never reach `history`, which is structured-only. No code path shares a
writer between the two tables.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

__all__ = ["PRFeedbackEntry", "PRFeedbackWriteFailedError"]


@dataclass(frozen=True)
class PRFeedbackEntry:
    """One persisted `pr_feedback` row."""

    feedback_id: uuid.UUID
    run_id: uuid.UUID
    repo_id: int
    pr_number: int
    feedback_text: str
    author_login: str
    created_at: datetime


class PRFeedbackWriteFailedError(Exception):
    """A `pr_feedback` insert returned no row though it always `RETURNING`s one.

    Definitive, never retryable (AD-22): a missing insert result is a
    data-integrity fault, not a transient condition.
    """

    retryable: bool = False

    def __init__(self, run_id: uuid.UUID) -> None:
        super().__init__(f"pr_feedback write for run {run_id} returned no row")
        self.run_id = run_id
