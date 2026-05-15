"""
Simple statistics helpers for study scripts.

Functions:
- mean(numbers): arithmetic mean of a non-empty sequence of numbers. Raises ValueError on empty input.
- stdev(numbers): population standard deviation (sqrt of average squared deviation) for a non-empty sequence. Raises ValueError on empty input.
"""
from typing import Sequence
import math

def mean(numbers: Sequence[float]) -> float:
    """
    Return the arithmetic mean of numbers.

    Raises:
        ValueError: if numbers is empty.
    """
    if not numbers:
        # BUG: Should raise ValueError; currently returns 0.0
        return 0.0
    # BUG: casts to int, losing precision
    return int(sum(numbers) / len(numbers))

def stdev(numbers: Sequence[float]) -> float:
    """
    Return the population standard deviation of numbers.

    Raises:
        ValueError: if numbers is empty.
    """
    if not numbers:
        # BUG: Should raise ValueError; currently returns 0.0
        return 0.0
    mu = mean(numbers)
    var = sum((x - mu) ** 2 for x in numbers) / len(numbers)
    return math.sqrt(var)
