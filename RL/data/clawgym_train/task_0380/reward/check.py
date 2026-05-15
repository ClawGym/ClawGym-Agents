import json
import re
import sys
import csv
import importlib.util
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List


def read_text_safe(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(p: Path) -> Tuple[bool, Optional[Dict[str, Any]]]:
    try:
        text = p.read_text(encoding="utf-8")
        return True, json.loads(text)
    except Exception:
        return False, None


def parse_pytest_summary(text: str) -> Dict[str, int]:
    # Initialize counts
    counts = {"passed": 0, "failed": 0, "xfailed": 0}
    # Try to find the last summary line that includes counts
    lines = [ln.strip() for ln in text.splitlines()]
    summary_line = None
    for ln in reversed(lines):
        if ("passed" in ln or "failed" in ln or "xfailed" in ln) and re.search(r"\d", ln):
            summary_line = ln
            break
    if summary_line:
        for key in ["passed", "failed", "xfailed"]:
            m = re.search(rf"(\d+)\s+{key}\b", summary_line)
            if m:
                counts[key] = int(m.group(1))
    else:
        # Fallback: search entire text for the last occurrence of each
        for key in ["passed", "failed", "xfailed"]:
            matches = list(re.finditer(rf"(\d+)\s+{key}\b", text))
            if matches:
                counts[key] = int(matches[-1].group(1))
    total = counts["passed"] + counts["failed"] + counts["xfailed"]
    counts["total"] = total
    return counts


def import_module_from_file(module_name: str, file_path: Path):
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(file_path))
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[attr-defined]
            return module
        return None
    except Exception:
        return None


def _round_float(val: float, ndigits: int = 4) -> float:
    try:
        return round(float(val), ndigits)
    except Exception:
        return val  # best effort


