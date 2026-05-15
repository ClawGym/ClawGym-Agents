import json


def load_json_file(path):
    # Duplicate of main.read_json; TODO: deduplicate
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def count_records(records):
    # TODO: optimize if records is large
    return len(records)
