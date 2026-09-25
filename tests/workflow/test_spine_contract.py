"""Story 2.1 AC1: the table's edge set equals the spine's AD-1 mermaid block.

The spine is the source of truth; this test parses its committed mermaid
block plus the FAILED prose rule and fails loudly when the workflow table
or the generated diagram drift from it.
"""

import re
from pathlib import Path
from typing import Final

from workflow.diagram import DIAGRAM_PATH, render, render_edges, write
from workflow.run_states import TERMINAL_RUN_STATES, RUN_STATES, RunState
from workflow.transitions import TRANSITIONS, declared_edges

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SPINE: Final[Path] = (
    REPO_ROOT
    / "_bmad-output"
    / "planning-artifacts"
    / "architecture"
    / "architecture-stage4-2026-09-25"
    / "ARCHITECTURE-SPINE.md"
)


def spine_ad1_block_edges() -> set[tuple[str, str]]:
    """Parse state-to-state edges of the first mermaid block under AD-1."""
    lines = SPINE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("### AD-1"))
    in_block = False
    edges: set[tuple[str, str]] = set()
    for line in lines[start:]:
        if line.strip() == "```mermaid":
            in_block = True
            continue
        if in_block and line.strip() == "```":
            break
        if in_block and "-->" in line:
            left, right = line.split("-->", 1)
            src = left.strip()
            dst = right.split(":", 1)[0].strip()
            endpoints = (src, dst)
            if all(not name.startswith("[") for name in endpoints):
                edges.add(endpoints)
    return edges


def test_ac1_table_edges_equal_spine_mermaid_block() -> None:
    from workflow.transitions import declared_edges

    from_spine = spine_ad1_block_edges()
    from_table = declared_edges()
    assert from_table == from_spine, (
        f"spine-only: {sorted(from_spine - from_table)}; "
        f"table-only: {sorted(from_table - from_spine)}"
    )


def test_ac1_diagram_edges_declared_plus_derived_failed() -> None:
    from workflow.run_states import TERMINAL_RUN_STATES as terminal
    from workflow.transitions import declared_edges

    expected = {("[*]", "RECEIVED")} | declared_edges()
    expected |= {(state.name, "[*]") for state in terminal}
    expected |= {
        (state.name, "FAILED") for state in set(RunState) - terminal
    }
    assert render_edges() == expected


def test_ac1_spine_keeps_the_derived_failed_rule_in_prose() -> None:
    text = SPINE.read_text(encoding="utf-8")
    assert re.search(r"Any non-terminal state may also move to `FAILED`", text)


def test_ac1_regenerated_diagram_file_matches_the_committed_one(
    tmp_path: Path,
) -> None:
    regenerated = tmp_path / "STATE_DIAGRAM.md"
    write(regenerated)
    assert regenerated.read_text(encoding="utf-8") == DIAGRAM_PATH.read_text(
        encoding="utf-8"
    )


def test_ac1_diagram_mermaid_block_lists_every_table_row() -> None:
    text = render()
    for state in RUN_STATES:
        # entry state appears as the [*] target; terminals as [*] sources
        assert state.name in text
    for row in TRANSITIONS:
        assert f"{row.from_state.name} --> {row.to_state.name}" in text
