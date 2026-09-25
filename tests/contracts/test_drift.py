"""AC3: schema drift gate, layer-contract checker and the check-target wiring."""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest
from pydantic import TypeAdapter, ValidationError

from contracts.approval import ApprovalPayload
from contracts.citations import Sha40
from contracts.verdict import ShaPrefix
from tests.contracts.samples import FULL_SHA

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
GENERATOR: Final[Path] = REPO_ROOT / "scripts" / "generate_schemas.py"
CHECKER: Final[Path] = REPO_ROOT / "scripts" / "check_layer_contract.py"
SCHEMAS: Final[Path] = REPO_ROOT / "guardrails" / "schemas"


def run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )


def test_ac3_committed_schemas_are_byte_identical_after_regen() -> None:
    done = run_tool(str(GENERATOR), "--check")
    assert done.returncode == 0, done.stdout + done.stderr


def test_ac3_drift_fails_non_zero_then_regen_restores_zero_diff(tmp_path: Path) -> None:
    sandbox = tmp_path / "schemas"
    shutil.copytree(SCHEMAS, sandbox)

    committed = sandbox / "AgentError.json"
    committed.write_text('{"drifted": true}')

    drifted = run_tool(str(GENERATOR), "--check", "--schemas-dir", str(sandbox))
    assert drifted.returncode == 1
    assert "AgentError.json" in drifted.stdout

    run_tool(str(GENERATOR), "--schemas-dir", str(sandbox))
    restored = run_tool(str(GENERATOR), "--check", "--schemas-dir", str(sandbox))
    assert restored.returncode == 0, restored.stdout + restored.stderr


def test_ac3_orphan_schema_fails_the_drift_check(tmp_path: Path) -> None:
    sandbox = tmp_path / "schemas"
    shutil.copytree(SCHEMAS, sandbox)
    (sandbox / "PreviouslyGenerated.json").write_text('{"stale": true}')

    done = run_tool(str(GENERATOR), "--check", "--schemas-dir", str(sandbox))
    assert done.returncode == 1
    assert "PreviouslyGenerated.json" in done.stdout


def test_ac3_check_target_runs_the_schema_drift_recipe() -> None:
    done = subprocess.run(
        ["make", "-n", "check"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "generate_schemas.py --check" in done.stdout


def test_ac3_layer_contract_passes_on_the_committed_tree() -> None:
    done = run_tool(str(CHECKER))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "LAYER CONTRACT" in done.stdout


def test_ac3_approval_class_override_field_is_in_schema() -> None:
    properties = ApprovalPayload.model_json_schema(mode="validation")["properties"]
    assert "class_override" in properties


def test_ac3_short_prefix_type_is_dry_run_only() -> None:
    prefix = TypeAdapter(ShaPrefix)
    assert prefix.validate_python("abc1234") == "abc1234"
    with pytest.raises(ValidationError) as exc:
        prefix.validate_python("abc123")
    assert "String should match" in str(exc.value)


def test_ac3_full_sha_accepted_only_forty_chars() -> None:
    sha = TypeAdapter(Sha40)
    assert sha.validate_python(FULL_SHA) == FULL_SHA
    with pytest.raises(ValidationError) as exc:
        sha.validate_python(FULL_SHA[:39])
    assert "String should match" in str(exc.value)
