import json
from typing import Dict, List


def load_config(path: str = "config/terms.json") -> Dict:
    """Load JSON config with keys: violent_terms (list[str]), exceptions (list[str]), threshold (int)."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _count_matches(text: str, terms: List[str]) -> int:
    t = text.lower()
    return sum(1 for term in terms if term.lower() in t)


def classify_text(text: str, cfg: Dict) -> bool:
    """Return True if text should be flagged (violent), else False.

    Logic: count unique occurrences of any violent_terms present in the text (substring match).
    If exceptions are present, reduce the count by the number of exception terms present (not below 0).
    Flag if adjusted count >= threshold.
    """
    violent_terms = cfg.get("violent_terms", [])
    exceptions = cfg.get("exceptions", [])
    try:
        threshold = int(cfg.get("threshold", 1))
    except Exception:
        threshold = 1

    hits = _count_matches(text, violent_terms)
    if exceptions:
        ex_hits = _count_matches(text, exceptions)
        hits = max(0, hits - ex_hits)
    return hits >= threshold


if __name__ == "__main__":
    cfg = load_config()
    example = "Sharing hotline and shelter resources for anyone facing abuse; you are not alone."
    print("Example flagged:", classify_text(example, cfg))
