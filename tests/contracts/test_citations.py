"""AC1/AC2: citations are a closed discriminated union with per-kind locators."""

import pytest
from pydantic import ValidationError

from contracts.citations import (
    CommitCitation,
    HistoryRowCitation,
    JevSignalCitation,
    LogLineCitation,
    MetricCitation,
    create_citation,
)
from contracts.enums import CitationKind

DISTILLED_LINE = 14


def test_ac1_citation_kind_is_exactly_the_spine_set() -> None:
    assert [member.value for member in CitationKind] == [
        "log_line",
        "commit",
        "metric",
        "history_row",
        "jev_signal",
    ]


def test_ac2_citation_kind_is_closed() -> None:
    with pytest.raises(ValidationError) as exc:
        create_citation({"kind": "guess", "answer": "x"})
    message = str(exc.value)
    assert "kind" in message
    for allowed in ("log_line", "commit", "metric", "history_row", "jev_signal"):
        assert allowed in message


def test_ac1_each_kind_carries_its_spine_locator() -> None:
    log_line = create_citation({"kind": "log_line", "log_line": DISTILLED_LINE})
    commit = create_citation({"kind": "commit", "sha": "a" * 40})
    metric = create_citation({"kind": "metric", "metric_key": "test_duration"})
    history = create_citation({"kind": "history_row", "row_id": "row-17"})
    jev = create_citation({"kind": "jev_signal", "answer": "screen-noul"})

    assert isinstance(log_line, LogLineCitation)
    assert log_line.log_line == DISTILLED_LINE
    assert isinstance(commit, CommitCitation)
    assert commit.sha == "a" * 40
    assert isinstance(metric, MetricCitation)
    assert metric.metric_key == "test_duration"
    assert isinstance(history, HistoryRowCitation)
    assert history.row_id == "row-17"
    assert isinstance(jev, JevSignalCitation)
    assert jev.answer == "screen-noul"


def test_ac2_short_sha_is_rejected_in_a_production_citation() -> None:
    with pytest.raises(ValidationError) as exc:
        create_citation({"kind": "commit", "sha": "abc1234"})
    assert "sha" in str(exc.value)


def test_ac2_citation_rejects_missing_locator_of_its_kind() -> None:
    with pytest.raises(ValidationError) as exc:
        create_citation({"kind": "log_line", "log_line": "not-a-number"})
    assert "log_line" in str(exc.value)
