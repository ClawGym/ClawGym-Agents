import json
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set


EPS = 1e-6


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _approx_equal(a: float, b: float, eps: float = EPS) -> bool:
    return abs(a - b) <= eps


def _to_float(value: Any) -> Optional[float]:
    try:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            v = value.strip()
            if v == "":
                return None
            return float(v)
        return None
    except Exception:
        return None


def _to_int(value: Any) -> Optional[int]:
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if value.is_integer():
                return int(value)
            return None
        if isinstance(value, str):
            v = value.strip()
            if v == "":
                return None
            return int(v)
        return None
    except Exception:
        return None


def _to_bool_fuzzy(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "t", "yes", "y", "1"}:
            return True
        if v in {"false", "f", "no", "n", "0"}:
            return False
    return None


def _safe_get(row: Dict[str, Any], key: str) -> Optional[Any]:
    return row.get(key, None)


def _load_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    expenses_path = workspace / "input" / "expenses.csv"
    vendors_path = workspace / "input" / "vendors.csv"
    budgets_path = workspace / "input" / "budgets.csv"

    expenses_rows = _read_csv_dicts(expenses_path)
    vendors_rows = _read_csv_dicts(vendors_path)
    budgets_rows = _read_csv_dicts(budgets_path)

    if expenses_rows is None or vendors_rows is None or budgets_rows is None:
        return None

    # Validate required columns exist
    exp_required = {"date", "event", "category", "vendor_id", "amount", "funding_source"}
    vend_required = {"vendor_id", "vendor_name", "is_indigenous_owned", "is_fossil_affiliated"}
    bud_required = {"funding_source", "allocated_amount"}

    def has_cols(rows: List[Dict[str, str]], req: Set[str]) -> bool:
        if not rows:
            # No data rows; try to validate using csv header separately
            return True
        return req.issubset(set(rows[0].keys()))

    if not has_cols(expenses_rows, exp_required):
        return None
    if not has_cols(vendors_rows, vend_required):
        return None
    if not has_cols(budgets_rows, bud_required):
        return None

    # Parse expenses
    expenses: List[Dict[str, Any]] = []
    for r in expenses_rows:
        amt = _to_float(r.get("amount"))
        if amt is None:
            return None
        expenses.append({
            "date": r.get("date"),
            "event": r.get("event"),
            "category": r.get("category"),
            "vendor_id": r.get("vendor_id"),
            "amount": amt,
            "funding_source": r.get("funding_source"),
        })

    # Parse vendors
    vendors: Dict[str, Dict[str, Any]] = {}
    for r in vendors_rows:
        vid = r.get("vendor_id")
        if vid is None:
            return None
        indig = _to_bool_fuzzy(r.get("is_indigenous_owned"))
        fossil = _to_bool_fuzzy(r.get("is_fossil_affiliated"))
        if indig is None or fossil is None:
            return None
        vendors[vid] = {
            "vendor_id": vid,
            "vendor_name": r.get("vendor_name"),
            "is_indigenous_owned": indig,
            "is_fossil_affiliated": fossil,
        }

    # Parse budgets
    budgets: Dict[str, float] = {}
    for r in budgets_rows:
        fs = r.get("funding_source")
        alloc = _to_float(r.get("allocated_amount"))
        if fs is None or alloc is None:
            return None
        budgets[fs] = alloc

    # Aggregations
    total_expenses = sum(e["amount"] for e in expenses)
    by_category: Dict[str, Dict[str, Any]] = {}
    by_event: Dict[str, float] = {}
    by_funding: Dict[str, float] = {}
    vendor_spend: Dict[str, float] = {}
    for e in expenses:
        cat = e["category"]
        by_category.setdefault(cat, {"total_spent": 0.0, "count": 0})
        by_category[cat]["total_spent"] += e["amount"]
        by_category[cat]["count"] += 1

        ev = e["event"]
        by_event[ev] = by_event.get(ev, 0.0) + e["amount"]

        fs = e["funding_source"]
        by_funding[fs] = by_funding.get(fs, 0.0) + e["amount"]

        vid = e["vendor_id"]
        vendor_spend[vid] = vendor_spend.get(vid, 0.0) + e["amount"]

    for cat, agg in by_category.items():
        cnt = agg["count"]
        agg["mean"] = agg["total_spent"] / cnt if cnt > 0 else 0.0

    # Indigenous and fossil spend totals
    indig_spend = 0.0
    fossil_spend = 0.0
    for vid, spend in vendor_spend.items():
        meta = vendors.get(vid)
        if meta:
            if meta["is_indigenous_owned"]:
                indig_spend += spend
            if meta["is_fossil_affiliated"]:
                fossil_spend += spend

    return {
        "expenses": expenses,
        "vendors": vendors,
        "budgets": budgets,
        "total_expenses": total_expenses,
        "by_category": by_category,
        "by_event": by_event,
        "by_funding": by_funding,
        "vendor_spend": vendor_spend,
        "indig_spend": indig_spend,
        "fossil_spend": fossil_spend,
        "expense_rows_count": len(expenses),
    }


