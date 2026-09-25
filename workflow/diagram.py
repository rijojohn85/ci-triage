"""Mermaid rendering of the AD-1 state diagram, straight from the table.

The diagram is generated, never maintained by hand (AD-1): the committed
`workflow/STATE_DIAGRAM.md` must be byte-identical to `render()` output,
which `scripts/generate_state_diagram.py --check` and the
`make state-diagram-drift` gate enforce.
"""

from pathlib import Path
from typing import Final

from workflow.run_states import TERMINAL_RUN_STATES, RunState
from workflow.transitions import transitions_from

__all__ = ["DIAGRAM_PATH", "render", "render_edges", "write"]

DIAGRAM_PATH: Final[Path] = Path(__file__).resolve().parent / "STATE_DIAGRAM.md"

_ENTRY_STATE: Final[str] = RunState.RECEIVED.name

_HEADER: Final[str] = (
    "# Run state diagram\n"
    "<!-- Generated from the AD-1 transition table in workflow/transitions.py;"
    " do not edit by hand. -->\n"
    "<!-- Regenerate: python scripts/generate_state_diagram.py;"
    " drift gate: make state-diagram-drift -->\n"
)

GraphRows = tuple[tuple[str, str, str], ...]


def _table_rows() -> GraphRows:
    """All table rows (from, to, label) in RunState order, FAILED row last."""
    return tuple(
        (row.from_state.name, row.to_state.name, row.label)
        for from_state in RunState
        for row in transitions_from(from_state)
    )


def _edge_lines() -> list[str]:
    lines: list[str] = [f"  [*] --> {_ENTRY_STATE}"]
    lines.extend(
        f"  {src} --> {dst}: {label}" if label else f"  {src} --> {dst}"
        for src, dst, label in _table_rows()
    )
    lines.extend(
        f"  {terminal.name} --> [*]"
        for terminal in sorted(TERMINAL_RUN_STATES, key=lambda state: state.name)
    )
    return lines


def render() -> str:
    """Deterministic mermaid + preamble, rebuilt from the transition table."""
    lines = [_HEADER, "```mermaid", "stateDiagram-v2", *_edge_lines(), "```"]
    return "\n".join(lines) + "\n"


def render_edges() -> set[tuple[str, str]]:
    """Edge set incl. entry, terminal exits and derived FAILED edges."""
    edges = {("[*]", _ENTRY_STATE)}
    for src, dst, _label in _table_rows():
        edges.add((src, dst))
    for terminal in TERMINAL_RUN_STATES:
        edges.add((terminal.name, "[*]"))
    return edges


def write(path: Path = DIAGRAM_PATH) -> str:
    """Regenerate the committed diagram file (idempotent, byte-stable)."""
    text = render()
    path.write_text(text, encoding="utf-8")
    return text
