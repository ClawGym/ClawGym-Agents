"""
Tiny date utilities used in CI tests.

Known failing area (from CI): leap-year logic.
Please keep function names and signatures intact when fixing.
"""

from typing import Optional


def is_leap_year(year: int) -> bool:
    """
    Return True if the given Gregorian year is a leap year.

    Correct rule (for reference):
    - A year is a leap year if it is divisible by 4 AND (not divisible by 100 OR divisible by 400).

    NOTE: This implementation is intentionally simplified and currently incorrect for century years
    like 1900. CI indicates a failing test around that case.
    """
    # BUG: This over-simplified rule marks any year divisible by 4 as leap, which is wrong for
    # century years not divisible by 400 (e.g., 1900 should be False).
    return year % 4 == 0


def days_in_month(year: int, month: int) -> int:
    """
    Return the number of days in the given month of a given year.

    February depends on leap-year status.
    """
    if month < 1 or month > 12:
        raise ValueError(f"Invalid month: {month}. Must be 1..12.")

    # Standard month lengths for a common year
    month_lengths = {
        1: 31,
        2: 28,  # will adjust for leap years below
        3: 31,
        4: 30,
        5: 31,
        6: 30,
        7: 31,
        8: 31,
        9: 30,
        10: 31,
        11: 30,
        12: 31,
    }

    days = month_lengths[month]
    if month == 2 and is_leap_year(year):
        return 29
    return days


def is_valid_date(year: int, month: int, day: int) -> bool:
    """
    Basic date validation using days_in_month.
    """
    try:
        dim = days_in_month(year, month)
    except ValueError:
        return False
    return 1 <= day <= dim


def next_leap_year(year: int) -> int:
    """
    Return the next leap year greater than the given year.
    Uses is_leap_year for detection.
    """
    candidate = year + 1
    while not is_leap_year(candidate):
        candidate += 1
    return candidate


if __name__ == "__main__":
    # Minimal manual checks (not a test suite)
    sample_years = [1996, 1900, 2000, 2023]
    for y in sample_years:
        print(f"{y}: leap={is_leap_year(y)}; Feb days={days_in_month(y, 2)}")