"""Layer-contract checker pins: relative imports, escaping levels, negatives."""

import subprocess
from pathlib import Path

from tests.contracts.test_drift import CHECKER, run_tool


def sandbox_tree(tmp_path: Path) -> Path:
    """Checker root with the directories and runtime YAML the checker requires."""
    root = tmp_path / "sandbox"
    for name in ("contracts", "guardrails", "agents"):
        (root / name).mkdir(parents=True)
    runtime = root / "config"
    runtime.mkdir()
    (runtime / "runtime.yaml").write_text(
        "jev:\n  model_id: claude-haiku-4-5-20251001\n  step_timeout: 30\n"
        "analyzer:\n  model_id: claude-haiku-4-5-20251001\n  step_timeout: 30\n"
        "proposer:\n  model_id: claude-sonnet-5\n  step_timeout: 30\n"
        "reviewer:\n  model_id: claude-sonnet-5\n  step_timeout: 30\n"
    )
    return root


def _run_checker(root: Path) -> subprocess.CompletedProcess[str]:
    return run_tool(str(CHECKER), "--root", str(root))


def write(root: Path, relative: str, code: str) -> None:
    (root / relative).write_text(code)


def test_checker_admits_single_level_relative_self_import(tmp_path: Path) -> None:
    root = sandbox_tree(tmp_path)
    write(root, "contracts/fixture.py", "from .enums import something\n")
    write(root, "contracts/enums.py", "VALUE = 1\n")
    write(root, "guardrails/fixture.py", "from .support import something\n")
    write(root, "guardrails/support.py", "VALUE = 1\n")

    done = _run_checker(root)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "LAYER CONTRACT: PASS" in done.stdout


def test_checker_rejects_multi_level_escaping_relative_import(tmp_path: Path) -> None:
    root = sandbox_tree(tmp_path)
    write(root, "contracts/fixture.py", "from .. import anywhere\n")
    write(root, "guardrails/fixture.py", "from ..contracts.enums import something\n")

    done = _run_checker(root)
    assert done.returncode == 1
    assert "LAYER CONTRACT" in done.stdout
    assert ".." in done.stdout


def test_checker_rejects_contracts_importing_app_layer(tmp_path: Path) -> None:
    root = sandbox_tree(tmp_path)
    write(root, "contracts/fixture.py", "import workflow.state\n")

    done = _run_checker(root)
    assert done.returncode == 1
    assert "LAYER CONTRACT" in done.stdout
    assert "workflow.state" in done.stdout


def test_checker_rejects_guardrails_importing_agents(tmp_path: Path) -> None:
    root = sandbox_tree(tmp_path)
    write(root, "guardrails/fixture.py", "import agents.jev\n")

    done = _run_checker(root)
    assert done.returncode == 1
    assert "agents.jev" in done.stdout


def test_checker_keeps_root_default_for_the_real_tree() -> None:
    done = run_tool(str(CHECKER))
    assert done.returncode == 0, done.stdout + done.stderr
