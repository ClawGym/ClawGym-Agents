# Utility functions for basic arithmetic used in my math practice.

from typing import Iterable


def add(a: float, b: float) -> float:
    """Return the sum of a and b."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Return the difference a - b.
    NOTE: This function currently contains a defect for CI demonstration purposes.
    """
    # Intentional bug to produce a failing test in the CI dry run:
    return a + b  # should be: a - b


def mean(nums: Iterable[float]) -> float:
    """Return the arithmetic mean of nums. Raises ValueError if empty."""
    nums = list(nums)
    if len(nums) == 0:
        raise ValueError("mean() arg is an empty sequence")
    return sum(nums) / len(nums)
