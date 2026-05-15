import os
import csv
import json
from pathlib import Path

# This script is intentionally incomplete. You are expected to modify it to:
# 1) Read config/weights.json and input/supplements.csv
# 2) Normalize numeric fields using min-max (or the method in config)
# 3) Compute a risk_score per supplement using weights and penalties
# 4) Sort with tie-breakers from config and write outputs:
#    - outputs/ranked_supplements.csv (full ranked list)
#    - outputs/high_risk_top10.csv (top 10 only)
#    - outputs/top5_summary.md (concise rationale/weights summary)
# Keep it self-contained (standard library only).

DATA_PATH = Path("input/supplements.csv")
CONFIG_PATH = Path("config/weights.json")
OUT_DIR = Path("outputs")
RANKED_CSV = OUT_DIR / "ranked_supplements.csv"
TOP10_CSV = OUT_DIR / "high_risk_top10.csv"
SUMMARY_MD = OUT_DIR / "top5_summary.md"

NUM_KEYS = ["adverse_event_reports", "interactions_count", "service_member_incidents"]


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_records(path: Path) -> list:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            # Cast numeric/flag fields to int for consistency
            for k in ["adverse_event_reports", "interactions_count", "service_member_incidents", "banned_substances_flag", "quality_seal_flag"]:
                r[k] = int(r[k])
            rows.append(r)
    return rows


def minmax_params(records: list, keys: list) -> dict:
    params = {}
    for k in keys:
        vals = [int(r[k]) for r in records]
        mn = min(vals)
        mx = max(vals)
        params[k] = (mn, mx)
    return params


def normalize(value: float, mn: float, mx: float) -> float:
    # If all values equal, return 0.0 per requirement
    if mx == mn:
        return 0.0
    x = (value - mn) / (mx - mn)
    # Clip to [0,1]
    if x < 0.0:
        x = 0.0
    elif x > 1.0:
        x = 1.0
    return x


def compute_risk_score(rec: dict, params: dict, cfg: dict) -> float:
    """
    TODO: Implement the scoring model described in the request.
    Current placeholder returns 0.0 for all rows and does NOT reflect risk.
    """
    # Example skeleton for your implementation:
    # ae = normalize(rec["adverse_event_reports"], *params["adverse_event_reports"]) 
    # inter = normalize(rec["interactions_count"], *params["interactions_count"]) 
    # inc = normalize(rec["service_member_incidents"], *params["service_member_incidents"]) 
    # w = cfg["weights"]
    # ev_pen = cfg["evidence_penalty"].get(rec["evidence_level"], 0.0)
    # score = (
    #    w["adverse_event_reports"] * ae +
    #    w["interactions_count"] * inter +
    #    w["service_member_incidents"] * inc +
    #    w["banned_substances_flag"] * rec["banned_substances_flag"] +
    #    ev_pen +
    #    w["quality_seal_bonus"] * rec["quality_seal_flag"]
    # )
    # return float(score)
    return 0.0


def sort_key(rec: dict, cfg: dict):
    # Default placeholder sorts by supplement name only (incorrect per requirements).
    # You must replace this with a key that applies cfg["tie_breakers"] after risk_score.
    return rec.get("supplement", "")


def write_csv(path: Path, rows: list):
    if not rows:
        return
    fieldnames = [
        "supplement", "rank", "risk_score", "evidence_level", "banned_substances_flag",
        "quality_seal_flag", "adverse_event_reports", "interactions_count", "service_member_incidents"
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            out = {k: r.get(k, "") for k in fieldnames}
            writer.writerow(out)


def write_summary(path: Path, cfg: dict, ranked: list):
    # Minimal placeholder summary. You must replace with the report described in the request.
    lines = []
    lines.append("# Supplement Risk Ranking Summary\n\n")
    lines.append("This is a placeholder. Implement the final report with weights, method, and top 5 rationales.\n")
    with path.open("w", encoding="utf-8") as f:
        f.write("".join(lines))


def main():
    cfg = load_config(CONFIG_PATH)
    records = load_records(DATA_PATH)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Compute normalization params
    params = minmax_params(records, NUM_KEYS)

    # Compute risk scores (currently all zeros)
    for r in records:
        r["risk_score"] = compute_risk_score(r, params, cfg)

    # Sort incorrectly by supplement name (you must replace with risk desc + tie-breakers)
    records_sorted = sorted(records, key=lambda r: sort_key(r, cfg))

    # Assign ranks based on current sort (not correct until you implement proper sorting)
    for i, r in enumerate(records_sorted, start=1):
        r["rank"] = i
        # Round risk_score for output display
        try:
            r["risk_score"] = round(float(r["risk_score"]), 3)
        except Exception:
            r["risk_score"] = 0.0

    # Write full and top10 CSVs
    write_csv(RANKED_CSV, records_sorted)
    write_csv(TOP10_CSV, records_sorted[:10])

    # Write summary placeholder
    write_summary(SUMMARY_MD, cfg, records_sorted)

    print(f"Wrote {RANKED_CSV} and {TOP10_CSV} and {SUMMARY_MD} (placeholders).")


if __name__ == "__main__":
    main()