def _check_all_outputs_present(workspace: Path) -> float:
    outdir = workspace / "output"
    expected = [
        outdir / "category_summary.csv",
        outdir / "event_totals.csv",
        outdir / "funding_status.csv",
        outdir / "vendor_breakdown.json",
        outdir / "checks.json",
    ]
    return 1.0 if all(p.is_file() for p in expected) else 0.0


def _check_category_summary_correct(workspace: Path, expected: Dict[str, Any]) -> float:
    path = workspace / "output" / "category_summary.csv"
    rows = _read_csv_dicts(path)
    if rows is None:
        return 0.0
    # Check header order
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
    except Exception:
        return 0.0
    expected_header = ["category", "total_spent", "transaction_count", "mean_transaction_amount"]
    if header != expected_header:
        return 0.0

    # Build mapping
    seen: Set[str] = set()
    output_map: Dict[str, Tuple[float, int, float]] = {}
    for r in rows:
        cat = r.get("category")
        if cat is None:
            return 0.0
        if cat in seen:
            return 0.0
        seen.add(cat)
        total = _to_float(r.get("total_spent"))
        cnt = _to_int(r.get("transaction_count"))
        mean = _to_float(r.get("mean_transaction_amount"))
        if total is None or cnt is None or mean is None:
            return 0.0
        output_map[cat] = (total, cnt, mean)

    exp_map = expected["by_category"]
    if set(output_map.keys()) != set(exp_map.keys()):
        return 0.0

    for cat, agg in exp_map.items():
        exp_total = float(agg["total_spent"])
        exp_cnt = int(agg["count"])
        exp_mean = float(agg["mean"])
        out_total, out_cnt, out_mean = output_map[cat]
        if not _approx_equal(out_total, exp_total):
            return 0.0
        if out_cnt != exp_cnt:
            return 0.0
        if not _approx_equal(out_mean, exp_mean):
            return 0.0

    return 1.0


def _check_event_totals_correct(workspace: Path, expected: Dict[str, Any]) -> float:
    path = workspace / "output" / "event_totals.csv"
    rows = _read_csv_dicts(path)
    if rows is None:
        return 0.0
    # Check header order
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
    except Exception:
        return 0.0
    expected_header = ["event", "total_spent"]
    if header != expected_header:
        return 0.0

    output_map: Dict[str, float] = {}
    for r in rows:
        ev = r.get("event")
        amt = _to_float(r.get("total_spent"))
        if ev is None or amt is None:
            return 0.0
        if ev in output_map:
            return 0.0
        output_map[ev] = amt

    exp_map: Dict[str, float] = expected["by_event"]
    if set(output_map.keys()) != set(exp_map.keys()):
        return 0.0
    for ev, amt in exp_map.items():
        if not _approx_equal(output_map[ev], float(amt)):
            return 0.0
    # Reconcile sum equals total
    if not _approx_equal(sum(output_map.values()), float(expected["total_expenses"])):
        return 0.0
    return 1.0


