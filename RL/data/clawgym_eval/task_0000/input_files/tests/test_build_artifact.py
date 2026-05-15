import json
import os
from tools.summarize import compute_summary

def test_summary_artifact_matches_computation():
    path = os.path.join("build", "summary.json")
    assert os.path.exists(path), "Expected build/summary.json to exist. Run the summarizer first."
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    expected = compute_summary("data/tasks.csv")
    assert data == expected, "build/summary.json does not match computed summary from data/tasks.csv"
