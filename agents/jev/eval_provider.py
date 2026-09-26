"""The promptfoo Python provider for the Jev eval (story 3.1, F14).

Unlike the chat-prompt target, this provider exercises the SERVED surface:
it builds the `EvidencePack` from the case vars, calls the real
`classify()` with the real `TypeSafeJevProvider` (pinned model and timeout
from `config/runtime.yaml`, AD-19), and returns the `JevResult` JSON — the
same shape the A2A service answers with (AD-6).

Needs `TYPESAFE_API_KEY` in the environment; without one every case errors
(the eval is never faked). Referenced from `jev.test.yaml` as
`file://agents/jev/eval_provider.py` — promptfoo's documented way to load a
Python provider (docs source: context7, promptfoo `providers/python`).
"""

import asyncio
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))  # the promptfoo worker imports us cold

from agents.jev.classifier import classify  # noqa: E402 — bootstrap first
from agents.jev.provider import TypeSafeJevProvider  # noqa: E402
from agents.jev.runtime import load_jev_runtime  # noqa: E402
from contracts.evidence import DistilledLogLine, EvidencePack  # noqa: E402

_LAST_GREEN = "0" * 40  # placeholder sha; the eval pins no real commit


def _pack_from_vars(vars_: Mapping[str, Any]) -> EvidencePack:
    log = str(vars_.get("log", "")).strip()
    lines = [
        DistilledLogLine(line_number=number, text=text)
        for number, text in enumerate(log.splitlines(), start=1)
    ]
    return EvidencePack(
        repo_id="eval/repo",
        last_green=_LAST_GREEN,
        distilled_log=lines,
        commits=[],
        candidate_suspects=[],
        history_rows=[],
        metrics={},
    )


def call_api(
    prompt: str, options: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """promptfoo's Python provider entry: one real classify call per case."""
    del prompt, options  # the vars carry the log; the prompt is unused here
    pack = _pack_from_vars(context.get("vars", {}))
    runtime = load_jev_runtime()
    try:
        result = asyncio.run(classify(pack, TypeSafeJevProvider(), runtime))
    except Exception as error:
        return {"error": f"{type(error).__name__}: {error}"}
    return {"output": json.dumps(result.model_dump(mode="json"))}