def _check_funding_status_correct(workspace: Path, expected: Dict[str, Any]) -> float:
    path = workspace / "output" / "funding_status.csv"
    rows = _read_csv_dicts(path)
    if rows is None:
        return 0.0
    # Check header order
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
    except Exception:
        return 0.0
    expected_header = ["funding_source", "allocated_amount", "total_spent", "remaining_amount", "over_budget"]
    if header != expected_header:
        return 0.0

    budgets: Dict[str, float] = expected["budgets"]
    by_funding: Dict[str, float] = expected["by_funding"]

    output_map: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        fs = r.get("funding_source")
        if fs is None:
            return 0.0
        if fs in output_map:
            return 0.0
        alloc = _to_float(r.get("allocated_amount"))
        spent = _to_float(r.get("total_spent"))
        remaining = _to_float(r.get("remaining_amount"))
        overb = _to_bool_fuzzy(r.get("over_budget"))
        if alloc is None or spent is None or remaining is None or overb is None:
            return 0.0
        output_map[fs] = {
            "allocated_amount": alloc,
            "total_spent": spent,
            "remaining_amount": remaining,
            "over_budget": overb,
        }

    # Expect exactly rows for funding sources present in budgets file
    if set(output_map.keys()) != set(budgets.keys()):
        return 0.0

    for fs, alloc in budgets.items():
        spent = by_funding.get(fs, 0.0)
        remaining = alloc - spent
        overb = remaining < 0
        out = output_map[fs]
        if not _approx_equal(out["allocated_amount"], float(alloc)):
            return 0.0
        if not _approx_equal(out["total_spent"], float(spent)):
            return 0.0
        if not _approx_equal(out["remaining_amount"], float(remaining)):
            return 0.0
        if out["over_budget"] != overb:
            return 0.0

    return 1.0


def _check_vendor_breakdown_correct(workspace: Path, expected: Dict[str, Any]) -> float:
    path = workspace / "output" / "vendor_breakdown.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return 0.0

    if "vendors" not in data or "overall" not in data:
        return 0.0
    vendors_list = data.get("vendors")
    overall = data.get("overall")
    if not isinstance(vendors_list, list) or not isinstance(overall, dict):
        return 0.0

    total_expenses = float(expected["total_expenses"])
    indig_spend = float(expected["indig_spend"])
    fossil_spend = float(expected["fossil_spend"])

    # Validate overall fields
    ov_total = _to_float(overall.get("total_spent"))
    if ov_total is None or not _approx_equal(ov_total, total_expenses):
        return 0.0

    ov_pct_indig = _to_float(overall.get("percent_to_indigenous_owned"))
    ov_pct_fossil = _to_float(overall.get("percent_to_fossil_affiliated"))
    if ov_pct_indig is None or ov_pct_fossil is None:
        return 0.0

    # The spec uses "percent", interpret as 0-100 scale
    exp_pct_indig = (indig_spend / total_expenses * 100.0) if total_expenses > 0 else 0.0
    exp_pct_fossil = (fossil_spend / total_expenses * 100.0) if total_expenses > 0 else 0.0

    if not _approx_equal(ov_pct_indig, exp_pct_indig):
        return 0.0
    if not _approx_equal(ov_pct_fossil, exp_pct_fossil):
        return 0.0

    # Build vendors index from output
    out_vendors: Dict[str, Dict[str, Any]] = {}
    for item in vendors_list:
        if not isinstance(item, dict):
            return 0.0
        vid = item.get("vendor_id")
        if not isinstance(vid, str):
            return 0.0
        if vid in out_vendors:
            return 0.0
        out_vendors[vid] = item

    # All vendors appearing in expenses must be present with correct values
    vendors_meta: Dict[str, Dict[str, Any]] = expected["vendors"]
    vendor_spend: Dict[str, float] = expected["vendor_spend"]

    for vid, spend in vendor_spend.items():
        if vid not in out_vendors:
            return 0.0
        item = out_vendors[vid]
        meta = vendors_meta.get(vid)
        if meta is None:
            return 0.0
        # Validate fields
        if item.get("vendor_name") != meta["vendor_name"]:
            return 0.0
        indig = item.get("is_indigenous_owned")
        fossil = item.get("is_fossil_affiliated")
        if not isinstance(indig, bool) or not isinstance(fossil, bool):
            return 0.0
        if indig != meta["is_indigenous_owned"]:
            return 0.0
        if fossil != meta["is_fossil_affiliated"]:
            return 0.0
        it_total = _to_float(item.get("total_spent"))
        it_share = _to_float(item.get("share_of_total"))
        if it_total is None or it_share is None:
            return 0.0
        if not _approx_equal(it_total, float(spend)):
            return 0.0
        exp_share = (spend / total_expenses) if total_expenses > 0 else 0.0
        if not _approx_equal(it_share, exp_share):
            return 0.0

    return 1.0


