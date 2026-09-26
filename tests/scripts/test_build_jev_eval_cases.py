"""AC tests for the deterministic Jev eval case generator (story 3.2, AC1).

The generator turns the human-labelled manifest plus its real CI logs into the
committed `test-data/jev-eval/cases.generated.yaml` (labelled + unknown +
trick). These tests prove the file is byte-reproducible, that labelled cases go
through the REAL distiller, and that the unknown and trick rules hold.

The generator script is loaded by path (the `tests/scripts/test_verify_demo_repo.py`
precedent) so the tests call its functions directly.
"""

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_jev_eval_cases.py"
EVAL_DIR = ROOT / "test-data" / "jev-eval"
MANIFEST = EVAL_DIR / "manifest.yaml"
GENERATED = EVAL_DIR / "cases.generated.yaml"

# The runner-prefix shape the distiller strips; the generator must match markers
# against the stripped line, so the test states the rule independently.
_RUNNER_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ")

_spec = importlib.util.spec_from_file_location("build_jev_eval_cases", SCRIPT)
assert _spec is not None and _spec.loader is not None
generator = importlib.util.module_from_spec(_spec)
sys.modules["build_jev_eval_cases"] = generator
_spec.loader.exec_module(generator)

from workflow.distiller import ERROR_MARKERS  # noqa: E402 — after the path bootstrap
from workflow.thresholds import load_thresholds  # noqa: E402


def _cases() -> list[dict[str, Any]]:
    return yaml.safe_load(GENERATED.read_text(encoding="utf-8"))


def _of_kind(kind: str) -> list[dict[str, Any]]:
    return [case for case in _cases() if case["vars"]["case_kind"] == kind]


def _manifest() -> dict[str, dict[str, Any]]:
    entries = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    return {entry["id"]: entry for entry in entries}


def test_ac1_generated_cases_file_is_reproducible() -> None:
    committed = GENERATED.read_text(encoding="utf-8")
    regenerated = generator.render_cases_yaml(generator.build_cases(ROOT))
    assert committed == regenerated


def test_ac1_generated_cases_check_mode_is_a_drift_gate(tmp_path: Path) -> None:
    clean = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert clean.returncode == 0, clean.stdout + clean.stderr
    drifted = tmp_path / "cases.generated.yaml"
    drifted.write_text(
        GENERATED.read_text(encoding="utf-8").replace(
            "case_kind: labelled", "case_kind: trick"
        ),
        encoding="utf-8",
    )
    dirty = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", "--out", str(drifted)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert dirty.returncode == 1
    assert drifted.name in dirty.stdout + dirty.stderr


def test_ac1_labelled_cases_use_the_real_distiller() -> None:
    limits = load_thresholds().distiller
    manifest = _manifest()
    labelled = _of_kind("labelled")
    assert len(labelled) == 38
    for case in labelled:
        entry = manifest[case["vars"]["case_id"]]
        log = (
            (EVAL_DIR / entry["log_file"]).read_text(encoding="utf-8").lstrip("\ufeff")
        )
        distilled = generator.distill(log, None, limits)
        expected = [
            {"line_number": line.line_number, "text": line.text} for line in distilled
        ]
        assert case["vars"]["lines"] == expected


def test_ac1_unknown_cases_carry_no_cause_lines() -> None:
    unknown = _of_kind("unknown")
    assert len(unknown) == 8
    for case in unknown:
        lines = case["vars"]["lines"]
        assert lines[-1]["text"] == generator.BARE_ERROR_LINE
        for line in lines[:-1]:
            assert not any(marker.search(line["text"]) for marker in ERROR_MARKERS)
            stripped = _RUNNER_PREFIX.sub("", line["text"])
            assert not any(marker.search(stripped) for marker in ERROR_MARKERS)


def test_ac1_unknown_cases_spread_across_repos() -> None:
    unknown = _of_kind("unknown")
    repos = [case["vars"]["repo"] for case in unknown]
    assert len(set(repos)) == len(repos)
    assert len(set(repos)) >= 5


def test_ac1_trick_cases_are_verdict_flips_with_varied_styles() -> None:
    trick = _of_kind("trick")
    assert len(trick) == 6
    injections = [case["vars"]["lines"][-1]["text"] for case in trick]
    assert len(set(injections)) == 6  # varied styles, no repeats
    for case in trick:
        target = case["description"].rsplit("flip to ", 1)[1].rstrip(")")
        assert target != case["vars"]["expected_label"]  # a real flip
        assert target in case["vars"]["lines"][-1]["text"]


def test_ac1_trick_cases_cover_all_four_classes() -> None:
    labels = {case["vars"]["expected_label"] for case in _of_kind("trick")}
    assert labels == {"code", "flaky", "infra", "external"}


def test_ac1_trick_cases_use_different_repos() -> None:
    repos = [case["vars"]["repo"] for case in _of_kind("trick")]
    assert len(set(repos)) == len(repos) == 6


def test_ac1_trick_cases_keep_the_true_label() -> None:
    manifest = _manifest()
    for case in _of_kind("trick"):
        source_id = case["vars"]["case_id"].removeprefix("trick-")
        assert case["vars"]["expected_label"] == manifest[source_id]["label"]


def test_ac1_root_eval_entrypoint_loads_generated_cases() -> None:
    config = yaml.safe_load((ROOT / "jev.test.yaml").read_text(encoding="utf-8"))
    target = config["targets"][0]
    assert target["id"] == "file://agents/jev/eval_provider.py"
    assert target["config"]["pythonExecutable"] == "./.venv/bin/python"
    assert target["config"]["maxRetries"] == 0
    assert "file://test-data/jev-eval/cases.generated.yaml" in config["tests"]
    # the six inline fixtures stay (the generated file is added, not a replacement)
    inline = [case for case in config["tests"] if isinstance(case, dict)]
    assert len(inline) == 6
