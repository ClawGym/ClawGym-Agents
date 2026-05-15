import json
from pathlib import Path

TIMEOUT_SEC = 2  # TODO: read from config/settings.json instead of hardcoding
INPUT_PATH = "data/sample.json"  # TODO: read from config/settings.json


def read_json(path):
    # TODO: consolidate JSON loading with helpers.load_json_file
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def process(records):
    # TODO: add error handling for empty list
    return [r["name"].upper() for r in records]


def main():
    records = read_json(INPUT_PATH)
    names = process(records)
    # NICE-TO-HAVE: make the record limit configurable
    limit = 2
    print(f"Processed {len(names[:limit])} of {len(names)} records with timeout={TIMEOUT_SEC}")


if __name__ == "__main__":
    main()
