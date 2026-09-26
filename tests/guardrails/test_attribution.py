"""Story 4.1 tests for `guardrails/attribution.py` (AC3, AD-27).

The deep author-key walk moved here from `workflow/task_store.py` (DRY: one
walk, two consumers — the task-artifact projection strips, the validator's
blame-free check finds). The field name comes from `contracts.evidence`.
"""

from guardrails.attribution import (
    attribution_location,
    contains_author_attribution,
    strip_author_attribution,
)

NESTED = {
    "commits": [
        {"sha": "a", "message": "m", "author_login": "someone"},
        {"sha": "b", "message": "m"},
    ],
    "wrap": {"deep": [{"deeper": {"author_login": "hidden"}}]},
    "plain": "text",
}


# --- AC3: the deep scan finds the author key at any depth


def test_ac3_deep_scan_finds_author_key_at_any_depth() -> None:
    assert attribution_location(NESTED) == "commits[0].author_login"


def test_ac3_deep_scan_reports_the_deepest_first_match_path() -> None:
    value = {"outer": {"inner": {"author_login": "someone"}}}

    assert attribution_location(value) == "outer.inner.author_login"


def test_ac3_deep_scan_finds_inside_sequences() -> None:
    value = [{"a": [{"author_login": "someone"}]}]

    assert attribution_location(value) == "[0].a[0].author_login"


def test_ac3_absent_author_key_has_no_location() -> None:
    assert attribution_location({"commits": [{"sha": "a", "message": "m"}]}) is None
    assert attribution_location("scalar") is None
    assert attribution_location(None) is None


def test_ac3_contains_mirrors_the_location_scan() -> None:
    assert contains_author_attribution(NESTED) is True
    assert contains_author_attribution({"commits": [{"sha": "a"}]}) is False


# --- AC3: the strip drops the author key at any depth, touching nothing else


def test_ac3_strip_removes_every_author_key_and_keeps_the_rest() -> None:
    stripped = strip_author_attribution(NESTED)

    assert stripped == {
        "commits": [{"sha": "a", "message": "m"}, {"sha": "b", "message": "m"}],
        "wrap": {"deep": [{"deeper": {}}]},
        "plain": "text",
    }


def test_ac3_strip_passes_scalars_and_sequences_through() -> None:
    assert strip_author_attribution("text") == "text"
    assert strip_author_attribution([1, (2, 3)]) == [1, [2, 3]]
    assert strip_author_attribution(None) is None
