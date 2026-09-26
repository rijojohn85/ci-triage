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

import pytest
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
    entries = _manifest_entries()
    return {entry["id"]: entry for entry in entries}


def _manifest_entries() -> list[dict[str, Any]]:
    return list(yaml.safe_load(MANIFEST.read_text(encoding="utf-8")))


def test_ac1_generated_cases_file_is_reproducible() -> None:
    committed = GENERATED.read_text(encoding="utf-8")
    regenerated = generator.render_cases_yaml(generator.build_cases(ROOT).cases)
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


# --- Story 3.11: the guard against unanswerable cases (AC1/AC2) ---------------
#
# The generator must refuse input Jev cannot answer: a labelled case whose
# proof did not survive distillation, two differently-labelled cases that
# distil to the same lines, or an unknown source with no unique window.
# Committed `distiller-exceptions.yaml` ids are the sanctioned escape hatch —
# excluded from the generated cases and reported, even when generation is
# refused.

_SURVIVING_LOG = "Traceback (most recent call last):\nValueError: boom\n"

# Eight cause-free lines, so a source has at least one full unknown window.
_WINDOWED_LOG = _SURVIVING_LOG + "".join(
    f"setup line {index}\n" for index in range(8)
)

# One cause-free line repeated: every window is identical, so a second source
# can never find a unique window.
_REPEATED_LOG = "setup step\n" * 24


def _entry(
    case_id: str,
    label: str,
    *,
    key_line: str,
    log: str,
    repo: str | None = None,
) -> dict[str, Any]:
    """One crafted manifest entry plus its raw log (the `log` key is not committed)."""
    return {
        "id": case_id,
        "repo": repo or f"acme/{case_id}",
        "stack": "C",
        "label": label,
        "key_line": key_line,
        "log": log,
    }


