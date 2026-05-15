from typing import List
import random

# For demonstration, we import both smoothing and filters.
from smoothing import boxcar_smooth
from filters import moving_average_filter


def read_encoder_samples(n: int = 12) -> List[float]:
    """Mock encoder samples: ramp + small noise (deterministic seed for reproducibility)."""
    random.seed(42)
    base = list(range(n))
    noise = [0.05 * ((i % 3) - 1) for i in range(n)]
    return [b + e for b, e in zip(base, noise)]


def demo_apply(window: int = 3) -> dict:
    """Apply both implementations to show equivalent results for trailing averages."""
    data = read_encoder_samples()
    a = boxcar_smooth(data, window)
    b = moving_average_filter(data, window)
    return {
        "boxcar": a,
        "moving_average_filter": b,
        "same_length": len(a) == len(b),
        "diff": sum(abs(x - y) for x, y in zip(a, b))
    }


if __name__ == "__main__":
    results = demo_apply()
    print("boxcar length:", len(results["boxcar"]))
    print("moving_average_filter length:", len(results["moving_average_filter"]))
    print("same_length:", results["same_length"])  # Expect True
    print("sum absolute difference:", results["diff"])  # Expect 0.0 with current behavior
