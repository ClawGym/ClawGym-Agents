import os
import pandas as pd
import yaml


def load_config(path: str = "config/pipeline.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)


def run(cfg: dict):
    input_path = cfg.get("input_path", "input/data/sales_small.csv")
    output_path = cfg.get("output_path", "outputs/region_metrics.csv")
    # v1: simple, single DataFrame approach
    df = pd.read_csv(input_path)
    df["revenue"] = df["units"] * df["price"]
    agg = (
        df.groupby("region", as_index=False)
          .agg(sum_units=("units", "sum"), sum_revenue=("revenue", "sum"))
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    agg.to_csv(output_path, index=False)


if __name__ == "__main__":
    cfg = load_config()
    run(cfg)
