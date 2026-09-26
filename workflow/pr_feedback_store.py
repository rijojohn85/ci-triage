"""The one Postgres adapter for `pr_feedback` (story 2.6, AC3/RT-04, AD-15).

The connection Protocol + opener are shared with `workflow/history_store.py`
via `workflow/db.py` (DRY). No lease is needed — PR feedback is written
after the run is already terminal, same as `history`. `PostgresPRFeedbackStore`
is the one implementation; no separate Protocol is declared for it (unlike
`HistoryStore`, it is never consumed as an abstract type or faked anywhere).
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import cast

from workflow.db import Connection, open_connection
from workflow.pr_feedback import PRFeedbackEntry, PRFeedbackWriteFailedError

__all__ = ["PostgresPRFeedbackStore"]

_INSERT_SQL = """
INSERT INTO pr_feedback (
    feedback_id, run_id, repo_id, pr_number, feedback_text, author_login
)
VALUES (%s, %s, %s, %s, %s, %s)
RETURNING created_at
"""

_LIST_FOR_RUN_SQL = """
SELECT feedback_id, run_id, repo_id, pr_number, feedback_text, author_login, created_at
FROM pr_feedback
WHERE repo_id = %s AND run_id = %s
ORDER BY created_at
"""


class PostgresPRFeedbackStore:
    """I/O adapter: write one feedback row, list a run's feedback (repo-scoped)."""

    def __init__(
        self,
        dsn: str,
        connect: Callable[[str], Connection] | None = None,
    ) -> None:
        self._dsn = dsn
        self._connect: Callable[[str], Connection] = connect or open_connection

    def write(
        self,
        run_id: uuid.UUID,
        repo_id: int,
        pr_number: int,
        feedback_text: str,
        author_login: str,
    ) -> PRFeedbackEntry:
        feedback_id = uuid.uuid4()
        with self._connect(self._dsn) as conn:
            created = conn.execute(
                _INSERT_SQL,
                (feedback_id, run_id, repo_id, pr_number, feedback_text, author_login),
            ).fetchone()
        if created is None:  # pragma: no cover - defensive, INSERT always returns a row
            raise PRFeedbackWriteFailedError(run_id)
        return PRFeedbackEntry(
            feedback_id=feedback_id,
            run_id=run_id,
            repo_id=repo_id,
            pr_number=pr_number,
            feedback_text=feedback_text,
            author_login=author_login,
            created_at=cast(datetime, created[0]),
        )

    def list_for_run(self, repo_id: int, run_id: uuid.UUID) -> list[PRFeedbackEntry]:
        with self._connect(self._dsn) as conn:
            rows = conn.execute(_LIST_FOR_RUN_SQL, (repo_id, run_id)).fetchall()
        return [
            PRFeedbackEntry(
                feedback_id=cast(uuid.UUID, row[0]),
                run_id=cast(uuid.UUID, row[1]),
                repo_id=cast(int, row[2]),
                pr_number=cast(int, row[3]),
                feedback_text=str(row[4]),
                author_login=str(row[5]),
                created_at=cast(datetime, row[6]),
            )
            for row in rows
        ]