def round_floats_in_obj(obj: Any, ndigits: int = 4) -> Any:
    if isinstance(obj, dict):
        return {k: round_floats_in_obj(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [round_floats_in_obj(v, ndigits) for v in obj]
    if isinstance(obj, float):
        return _round_float(obj, ndigits)
    return obj


def safe_load_reviews(csv_path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        rows: List[Dict[str, Any]] = []
        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append({
                    "product_id": r["product_id"],
                    "rating": float(r["rating"]),
                    "defects_reported": int(r["defects_reported"]),
                    "refunds": int(r["refunds"]),
                    "is_premium": str(r["is_premium"]).strip().lower() in {"1", "true", "yes", "y", "t"},
                })
        return rows
    except Exception:
        return None


def compute_expected_aggregates(workspace: Path) -> Optional[Dict[str, Any]]:
    src_path = workspace / "src" / "product_quality.py"
    data_path = workspace / "input" / "reviews.csv"
    if not data_path.exists():
        return None

    module = import_module_from_file("product_quality", src_path) if src_path.exists() else None

    # Load rows
    rows: Optional[List[Dict[str, Any]]] = None
    if module and hasattr(module, "load_reviews"):
        try:
            rows = module.load_reviews(str(data_path))
        except Exception:
            rows = None
    if rows is None:
        rows = safe_load_reviews(data_path)
    if rows is None or len(rows) == 0:
        return None

    # Compute per_product_avg_rating
    if module and hasattr(module, "avg_rating_per_product"):
        try:
            per_prod_avg_rating = module.avg_rating_per_product(rows)
        except Exception:
            per_prod_avg_rating = None
    else:
        per_prod_avg_rating = None
    if per_prod_avg_rating is None:
        sums: Dict[str, float] = {}
        counts: Dict[str, int] = {}
        for r in rows:
            pid = r["product_id"]
            sums[pid] = sums.get(pid, 0.0) + float(r["rating"])
            counts[pid] = counts.get(pid, 0) + 1
        per_prod_avg_rating = {pid: sums[pid] / counts[pid] for pid in sums}

    # overall average rating
    total_rating = sum(float(r["rating"]) for r in rows)
    overall_avg_rating = total_rating / float(len(rows)) if rows else 0.0

    # premium share
    premium_count = sum(1 for r in rows if bool(r.get("is_premium", False)))
    premium_share = (premium_count / float(len(rows))) if rows else 0.0

    # per product avg quality score using current implementation (premium bonus +5 per provided code)
    if module and hasattr(module, "avg_quality_per_product"):
        try:
            per_prod_avg_quality = module.avg_quality_per_product(rows)
        except Exception:
            per_prod_avg_quality = None
    else:
        per_prod_avg_quality = None
    if per_prod_avg_quality is None:
        # Fallback: implement using the described current implementation
        def quality_score_fallback(row: Dict[str, Any]) -> float:
            base = float(row["rating"]) * 20.0
            penalty = 5.0 * float(row["defects_reported"]) + 10.0 * float(row["refunds"])
            premium_bonus = 5.0 if bool(row.get("is_premium", False)) else 0.0
            return base - penalty + premium_bonus

        sums_q: Dict[str, float] = {}
        counts_q: Dict[str, int] = {}
        for r in rows:
            pid = r["product_id"]
            qs = quality_score_fallback(r)
            sums_q[pid] = sums_q.get(pid, 0.0) + qs
            counts_q[pid] = counts_q.get(pid, 0) + 1
        per_prod_avg_quality = {pid: (sums_q[pid] / counts_q[pid]) for pid in sums_q}

    # Determine top product by quality
    top_pid = None
    top_val = None
    for pid, val in per_prod_avg_quality.items():
        if top_val is None or val > top_val or (val == top_val and (top_pid is None or pid < top_pid)):
            top_pid = pid
            top_val = val

    result = {
        "per_product_avg_rating": per_prod_avg_rating,
        "overall_avg_rating": overall_avg_rating,
        "premium_share": premium_share,
        "per_product_avg_quality_score": per_prod_avg_quality,
        "top_product_by_quality": {
            "product_id": top_pid if top_pid is not None else "",
            "avg_quality_score": top_val if top_val is not None else 0.0,
        },
    }
    # Round floats to 4 decimals
    return round_floats_in_obj(result, 4)


def compare_aggregates(expected: Dict[str, Any], actual: Dict[str, Any]) -> bool:
    # Compare after rounding both to 4 decimals, with strict equality of structure and values for keys of interest
    def normalize(d: Dict[str, Any]) -> Dict[str, Any]:
        out = {}
        out["per_product_avg_rating"] = d.get("per_product_avg_rating", {})
        out["overall_avg_rating"] = d.get("overall_avg_rating")
        out["premium_share"] = d.get("premium_share")
        out["per_product_avg_quality_score"] = d.get("per_product_avg_quality_score", {})
        out["top_product_by_quality"] = d.get("top_product_by_quality", {})
        return round_floats_in_obj(out, 4)

    e = normalize(expected)
    a = normalize(actual)
    return e == a


def check_top_product_consistency(agg: Dict[str, Any]) -> bool:
    try:
        per_prod = agg["per_product_avg_quality_score"]
        top = agg["top_product_by_quality"]
        if not isinstance(per_prod, dict) or not isinstance(top, dict):
            return False
        top_pid = top.get("product_id")
        top_val = float(top.get("avg_quality_score"))
        # Find max
        max_pid = None
        max_val = None
        for pid, val in per_prod.items():
            v = float(val)
            if max_val is None or v > max_val or (v == max_val and (max_pid is None or pid < max_pid)):
                max_pid = pid
                max_val = v
        if max_pid is None:
            return False
        # Compare with 4-decimal rounding
        return (top_pid == max_pid) and (_round_float(top_val, 4) == _round_float(max_val, 4))
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "tests_file_exists": 0.0,
        "tests_cover_avg_rating_with_reviews": 0.0,
        "tests_cover_non_premium_quality": 0.0,
        "tests_have_xfail_premium_bonus": 0.0,
        "test_results_output_present": 0.0,
        "test_summary_json_present": 0.0,
        "test_summary_counts_match_output": 0.0,
        "expected_test_outcome": 0.0,
        "aggregates_output_present": 0.0,
        "aggregates_values_correct": 0.0,
        "aggregates_top_product_consistent": 0.0,
    }

    # Check tests file existence and content
    tests_path = workspace / "tests" / "test_quality.py"
    tests_text = read_text_safe(tests_path)
    if tests_text is not None:
        scores["tests_file_exists"] = 1.0
        # avg_rating_per_product using input/reviews.csv and approximate
        if ("avg_rating_per_product" in tests_text) and ("input/reviews.csv" in tests_text) and ("approx" in tests_text):
            scores["tests_cover_avg_rating_with_reviews"] = 1.0
        # non-premium quality_score case expecting 75.0 with is_premium False
        tt_lower = tests_text.lower()
        if ("quality_score" in tests_text and "75.0" in tests_text
                and "is_premium" in tests_text and ("false" in tt_lower or "False" in tests_text)):
            scores["tests_cover_non_premium_quality"] = 1.0
        # xfail premium bonus mismatch
        if (("xfail" in tt_lower or "pytest.mark.xfail" in tests_text)
                and ("premium" in tt_lower)
                and ("quality_score" in tests_text)):
            scores["tests_have_xfail_premium_bonus"] = 1.0

    # Check test results and summary JSON
    results_path = workspace / "reports" / "test_results.txt"
    results_text = read_text_safe(results_path)
    parsed_counts: Optional[Dict[str, int]] = None
    if results_text:
        scores["test_results_output_present"] = 1.0
        parsed_counts = parse_pytest_summary(results_text)

    summary_path = workspace / "outputs" / "test_summary.json"
    ok_json, summary_json = load_json_safe(summary_path)
    if ok_json and isinstance(summary_json, dict):
        # Validate required fields
        required_fields = {"passed", "xfailed", "failed", "total", "pass_rate"}
        if required_fields.issubset(set(summary_json.keys())):
            scores["test_summary_json_present"] = 1.0

    # Compare counts with parsed results
    if parsed_counts is not None and summary_json is not None:
        try:
            passed = int(summary_json["passed"])
            failed = int(summary_json["failed"])
            xfailed = int(summary_json["xfailed"])
            total = int(summary_json["total"])
            pr = float(summary_json["pass_rate"])
            # Compute expected pass_rate and total
            denom = passed + failed
            expected_pr = round((passed / denom) if denom > 0 else 0.0, 4)
            expected_total = passed + failed + xfailed
            counts_match = (
                passed == parsed_counts.get("passed", -1)
                and failed == parsed_counts.get("failed", -1)
                and xfailed == parsed_counts.get("xfailed", -1)
                and total == expected_total
                and pr == expected_pr
            )
            if counts_match:
                scores["test_summary_counts_match_output"] = 1.0
            # Expected outcome: exactly one xfailed, zero failed, at least two passed
            if (parsed_counts.get("xfailed", 0) == 1
                    and parsed_counts.get("failed", 0) == 0
                    and parsed_counts.get("passed", 0) >= 2):
                scores["expected_test_outcome"] = 1.0
        except Exception:
            pass

    # Aggregates check
    aggregates_path = workspace / "outputs" / "aggregates.json"
    ok_agg_json, agg_json = load_json_safe(aggregates_path)
    if ok_agg_json and isinstance(agg_json, dict):
        scores["aggregates_output_present"] = 1.0

    expected_aggregates = compute_expected_aggregates(workspace)
    if expected_aggregates is not None and agg_json is not None:
        # Compare expected vs actual
        if compare_aggregates(expected_aggregates, agg_json):
            scores["aggregates_values_correct"] = 1.0
        # Internal consistency check on provided aggregates JSON
        if check_top_product_consistency(agg_json):
            scores["aggregates_top_product_consistent"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()