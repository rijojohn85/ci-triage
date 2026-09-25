#!/usr/bin/env python3
"""Layer-contract checker (stdlib only: ast + pathlib), enforced from Story 0.1 (AC2).

Checks:
1. contracts/ imports stdlib + pydantic + intra-package modules only (amended
   in Story 0.2: AD-6 mandates Pydantic; the 0.1 stdlib-only wording loses).
2. guardrails/ imports only contracts/ (+ pydantic + intra-package + stdlib).
3. agents/* import no GitHub API clients or Postgres clients.
4. gateway/* imports no LLM (anthropic/a2a) or GitHub API clients (AD-17).
5. No secrets hardcoded (basic scan for key assigns) in Python files.
6. Runtime YAML: only allowed model IDs (claude-haiku-4-5-20251001,
   claude-sonnet-5); one step_timeout per agent key.

Exit non-zero on any violation; prints PASS lines per check on success.
"""

import argparse
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
PYDANTIC = "pydantic"
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
# AD-17: the gateway is transport only — no LLM client and no GitHub client
# (psycopg for enqueue is allowed, unlike for the spokes).
FORBIDDEN_GATEWAY_MODULES = (
    "anthropic",
    "a2a",
    "github",
    "pygithub",
    "gidgethub",
    "ghapi",
    "gitpython",
    "githubkit",
)
ALLOWED_MODELS = {"claude-haiku-4-5-20251001", "claude-sonnet-5"}
MODEL_ID_RE = re.compile(r"claude-[a-z0-9.\-]+", re.IGNORECASE)
EXPECTED_AGENTS = {"jev", "analyzer", "proposer", "reviewer"}

errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def imports_of(path: Path) -> set[str]:
    """Record imports; relative imports surface as one "." per level (see checks)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        fail(f"{path}: syntax error: {e}")
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            marker = "." * node.level
            if node.module:
                mods.add(f"{marker}{node.module}")
            elif node.level:  # pure `from .. import x` style
                mods.add(marker)
    return mods


def project_top_of(mod: str) -> str:
    return mod.split(".", maxsplit=1)[0] if mod else ""


def is_self_import(imp: str, owner_dir: str) -> bool:
    """Level-1 relative import or absolute `owner_dir.*`; level-2 imports escape."""
    if imp.startswith(".."):
        return False
    return imp.startswith(".") or imp == owner_dir or imp.startswith(f"{owner_dir}.")


def is_stdlib(top: str) -> bool:
    return top in sys.stdlib_module_names or top in {"__future__"}


def admitted(imp: str, owner_dir: str, extras: tuple[str, ...]) -> bool:
    if imp.startswith(".."):
        return False  # even an inter-package relative import leaves the package
    top = project_top_of(imp) or imp
    return (
        is_stdlib(top)
        or top in extras
        or is_self_import(imp, owner_dir)
        or any(top.startswith(f"{extra}.") for extra in extras)
    )


def check_layer(
    owner_dir: str,
    group_files: list[Path],
    allowed_extras: tuple[str, ...],
    message: str,
    root: Path,
) -> None:
    """One layer rule: stdlib + intra-package + admitted extras (SOLID-D)."""
    bad = []
    for f in group_files:
        for imp in imports_of(f):
            if not admitted(imp, owner_dir, allowed_extras):
                bad.append(f"{f.relative_to(root)} imports {imp}")
    if bad:
        for b in bad:
            fail(f"LAYER CONTRACT ({owner_dir}) {message}: {b}")
    else:
        print(f"PASS: {owner_dir}/ {message}")


LAYERS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("contracts", (PYDANTIC,), "imports stdlib + pydantic + intra-package only"),
    (
        "guardrails",
        (PYDANTIC, "contracts"),
        "depends only on contracts (+ pydantic, self, stdlib)",
    ),
)


def check_agents(files: list[Path], root: Path) -> None:
    # AST import scanning only: fail on actual imports matching forbidden package names.
    bad = []
    for f in files:
        for imp in imports_of(f):
            top = project_top_of(imp).lower()
            if top in FORBIDDEN_AGENT_MODULES:
                bad.append(f"{f.relative_to(root)} imports {imp}")
    if bad:
        for b in bad:
            fail(f"LAYER CONTRACT (agents) no GitHub/Postgres clients: {b}")
    else:
        print("PASS: agents/ has no GitHub/Postgres client imports")


def check_gateway(files: list[Path], root: Path) -> None:
    # AD-17: no LLM or GitHub client in the gateway (psycopg enqueue is fine).
    bad = []
    for f in files:
        for imp in imports_of(f):
            top = project_top_of(imp).lower()
            if top in FORBIDDEN_GATEWAY_MODULES:
                bad.append(f"{f.relative_to(root)} imports {imp}")
    if bad:
        for b in bad:
            fail(f"LAYER CONTRACT (gateway) no LLM/GitHub clients: {b}")
    else:
        print("PASS: gateway/ has no LLM/GitHub client imports")


def check_secrets_in_python(files: list[Path], root: Path) -> None:
    bad = []
    for f in files:
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(
            r"(?i)\b(api_key|secret|token|password|private_key)\b\s*="
            r"\s*[\"'][^$\\{][^\"']{8,}[\"']",
            src,
        ):
            bad.append(
                f"{f.relative_to(root)} possible hardcoded secret "
                f"at line start '{m.group(0)[:20]}...'"
            )
    if bad:
        for b in bad:
            fail(f"SECRETS: {b}")
    else:
        print("PASS: no hardcoded secrets in Python files")


def check_runtime_yaml(root: Path) -> None:
    yaml_path = root / "config" / "runtime.yaml"
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


def collect(root: Path) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {
        "contracts": [],
        "guardrails": [],
        "agents": [],
        "gateway": [],
        "python": [],
    }
    for py in root.rglob("*.py"):
        rel = str(py.relative_to(root))
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
        elif rel.startswith("gateway/"):
            groups["gateway"].append(py)
    return groups


def check_dirs(root: Path) -> None:
    for d in ("contracts", "guardrails", "agents"):
        if not (root / d).is_dir():
            fail(f"LAYOUT: required directory '{d}/' missing")
    if not errors or not any(e.startswith("LAYOUT") for e in errors):
        print("PASS: contracts/, guardrails/, agents/ directories exist")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository root to check (tests plant fixture trees elsewhere)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    root = parse_args(argv).root.resolve()
    check_dirs(root)
    groups = collect(root)
    for owner_dir, extras, message in LAYERS:
        check_layer(owner_dir, groups[owner_dir], extras, message, root)
    check_agents(groups["agents"], root)
    check_gateway(groups["gateway"], root)
    check_secrets_in_python(groups["python"], root)
    check_runtime_yaml(root)
    if errors:
        print("\nFAILURES:")
        for e in errors:
            print(f"  FAIL: {e}")
        return 1
    print("\nLAYER CONTRACT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
