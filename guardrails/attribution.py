"""Deep author-attribution walk (AD-27): find, locate and strip `author_login`.

Pure domain code (stdlib + `contracts` only, layer contract). The walk moved
here from `workflow/task_store.py` (story 4.1, DRY): one walk serves two
consumers — the task-artifact projection strips the key, and the validator's
blame-free check finds it. The field name has one source,
`contracts.evidence.AUTHOR_ATTRIBUTION_FIELD`.
"""

from collections.abc import Mapping

from contracts.evidence import AUTHOR_ATTRIBUTION_FIELD

__all__ = [
    "attribution_location",
    "contains_author_attribution",
    "strip_author_attribution",
]


def attribution_location(value: object) -> str | None:
    """Dotted path of the first `author_login` key at any depth, or `None`.

    The path shape matches the validator's issue locations: mapping keys join
    with `.`, sequence items index with `[n]` (e.g. `commits[0].author_login`).
    """
    return _find(value, "")


def contains_author_attribution(value: object) -> bool:
    """True when an `author_login` key survives at any depth (AD-27)."""
    return attribution_location(value) is not None


def strip_author_attribution(value: object) -> object:
    """Drop the AD-27 author key at any depth; everything else is untouched."""
    if isinstance(value, Mapping):
        return {
            key: strip_author_attribution(item)
            for key, item in value.items()
            if key != AUTHOR_ATTRIBUTION_FIELD
        }
    if isinstance(value, (list, tuple)):
        return [strip_author_attribution(item) for item in value]
    return value


def _find(value: object, prefix: str) -> str | None:
    """One depth-first walk for both finders; `prefix` is the path so far."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key == AUTHOR_ATTRIBUTION_FIELD:
                return path
            found = _find(item, path)
            if found is not None:
                return found
        return None
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found = _find(item, f"{prefix}[{index}]")
            if found is not None:
                return found
    return None
