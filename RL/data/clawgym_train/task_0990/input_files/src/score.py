import argparse
import json
import os
from typing import Dict, Any, List, Tuple

# Scoring utilities

def compute_total(responses: Dict[str, Any], weights: Dict[str, float]) -> float:
    total = 0.0
    for q, w in weights.items():
        v = responses.get(q, "skip")
        if v is None:
            v = "skip"
        if isinstance(v, (int, float)):
            total += float(v) * float(w)
        elif isinstance(v, str) and v.strip().lower() == "skip":
            total += 0.0
        else:
            # If an unexpected type/string appears, treat as 0 to avoid penalizing.
            total += 0.0
    return total


def load_weights(path: str) -> Dict[str, float]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    weights = data.get("weights")
    if not isinstance(weights, dict):
        raise ValueError("weights.json must contain an object under key 'weights'")
    # Ensure float conversion
    return {str(k): float(v) for k, v in weights.items()}


def load_jsonl(path: str) -> List[Dict[str, Any]]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def score_records(weights_path: str, input_path: str) -> Tuple[List[Dict[str, Any]], float]:
    weights = load_weights(weights_path)
    raw = load_jsonl(input_path)
    out_records = []
    for r in raw:
        rid = r.get("id")
        responses = r.get("responses", {})
        total = compute_total(responses, weights)
        out_records.append({"id": rid, "total": total})
    avg = sum([r["total"] for r in out_records]) / float(len(out_records)) if out_records else 0.0
    return out_records, avg


def main():
    parser = argparse.ArgumentParser(description="Score questionnaire responses.")
    parser.add_argument("--weights", required=True, help="Path to weights JSON (with key 'weights')")
    parser.add_argument("--input", required=True, help="Path to JSONL responses")
    parser.add_argument("--out", required=True, help="Path to write results JSON")
    args = parser.parse_args()

    records, avg = score_records(args.weights, args.input)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"records": records, "average_total": avg}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
