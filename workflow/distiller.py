"""Deterministic CI-log distiller (AD-20, AD-24).

A pure text transform (SOLID-S): no model, no network, no filesystem, no
clock. Raw CI logs are untrusted and huge, so this module keeps only the
useful evidence — error blocks, stack traces and JUnit failure/error content —
strips ANSI/control characters, numbers the survivors through
`contracts.evidence.DistilledLogLine` and clips the kept text to the byte
bound read from `guardrails/thresholds.yaml` (AD-19). The same input always
yields the same output, so the `log_line` citation numbers stay stable (AD-7).

Adding a new CI error style is open/closed: add one entry to `ERROR_MARKERS`,
never a new branch.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from contracts.evidence import DistilledLogLine
from workflow.thresholds import DistillerLimits

__all__ = ["ERROR_MARKERS", "distill"]

_ANSI_ESCAPE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC ... BEL/ST
    r"|\x1b\[[0-?]*[ -/]*[@-~]"  # CSI
    r"|\x1b[@-Z\\-_]"  # other two-character escapes
)

# Everything below 0x20 except tab (0x09) and newline (0x0a), plus DEL and
# the C1 controls (U+0080-U+009F).
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u0080-\u009f]")

# One ordered registry (SOLID-O): a new CI error style is a new entry.
ERROR_MARKERS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        r"Traceback \(most recent call last\):",
        r'\bFile "[^"]*", line \d+',
        r"^\s*(?:ERROR|FATAL|FAIL|FAILED|panic"
        r"|AssertionError|Error|Exception)\b",
        r"\b[A-Za-z_]\w*(?:Error|Exception)\b",
        r"^\s*E\s+\S",
        r"^>\s",
        r"##\[error\]",
        r"^_{5,}.*_{5,}$",
        r"=+ FAILURES =+",
        r"^goroutine \d+",
        r"^\s+at [\w.$]+\(",
        r"^FAILED\s",
    )
)

# JUnit XML is untrusted data (AD-20); a document declaring a DTD or entity is
# skipped whole, so an entity expansion (e.g. billion laughs) never runs.
_UNTRUSTED_XML_MARKERS = ("<!DOCTYPE", "<!ENTITY")

_JUNIT_FAILURE_TAGS = {"failure": "FAIL", "error": "ERROR"}


def _strip_controls(text: str) -> str:
    """Remove ANSI escapes and non-printing controls (ASCII and C1); keep tabs
    and newlines."""
    without_ansi = _ANSI_ESCAPE.sub("", text)
    return _CONTROL_CHARS.sub("", without_ansi)


def _matches_error_marker(line: str) -> bool:
    return any(marker.search(line) is not None for marker in ERROR_MARKERS)


def _evidence_text_lines(cleaned_log: str) -> list[str]:
    """Keep marker lines and their indented continuations; drop narrative.

    A blank line neither starts evidence nor ends a block: pytest prints an
    error banner, a blank line, then the indented failing source, so the
    continuation has to survive that gap.
    """
    kept: list[str] = []
    previous_kept = False
    for line in cleaned_log.split("\n"):
        if not line.strip():
            continue
        if _matches_error_marker(line) or (previous_kept and line[:1].isspace()):
            kept.append(line)
            previous_kept = True
        else:
            previous_kept = False
    return kept


def _junit_header(status: str, testcase: ET.Element, element: ET.Element) -> str:
    classname = (testcase.get("classname") or "").strip()
    name = (testcase.get("name") or "").strip()
    test_id = f"{classname}::{name}" if classname else name or "unknown"
    message = (element.get("message") or "").strip()
    return f"{status} {test_id}: {message}" if message else f"{status} {test_id}"


def _local_name(tag: str) -> str:
    """Element tag with any `{namespace}` prefix removed."""
    return tag.rsplit("}", 1)[-1]


def _junit_evidence(junit_xml: str | None) -> list[str]:
    """`<failure>`/`<error>` content as evidence lines; DTD/ENTITY is skipped.

    Tags are matched on their local name so a namespaced JUnit document still
    yields evidence, and every returned line is control-stripped because JUnit
    XML is untrusted (AD-20).
    """
    if not junit_xml or any(marker in junit_xml for marker in _UNTRUSTED_XML_MARKERS):
        return []
    try:
        root = ET.fromstring(junit_xml)
    except ET.ParseError:
        return []
    evidence: list[str] = []
    for testcase in root.iter():
        if _local_name(testcase.tag) != "testcase":
            continue
        for element in testcase:
            status = _JUNIT_FAILURE_TAGS.get(_local_name(element.tag))
            if status is None:
                continue
            evidence.append(_junit_header(status, testcase, element))
            body = (element.text or "").strip("\n")
            evidence.extend(line for line in body.splitlines() if line.strip())
    stripped = [_strip_controls(line) for line in evidence]
    return [line for line in stripped if line.strip()]


def _fallback_lines(cleaned_log: str) -> list[str]:
    """No marker and no JUnit evidence: keep the last non-empty line so the
    evidence pack still has at least one line (documented fallback)."""
    lines = [line for line in cleaned_log.split("\n") if line.strip()]
    return [lines[-1]] if lines else [""]


def _truncate_utf8(text: str, max_bytes: int) -> str:
    """Longest prefix of `text` within `max_bytes`, never splitting a char."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    clipped = encoded[:max_bytes]
    while clipped:
        try:
            return clipped.decode("utf-8")
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return ""


def _clip_to_bytes(lines: list[str], max_bytes: int) -> list[DistilledLogLine]:
    """Number kept lines from 1 and stop at the byte bound.

    `max_bytes` bounds the total UTF-8 size of the kept evidence text; the
    line-number labels are metadata, not evidence. Truncation never renumbers
    the survivors (AD-7).
    """
    kept: list[DistilledLogLine] = []
    used = 0
    for text in lines:
        remaining = max_bytes - used
        if remaining <= 0:
            break
        clipped = _truncate_utf8(text, remaining)
        kept.append(DistilledLogLine(line_number=len(kept) + 1, text=clipped))
        used += len(clipped.encode("utf-8"))
        if clipped != text:
            break
    if not kept:
        kept.append(DistilledLogLine(line_number=1, text=""))
    return kept


def distill(
    ci_log: str,
    junit_xml: str | None,
    limits: DistillerLimits,
) -> list[DistilledLogLine]:
    """Distil raw CI text plus optional JUnit XML into numbered evidence lines."""
    cleaned = _strip_controls(ci_log)
    evidence = _evidence_text_lines(cleaned) + _junit_evidence(junit_xml)
    if not evidence:
        evidence = _fallback_lines(cleaned)
    return _clip_to_bytes(evidence, limits.max_bytes)
