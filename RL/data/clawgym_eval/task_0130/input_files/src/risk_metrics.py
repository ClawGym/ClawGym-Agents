#!/usr/bin/env python3
import os
import json
import yaml

# You may add additional imports as needed (e.g., pandas, numpy)

def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def main():
    cfg_path = os.path.join("config", "config.yaml")
    cfg = load_config(cfg_path)
    # Implement the pipeline:
    # - Load CSV at cfg["csv_path"]
    # - Parse dates and filter between cfg["start_date"] and cfg["end_date"]
    # - Compute daily percentage returns from the value series
    # - Compute left-tail VaR and CVaR at cfg["var_level"]
    # - Save processed CSV and metrics JSON under cfg["output_dir"] as required
    raise NotImplementedError("Implement data load, filtering, return calc, VaR/CVaR, and outputs per task requirements.")

if __name__ == "__main__":
    main()
