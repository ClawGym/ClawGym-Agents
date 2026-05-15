"""
Simple climate utilities used in quick tests.

Functions:
- compute_net_emissions(emissions, offsets): sum(emissions) - sum(offsets)
- compute_carbon_budget(allowance, current_emissions): remaining budget
"""
from typing import Iterable


def compute_net_emissions(emissions: Iterable[float], offsets: Iterable[float]) -> float:
    """Return total emissions minus offsets.

    Both inputs can be any iterable of numbers.
    """
    return sum(emissions) - sum(offsets)


def compute_carbon_budget(allowance: float, current_emissions: float) -> float:
    """Return remaining budget given an allowance and current emissions."""
    return allowance - current_emissions
