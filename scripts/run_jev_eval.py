#!/usr/bin/env python3
"""The Jev eval harness (story 3.2, AC1/AC2): run the root suite, save a receipt.

Owns every side effect (SOLID-S): resolves a node promptfoo 0.123.1 can run on
(Node 26, minimum from .nvmrc), runs `promptfoo eval` on the root
`jev.test.yaml` with repeats read from the OQ-1 bar, then hands raw output to the pure
scorer (`workflow.jev_eval`) and writes `results/jev-eval/<date>-<model>/`
(`promptfoo-output.json`, `summary.json`, `summary.md`). It prints the verdict
as-is and never tunes the prompt, relabels a case, drops a hard case or moves
the bar.

The scored population is the generated cases (those carrying `case_kind`); the
six inline service fixtures the suite also runs are reported as smoke cases so
no model call goes unaccounted (AD-18).

`--from-output <path>` skips promptfoo and re-scores an existing raw output
(zero model calls), so a receipt can be re-derived from its committed evidence.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # contracts/ is not a pip package; run from anywhere

from agents.jev.questions import JEV_CLASSES_PATH  # noqa: E402 — path set above
from agents.jev.runtime import load_jev_runtime  # noqa: E402
from workflow.jev_eval import (  # noqa: E402
    EvalSummary,
    RunMeta,
    build_attempt,
    render_summary_md,
    score_attempts,
)
from workflow.thresholds import load_thresholds  # noqa: E402

CONFIG: Final[Path] = ROOT / "jev.test.yaml"
PROMPTFOO: Final[Path] = ROOT / "node_modules" / ".bin" / "promptfoo"
RESULTS_DIR: Final[Path] = ROOT / "results" / "jev-eval"
MIN_NODE: Final[tuple[int, ...]] = tuple(
    int(part)
    for part in (ROOT / ".nvmrc").read_text(encoding="utf-8").strip().split(".")
)
_VERSION_RE: Final[re.Pattern[str]] = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def _node_version(binary: Path) -> tuple[int, int, int] | None:
    try:
        done = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _VERSION_RE.fullmatch(done.stdout.strip())
    if done.returncode != 0 or match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _version_key(name: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(name)
    if match is None:
        return (0, 0, 0)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _nvm_candidates() -> list[Path]:
    node_dir = (
        Path(os.environ.get("NVM_DIR", Path.home() / ".nvm")) / "versions" / "node"
    )
    if not node_dir.is_dir():
        return []
    ordered = sorted(
        node_dir.iterdir(), key=lambda path: _version_key(path.name), reverse=True
    )
    return [path / "bin" / "node" for path in ordered]


def _candidate_nodes() -> list[Path]:
    candidates: list[Path] = []
    override = os.environ.get("PROMPTFOO_NODE") or os.environ.get("NODE_BIN")
    if override:
        candidates.append(Path(override))
    found = shutil.which("node")
    if found:
        candidates.append(Path(found))
    candidates += _nvm_candidates()
    candidates += [Path("/usr/local/bin/node"), Path("/usr/bin/node")]
    return candidates


def resolve_node() -> Path:
    """The first supported Node 26, or a clear error naming what was tried."""
    tried: list[str] = []
    for candidate in _candidate_nodes():
        if not candidate.is_file():
            continue
        version = _node_version(candidate)
        tried.append(f"{candidate} ({version or 'not runnable'})")
        if version is not None and version[0] == MIN_NODE[0] and version >= MIN_NODE:
            return candidate
    wanted = ".".join(str(part) for part in MIN_NODE)
    raise SystemExit(
        f"no supported Node {MIN_NODE[0]} >= {wanted} found; "
        "run `nvm install` and `nvm use` from the repository root; tried: "
        + ("; ".join(tried) or "nothing")
    )


def _run_promptfoo(node: Path, repeats: int, output: Path) -> None:
    if not PROMPTFOO.is_file():
        raise SystemExit("promptfoo is not installed; run scripts/bootstrap.sh")
    env = dict(os.environ)
    env["PATH"] = f"{node.parent}{os.pathsep}{env.get('PATH', '')}"
    env["PROMPTFOO_PYTHON"] = str(ROOT / ".venv" / "bin" / "python")
    command = [
        str(PROMPTFOO),
        "eval",
        "-c",
        str(CONFIG),
        "--output",
        str(output),
        "--no-cache",
        "--no-progress-bar",
        "--repeat",
        str(repeats),
    ]
    done = subprocess.run(command, cwd=ROOT, env=env, check=False)
    if done.returncode != 0:
        raise SystemExit(f"promptfoo eval failed with exit code {done.returncode}")


def _read_output(path: Path) -> tuple[list[dict[str, Any]], str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    version = str(data.get("metadata", {}).get("promptfooVersion", "unknown"))
    return list(data["results"]["results"]), version


def _is_scored(result: dict[str, Any]) -> bool:
    """A generated case carries `case_kind`; the six inline fixtures do not."""
    return "case_kind" in result.get("vars", {})


def _calls(results: Iterable[dict[str, Any]]) -> int:
    total = 0
    for result in results:
        usage = result.get("tokenUsage", {})
        value = usage.get("numRequests") if isinstance(usage, dict) else None
        total += value if isinstance(value, int) else 0
    return total


def _summary(
    results: Sequence[dict[str, Any]], promptfoo_version: str, repeats: int
) -> EvalSummary:
    thresholds = load_thresholds()
    limits = thresholds.eval.jev
    scored = [result for result in results if _is_scored(result)]
    smoke = [result for result in results if not _is_scored(result)]
    attempts = [
        build_attempt(result.get("vars", {}), result, thresholds.confidence)
        for result in scored
    ]
    meta = RunMeta(
        model=load_jev_runtime().model,
        promptfoo_version=promptfoo_version,
        classes_sha256=_sha256(JEV_CLASSES_PATH),
        git_commit=_git_commit(),
        date=_local_date(),
        repeats=repeats,
    )
    summary = score_attempts(
        attempts, limits=limits, cutoffs=thresholds.confidence, meta=meta
    )
    return summary.model_copy(
        update={
            "smoke_total": len(smoke),
            "smoke_passed": sum(1 for result in smoke if result.get("success")),
            "smoke_calls": _calls(smoke),
        }
    )


def _sha256(path: Path) -> str:
    """The SHA-256 of the prompt file the classifier loads (AD-19 provenance)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str:
    """The full sha of the commit the receipt was produced from."""
    done = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else "unknown"


