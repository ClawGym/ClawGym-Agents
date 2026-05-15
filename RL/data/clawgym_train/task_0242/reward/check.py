import json
import csv
import math
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _count_all_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def _load_weights(path: Path) -> Dict[str, float]:
    weights: Dict[str, float] = {}
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cat = (row.get("category") or "").strip()
                w_str = (row.get("weight") or "").strip()
                if not cat:
                    continue
                try:
                    w = float(w_str)
                except Exception:
                    continue
                weights[cat] = w
    except Exception:
        return {}
    return weights


def _parse_jsonl(path: Path) -> List[dict]:
    records: List[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    # keep empty line for line count but skip parsing
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                records.append(obj)
    except Exception:
        return []
    return records


def _to_float(val) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def _to_int(val) -> Optional[int]:
    try:
        return int(val)
    except Exception:
        return None


def _filter_and_score(records: List[dict], weights: Dict[str, float]) -> List[dict]:
    kept: List[dict] = []
    for r in records:
        price = _to_float(r.get("price"))
        if price is None:
            continue
        if not (5.0 <= price <= 100.0):
            continue
        cat = r.get("category")
        if cat not in weights:
            continue
        rating = _to_float(r.get("rating"))
        if rating is None:
            continue
        reviews = _to_int(r.get("reviews_count"))
        if reviews is None or reviews < 0:
            reviews = 0
        w = weights[cat]
        weighted_score = rating * w * math.log1p(reviews)
        kept.append({
            "id": r.get("id", ""),
            "name": r.get("name", ""),
            "category": cat,
            "price": price,
            "rating": rating,
            "reviews_count": reviews,
            "weighted_score": weighted_score,
        })
    return kept


def _sort_records(recs: List[dict]) -> List[dict]:
    return sorted(recs, key=lambda x: (-x["weighted_score"], -x["reviews_count"], x["price"]))


def _read_top10_csv(path: Path) -> Tuple[List[str], List[dict]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = [row for row in reader]
            return headers, rows
    except Exception:
        return [], []


def _load_summary_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _float_close(a: float, b: float, atol: float = 1e-9, rtol: float = 1e-9) -> bool:
    return abs(a - b) <= max(atol, rtol * max(abs(a), abs(b)))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "top10_order_and_ids_correct": 0.0,
        "top10_weighted_scores_correct": 0.0,
        "summary_totals_correct": 0.0,
        "summary_categories_correct": 0.0,
    }

    products_path = workspace / "input" / "products.jsonl"
    weights_path = workspace / "input" / "weights.csv"
    script_path = workspace / "scripts" / "process_data.py"

    # Gate on required inputs existing to avoid awarding points in empty workspaces
    if not (products_path.exists() and weights_path.exists() and script_path.exists()):
        return scores

    # Compute expected results
    total_lines = _count_all_lines(products_path)
    weights = _load_weights(weights_path)
    products = _parse_jsonl(products_path)
    filtered_scored = _filter_and_score(products, weights)
    filtered_sorted = _sort_records(filtered_scored)
    expected_top_n = 10
    expected_top = filtered_sorted[:expected_top_n]
    expected_filtered_count = len(filtered_scored)
    expected_counts_by_category: Dict[str, int] = {}
    for r in filtered_scored:
        c = r["category"]
        expected_counts_by_category[c] = expected_counts_by_category.get(c, 0) + 1
    expected_categories_included = sorted(expected_counts_by_category.keys())

    # Run the user's CLI in a temporary outdir
    produced_headers: List[str] = []
    produced_rows: List[dict] = []
    summary_obj: Optional[dict] = None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            outdir = Path(tmpdir)
            cmd = [
                sys.executable,
                str(script_path),
                "--products",
                str(products_path),
                "--weights",
                str(weights_path),
                "--outdir",
                str(outdir),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                top10_path = outdir / "top10.csv"
                summary_path = outdir / "summary.json"
                if top10_path.exists():
                    produced_headers, produced_rows = _read_top10_csv(top10_path)
                if summary_path.exists():
                    summary_obj = _load_summary_json(summary_path)
    except Exception:
        # If execution fails, all scores remain 0.0
        return scores

    # Only evaluate if outputs exist and inputs existed
    if not produced_rows or expected_filtered_count == 0:
        # No rows to compare; keep zero scores
        pass
    else:
        # Order and IDs check
        produced_ids = [row.get("id", "") for row in produced_rows]
        expected_ids = [r["id"] for r in expected_top]
        if produced_ids == expected_ids:
            scores["top10_order_and_ids_correct"] = 1.0

        # Weighted scores check only if IDs/order match to avoid partial credit
        if scores["top10_order_and_ids_correct"] == 1.0:
            all_match = True
            for row, exp in zip(produced_rows, expected_top):
                ws_str = row.get("weighted_score", "")
                try:
                    ws_val = float(ws_str)
                except Exception:
                    all_match = False
                    break
                if not _float_close(ws_val, exp["weighted_score"]):
                    all_match = False
                    break
            if all_match:
                scores["top10_weighted_scores_correct"] = 1.0

    # Summary checks
    if summary_obj and isinstance(summary_obj, dict) and expected_filtered_count >= 0:
        # totals
        tri = summary_obj.get("total_records_input", None)
        trf = summary_obj.get("total_records_filtered", None)
        if isinstance(tri, int) and isinstance(trf, int):
            if tri == total_lines and trf == expected_filtered_count:
                scores["summary_totals_correct"] = 1.0
        # categories
        cats = summary_obj.get("counts_by_category")
        incl = summary_obj.get("categories_included")
        cats_ok = isinstance(cats, dict) and cats == expected_counts_by_category
        incl_ok = isinstance(incl, list) and incl == expected_categories_included
        if cats_ok and incl_ok:
            scores["summary_categories_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()