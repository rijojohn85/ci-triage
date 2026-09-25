"""AC3: EvidencePack is the deterministic AD-24 shape with full-SHA production types."""

import pytest
from pydantic import ValidationError

from contracts.evidence import EvidencePack
from tests.contracts.samples import FULL_SHA

LOADED_METRIC = 12.5


def representative_evidence_payload() -> dict[str, object]:
    return {
        "repo_id": "org/demo-repo",
        "last_green": FULL_SHA,
        "distilled_log": [
            {"line_number": 1, "text": "FAILED tests/test_x.py::test_send - Errno 111"},
            {"line_number": 2, "text": "Traceback (most recent call last):"},
        ],
        "commits": [
            {"sha": FULL_SHA, "message": "fix: retry socket", "author_login": "someone"}
        ],
        "candidate_suspects": [
            {"sha": FULL_SHA, "rank": 1, "changed_files": ["tests/test_x.py"]}
        ],
        "history_rows": [
            {
                "row_id": "row-9",
                "fingerprint": "deadbeef",
                "test_id": "tests/test_x.py::test_send",
                "error_type": "ConnectionRefusedError",
            }
        ],
        "metrics": {"load_duration_seconds": LOADED_METRIC},
    }


def test_ac3_evidence_pack_validates_representative_payload() -> None:
    pack = EvidencePack.model_validate(representative_evidence_payload())
    assert pack.repo_id == "org/demo-repo"
    assert pack.last_green == FULL_SHA
    assert pack.distilled_log[0].line_number == 1
    assert pack.commits[0].sha == FULL_SHA
    assert pack.candidate_suspects[0].rank == 1
    assert pack.history_rows[0].row_id == "row-9"
    assert pack.metrics["load_duration_seconds"] == LOADED_METRIC


def test_ac3_evidence_pack_full_sha_only_in_production() -> None:
    payload = representative_evidence_payload()
    payload["commits"] = [{"sha": "abc1234", "message": "x", "author_login": "y"}]
    with pytest.raises(ValidationError) as exc:
        EvidencePack.model_validate(payload)
    assert "sha" in str(exc.value)


def test_ac3_distilled_log_lines_are_positive_and_text_backed() -> None:
    payload = representative_evidence_payload()
    payload["distilled_log"] = [{"line_number": 0, "text": "x"}]
    with pytest.raises(ValidationError) as exc:
        EvidencePack.model_validate(payload)
    assert "line_number" in str(exc.value)


def test_ac3_commit_author_login_must_be_non_empty() -> None:
    payload = representative_evidence_payload()
    payload["commits"] = [
        {"sha": FULL_SHA, "message": "fix: retry socket", "author_login": ""}
    ]
    with pytest.raises(ValidationError) as exc:
        EvidencePack.model_validate(payload)
    assert "author_login" in str(exc.value)


def test_ac3_metrics_reject_nan_and_infinity() -> None:
    payload = representative_evidence_payload()
    payload["metrics"] = {"load_duration_seconds": float("nan")}
    with pytest.raises(ValidationError) as exc:
        EvidencePack.model_validate(payload)
    assert "load_duration_seconds" in str(exc.value)
    payload["metrics"] = {"load_duration_seconds": float("inf")}
    with pytest.raises(ValidationError) as exc:
        EvidencePack.model_validate(payload)
    assert "load_duration_seconds" in str(exc.value)
