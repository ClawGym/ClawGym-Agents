from typing import Optional

def compute_tss(duration_min: float, avg_power: float, ftp: float) -> float:
    """
    Compute simple Training Stress Score (TSS).
    TSS = duration_hours * (intensity_factor^2) * 100
    intensity_factor = avg_power / ftp
    """
    if duration_min < 0 or avg_power < 0 or ftp <= 0:
        raise ValueError("Invalid inputs")
    hours = duration_min / 60.0
    intensity = avg_power / ftp
    return hours * (intensity ** 2) * 100.0

if __name__ == "__main__":
    # Simple placeholder main to avoid breaking existing Docker CMD
    print("metrics module")
