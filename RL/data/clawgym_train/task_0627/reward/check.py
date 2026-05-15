import json
import os
import sys
import csv
from decimal import Decimal, getcontext, InvalidOperation
from datetime import datetime
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

# Configure high precision for Decimal arithmetic
getcontext().prec = 40

def parse_iso8601(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, str) or not ts.strip():
        return None
    s = ts.strip()
    # Normalize Zulu time to +00:00 for fromisoformat
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        # Try to add timezone if missing (best-effort)
        try:
            return datetime.fromisoformat(s + "+00:00")
        except Exception:
            return None

def approx_equal(a: float, b: float, eps: float = 1e-9) -> bool:
    return abs(a - b) <= eps

def safe_float(val: Any) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        try:
            return float(str(val))
        except Exception:
            return None

def read_json(path: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def read_jsonl_lines(path: str) -> Tuple[bool, Optional[List[str]]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines()]
        return True, lines
    except Exception:
        return False, None

def load_csv_transactions(path: str) -> Tuple[bool, List[Dict[str, str]]]:
    rows: List[Dict[str, str]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # Expect columns: transaction_id,date,category,amount
            for row in reader:
                rows.append(row)
        return True, rows
    except Exception:
        return False, []

def compute_expected_metrics(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    count = 0
    sum_amt = Decimal("0")
    max_amt: Optional[Decimal] = None
    by_month: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_category: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    negative_ids: List[str] = []
    id_counter: Counter = Counter()

    for row in rows:
        tid = str(row.get("transaction_id", "")).strip()
        date_str = str(row.get("date", "")).strip()
        category = str(row.get("category", "")).strip()
        amount_str = str(row.get("amount", "")).strip()
        try:
            amt = Decimal(amount_str)
        except (InvalidOperation, ValueError):
            # Treat unparsable amount as zero to avoid crashing, but still count the row
            amt = Decimal("0")

        id_counter[tid] += 1
        count += 1
        sum_amt += amt
        if max_amt is None or amt > max_amt:
            max_amt = amt

        # Month key as YYYY-MM if possible
        month_key = date_str[:7] if len(date_str) >= 7 else ""
        if month_key:
            by_month[month_key] += amt
        by_category[category] += amt

        if amt < 0:
            negative_ids.append(tid)

    avg_amt = (sum_amt / Decimal(count)) if count > 0 else Decimal("0")
    duplicate_ids = sorted([tid for tid, c in id_counter.items() if c > 1])

    return {
        "count": count,
        "sum": sum_amt,
        "avg": avg_amt,
        "max": (max_amt if max_amt is not None else Decimal("0")),
        "by_month": dict(by_month),
        "by_category": dict(by_category),
        "negative_ids": negative_ids,
        "duplicate_ids": duplicate_ids,
    }

def decimal_to_float(d: Decimal) -> float:
    return float(d)

def compare_mapping_numbers(summary_map: Dict[str, Any], expected_map: Dict[str, Decimal], eps: float = 1e-9) -> bool:
    # Only require that each expected key exists in summary_map and matches within tolerance
    for key, dec_val in expected_map.items():
        if key not in summary_map:
            return False
        v = summary_map.get(key)
        vf = safe_float(v)
        if vf is None:
            return False
        if not approx_equal(vf, decimal_to_float(dec_val), eps):
            return False
    return True

def list_to_set_of_str(values: Any) -> Optional[set]:
    if not isinstance(values, list):
        return None
    try:
        return set(str(v) for v in values)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks: Dict[str, bool] = {
        # Start file checks
        "start_exists": False,
        "start_valid_fields": False,
        # Progress checks
        "progress_exists": False,
        "progress_min_updates": False,
        "progress_all_lines_parseable": False,
        "progress_fields_and_range_valid": False,
        "progress_strictly_increasing": False,
        # Summary structure and correctness
        "summary_exists": False,
        "summary_has_required_keys": False,
        "summary_totals_count_correct": False,
        "summary_totals_sum_correct": False,
        "summary_totals_avg_correct": False,
        "summary_totals_max_correct": False,
        "summary_by_month_correct": False,
        "summary_by_category_correct": False,
        "summary_anomalies_negative_correct": False,
        "summary_anomalies_duplicate_correct": False,
        # Done checks
        "done_exists": False,
        "done_structure_valid": False,
        "done_records_match_summary": False,
        "done_completed_after_started": False,
    }

    # Paths
    start_path = os.path.join(output_dir, "start.json")
    progress_path = os.path.join(output_dir, "progress.jsonl")
    summary_path = os.path.join(output_dir, "summary.json")
    done_path = os.path.join(output_dir, "done.json")
    input_csv_path = os.path.join(input_dir, "transactions.csv")

    # Track values across checks
    started_dt: Optional[datetime] = None
    completed_dt: Optional[datetime] = None
    summary_count: Optional[int] = None

    # 1) Start file
    ok, start_json = read_json(start_path)
    if ok and isinstance(start_json, dict):
        checks["start_exists"] = True
        status = start_json.get("status")
        description = start_json.get("description")
        started_at = start_json.get("started_at")
        started_dt = parse_iso8601(started_at)
        if (
            status == "started"
            and isinstance(description, str)
            and description.strip() != ""
            and isinstance(started_at, str)
            and started_dt is not None
        ):
            checks["start_valid_fields"] = True

    # 2) Progress stream
    ok, lines = read_jsonl_lines(progress_path)
    if ok and isinstance(lines, list):
        checks["progress_exists"] = True
        # Filter out empty lines
        json_lines: List[Dict[str, Any]] = []
        all_parseable = True
        for ln in lines:
            ln_strip = ln.strip()
            if not ln_strip:
                continue
            try:
                obj = json.loads(ln_strip)
                if isinstance(obj, dict):
                    json_lines.append(obj)
                else:
                    all_parseable = False
            except Exception:
                all_parseable = False
        if len(json_lines) >= 3:
            checks["progress_min_updates"] = True
        if all_parseable and len(json_lines) > 0:
            checks["progress_all_lines_parseable"] = True
            # Validate fields and percent ranges
            fields_ok = True
            percents: List[float] = []
            for obj in json_lines:
                msg = obj.get("message")
                pct = obj.get("percent")
                if not isinstance(msg, str):
                    fields_ok = False
                    break
                if not isinstance(pct, (int, float)):
                    fields_ok = False
                    break
                pctf = float(pct)
                if not (0.0 < pctf < 100.0):
                    fields_ok = False
                    break
                percents.append(pctf)
            if fields_ok:
                checks["progress_fields_and_range_valid"] = True
                # Strictly increasing
                increasing = all(percents[i] > percents[i - 1] for i in range(1, len(percents)))
                if increasing:
                    checks["progress_strictly_increasing"] = True

    # 3) Summary correctness
    ok, summary_json = read_json(summary_path)
    if ok and isinstance(summary_json, dict):
        checks["summary_exists"] = True
        has_keys = (
            "totals" in summary_json
            and "by_month" in summary_json
            and "by_category" in summary_json
            and "anomalies" in summary_json
            and isinstance(summary_json.get("totals"), dict)
            and isinstance(summary_json.get("by_month"), dict)
            and isinstance(summary_json.get("by_category"), dict)
            and isinstance(summary_json.get("anomalies"), dict)
        )
        if has_keys:
            checks["summary_has_required_keys"] = True

        # Load input CSV and compute expected
        inp_ok, rows = load_csv_transactions(input_csv_path)
        if inp_ok:
            expected = compute_expected_metrics(rows)

            # Totals validation
            totals = summary_json.get("totals") if isinstance(summary_json.get("totals"), dict) else {}
            # Count
            reported_count = totals.get("count")
            if isinstance(reported_count, int) and reported_count == expected["count"]:
                checks["summary_totals_count_correct"] = True
                summary_count = reported_count
            # Sum
            reported_sum = totals.get("sum")
            rs = safe_float(reported_sum)
            if rs is not None and approx_equal(rs, decimal_to_float(expected["sum"]), 1e-9):
                checks["summary_totals_sum_correct"] = True
            # Avg
            reported_avg = totals.get("avg")
            ra = safe_float(reported_avg)
            if ra is not None and approx_equal(ra, decimal_to_float(expected["avg"]), 1e-9):
                checks["summary_totals_avg_correct"] = True
            # Max
            reported_max = totals.get("max")
            rm = safe_float(reported_max)
            if rm is not None and approx_equal(rm, decimal_to_float(expected["max"]), 1e-9):
                checks["summary_totals_max_correct"] = True

            # by_month
            by_month = summary_json.get("by_month") if isinstance(summary_json.get("by_month"), dict) else {}
            if compare_mapping_numbers(by_month, expected["by_month"], 1e-9):
                checks["summary_by_month_correct"] = True

            # by_category
            by_category = summary_json.get("by_category") if isinstance(summary_json.get("by_category"), dict) else {}
            if compare_mapping_numbers(by_category, expected["by_category"], 1e-9):
                checks["summary_by_category_correct"] = True

            # anomalies
            anomalies = summary_json.get("anomalies") if isinstance(summary_json.get("anomalies"), dict) else {}
            neg_list_summary = anomalies.get("negative_amounts")
            dup_list_summary = anomalies.get("duplicate_ids")
            neg_set = list_to_set_of_str(neg_list_summary)
            dup_set = list_to_set_of_str(dup_list_summary)
            if neg_set is not None and neg_set == set(str(x) for x in expected["negative_ids"]):
                checks["summary_anomalies_negative_correct"] = True
            if dup_set is not None and dup_set == set(str(x) for x in expected["duplicate_ids"]):
                checks["summary_anomalies_duplicate_correct"] = True

    # 4) Done file
    ok, done_json = read_json(done_path)
    if ok and isinstance(done_json, dict):
        checks["done_exists"] = True
        status = done_json.get("status")
        completed_at = done_json.get("completed_at")
        completed_dt = parse_iso8601(completed_at)
        results = done_json.get("results") if isinstance(done_json.get("results"), dict) else None
        structure_ok = (
            status == "done"
            and isinstance(completed_at, str)
            and completed_dt is not None
            and isinstance(results, dict)
            and results.get("summary_file") == "output/summary.json"
            and results.get("progress_file") == "output/progress.jsonl"
            and isinstance(results.get("records_processed"), int)
        )
        if structure_ok:
            checks["done_structure_valid"] = True

        # records_processed equals totals.count from summary.json
        if structure_ok and summary_count is not None:
            if results.get("records_processed") == summary_count:
                checks["done_records_match_summary"] = True

        # completed_at > started_at
        if completed_dt is not None and started_dt is not None and completed_dt > started_dt:
            checks["done_completed_after_started"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # Model explicit no-op baseline: if output dir missing or empty, reward must be 0.0
    if not os.path.isdir(output_dir) or not any(os.scandir(output_dir)):
        reward_value = 0.0
    else:
        reward_value = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": reward_value}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()