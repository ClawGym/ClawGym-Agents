import os
import json
import pandas as pd

INPUT_PATH = "data/farm_practices.csv"  # NOTE: may be wrong
OUTPUT_DIR = "output"


def compute_wue(df: pd.DataFrame) -> pd.DataFrame:
    # Compute water use efficiency (WUE)
    df = df.copy()
    # Intentionally using a possibly wrong column name here:
    df["water_use_efficiency"] = df["yield_kg_ha"] / df["water_used_mm"]
    return df


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    # Average WUE per region and method
    # Uses np.mean but numpy may not be imported
    grouped = df.groupby(["region", "method"]).agg({"water_use_efficiency": np.mean}).reset_index()
    pivot = grouped.pivot(index="region", columns="method", values="water_use_efficiency")
    pivot = pivot.rename_axis(None, axis=1).reset_index()
    return pivot


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load data
    df = pd.read_csv(INPUT_PATH)

    # Compute WUE and summarize
    df = compute_wue(df)
    pivot = summarize(df)

    # Overall average WUE
    overall = df["water_use_efficiency"].mean()

    # Build region-level results
    results = []
    for _, row in pivot.iterrows():
        region = row["region"]
        base = row.get("conventional", None)
        improved = row.get("mulch_drip", None)
        pct = ((improved - base) / base) * 100 if pd.notnull(base) and pd.notnull(improved) and base != 0 else None
        results.append({
            "region": region,
            "baseline": base,
            "improved": improved,
            "percent_improvement": pct
        })

    # Write summary JSON
    summary = {
        "overall_avg_wue": overall,
        "improvement_by_region": results
    }
    with open(os.path.join(OUTPUT_DIR, "summary.json"), "w") as f:
        json.dump(summary, f)

    # Write recommendations CSV
    recs = []
    for r in results:
        if r["percent_improvement"] is not None and r["percent_improvement"] > 0:
            recs.append({
                "region": r["region"],
                "recommended_method": "mulch_drip",
                "expected_wue_gain_pct": r["percent_improvement"]
            })
        else:
            recs.append({
                "region": r["region"],
                "recommended_method": "conventional",
                "expected_wue_gain_pct": 0
            })
    pd.DataFrame(recs).to_csv(os.path.join(OUTPUT_DIR, "recommendations.csv"), index=False)


if __name__ == "__main__":
    main()
