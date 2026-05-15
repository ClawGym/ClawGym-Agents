import math
import re

# Constants and scoring parameters
LENGTH_NORM = 120
LENGTH_BONUS_COEFF = 0.2
CAP = 5

# Marker vocabularies per category (all matching is case-insensitive)
MARKERS = {
    "evidence": {"evidence", "data", "study", "source", "sources", "cite", "cited"},
    "coherence": {"because", "therefore", "however", "but", "hence", "thus", "so", "although", "despite"},
    "nuance": {"depends", "context", "nuance", "trade-off", "tradeoff", "complex", "ambiguous", "uncertain", "uncertainty"},
    "originality": {"novel", "original", "unexpected", "fresh", "insight", "insightful", "new"},
}


def feature_counts(text: str):
    """
    Returns (tokens_count, counts_dict) where counts_dict has keys:
    evidence, coherence, nuance, originality.
    Matching is case-insensitive.
    Marker occurrence is counted by exact token match.
    """
    lower = text.lower()
    tokens = re.findall(r"\b[\w'-]+\b", lower)
    counts = {k: 0 for k in MARKERS.keys()}
    for tok in tokens:
        for cat, vocab in MARKERS.items():
            if tok in vocab:
                counts[cat] += 1
    return len(tokens), counts


def capped_counts(counts: dict) -> dict:
    return {k: min(v, CAP) for k, v in counts.items()}


def weighted_sum(counts: dict, weights: dict) -> float:
    # weights keys expected: evidence, coherence, nuance, originality
    s = 0.0
    for k, v in counts.items():
        s += weights.get(k, 0.0) * v
    return s


def compute_score(answer_text: str, weights: dict) -> float:
    """
    Compute analytic depth score:
      1) tokens, raw_counts = feature_counts(answer_text)
      2) apply cap per category: min(count, CAP)
      3) S = sum_k weights[k] * capped_counts[k]
      4) length_bonus = log(1 + tokens) / log(1 + LENGTH_NORM)
      5) final = S * (1 + LENGTH_BONUS_COEFF * length_bonus)
    Returns float score (no rounding).
    """
    tokens, raw_counts = feature_counts(answer_text)
    cc = capped_counts(raw_counts)
    S = weighted_sum(cc, weights)
    length_bonus = math.log(1.0 + tokens) / math.log(1.0 + LENGTH_NORM)
    final = S * (1.0 + LENGTH_BONUS_COEFF * length_bonus)
    return final


if __name__ == "__main__":
    demo = "Because evidence and data matter, however context and new ideas help."
    w = {"evidence": 0.4, "coherence": 0.3, "nuance": 0.2, "originality": 0.1}
    print(round(compute_score(demo, w), 6))
