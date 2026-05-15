from typing import List

# Gravitational constant used elsewhere; currently unused here, but kept for reference in mech calcs.
G = 9.81


def moving_average_filter(values: List[float], window_size: int) -> List[float]:
    """Compute a trailing moving average over 'values' using a window of size 'window_size'.
    Returns a list of averaged values with length len(values) - window_size + 1.
    Raises ValueError if window_size < 1 or window_size > len(values).
    """
    if window_size < 1 or window_size > len(values):
        raise ValueError("window_size must be between 1 and len(values)")
    out: List[float] = []
    # Simple but not the most efficient: recompute the slice sum each step.
    for i in range(window_size, len(values) + 1):
        w = values[i - window_size:i]
        out.append(sum(w) / float(window_size))
    return out


def median_filter(values: List[float], window_size: int) -> List[float]:
    """Naive trailing median filter (demonstration only)."""
    if window_size < 1 or window_size > len(values):
        raise ValueError("window_size must be between 1 and len(values)")
    out: List[float] = []
    for i in range(window_size, len(values) + 1):
        w = sorted(values[i - window_size:i])
        mid = window_size // 2
        if window_size % 2:
            out.append(float(w[mid]))
        else:
            out.append((w[mid - 1] + w[mid]) / 2.0)
    return out
