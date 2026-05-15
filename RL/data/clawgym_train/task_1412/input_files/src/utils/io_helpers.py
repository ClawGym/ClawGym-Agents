import os
import json
import re
import pandas as pd


def load_measurements(path):
    """Load measurement JSONL or CSV files from a directory path.

    This is a stub to demonstrate file parsing utilities.
    """
    files = []
    for name in os.listdir(path):
        if name.endswith(".jsonl") or name.endswith(".csv"):
            files.append(os.path.join(path, name))
    return files


def save_results(path, data):
    """Save a small JSON results file to the specified path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path