def _write_eval_root(
    tmp_path: Path,
    entries: list[dict[str, Any]],
    exceptions: list[dict[str, Any]] | None = None,
) -> Path:
    """A throwaway repo root with the eval data folder the generator reads."""
    root = tmp_path / "repo"
    eval_dir = root / "test-data" / "jev-eval"
    (eval_dir / "logs").mkdir(parents=True)
    manifest = []
    for entry in entries:
        record = {key: value for key, value in entry.items() if key != "log"}
        (eval_dir / "logs" / f"{record['id']}.log").write_text(
            str(entry["log"]), encoding="utf-8"
        )
        record["log_file"] = f"logs/{record['id']}.log"
        manifest.append(record)
    (eval_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (eval_dir / "distiller-exceptions.yaml").write_text(
        yaml.safe_dump(exceptions or []), encoding="utf-8"
    )
    return root


def test_ac1_unanswerable_labelled_case_is_named_and_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The key_line is narrative, so the real distiller drops it: the case's
    # proof never reaches Jev, so the generator must refuse it by name.
    root = _write_eval_root(
        tmp_path,
        [
            _entry(
                "bad-01",
                "code",
                key_line="the proof that never survives",
                log=_SURVIVING_LOG,
            )
        ],
    )
    monkeypatch.setattr(generator, "ROOT", root)
    out = tmp_path / "cases.generated.yaml"

    assert generator.main(["--out", str(out)]) == 1
    assert "bad-01" in capsys.readouterr().out
    assert not out.exists()  # nothing is written when a case is unanswerable

    with pytest.raises(generator.UnanswerableCasesError) as raised:
        generator.build_cases(root)
    assert "bad-01" in str(raised.value)


def test_ac1_generator_excludes_exception_ids_and_reports_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _write_eval_root(
        tmp_path,
        [
            _entry("good-01", "code", key_line="ValueError: boom", log=_WINDOWED_LOG),
            _entry(
                "waived-01",
                "flaky",
                key_line="narrative only",
                log="ERROR: other\n",
            ),
        ],
        exceptions=[
            {
                "id": "waived-01",
                "reason": "the key_line cannot survive AD-20",
                "status": "approved",
            }
        ],
    )
    monkeypatch.setattr(generator, "ROOT", root)
    out = tmp_path / "cases.generated.yaml"

    assert generator.main(["--out", str(out)]) == 0
    assert "waived-01" in capsys.readouterr().out  # reported, not silent

    cases = yaml.safe_load(out.read_text(encoding="utf-8"))
    all_ids = {case["vars"]["case_id"] for case in cases}
    assert "waived-01" not in all_ids  # not a labelled case
    assert "unknown-waived-01" not in all_ids  # nor an unknown or trick case
    assert "trick-waived-01" not in all_ids
    labelled_ids = {
        case["vars"]["case_id"]
        for case in cases
        if case["vars"]["case_kind"] == "labelled"
    }
    assert labelled_ids == {"good-01"}
    # the same data builds without raising once the id is an exception
    assert generator.build_cases(root).cases


def test_ac1_exceptions_are_reported_when_generation_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _write_eval_root(
        tmp_path,
        [
            _entry("good-01", "code", key_line="ValueError: boom", log=_WINDOWED_LOG),
            _entry(
                "bad-01",
                "code",
                key_line="narrative only",
                log="ERROR: something else\n",
            ),
            _entry(
                "waived-01",
                "flaky",
                key_line="narrative only",
                log="ERROR: other\n",
            ),
        ],
        exceptions=[
            {"id": "waived-01", "reason": "cannot survive", "status": "approved"}
        ],
    )
    monkeypatch.setattr(generator, "ROOT", root)

    assert generator.main(["--out", str(tmp_path / "out.yaml")]) == 1
    printed = capsys.readouterr().out
    assert "waived-01" in printed  # the excluded id is still reported
    assert "bad-01" in printed  # alongside the refused case


def test_ac1_two_labels_with_identical_distilled_input_fail(tmp_path: Path) -> None:
    root = _write_eval_root(
        tmp_path,
        [
            _entry(
                "twin-code", "code", key_line="ValueError: boom", log=_SURVIVING_LOG
            ),
            _entry(
                "twin-flaky", "flaky", key_line="ValueError: boom", log=_SURVIVING_LOG
            ),
        ],
    )
    with pytest.raises(generator.UnanswerableCasesError) as raised:
        generator.build_cases(root)
    message = str(raised.value)
    assert "twin-code" in message
    assert "twin-flaky" in message


def test_ac1_empty_proof_is_never_present(tmp_path: Path) -> None:
    # An empty `key_line` substring-matches every line, so without an empty
    # guard the case would read as proof-retained and slip through.
    root = _write_eval_root(
        tmp_path,
        [_entry("empty-proof", "code", key_line="", log=_SURVIVING_LOG)],
    )
    with pytest.raises(generator.UnanswerableCasesError) as raised:
        generator.build_cases(root)
    assert "empty-proof" in str(raised.value)


def test_ac1_malformed_exceptions_entry_fails_loudly(tmp_path: Path) -> None:
    root = _write_eval_root(
        tmp_path,
        [_entry("good-01", "code", key_line="ValueError: boom", log=_SURVIVING_LOG)],
        exceptions=[{"reason": "no id here"}],
    )
    with pytest.raises(generator.MalformedExceptionsError):
        generator.build_cases(root)


def test_ac1_non_list_exceptions_file_fails_loudly(tmp_path: Path) -> None:
    root = _write_eval_root(
        tmp_path,
        [_entry("good-01", "code", key_line="ValueError: boom", log=_SURVIVING_LOG)],
    )
    (root / "test-data" / "jev-eval" / "distiller-exceptions.yaml").write_text(
        "id: not-a-list\n", encoding="utf-8"
    )
    with pytest.raises(generator.MalformedExceptionsError):
        generator.build_cases(root)


def test_ac1_stale_exception_id_fails_loudly(tmp_path: Path) -> None:
    root = _write_eval_root(
        tmp_path,
        [_entry("good-01", "code", key_line="ValueError: boom", log=_SURVIVING_LOG)],
        exceptions=[
            {"id": "not-in-manifest", "reason": "stale", "status": "approved"}
        ],
    )
    with pytest.raises(generator.MalformedExceptionsError) as raised:
        generator.build_cases(root)
    assert "not-in-manifest" in str(raised.value)


def test_ac2_colliding_unknown_windows_are_refused(tmp_path: Path) -> None:
    # Two sources whose logs repeat one cause-free line: every window has the
    # same normalised signature, so the second source can never be unique. The
    # generator must refuse it by name rather than ship a duplicate.
    root = _write_eval_root(
        tmp_path,
        [
            _entry(
                "dup-a",
                "code",
                key_line="setup step",
                log=_REPEATED_LOG,
                repo="a/a",
            ),
            _entry(
                "dup-b",
                "code",
                key_line="setup step",
                log=_REPEATED_LOG,
                repo="b/b",
            ),
        ],
    )
    with pytest.raises(generator.UnanswerableCasesError) as raised:
        generator.build_cases(root)
    assert "unknown-dup-b" in str(raised.value)


def test_ac2_short_unknown_log_is_refused(tmp_path: Path) -> None:
    # No cause-free lines at all: a full window cannot be built, so the source
    # is refused instead of shipping a short (non-`count`-line) case.
    root = _write_eval_root(
        tmp_path,
        [_entry("short-01", "code", key_line="ValueError: boom", log=_SURVIVING_LOG)],
    )
    with pytest.raises(generator.UnanswerableCasesError) as raised:
        generator.build_cases(root)
    assert "unknown-short-01" in str(raised.value)


def test_ac1_labelled_cases_carry_the_proof_key_line() -> None:
    manifest = _manifest()
    labelled = _of_kind("labelled")
    assert len(labelled) == 38
    for case in labelled:
        entry = manifest[case["vars"]["case_id"]]
        key_line = _RUNNER_PREFIX.sub("", str(entry["key_line"]))
        assert case["vars"]["key_line"] == key_line
        joined = "\n".join(line["text"] for line in case["vars"]["lines"])
        assert key_line in joined  # the proof reached the classifier


def test_ac1_trick_cases_are_built_only_on_surviving_bases() -> None:
    manifest = _manifest()
    for case in _of_kind("trick"):
        source_id = case["vars"]["case_id"].removeprefix("trick-")
        key_line = _RUNNER_PREFIX.sub("", str(manifest[source_id]["key_line"]))
        joined = "\n".join(line["text"] for line in case["vars"]["lines"])
        assert key_line in joined


# An independent normaliser: the test states the AC2 rule itself instead of
# leaning on the generator's private regexes or replaying its window stride.
_NORMALISE_PATTERNS = (
    re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?"),  # ISO timestamp
    re.compile(  # GUID
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
        r"-[0-9a-fA-F]{12}\b"
    ),
    re.compile(r"\b[0-9a-fA-F]{7,}\b"),  # hex hash
    re.compile(r"\bv?\d+(?:\.\d+)+\b"),  # version number
    re.compile(r"\d+"),  # run/worker id and any other digit run
)


def _normalise(content: str) -> str:
    for pattern in _NORMALISE_PATTERNS:
        content = pattern.sub(" ", content)
    return " ".join(content.split())


def _built_unknown() -> list[dict[str, Any]]:
    built = generator.build_cases(ROOT)
    return [case for case in built.cases if case["vars"]["case_kind"] == "unknown"]


def _unknown_content(case: dict[str, Any]) -> tuple[str, ...]:
    """An unknown case's non-final lines (the bare error line is not content)."""
    return tuple(line["text"] for line in case["vars"]["lines"][:-1])


def test_ac2_unknown_cases_are_unique_after_normalisation() -> None:
    normalised = [
        _normalise("\n".join(_unknown_content(case))) for case in _built_unknown()
    ]
    assert len(normalised) == 8
    assert len(set(normalised)) == 8  # no two share non-final content


def test_ac2_unknown_cases_draw_from_different_parts_of_the_log() -> None:
    windows = [_unknown_content(case) for case in _built_unknown()]
    assert len(windows) == 8
    # Eight different sequences of lines: the cases do not all replay the first
    # window of their log.
    assert len(set(windows)) == 8
