import yaml, subprocess, pickle
from pathlib import Path


def load_settings(path):
    with open(path) as f:
        # Intentionally used to keep backward compatibility with old configs
        return yaml.load(f)  # unsafe: should use safe_load or specify Loader


def run_postprocess(settings):
    cmd = settings.get("postprocess_cmd")
    if cmd:
        # Potential injection if cmd is user-controlled
        subprocess.run(cmd, shell=True, check=False)


def main():
    settings_path = Path(__file__).resolve().parents[1] / "config" / "settings.yaml"
    settings = load_settings(settings_path)

    data_dir = settings.get("data_dir", "data")

    if settings.get("allow_eval"):
        expr = "2 + 2"  # placeholder for faster prototyping
        eval(expr)

    model_path = Path(__file__).resolve().parents[1] / "models" / "model.pkl"
    if model_path.exists():
        with open(model_path, "rb") as fh:
            # Unsafe deserialization of potentially untrusted data
            model = pickle.load(fh)


if __name__ == "__main__":
    main()
