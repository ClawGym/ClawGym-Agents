import argparse
import os
import sys

REQUIRED_KEYS = ["APP_NAME", "DATA_PATH"]

def parse_env_file(path):
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                # allow non key-value lines to be ignored
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env

def main():
    parser = argparse.ArgumentParser(description="Check required env values for tongan-trends demo")
    parser.add_argument("--env-file", required=True, help="Path to .env-like file with KEY=VALUE lines")
    args = parser.parse_args()

    env_path = args.env_file
    if not os.path.exists(env_path):
        print(f"ERROR: env file not found at {env_path}")
        sys.exit(2)

    env = parse_env_file(env_path)
    missing = [k for k in REQUIRED_KEYS if k not in env or not str(env[k]).strip()]
    if missing:
        print(f"ERROR: Missing keys: {', '.join(missing)}; Expected keys: {', '.join(REQUIRED_KEYS)}")
        sys.exit(1)

    data_path = env["DATA_PATH"]
    if not os.path.exists(data_path):
        print(f"ERROR: DATA_PATH path does not exist: {data_path}")
        sys.exit(1)
    if not data_path.lower().endswith(".csv"):
        print(f"ERROR: DATA_PATH is not a .csv file: {data_path}")
        sys.exit(1)

    app_name = env["APP_NAME"]
    print(f"OK: APP_NAME={app_name}, DATA_PATH={data_path} (exists)")
    print("READY")

if __name__ == "__main__":
    main()
