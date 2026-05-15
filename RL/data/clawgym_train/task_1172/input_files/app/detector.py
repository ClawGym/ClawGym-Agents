from collections import Counter
from typing import List

# Simple frequency-based suspect finder: anyone with at least `threshold` mentions.
def find_suspects(events: List[str], threshold: int) -> List[str]:
    if threshold <= 0:
        # Treat non-positive threshold as 0 (everyone qualifies)
        threshold = 0
    counts = Counter(events)
    suspects = [k for k, v in counts.items() if v >= threshold]
    return sorted(suspects)
