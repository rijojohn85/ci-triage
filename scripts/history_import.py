"""Seed `history` rows from a JSON array (story 2.6, AC1/AC3).

The only way seed/backfilled history enters the database (the Boundaries &
Constraints in the spec: "seed rows enter only via a `history import`
script"). Reads a JSON array of import records from a file or stdin, builds
one `workflow.history.ImportRecord` per row and rejects any row with an
unexpected key (e.g. free-text `notes`) before writing anything, then calls
`HistoryStore.import_seed` and prints the returned `row_id`s.

Usage:
    python scripts/history_import.py --file seed.json
    cat seed.json | python scripts/history_import.py

Each row is a JSON object with exactly these keys: `repo_id`, `test_id`,
`error_type`, `top_stack_frames` (a list of strings), `terminal_state` (one
of DONE_PR/DONE_REPORT/REJECTED_BY_HUMAN/FAILED), and optionally
`human_verdict` (approved/rejected).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg

from workflow.history import HumanVerdict, ImportRecord, NonTerminalWriteError
from workflow.history_store import HistoryStore, PostgresHistoryStore
from workflow.run_states import RunState

EXIT_OK = 0
EXIT_INVALID_INPUT = 1
EXIT_NO_DSN = 2
EXIT_IMPORT_FAILED = 3


class HistoryImportError(Exception):
    """The input JSON could not be turned into import records."""


def build_records(raw_rows: list[dict[str, Any]]) -> list[ImportRecord]:
    """Build one `ImportRecord` per row; an unenumerated key is a `TypeError`."""
    records = []
    for raw in raw_rows:
        fields = dict(raw)
        try:
            fields["terminal_state"] = RunState(fields["terminal_state"])
            frames = fields["top_stack_frames"]
            if not isinstance(frames, list):
                # A plain string would otherwise split into characters via
                # tuple(), silently corrupting the fingerprint.
                raise HistoryImportError(
                    "top_stack_frames must be a JSON array of strings, "
                    f"got {type(frames).__name__}"
                )
            fields["top_stack_frames"] = tuple(frames)
            verdict = fields.get("human_verdict")
            fields["human_verdict"] = (
                HumanVerdict(verdict) if verdict is not None else None
            )
        except (KeyError, ValueError) as exc:
            raise HistoryImportError(str(exc)) from exc
        records.append(ImportRecord(**fields))  # extra key -> TypeError
    return records


def read_rows(source: Path | None) -> list[dict[str, Any]]:
    text = (
        source.read_text(encoding="utf-8") if source is not None else sys.stdin.read()
    )
    data = json.loads(text)
    if not isinstance(data, list):
        raise HistoryImportError("input must be a JSON array of import records")
    return data


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="JSON file of import records (default: read stdin)",
    )
    return parser.parse_args(argv)


def _default_store() -> HistoryStore:
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise HistoryImportError("DATABASE_URL is not set")
    return PostgresHistoryStore(dsn)


def main(
    argv: list[str] | None = None,
    store_factory: Callable[[], HistoryStore] | None = None,
) -> int:
    """Process boundary: argv/exit codes/env live only here."""
    args = parse_args(argv)
    try:
        rows = read_rows(args.file)
        records = build_records(rows)
    except (json.JSONDecodeError, HistoryImportError, TypeError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return EXIT_INVALID_INPUT

    try:
        store = (store_factory or _default_store)()
    except HistoryImportError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return EXIT_NO_DSN

    try:
        row_ids = store.import_seed(records)
    except (psycopg.Error, NonTerminalWriteError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return EXIT_IMPORT_FAILED

    for row_id in row_ids:
        print(row_id)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
