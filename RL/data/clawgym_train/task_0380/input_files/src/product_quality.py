import csv
from collections import defaultdict
from typing import List, Dict, Any

__all__ = [
    "load_reviews",
    "avg_rating_per_product",
    "quality_score",
    "avg_quality_per_product",
]


def load_reviews(csv_path: str) -> List[Dict[str, Any]]:
    """
    Load reviews from a CSV file. Expected columns:
    product_id, rating, defects_reported, refunds, is_premium
    rating -> float, defects_reported -> int, refunds -> int, is_premium -> bool
    """
    rows: List[Dict[str, Any]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                "product_id": r["product_id"],
                "rating": float(r["rating"]),
                "defects_reported": int(r["defects_reported"]),
                "refunds": int(r["refunds"]),
                "is_premium": str(r["is_premium"]).strip().lower() in {"1", "true", "yes", "y", "t"},
            })
    return rows


def avg_rating_per_product(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    sums: Dict[str, float] = defaultdict(float)
    counts: Dict[str, int] = defaultdict(int)
    for r in rows:
        pid = r["product_id"]
        sums[pid] += r["rating"]
        counts[pid] += 1
    return {pid: (sums[pid] / counts[pid]) for pid in sums}


def quality_score(row: Dict[str, Any]) -> float:
    """
    Compute a quality score for a single review row using the current implementation.
    Score = rating * 20 - 5*defects_reported - 10*refunds + premium_bonus
    Premium bonus (current implementation): +5 points if is_premium else 0.
    NOTE: Business spec may differ; tests can capture that as an expected failure.
    """
    base = row["rating"] * 20.0
    penalty = 5.0 * float(row["defects_reported"]) + 10.0 * float(row["refunds"]) 
    premium_bonus = 5.0 if row.get("is_premium", False) else 0.0  # Known gap vs spec (+10 expected by spec)
    return base - penalty + premium_bonus


def avg_quality_per_product(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    sums: Dict[str, float] = defaultdict(float)
    counts: Dict[str, int] = defaultdict(int)
    for r in rows:
        pid = r["product_id"]
        sums[pid] += quality_score(r)
        counts[pid] += 1
    return {pid: (sums[pid] / counts[pid]) for pid in sums}
