"""
Prototype scorer for antidepressant/antipsychotic candidates.

Scoring formula (do not edit for this task):
score = 100 * (EFFICACY_WEIGHT * efficacy_metric + TOLERABILITY_WEIGHT * tolerability_metric)

Where:
- efficacy_metric is a 0..1 value (e.g., effect_size_g clipped to [0,1])
- tolerability_metric is a 0..1 value (e.g., 1 - average AE rate)

Tie-breakers (when scores equal): lower cost_per_month_usd first, then medication name A->Z.
"""

EFFICACY_WEIGHT = 0.65
TOLERABILITY_WEIGHT = 0.35

def compute_score(efficacy_metric: float, tolerability_metric: float) -> float:
    return 100.0 * (EFFICACY_WEIGHT * efficacy_metric + TOLERABILITY_WEIGHT * tolerability_metric)

if __name__ == "__main__":
    print(f"Weights: efficacy={EFFICACY_WEIGHT}, tolerability={TOLERABILITY_WEIGHT}")
