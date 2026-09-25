"""Synthetic demo package for the blameless CI triage demo repository.

Deliberately tiny: the S1-S5 scenario drivers (stories 6.6, 6.7, 6.8) break
this baseline on purpose with seeded failures. The green baseline is what a
healthy run looks like before a scenario is applied.
"""

__version__ = "0.1.0"


def add(a: int, b: int) -> int:
    """Return the sum of two integers."""
    return a + b


def divide(a: int, b: int) -> float:
    """Return a / b as a float."""
    return a / b
