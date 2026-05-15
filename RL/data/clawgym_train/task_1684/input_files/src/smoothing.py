from typing import List

"""
Simple smoothing helpers for servo position/velocity traces.
Note: There is some overlap with filters.py; this is due for consolidation.
"""


def boxcar_smooth(series: List[float], k: int) -> List[float]:
    """Compute a trailing boxcar (moving average) over 'series' using a window of size k.
    Returns a list of averaged values with length len(series) - k + 1.
    Raises ValueError if k < 1 or k > len(series).
    """
    if k < 1 or k > len(series):
        raise ValueError("k must be between 1 and len(series)")
    out: List[float] = []
    # Same trailing-average behavior as filters.moving_average_filter, but with different parameter names.
    for i in range(k, len(series) + 1):
        window = series[i - k:i]
        out.append(sum(window) / float(k))
    return out


def ema(series: List[float], alpha: float) -> List[float]:
    """Exponential moving average with factor alpha in (0,1]."""
    if not (0 < alpha <= 1):
        raise ValueError("alpha must be in (0, 1]")
    if not series:
        return []
    out: List[float] = [series[0]]
    for x in series[1:]:
        out.append(alpha * x + (1 - alpha) * out[-1])
    return out
