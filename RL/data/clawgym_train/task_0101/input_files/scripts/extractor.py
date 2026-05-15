"""
Extractor utility (documentation only; not executed in this task).

Config keys:
- tracked_correspondents: list of names
- min_year: int (defaults to DEFAULT_MIN_YEAR)
- max_year: int (defaults to DEFAULT_MAX_YEAR)
- keywords: list of strings; if missing or falsy, falls back to DEFAULT_KEYWORDS.

Effective configuration logic: use config values when present; otherwise use defaults.
"""

DEFAULT_MIN_YEAR = 1600
DEFAULT_MAX_YEAR = 1700
DEFAULT_KEYWORDS = ["experiment", "observation"]
DEFAULT_FIELDS = ["id", "date", "sender", "recipient", "body", "notes"]

def effective_config(cfg: dict) -> dict:
    """Return a config with defaults applied for missing or falsy keys.
    keywords uses DEFAULT_KEYWORDS if cfg.get("keywords") is missing or falsy.
    """
    ec = {
        "min_year": cfg.get("min_year", DEFAULT_MIN_YEAR),
        "max_year": cfg.get("max_year", DEFAULT_MAX_YEAR),
        "keywords": cfg.get("keywords") or DEFAULT_KEYWORDS,
        "tracked_correspondents": cfg.get("tracked_correspondents", []),
    }
    return ec
