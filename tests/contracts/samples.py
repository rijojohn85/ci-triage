"""Shared payload literals for the contract suites (spine conventions)."""

import uuid

# RFC 9562 UUIDv7: the run_id/task_id/contextId convention root (any 3.10+ runtime).
RUN_ID = uuid.UUID("017f22e2-79b0-7cc3-98c4-dc0c0c07398f")

# Full 40-char hex SHA, used by suspects, commits and citations (AD-6, AD-26).
FULL_SHA = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f80912"
