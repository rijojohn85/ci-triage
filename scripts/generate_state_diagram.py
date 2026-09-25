#!/usr/bin/env python3
"""Regenerate the committed AD-1 state diagram (`workflow/STATE_DIAGRAM.md`).

Renders `workflow/diagram.py`'s view of the transition table. Modes: rewrite
the committed file (default) or `--check` (byte-identical drift gate used by
`make state-diagram-drift`), which exits 1 on drift. Mirrors the CLI shape of
`scripts/generate_schemas.py`.
"""

import argparse
import sys
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))  # workflow/ is not a pip package; run from anywhere

from workflow import diagram  # noqa: E402 — path set right above


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="byte-diff the committed diagram against regeneration; exit 1 on drift",
    )
    parser.add_argument("--diagram-path", type=Path, default=diagram.DIAGRAM_PATH)
    args = parser.parse_args()
    if args.check:
        expected = diagram.render()
        committed = (
            args.diagram_path.read_text(encoding="utf-8")
            if args.diagram_path.is_file()
            else None
        )
        if committed != expected:
            print(
                f"STATE DIAGRAM DRIFT: {args.diagram_path}"
                " differs from regenerated output"
            )
            print("Run scripts/generate_state_diagram.py to refresh the diagram.")
            return 1
        print("PASS: committed state diagram byte-identical")
        return 0
    diagram.write(args.diagram_path)
    print(f"WROTE {args.diagram_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
