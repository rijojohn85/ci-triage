"""The one shared `run_step` column set for the integration tests (DRY).

Story 2.3's base columns plus story 6.1's audit columns (AD-18); both
integration test files assert against this single constant.
"""

from typing import Final

EXPECTED_RUN_STEP_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "step_id",
        "run_id",
        "repo_id",
        "step",
        "attempt",
        "status",
        "output",
        "created_at",
        # Story 6.1 (AD-18): the audit columns on every attempt row. Story
        # 2.3's original "no model/token columns yet" guard is superseded by
        # the 6.1 spec; cost columns still arrive only with 6.2.
        "model",
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens_5m",
        "cache_creation_input_tokens_1h",
        "outcome",
    }
)
