"""Story 3.2 tests for the eval harness's pure helpers (`scripts/run_jev_eval.py`).

The harness owns every side effect; these tests exercise the parts that can be
checked without promptfoo and without a model: node resolution, the raw-output
reader, the scored/smoke split, the call counter and the receipt-directory slug,
plus a `--from-output` re-score that makes zero model calls.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_jev_eval.py"

_spec = importlib.util.spec_from_file_location("run_jev_eval", SCRIPT)
assert _spec is not None and _spec.loader is not None
harness = importlib.util.module_from_spec(_spec)
sys.modules["run_jev_eval"] = harness
_spec.loader.exec_module(harness)


# --- node resolution ----------------------------------------------------------


def _touch(path: Path) -> Path:
    path.write_text("", encoding="utf-8")
    return path


def test_candidate_nodes_are_ordered_override_path_nvm_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROMPTFOO_NODE", "/override/node")
    monkeypatch.delenv("NODE_BIN", raising=False)
    monkeypatch.setattr(harness.shutil, "which", lambda name: "/path/node")
    monkeypatch.setattr(
        harness,
        "_nvm_candidates",
        lambda: [Path("/nvm/v24/bin/node"), Path("/nvm/v22/bin/node")],
    )
    assert harness._candidate_nodes() == [
        Path("/override/node"),
        Path("/path/node"),
        Path("/nvm/v24/bin/node"),
        Path("/nvm/v22/bin/node"),
        Path("/usr/local/bin/node"),
        Path("/usr/bin/node"),
    ]


def test_candidate_nodes_honours_the_node_bin_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROMPTFOO_NODE", raising=False)
    monkeypatch.setenv("NODE_BIN", "/alias/node")
    monkeypatch.setattr(harness.shutil, "which", lambda name: None)
    monkeypatch.setattr(harness, "_nvm_candidates", lambda: [])
    assert harness._candidate_nodes()[0] == Path("/alias/node")


def test_nvm_candidates_are_newest_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    node_dir = tmp_path / "versions" / "node"
    for name in ("v22.20.0", "v24.13.1", "not-a-version"):
        (node_dir / name).mkdir(parents=True)
    monkeypatch.setenv("NVM_DIR", str(tmp_path))
    assert harness._nvm_candidates() == [
        node_dir / "v24.13.1" / "bin" / "node",
        node_dir / "v22.20.0" / "bin" / "node",
        node_dir / "not-a-version" / "bin" / "node",
    ]


def test_resolve_node_picks_the_first_suitable_candidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    too_old = _touch(tmp_path / "old-node")
    suitable = _touch(tmp_path / "new-node")
    monkeypatch.setattr(harness, "_candidate_nodes", lambda: [too_old, suitable])
    versions = {too_old: (22, 20, 0), suitable: (24, 13, 1)}
    monkeypatch.setattr(harness, "_node_version", lambda binary: versions[binary])
    assert harness.resolve_node() == suitable


def test_resolve_node_errors_clearly_when_none_is_suitable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    too_old = _touch(tmp_path / "old-node")
    unreadable = _touch(tmp_path / "broken-node")
    monkeypatch.setattr(harness, "_candidate_nodes", lambda: [too_old, unreadable])
    versions: dict[Path, tuple[int, int, int] | None] = {
        too_old: (22, 20, 0),
        unreadable: None,
    }
    monkeypatch.setattr(harness, "_node_version", lambda binary: versions[binary])
    with pytest.raises(SystemExit) as caught:
        harness.resolve_node()
    message = str(caught.value)
    assert "no node >= 22.22.0" in message
    assert str(too_old) in message
    assert "not runnable" in message


# --- raw output reading -------------------------------------------------------


def _raw_output(results: list[dict[str, Any]], version: str = "0.123.1") -> str:
    return json.dumps(
        {"metadata": {"promptfooVersion": version}, "results": {"results": results}}
    )


def test_read_output_returns_results_and_version(tmp_path: Path) -> None:
    path = tmp_path / "out.json"
    path.write_text(
        _raw_output([{"vars": {"case_kind": "labelled"}}]), encoding="utf-8"
    )
    results, version = harness._read_output(path)
    assert version == "0.123.1"
    assert results == [{"vars": {"case_kind": "labelled"}}]


def test_read_output_defaults_the_version_to_unknown(tmp_path: Path) -> None:
    path = tmp_path / "out.json"
    path.write_text(json.dumps({"results": {"results": []}}), encoding="utf-8")
    results, version = harness._read_output(path)
    assert results == []
    assert version == "unknown"


# --- scored/smoke split and the call counter ----------------------------------


def test_is_scored_only_for_generated_cases() -> None:
    assert harness._is_scored({"vars": {"case_kind": "labelled"}}) is True
    assert harness._is_scored({"vars": {"log": "inline fixture"}}) is False
    assert harness._is_scored({}) is False


def test_calls_sums_reported_num_requests() -> None:
    assert (
        harness._calls(
            [{"tokenUsage": {"numRequests": 2}}, {"tokenUsage": {"numRequests": 1}}]
        )
        == 3
    )


def test_calls_ignores_missing_or_malformed_counts() -> None:
    assert (
        harness._calls([{}, {"tokenUsage": None}, {"tokenUsage": {"numRequests": "x"}}])
        == 0
    )


# --- receipt directory --------------------------------------------------------


def test_receipt_dir_slugifies_the_model_id(tmp_path: Path) -> None:
    summary = harness.EvalSummary.model_construct(
        model="typesafe/jev-1.13", date="2026-09-27"
    )
    assert harness._receipt_dir(tmp_path, summary) == (
        tmp_path / "2026-09-27-typesafe-jev-1.13"
    )


def test_local_date_is_an_iso_day() -> None:
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", harness._local_date())


# --- --from-output re-scores committed evidence with zero model calls ----------


def _jev_result(answer: str = "code") -> str:
    return json.dumps(
        {
            "classification": {
                "choice": {
                    "answer": answer,
                    "confidence": 0.9,
                    "probabilities": {
                        "code": 0.9,
                        "flaky": 0.0,
                        "infra": 0.0,
                        "external": 0.0,
                        "unknown": 0.0,
                    },
                },
                "injection_screen": {"noul": 0.0},
            },
            "usage": {
                "model": "typesafe/jev-1.13",
                "input_tokens": 10,
                "output_tokens": 5,
            },
        }
    )


def test_from_output_rescores_and_writes_the_receipt(tmp_path: Path) -> None:
    raw = tmp_path / "promptfoo-output.json"
    raw.write_text(
        _raw_output(
            [
                {
                    "vars": {
                        "case_id": "curl-infra-01",
                        "case_kind": "labelled",
                        "expected_label": "infra",
                        "repo": "curl/curl",
                    },
                    "tokenUsage": {"numRequests": 1},
                    "response": {"output": _jev_result("infra")},
                }
            ]
            * 3
        ),
        encoding="utf-8",
    )
    before = raw.read_bytes()
    exit_code = harness.main(
        ["--from-output", str(raw), "--results-dir", str(tmp_path)]
    )
    assert exit_code == 1  # FAILED: no trick cases, so the injection bar cannot hold
    receipts = list(tmp_path.glob("*-typesafe-jev-1.13"))
    assert len(receipts) == 1
    assert (receipts[0] / "summary.md").is_file()
    assert (receipts[0] / "promptfoo-output.json").read_bytes() == before
    summary = json.loads((receipts[0] / "summary.json").read_text(encoding="utf-8"))
    assert summary["verdict"] == "FAILED"
    assert summary["attempts_count"] == 3
    assert summary["calls_made"] == 3


# --- Story 3.12 AC2: the receipt label and the comparison table ---------------

COMMITTED_BASELINE = ROOT / "results" / "jev-eval" / "2026-09-27-typesafe-jev-1.13"


def _labelled_output(answer: str = "infra") -> str:
    return _raw_output(
        [
            {
                "vars": {
                    "case_id": "curl-infra-01",
                    "case_kind": "labelled",
                    "expected_label": "infra",
                    "repo": "curl/curl",
                },
                "tokenUsage": {"numRequests": 1},
                "response": {"output": _jev_result(answer)},
            }
        ]
        * 3
    )


def test_ac2_receipt_dir_carries_the_label(tmp_path: Path) -> None:
    summary = harness.EvalSummary.model_construct(
        model="typesafe/jev-1.13", date="2026-09-27", label="before"
    )
    assert harness._receipt_dir(tmp_path, summary) == (
        tmp_path / "2026-09-27-typesafe-jev-1.13-before"
    )


def test_ac2_compare_reads_each_baseline_summary() -> None:
    summary = harness._read_baseline(COMMITTED_BASELINE)
    assert summary.model == "typesafe/jev-1.13"
    assert summary.label == ""  # the 3.2 receipt predates --label
    assert summary.verdict.value == "FAILED"
    assert summary.evidence_total == 0  # the 3.2 receipt predates the stored count
    assert summary.attempts and not any(a.proof_present for a in summary.attempts)
    # Recomputed from its attempts, the legacy column still reads 0/38, not 0/0.
    text = harness.render_comparison_md(summary, [])
    assert "| evidence retention | 0/38 |" in text


def test_ac2_compare_writes_comparison_md_beside_the_receipt(tmp_path: Path) -> None:
    raw = tmp_path / "promptfoo-output.json"
    raw.write_text(_labelled_output(), encoding="utf-8")
    baselines = tmp_path / "baselines"
    harness.main(["--from-output", str(raw), "--results-dir", str(baselines)])
    baseline_dir = next(baselines.glob("*-typesafe-jev-1.13"))
    harness.main(
        [
            "--from-output",
            str(raw),
            "--results-dir",
            str(tmp_path),
            "--label",
            "after",
            "--compare",
            str(baseline_dir),
        ]
    )
    receipt = next(tmp_path.glob("*-typesafe-jev-1.13-after"))
    comparison = receipt / "comparison.md"
    assert comparison.is_file()
    header = next(
        line
        for line in comparison.read_text(encoding="utf-8").splitlines()
        if line.startswith("| metric |")
    )
    assert [cell.strip() for cell in header.strip("|").split("|")] == [
        "metric",
        baseline_dir.name,
        receipt.name,
    ]


def test_ac2_receipt_dir_dates_a_dateless_summary(tmp_path: Path) -> None:
    """A dateless summary is dated now, never named `unknown-<model>`."""
    summary = harness.EvalSummary.model_construct(model="typesafe/jev-1.13")
    assert harness._receipt_dir(tmp_path, summary) == (
        tmp_path / f"{harness._local_date()}-typesafe-jev-1.13"
    )


def test_ac2_label_that_slugs_to_nothing_is_rejected(tmp_path: Path) -> None:
    raw = tmp_path / "promptfoo-output.json"
    raw.write_text(_labelled_output(), encoding="utf-8")
    with pytest.raises(SystemExit) as caught:
        harness.main(
            [
                "--from-output",
                str(raw),
                "--results-dir",
                str(tmp_path),
                "--label",
                "!",
            ]
        )
    assert "no usable characters" in str(caught.value)


def test_ac2_compare_rejects_a_non_receipt_directory(tmp_path: Path) -> None:
    raw = tmp_path / "promptfoo-output.json"
    raw.write_text(_labelled_output(), encoding="utf-8")
    not_a_receipt = tmp_path / "not-a-receipt"
    not_a_receipt.mkdir()
    with pytest.raises(SystemExit) as caught:
        harness.main(
            [
                "--from-output",
                str(raw),
                "--results-dir",
                str(tmp_path),
                "--compare",
                str(not_a_receipt),
            ]
        )
    assert "not a receipt directory" in str(caught.value)


def test_ac2_compare_refuses_a_self_or_duplicate_baseline(tmp_path: Path) -> None:
    raw = tmp_path / "promptfoo-output.json"
    raw.write_text(_labelled_output(), encoding="utf-8")
    baselines = tmp_path / "baselines"
    harness.main(["--from-output", str(raw), "--results-dir", str(baselines)])
    baseline_dir = next(baselines.glob("*-typesafe-jev-1.13"))

    with pytest.raises(SystemExit) as repeated:
        harness.main(
            [
                "--from-output",
                str(raw),
                "--results-dir",
                str(tmp_path),
                "--label",
                "after",
                "--compare",
                str(baseline_dir),
                "--compare",
                str(baseline_dir),
            ]
        )
    assert "twice" in str(repeated.value)

    harness.main(
        ["--from-output", str(raw), "--results-dir", str(tmp_path), "--label", "after"]
    )
    self_dir = next(tmp_path.glob("*-typesafe-jev-1.13-after"))
    with pytest.raises(SystemExit) as self_column:
        harness.main(
            [
                "--from-output",
                str(raw),
                "--results-dir",
                str(tmp_path),
                "--label",
                "after",
                "--compare",
                str(self_dir),
            ]
        )
    assert "own receipt" in str(self_column.value)
