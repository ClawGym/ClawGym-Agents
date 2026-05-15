from pathlib import Path
import sys
import pandas as pd


def main():
    script_dir = Path(__file__).resolve().parent
    root = script_dir.parent.parent
    data_path = root / "input" / "data" / "formulations.csv"
    out_path = root / "output" / "formulation_summary.csv"

    if not data_path.exists():
        print(f"Input CSV not found: {data_path}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(data_path)
    required_cols = {"Product", "Ingredient", "BatchSizeKg", "CostPerKg"}
    missing = required_cols - set(df.columns)
    if missing:
        print(f"Missing required columns: {sorted(missing)}", file=sys.stderr)
        sys.exit(2)

    # Ensure numeric types
    df["BatchSizeKg"] = pd.to_numeric(df["BatchSizeKg"], errors="coerce").fillna(0.0)
    df["CostPerKg"] = pd.to_numeric(df["CostPerKg"], errors="coerce").fillna(0.0)

    df["_weighted_cost"] = df["BatchSizeKg"] * df["CostPerKg"]

    grouped = df.groupby("Product").agg(
        total_batch_kg=("BatchSizeKg", "sum"),
        total_weighted_cost=("_weighted_cost", "sum"),
        num_ingredients=("Ingredient", "nunique"),
    ).reset_index()

    # Weighted average cost per kg
    grouped["avg_cost_per_kg"] = grouped.apply(
        lambda r: (r["total_weighted_cost"] / r["total_batch_kg"]) if r["total_batch_kg"] else 0.0,
        axis=1,
    )

    grouped = grouped.drop(columns=["total_weighted_cost"]).sort_values("Product").reset_index(drop=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    grouped.to_csv(out_path, index=False)
    print(f"Wrote summary to {out_path} with {len(grouped)} rows.")


if __name__ == "__main__":
    main()