def _check_checks_json_correct(workspace: Path, expected: Dict[str, Any]) -> float:
    path = workspace / "output" / "checks.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return 0.0

    required_keys = {
        "expense_rows",
        "vendors_covered",
        "coverage_rate",
        "reconciles_by_funding",
        "reconciles_by_event",
    }
    if not required_keys.issubset(set(data.keys())):
        return 0.0

    # Compute expected metrics
    expense_rows_count = expected["expense_rows_count"]
    vendors_meta: Dict[str, Dict[str, Any]] = expected["vendors"]
    expenses: List[Dict[str, Any]] = expected["expenses"]
    by_funding: Dict[str, float] = expected["by_funding"]
    by_event: Dict[str, float] = expected["by_event"]
    total_expenses = float(expected["total_expenses"])

    # Vendor coverage
    matched = 0
    for e in expenses:
        if e["vendor_id"] in vendors_meta:
            matched += 1
    coverage_rate = (matched / len(expenses)) if expenses else 0.0
    vendors_covered = (matched == len(expenses))

    reconciles_by_funding = _approx_equal(sum(by_funding.values()), total_expenses)
    reconciles_by_event = _approx_equal(sum(by_event.values()), total_expenses)

    out_expense_rows = _to_int(data.get("expense_rows"))
    out_vendors_covered = _to_bool_fuzzy(data.get("vendors_covered"))
    out_coverage_rate = _to_float(data.get("coverage_rate"))
    out_reconciles_by_funding = _to_bool_fuzzy(data.get("reconciles_by_funding"))
    out_reconciles_by_event = _to_bool_fuzzy(data.get("reconciles_by_event"))

    if out_expense_rows is None or out_vendors_covered is None or out_coverage_rate is None:
        return 0.0
    if out_reconciles_by_funding is None or out_reconciles_by_event is None:
        return 0.0

    if out_expense_rows != expense_rows_count:
        return 0.0
    if out_vendors_covered != vendors_covered:
        return 0.0
    if not _approx_equal(out_coverage_rate, coverage_rate):
        return 0.0
    if out_reconciles_by_funding != reconciles_by_funding:
        return 0.0
    if out_reconciles_by_event != reconciles_by_event:
        return 0.0

    return 1.0


def _find_cli_script_with_flags(workspace: Path) -> float:
    # Search for a .py file that includes the required flags tokens
    required_tokens = {"--expenses", "--vendors", "--budgets", "--outdir"}
    found = False

    def should_skip_dir(name: str) -> bool:
        name_lower = name.lower()
        return name_lower in {
            ".git", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache",
            "venv", ".venv", "env", ".tox", "output", ".ruff_cache"
        } or name_lower.startswith("dist") or name_lower.startswith("build")

    for p in workspace.rglob("*.py"):
        if should_skip_dir(p.parent.name):
            continue
        # Heuristically skip very large files
        try:
            if p.stat().st_size > 1_000_000:
                continue
        except Exception:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if all(tok in text for tok in required_tokens):
            found = True
            break

    return 1.0 if found else 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "all_outputs_present": 0.0,
        "category_summary_correct": 0.0,
        "event_totals_correct": 0.0,
        "funding_status_correct": 0.0,
        "vendor_breakdown_correct": 0.0,
        "checks_json_correct": 0.0,
        "cli_script_with_expected_flags": 0.0,
    }

    scores["all_outputs_present"] = _check_all_outputs_present(workspace)
    expected = _load_inputs(workspace)

    # Check CLI script existence with flags regardless of inputs
    scores["cli_script_with_expected_flags"] = _find_cli_script_with_flags(workspace)

    if expected is None:
        # Without valid inputs we cannot validate content; return zeros for those checks
        return scores

    # Content checks based on expected values
    scores["category_summary_correct"] = _check_category_summary_correct(workspace, expected)
    scores["event_totals_correct"] = _check_event_totals_correct(workspace, expected)
    scores["funding_status_correct"] = _check_funding_status_correct(workspace, expected)
    scores["vendor_breakdown_correct"] = _check_vendor_breakdown_correct(workspace, expected)
    scores["checks_json_correct"] = _check_checks_json_correct(workspace, expected)

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()