"""AC1: the questions load once from `prompts/jev-classes.yaml` (AD-11, AD-19).

The yaml is the single copy of the five class descriptions and the Noul
injection-screen instruction; no class text lives in code, and the agent and
the eval reference the same file.
"""

from pathlib import Path

import yaml

from agents.jev import questions as questions_module
from agents.jev.questions import CHOICE_KEY, JEV_CLASSES_PATH, NOUL_KEY, load_questions
from contracts.enums import FAILURE_CLASSES


def test_ac1_questions_load_once_from_jev_classes_yaml() -> None:
    first = load_questions()
    second = load_questions()

    assert first is second, "the questions load once per process (AD-11)"

    raw = yaml.safe_load(JEV_CLASSES_PATH.read_text(encoding="utf-8"))
    assert set(first.choice.criteria) == set(FAILURE_CLASSES), (
        "the Choice carries exactly the five class labels (AD-11)"
    )
    assert first.choice.instructions == raw["choice"]["instructions"]
    for label, text in raw["choice"]["criteria"].items():
        assert first.choice.criteria[label] == text
    assert first.noul.instructions == raw["noul"]["instructions"]


def test_ac1_questions_mapping_carries_both_questions() -> None:
    mapping = load_questions().as_mapping()

    assert set(mapping) == {CHOICE_KEY, NOUL_KEY}, (
        "one call carries BOTH the Choice and the Noul (AD-11)"
    )


def test_ac1_no_class_text_in_code() -> None:
    """A distinctive phrase of every yaml entry is absent from the agent code."""
    raw = yaml.safe_load(JEV_CLASSES_PATH.read_text(encoding="utf-8"))
    texts = [
        raw["choice"]["instructions"],
        raw["noul"]["instructions"],
        *raw["choice"]["criteria"].values(),
    ]
    phrases = [text.split()[0] + " " + text.split()[1] for text in texts]

    for source in Path(questions_module.__file__).parent.glob("*.py"):
        code = source.read_text(encoding="utf-8")
        for phrase in phrases:
            assert phrase not in code, f"class text leaked into {source.name} (AD-19)"
