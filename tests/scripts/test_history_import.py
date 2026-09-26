"""Story 2.6 CLI unit tests: `scripts/history_import.py` (AC1/AC3).

Drives `main()` with an injected fake store so no database is touched.
"""

import json
import uuid
from pathlib import Path

import pytest

from scripts.history_import import (
    EXIT_IMPORT_FAILED,
    EXIT_INVALID_INPUT,
    EXIT_OK,
    HistoryImportError,
    build_records,
    main,
)
from workflow.history import HumanVerdict, ImportRecord, NonTerminalWriteError
from workflow.run_states import RunState

VALID_ROWS = [
    {
        "repo_id": 7,
        "test_id": "tests/test_x.py::test_y",
        "error_type": "AssertionError",
        "top_stack_frames": ["frame_a", "frame_b"],
        "terminal_state": "FAILED",
    },
    {
        "repo_id": 7,
        "test_id": "tests/test_z.py::test_w",
        "error_type": "ValueError",
        "top_stack_frames": ["frame_c"],
        "terminal_state": "DONE_REPORT",
        "human_verdict": "approved",
    },
]


class FakeStore:
    def __init__(self) -> None:
        self.imported: list[ImportRecord] = []

    def import_seed(self, records: list[ImportRecord]) -> list[uuid.UUID]:
        self.imported.extend(records)
        return [uuid.uuid4() for _ in records]

    def write_terminal(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError

    def lookup(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError


class FailingStore:
    """Simulates a DB-layer failure from `import_seed` itself."""

    def import_seed(self, records: list[ImportRecord]) -> list[uuid.UUID]:
        raise NonTerminalWriteError(None, RunState.AWAITING_APPROVAL)

    def write_terminal(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError

    def lookup(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError


def write_json(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


class TestBuildRecords:
    def test_ac1_valid_rows_build_import_records(self) -> None:
        records = build_records(VALID_ROWS)

        assert len(records) == 2
        assert records[0].terminal_state is RunState.FAILED
        assert records[0].human_verdict is None
        assert records[1].human_verdict is HumanVerdict.APPROVED
        assert records[1].top_stack_frames == ("frame_c",)

    def test_ac3_extra_free_text_key_rejected(self) -> None:
        rows = [{**VALID_ROWS[0], "notes": "this is free text"}]

        with pytest.raises(TypeError):
            build_records(rows)

    def test_top_stack_frames_must_be_a_list_not_a_string(self) -> None:
        # A plain string would otherwise silently split into individual
        # characters via tuple(), corrupting the fingerprint.
        rows = [{**VALID_ROWS[0], "top_stack_frames": "frame_a"}]

        with pytest.raises(HistoryImportError):
            build_records(rows)

    def test_empty_string_human_verdict_is_rejected_not_swallowed(self) -> None:
        rows = [{**VALID_ROWS[0], "human_verdict": ""}]

        with pytest.raises(HistoryImportError):
            build_records(rows)


class TestMain:
    def test_ac1_valid_batch_prints_row_ids(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = write_json(tmp_path, VALID_ROWS)
        store = FakeStore()

        exit_code = main(["--file", str(path)], store_factory=lambda: store)

        assert exit_code == EXIT_OK
        assert len(store.imported) == 2
        out_lines = capsys.readouterr().out.strip().splitlines()
        assert len(out_lines) == 2
        for line in out_lines:
            uuid.UUID(line)  # each printed line is a valid row_id

    def test_ac3_rejects_a_record_with_an_extra_free_text_key(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rows = [{**VALID_ROWS[0], "notes": "free text should never pass"}]
        path = write_json(tmp_path, rows)
        store = FakeStore()

        exit_code = main(["--file", str(path)], store_factory=lambda: store)

        assert exit_code == EXIT_INVALID_INPUT
        assert store.imported == []
        assert "FAIL" in capsys.readouterr().err

    def test_missing_file_fails_cleanly_not_a_raw_traceback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "does-not-exist.json"

        exit_code = main(["--file", str(missing)], store_factory=FakeStore)

        assert exit_code == EXIT_INVALID_INPUT
        assert "FAIL" in capsys.readouterr().err

    def test_import_seed_failure_is_caught_not_a_raw_traceback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = write_json(tmp_path, VALID_ROWS)

        exit_code = main(["--file", str(path)], store_factory=FailingStore)

        assert exit_code == EXIT_IMPORT_FAILED
        assert "FAIL" in capsys.readouterr().err
