import yaml

def load_config(path):
    with open(path) as f:
        cfg = yaml.safe_load(f)
    # wastage_percent should be an integer percent (e.g., 10 for 10%)
    wastage_fraction = cfg.get("wastage_percent", 0) / 100.0
    rounding = cfg.get("rounding", "ceil")
    return wastage_fraction, rounding

if __name__ == "__main__":
    wf, r = load_config("config.yaml")
    print(f"Wastage fraction={wf}, rounding={r}")
