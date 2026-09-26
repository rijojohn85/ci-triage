"""Story 3.2 AC1 tests for the promptfoo Python provider's case mapping.

The provider accepts two case shapes: generated cases carry `lines` (already
numbered by the real distiller) and the inline fixtures carry a `log` string.
These tests prove the mapping is faithful — `lines` numbers are kept verbatim,
`log` is numbered 1..n, `repo` is carried — and that a malformed case is
reported as a provider error, never raised into promptfoo.
"""

import pytest

from agents.jev.eval_provider import _distilled_lines, _pack_from_vars, call_api


def test_ac1_generated_lines_keep_their_own_line_numbers() -> None:
    """`lines` are used as-is: the distiller's numbering is never redone (AD-7)."""
    lines = _distilled_lines(
        {
            "lines": [
                {"line_number": 7, "text": "first kept line"},
                {"line_number": 9, "text": "second kept line"},
            ]
        }
    )
    assert [line.line_number for line in lines] == [7, 9]
    assert [line.text for line in lines] == ["first kept line", "second kept line"]


def test_ac1_log_case_is_numbered_from_one() -> None:
    lines = _distilled_lines({"log": "alpha\nbeta\n"})
    assert [(line.line_number, line.text) for line in lines] == [
        (1, "alpha"),
        (2, "beta"),
    ]


def test_ac1_empty_lines_is_authoritative_not_a_log_fallthrough() -> None:
    """A present-but-empty `lines` is an empty log, never the `log` branch."""
    lines = _distilled_lines({"lines": [], "log": "alpha\nbeta"})
    assert lines == []


def test_ac1_pack_carries_repo_and_the_numbered_lines() -> None:
    pack = _pack_from_vars(
        {"repo": "curl/curl", "lines": [{"line_number": 3, "text": "kept"}]}
    )
    assert pack.repo_id == "curl/curl"
    assert [(line.line_number, line.text) for line in pack.distilled_log] == [
        (3, "kept")
    ]


def test_ac1_pack_defaults_repo_when_the_case_has_none() -> None:
    assert _pack_from_vars({"log": "alpha"}).repo_id == "eval/repo"


def test_ac1_malformed_lines_returns_an_error_not_an_exception() -> None:
    """A malformed `lines` entry is a provider error, never a raised exception."""
    result = call_api(
        "prompt",
        {},
        {"vars": {"lines": [{"line_number": "not-a-number", "text": "x"}]}},
    )
    assert "error" in result
    assert "output" not in result


def test_ac1_non_list_lines_returns_an_error() -> None:
    result = call_api("prompt", {}, {"vars": {"lines": "not a list"}})
    assert "error" in result


def test_ac1_log_and_lines_helpers_are_pure() -> None:
    """The helpers never touch the network or the clock (SOLID-S)."""
    with pytest.raises(ValueError):
        _distilled_lines({"lines": {"line_number": 1}})