def _local_date() -> str:
    """The local system date, so the receipt folder reads as the day it ran."""
    return datetime.now().strftime("%Y-%m-%d")


def _receipt_dir(base: Path, summary: EvalSummary) -> Path:
    model = re.sub(r"[^A-Za-z0-9._-]+", "-", summary.model).strip("-")
    return base / f"{summary.date or _local_date()}-{model}"


def _write_receipt(directory: Path, raw_output: Path, summary: EvalSummary) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "promptfoo-output.json"
    if raw_output.resolve() != destination.resolve():
        shutil.copyfile(raw_output, destination)
    (directory / "summary.json").write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (directory / "summary.md").write_text(render_summary_md(summary), encoding="utf-8")


def _write_from_raw(
    raw_output: Path, repeats: int, results_dir: Path
) -> tuple[EvalSummary, Path]:
    """Score one raw promptfoo output and write its receipt (zero model calls)."""
    results, version = _read_output(raw_output)
    summary = _summary(results, version, repeats)
    directory = _receipt_dir(results_dir, summary)
    _write_receipt(directory, raw_output, summary)
    return summary, directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=RESULTS_DIR,
        help="where the receipt directory is written (default: results/jev-eval)",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=None,
        help="override the repeats count from the OQ-1 bar (default: the bar)",
    )
    parser.add_argument(
        "--from-output",
        type=Path,
        default=None,
        help=(
            "re-score an existing raw promptfoo output instead of running the "
            "suite (zero model calls), so a receipt can be re-derived from its "
            "committed evidence"
        ),
    )
    args = parser.parse_args(argv)

    thresholds = load_thresholds()
    bar = thresholds.eval.jev
    repeats = args.repeats if args.repeats is not None else (bar.repeats if bar else 1)

    if args.from_output is not None:
        summary, directory = _write_from_raw(
            args.from_output, repeats, args.results_dir
        )
    else:
        node = resolve_node()
        temp_output = args.results_dir / "_promptfoo-output.json"
        temp_output.parent.mkdir(parents=True, exist_ok=True)
        try:
            _run_promptfoo(node, repeats, temp_output)
            summary, directory = _write_from_raw(temp_output, repeats, args.results_dir)
        finally:
            temp_output.unlink(missing_ok=True)

    print(render_summary_md(summary))
    print(f"\nVERDICT: {summary.verdict.value}")
    print(f"receipt: {directory}")
    return 0 if summary.verdict.value in {"PASSED", "measured / pending-bar"} else 1


if __name__ == "__main__":
    sys.exit(main())
