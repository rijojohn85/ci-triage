"""The one `system_one` call's questions, built once from the yaml (AD-11, AD-19).

`prompts/jev-classes.yaml` is the single copy of the five class descriptions
and the Noul injection-screen instruction (the eval suite documents the same
file); no class text lives in code. The questions are loaded once per
process and carried as the SDK's `Choice`/`Noul` primitives — the distilled
log never enters them (AD-20); it travels as the call's `state`.
"""

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Final, NamedTuple

import yaml
from typesafe_sdk import Choice, Noul

from contracts.enums import FAILURE_CLASSES

__all__ = [
    "CHOICE_KEY",
    "JEV_CLASSES_PATH",
    "NOUL_KEY",
    "JevQuestions",
    "load_questions",
]

JEV_CLASSES_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent.parent / "prompts" / "jev-classes.yaml"
)
CHOICE_KEY: Final[str] = "choice"
NOUL_KEY: Final[str] = "noul"


class JevQuestions(NamedTuple):
    """The batched question pair of the one `system_one` call (AD-11)."""

    choice: Choice
    noul: Noul

    def as_mapping(self) -> Mapping[str, Choice | Noul]:
        """The questions keyed by the names their answers are read back under."""
        return {CHOICE_KEY: self.choice, NOUL_KEY: self.noul}


@lru_cache(maxsize=1)
def load_questions() -> JevQuestions:
    """Build the question pair once per process from the single yaml (AD-11).

    The cache is path-independent: the yaml location is the module constant,
    so an alternate-path read (tests) cannot evict the default entry.
    """
    return _build_questions(JEV_CLASSES_PATH)


def _build_questions(path: Path) -> JevQuestions:
    """Read one class-description file into the SDK question pair."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    criteria: dict[str, str] = dict(raw["choice"]["criteria"])
    if set(criteria) != set(FAILURE_CLASSES):
        raise ValueError(
            f"prompts/jev-classes.yaml must describe exactly the five classes "
            f"{', '.join(FAILURE_CLASSES)}; got {', '.join(sorted(criteria))}"
        )
    return JevQuestions(
        choice=Choice(
            instructions=raw["choice"]["instructions"],
            criteria={label: criteria[label] for label in FAILURE_CLASSES},
        ),
        noul=Noul(instructions=raw["noul"]["instructions"]),
    )
