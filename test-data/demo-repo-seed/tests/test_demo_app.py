"""Green baseline tests for the demo package.

The S1-S5 scenario drivers edit or add to this file on purpose (seeded
failures, flaky seeds, timeout bump). At baseline both tests pass.
"""

import pytest

from demo_app import add, divide


def test_add_two_numbers() -> None:
    assert add(2, 3) == 5


def test_divide_by_nonzero() -> None:
    assert divide(6, 3) == pytest.approx(2.0)
