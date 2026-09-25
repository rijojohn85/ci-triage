#!/usr/bin/env python3
"""Deterministic JSON Schema generator for contracts' public envelope models (AD-6).

Regenerates one committed `guardrails/schemas/<Model>.json` per envelope model,
sorted-key stable dump. Modes: rewrite committed files (default) or `--check`
(byte-identical gate used by `make schema-drift`), which exits 1 on drift.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Final

from pydantic import BaseModel

ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SCHEMA_DIR: Final[Path] = ROOT / "guardrails" / "schemas"

sys.path.insert(0, str(ROOT))  # contracts/ is not a pip package; run from anywhere

from contracts.a2a import DataPart  # noqa: E402 — path set right above
from contracts.approval import ApprovalPayload, Escalation  # noqa: E402
from contracts.errors import AgentError  # noqa: E402
from contracts.evidence import EvidencePack  # noqa: E402
from contracts.jev import JevClassification  # noqa: E402
from contracts.verdict import TriageVerdict  # noqa: E402

EnvelopeModels = tuple[type[BaseModel], ...]

# One committed schema per public envelope model (nested shapes come via $defs).
ENVELOPE_MODELS: Final[EnvelopeModels] = (
    TriageVerdict,
    EvidencePack,
    ApprovalPayload,
    Escalation,
    AgentError,
    DataPart,
    JevClassification,
)


def schema_text(model: type[BaseModel]) -> str:
    """Drift-stable dump: validation mode, sorted keys, trailing newline."""
    schema = model.model_json_schema(mode="validation")
    return json.dumps(schema, sort_keys=True, indent=2) + "\n"


def regenerate(schemas_dir: Path) -> None:
    """Write one committed schema per envelope model, nothing else."""
    schemas_dir.mkdir(parents=True, exist_ok=True)
    for model in ENVELOPE_MODELS:
        (schemas_dir / f"{model.__name__}.json").write_text(
            schema_text(model), encoding="utf-8"
        )


def drifting_files(schemas_dir: Path) -> list[str]:
    """Files failing the gate: byte drift, missing files, or orphaned JSON."""
    committed_names = {f"{model.__name__}.json" for model in ENVELOPE_MODELS}
    drifted: list[str] = []
    for model in ENVELOPE_MODELS:
        expected = schema_text(model)
        path = schemas_dir / f"{model.__name__}.json"
        committed = path.read_text(encoding="utf-8") if path.is_file() else None
        if committed != expected:
            drifted.append(f"{model.__name__}.json")
    if schemas_dir.is_dir():
        for orphan in sorted(schemas_dir.glob("*.json")):
            if orphan.name not in committed_names:
                drifted.append(orphan.name)
    return drifted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="byte-diff committed schemas against regeneration; exit 1 on drift",
    )
    parser.add_argument("--schemas-dir", type=Path, default=SCHEMA_DIR)
    args = parser.parse_args()
    if args.check:
        drifted = drifting_files(args.schemas_dir)
        if drifted:
            for name in drifted:
                print(f"SCHEMA DRIFT: {name} differs from regenerated output")
            print("Run scripts/generate_schemas.py to refresh guardrails/schemas/.")
            return 1
        print(f"PASS: {len(ENVELOPE_MODELS)} committed schemas byte-identical")
        return 0
    regenerate(args.schemas_dir)
    print(f"WROTE {len(ENVELOPE_MODELS)} schemas to {args.schemas_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
