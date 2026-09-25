#!/usr/bin/env python3
"""Layer-contract checker (stdlib only: ast + pathlib), enforced from Story 0.1 (AC2).

Checks:
1. contracts/ imports nothing from the app layers (stdlib-only dependencies).
2. guardrails/ imports only contracts/ (+stdlib).
3. agents/* import no GitHub API clients or Postgres clients.
4. No secrets hardcoded (basic scan for key assigns) in Python files.
5. Runtime YAML: only allowed model IDs (claude-haiku-4-5-20251001,
   claude-sonnet-5); one step_timeout per agent key.

Exit non-zero on any violation; prints PASS lines per check on success.
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_LAYERS = {
    "workflow",
    "agents",
    "gateway",
    "guardrails",
    "monitoring",
    "punch_out",
    "results",
    "runs",
    "test_data",
}
GUARDRAILS_ALLOWED = {"contracts"}  # plus stdlib
FORBIDDEN_AGENT_MODULES = (
    "github",
    "pygithub",
    "gidgethub",
    "ghapi",
    "gitpython",
    "psycopg",
    "psycopg2",
    "sqlalchemy",
    "asyncpg",
    "pg8000",
    "githubkit",
)
ALLOWED_MODELS = {"claude-haiku-4-5-20251001", "claude-sonnet-5"}
MODEL_ID_RE = re.compile(r"claude-[a-z0-9.\-]+", re.IGNORECASE)
EXPECTED_AGENTS = {"jev", "analyzer", "proposer", "reviewer"}

errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def imports_of(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        fail(f"{path}: syntax error: {e}")
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def project_top_of(mod: str) -> str:
    return mod.split(".", maxsplit=1)[0] if mod else ""


def is_stdlib(top: str) -> bool:
    return top in sys.stdlib_module_names or top in {"__future__"}


def check_contracts(files: list[Path]) -> None:
    # contracts/ may import stdlib only — anything else fails.
    bad = []
    for f in files:
        for imp in imports_of(f):
            top = project_top_of(imp)
            if not is_stdlib(top):
                bad.append(f"{f.relative_to(ROOT)} imports {imp}")
    if bad:
        for b in bad:
            fail(f"LAYER CONTRACT (contracts) imports stdlib only: {b}")
    else:
        print("PASS: contracts/ imports nothing but stdlib (no app-layer deps)")


def check_guardrails(files: list[Path]) -> None:
    # guardrails/ may import only contracts (+stdlib) — positive allowlist.
    bad = []
    for f in files:
        for imp in imports_of(f):
            top = project_top_of(imp)
            if is_stdlib(top):
                continue
            if top not in GUARDRAILS_ALLOWED:
                bad.append(f"{f.relative_to(ROOT)} imports {imp}")
    if bad:
        for b in bad:
            fail(f"LAYER CONTRACT (guardrails) imports only contracts(+stdlib): {b}")
    else:
        print("PASS: guardrails/ depends only on contracts (+stdlib)")


def check_agents(files: list[Path]) -> None:
    # AST import scanning only: fail on actual imports matching forbidden package names.
    bad = []
    for f in files:
        for imp in imports_of(f):
            top = project_top_of(imp).lower()
            if top in FORBIDDEN_AGENT_MODULES:
                bad.append(f"{f.relative_to(ROOT)} imports {imp}")
    if bad:
        for b in bad:
            fail(f"LAYER CONTRACT (agents) no GitHub/Postgres clients: {b}")
    else:
        print("PASS: agents/ has no GitHub/Postgres client imports")


def check_secrets_in_python(files: list[Path]) -> None:
    bad = []
    for f in files:
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(
            r"(?i)\b(api_key|secret|token|password|private_key)\b\s*="
            r"\s*[\"'][^$\\{][^\"']{8,}[\"']",
            src,
        ):
            bad.append(
                f"{f.relative_to(ROOT)} possible hardcoded secret "
                f"at line start '{m.group(0)[:20]}...'"
            )
    if bad:
        for b in bad:
            fail(f"SECRETS: {b}")
    else:
        print("PASS: no hardcoded secrets in Python files")


def check_runtime_yaml() -> None:
    yaml_path = ROOT / "config" / "runtime.yaml"
    if not yaml_path.exists():
        fail("config/runtime.yaml missing")
        return
    matched_model = False
    bad_model_lines: list[str] = []
    agent_keys: set[str] = set()
    step_timeouts = 0
    for i, line in enumerate(yaml_path.read_text(encoding="utf-8").splitlines(), 1):
        matched_model = _check_model_ids(line, i, bad_model_lines, matched_model)
        agent_keys |= _check_agent_key(line)
        if re.match(r"^\s*step_timeout:", line):
            step_timeouts += 1
    if bad_model_lines:
        for b in bad_model_lines:
            fail(f"RUNTIME YAML: {b}")
    elif matched_model:
        print(
            "PASS: runtime YAML model IDs within allowed set (Sonnet/Haiku pair only)"
        )
    else:
        fail(
            "RUNTIME YAML: no model IDs found; expected pinned "
            "Claude model IDs in runtime.yaml"
        )
    if agent_keys != EXPECTED_AGENTS or not agent_keys:
        fail(
            f"RUNTIME YAML: expected agent top-level keys {sorted(EXPECTED_AGENTS)}, "
            f"found {sorted(agent_keys)}"
        )
    elif step_timeouts != len(EXPECTED_AGENTS):
        fail(
            f"RUNTIME YAML: found {step_timeouts} step_timeout entries, "
            f"expected {len(EXPECTED_AGENTS)} (one per agent)"
        )
    else:
        print(
            f"PASS: runtime YAML has step_timeout for each of the "
            f"{len(EXPECTED_AGENTS)} agents"
        )


def _check_model_ids(
    line: str,
    line_num: int,
    bad_model_lines: list[str],
    matched_model: bool,
) -> bool:
    """Accumulate bad model IDs for one line; return matched-so-far."""
    matched = matched_model
    for mid in MODEL_ID_RE.findall(line):
        matched = True
        if mid.lower() not in ALLOWED_MODELS:
            bad_model_lines.append(
                f"runtime.yaml:{line_num}: model id '{mid}' not allowed"
            )
    return matched


def _check_agent_key(line: str) -> set[str]:
    """Return a one-element set on a top-level agent key line, else empty."""
    top_key = re.match(r"^([A-Za-z0-9_\-]+):\s*(?:#.*)?$", line)
    if top_key and top_key.group(1) in EXPECTED_AGENTS:
        return {top_key.group(1)}
    return set()


def collect() -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {
        "contracts": [],
        "guardrails": [],
        "agents": [],
        "python": [],
    }
    for py in ROOT.rglob("*.py"):
        rel = str(py.relative_to(ROOT))
        if rel.startswith(
            (
                ".venv",
                "node_modules",
                "_bmad",
                ".remember",
                ".agents",
                ".opencode",
                ".claude",
            )
        ):
            continue
        groups["python"].append(py)
        if rel.startswith("contracts/"):
            groups["contracts"].append(py)
        elif rel.startswith("guardrails/") and not rel.startswith(
            "guardrails/schemas/"
        ):
            groups["guardrails"].append(py)
        elif rel.startswith("agents/"):
            groups["agents"].append(py)
    return groups


def check_dirs() -> None:
    for d in ("contracts", "guardrails", "agents"):
        if not (ROOT / d).is_dir():
            fail(f"LAYOUT: required directory '{d}/' missing")
    if not errors or not any(e.startswith("LAYOUT") for e in errors):
        print("PASS: contracts/, guardrails/, agents/ directories exist")


def main() -> int:
    check_dirs()
    groups = collect()
    check_contracts(groups["contracts"])
    check_guardrails(groups["guardrails"])
    check_agents(groups["agents"])
    check_secrets_in_python(groups["python"])
    check_runtime_yaml()
    if errors:
        print("\nFAILURES:")
        for e in errors:
            print(f"  FAIL: {e}")
        return 1
    print("\nLAYER CONTRACT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
