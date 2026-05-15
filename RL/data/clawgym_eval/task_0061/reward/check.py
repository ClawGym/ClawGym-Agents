import json
import csv
import sys;
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Tuple, List


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[dict]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _parse_float(value: str) -> Optional[float]:
    if value is None:
        return None
    try:
        s = str(value).strip()
        s = s.replace("$", "").replace(",", "")
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        return float(s)
    except Exception:
        return None


def _approx_equal(a: float, b: float, tol: float = 1e-2) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _parse_date(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _load_cpi_series(cpi_path: Path) -> Tuple[Optional[Dict[Tuple[int, int], float]], Optional[float], Optional[str]]:
    if not cpi_path.exists():
        return None, None, "missing_cpi"
    rows = _load_csv_dicts(cpi_path)
    if rows is None:
        return None, None, "malformed_cpi"
    try:
        with cpi_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None, None, "malformed_cpi"
            fieldnames = header
    except Exception:
        return None, None, "malformed_cpi"
    if "DATE" not in fieldnames or "CPIAUCSL" not in fieldnames:
        return None, None, "missing_columns"

    cpi_map: Dict[Tuple[int, int], float] = {}
    for row in rows:
        date_str = row.get("DATE")
        val_str = row.get("CPIAUCSL")
        if date_str is None or val_str is None:
            continue
        try:
            dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        except Exception:
            try:
                dt = datetime.strptime(date_str.strip(), "%Y-%m")
            except Exception:
                continue
        val = _parse_float(val_str)
        if val is None:
            continue
        cpi_map[(dt.year, dt.month)] = val

    base_vals = []
    for m in range(1, 13):
        v = cpi_map.get((2019, m))
        if v is None:
            base_vals = []
            break
        base_vals.append(v)
    if len(base_vals) != 12:
        return cpi_map, None, "missing_2019_months"
    base_cpi = sum(base_vals) / 12.0
    return cpi_map, base_cpi, None


def _compute_expected_adjustments(transactions: List[dict], cpi_map: Dict[Tuple[int, int], float], base_cpi_2019: float) -> Optional[List[dict]]:
    results = []
    for row in transactions:
        date_str = row.get("date")
        cat = (row.get("category") or "").strip()
        amt_str = row.get("amount_usd")
        dt = _parse_date(date_str) if date_str else None
        if dt is None:
            return None
        cpi_val = cpi_map.get((dt.year, dt.month))
        if cpi_val is None or base_cpi_2019 is None:
            return None
        nominal = _parse_float(amt_str)
        if nominal is None:
            return None
        usd_2019 = nominal * (base_cpi_2019 / cpi_val)
        results.append({
            "date": date_str,
            "category": cat,
            "nominal_usd": nominal,
            "cpi_value": cpi_val,
            "base_cpi_2019": base_cpi_2019,
            "usd_2019": usd_2019,
        })
    return results


def _extract_floats_from_text(text: str) -> List[float]:
    if not text:
        return []
    pattern = re.compile(r'(?<!\w)(?:\$?\(?-?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?|\$?-?\d+(?:\.\d+)?)(?!\w)')
    matches = pattern.findall(text)
    floats = []
    for m in matches:
        val = _parse_float(m)
        if val is not None:
            floats.append(val)
    return floats


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "cpi_file_present_and_parsed": 0.0,
        "cpi_has_required_months_for_transactions": 0.0,
        "base_cpi_2019_computed": 0.0,
        "adjusted_transactions_structure": 0.0,
        "adjusted_transactions_row_count_and_order": 0.0,
        "adjusted_transactions_cpi_and_deflation_correct": 0.0,
        "budget_vs_actual_structure": 0.0,
        "budget_vs_actual_values_correct": 0.0,
        "total_row_present_and_correct": 0.0,
        "unmatched_categories_correct": 0.0,
        "manifest_includes_files_sizes_and_row_counts": 0.0,
        "email_contents_requirements": 0.0,
        "methodology_contents_requirements": 0.0,
        "no_direct_urls_in_outputs": 0.0,
    }

    txn_path = workspace / "input" / "transactions_media_study.csv"
    budget_path = workspace / "input" / "original_budget_2019.json"
    cpi_path = workspace / "external" / "CPIAUCSL.csv"

    adj_txn_path = workspace / "output" / "adjusted_transactions.csv"
    bva_path = workspace / "output" / "budget_vs_actual_2019dollars.csv"
    unmatched_path = workspace / "output" / "unmatched_categories.txt"
    manifest_path = workspace / "output" / "manifest.txt"
    email_path = workspace / "output" / "email_to_grants_manager.txt"
    methodology_path = workspace / "output" / "methodology.md"

    transactions = _load_csv_dicts(txn_path) or []
    budget_json = _load_json(budget_path) or {}
    budget_categories = {}
    if isinstance(budget_json, dict) and isinstance(budget_json.get("categories"), dict):
        budget_categories = budget_json.get("categories", {})

    cpi_map, base_cpi_2019, cpi_err = _load_cpi_series(cpi_path)
    if cpi_map is not None and cpi_err not in {"missing_cpi", "malformed_cpi", "missing_columns"}:
        scores["cpi_file_present_and_parsed"] = 1.0
    if base_cpi_2019 is not None:
        scores["base_cpi_2019_computed"] = 1.0

    if cpi_map is not None:
        all_months_present = True
        for row in transactions:
            dt = _parse_date(row.get("date", ""))
            if dt is None:
                all_months_present = False
                break
            if (dt.year, dt.month) not in cpi_map:
                all_months_present = False
                break
        scores["cpi_has_required_months_for_transactions"] = 1.0 if all_months_present and len(transactions) > 0 else 0.0

    expected_adjustments = None
    if transactions and cpi_map is not None and base_cpi_2019 is not None:
        expected_adjustments = _compute_expected_adjustments(transactions, cpi_map, base_cpi_2019)

    adj_rows = _load_csv_dicts(adj_txn_path)
    if adj_rows is not None:
        try:
            with adj_txn_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
        except Exception:
            header = None
        expected_header = ["date", "category", "nominal_usd", "cpi_value", "base_cpi_2019", "usd_2019"]
        if header == expected_header:
            scores["adjusted_transactions_structure"] = 1.0

        input_dates = [r.get("date", "").strip() for r in transactions]
        adj_dates = [r.get("date", "").strip() for r in adj_rows]
        if len(adj_rows) == len(transactions) and input_dates == adj_dates and len(transactions) > 0:
            scores["adjusted_transactions_row_count_and_order"] = 1.0

        all_ok = True
        if expected_adjustments is None:
            all_ok = False
        else:
            for idx, (exp, got) in enumerate(zip(expected_adjustments, adj_rows)):
                if (got.get("date") or "").strip() != exp["date"]:
                    all_ok = False
                    break
                if (got.get("category") or "").strip() != (transactions[idx].get("category") or "").strip():
                    all_ok = False
                    break
                got_nom = _parse_float(got.get("nominal_usd"))
                if got_nom is None or not _approx_equal(got_nom, exp["nominal_usd"], tol=1e-2):
                    all_ok = False
                    break
                got_cpi = _parse_float(got.get("cpi_value"))
                if got_cpi is None or not _approx_equal(got_cpi, exp["cpi_value"], tol=1e-6):
                    all_ok = False
                    break
                got_base = _parse_float(got.get("base_cpi_2019"))
                if got_base is None or not _approx_equal(got_base, exp["base_cpi_2019"], tol=1e-6):
                    all_ok = False
                    break
                got_usd2019 = _parse_float(got.get("usd_2019"))
                if got_usd2019 is None or not _approx_equal(got_usd2019, exp["usd_2019"], tol=2e-2):
                    all_ok = False
                    break
        if all_ok and len(adj_rows) > 0:
            scores["adjusted_transactions_cpi_and_deflation_correct"] = 1.0

    expected_actuals_by_cat: Dict[str, float] = {}
    total_actual = None
    total_planned = None
    total_variance = None
    if expected_adjustments is not None:
        for rec in expected_adjustments:
            cat = (rec["category"] or "").strip()
            expected_actuals_by_cat[cat] = expected_actuals_by_cat.get(cat, 0.0) + rec["usd_2019"]
        total_actual = sum(expected_actuals_by_cat.values())
        total_planned = 0.0
        for c, amt in budget_categories.items():
            f = _parse_float(str(amt))
            if f is None:
                total_planned = None
                break
            total_planned += f
        if total_planned is not None:
            total_variance = total_actual - total_planned

    bva_rows = _load_csv_dicts(bva_path)
    if bva_rows is not None:
        try:
            with bva_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                bva_header = next(reader, None)
        except Exception:
            bva_header = None
        expected_bva_header = ["category", "planned_budget_2019_usd", "actual_spend_2019_usd", "variance_2019_usd"]
        if bva_header == expected_bva_header:
            scores["budget_vs_actual_structure"] = 1.0

        bva_map: Dict[str, dict] = {}
        for r in bva_rows:
            bva_map[(r.get("category") or "").strip()] = r
        total_row_ok = False
        if bva_rows:
            last_cat = (bva_rows[-1].get("category") or "").strip()
            if last_cat == "TOTAL":
                if total_actual is not None and total_planned is not None and total_variance is not None:
                    t_planned = _parse_float(bva_rows[-1].get("planned_budget_2019_usd"))
                    t_actual = _parse_float(bva_rows[-1].get("actual_spend_2019_usd"))
                    t_var = _parse_float(bva_rows[-1].get("variance_2019_usd"))
                    if (
                        t_planned is not None and t_actual is not None and t_var is not None and
                        _approx_equal(t_planned, total_planned, tol=0.05) and
                        _approx_equal(t_actual, total_actual, tol=0.05) and
                        _approx_equal(t_var, total_variance, tol=0.05)
                    ):
                        total_row_ok = True
        if total_row_ok:
            scores["total_row_present_and_correct"] = 1.0

        per_values_ok = True
        if expected_actuals_by_cat and budget_categories:
            for cat, planned in budget_categories.items():
                row = bva_map.get(cat)
                if row is None:
                    per_values_ok = False
                    break
                row_planned = _parse_float(row.get("planned_budget_2019_usd"))
                if row_planned is None or not _approx_equal(row_planned, float(planned), tol=0.01):
                    per_values_ok = False
                    break
                exp_actual = expected_actuals_by_cat.get(cat, 0.0)
                row_actual = _parse_float(row.get("actual_spend_2019_usd"))
                if row_actual is None or not _approx_equal(row_actual, exp_actual, tol=0.05):
                    per_values_ok = False
                    break
                row_var = _parse_float(row.get("variance_2019_usd"))
                if row_var is None or not _approx_equal(row_var, exp_actual - float(planned), tol=0.05):
                    per_values_ok = False
                    break
        else:
            per_values_ok = False
        if per_values_ok:
            scores["budget_vs_actual_values_correct"] = 1.0

    if transactions:
        txn_cats = set((r.get("category") or "").strip() for r in transactions)
        budget_cats = set((c or "").strip() for c in budget_categories.keys())
        expected_unmatched = sorted([c for c in txn_cats if c and c not in budget_cats])
    else:
        expected_unmatched = []

    unmatched_ok = False
    if unmatched_path.exists():
        text = _read_text(unmatched_path) or ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
        if not lines and not expected_unmatched:
            unmatched_ok = True
        else:
            if not expected_unmatched:
                unmatched_ok = any(ln.lower() == "none" for ln in lines)
            else:
                unmatched_ok = set(lines) == set(expected_unmatched)
    if unmatched_ok:
        scores["unmatched_categories_correct"] = 1.0

    manifest_ok = False
    if manifest_path.exists():
        mtext = _read_text(manifest_path) or ""
        has_txn_path = "input/transactions_media_study.csv" in mtext
        has_budget_path = "input/original_budget_2019.json" in mtext
        has_cpi_path = "external/CPIAUCSL.csv" in mtext

        def _size(p: Path) -> Optional[int]:
            try:
                return p.stat().st_size
            except Exception:
                return None

        txn_size = _size(txn_path)
        budget_size = _size(budget_path)
        cpi_size = _size(cpi_path)

        has_sizes = True
        for sz in [txn_size, budget_size, cpi_size]:
            if sz is None:
                has_sizes = False
                break
            if str(sz) not in mtext:
                has_sizes = False
                break

        txn_rows_count = len(transactions) if transactions else None
        cpi_rows = _load_csv_dicts(cpi_path)
        cpi_rows_count = len(cpi_rows) if cpi_rows is not None else None

        has_counts = True
        if txn_rows_count is None or cpi_rows_count is None:
            has_counts = False
        else:
            if str(txn_rows_count) not in mtext or str(cpi_rows_count) not in mtext:
                has_counts = False

        if has_txn_path and has_budget_path and has_cpi_path and has_sizes and has_counts:
            manifest_ok = True
    if manifest_ok:
        scores["manifest_includes_files_sizes_and_row_counts"] = 1.0

    email_ok = False
    if email_path.exists():
        etext = _read_text(email_path) or ""
        has_attach = ("adjusted_transactions.csv" in etext) and ("budget_vs_actual_2019dollars.csv" in etext)
        asks_realloc = ("reallocation" in etext.lower()) or ("re-allocat" in etext.lower())
        totals_present = False
        if total_planned is not None and total_actual is not None:
            nums = _extract_floats_from_text(etext)
            found_planned = any(_approx_equal(n, total_planned, tol=1.0) for n in nums)
            found_actual = any(_approx_equal(n, total_actual, tol=1.0) for n in nums)
            totals_present = found_planned and found_actual
        top_variances_ok = False
        if expected_actuals_by_cat and budget_categories:
            variances = []
            for cat, planned in budget_categories.items():
                planned_f = _parse_float(str(planned)) or 0.0
                actual_f = expected_actuals_by_cat.get(cat, 0.0)
                var = actual_f - planned_f
                variances.append((cat, var))
            over = sorted([x for x in variances if x[1] > 0], key=lambda x: abs(x[1]), reverse=True)[:2]
            under = sorted([x for x in variances if x[1] < 0], key=lambda x: abs(x[1]), reverse=True)[:2]
            over_ok = all(cat in etext for cat, _ in over) if over else True
            under_ok = all(cat in etext for cat, _ in under) if under else True
            top_variances_ok = over_ok and under_ok
        mentions_2019 = ("2019" in etext and "dollar" in etext.lower()) or ("2019 dollars" in etext.lower())
        if has_attach and asks_realloc and totals_present and top_variances_ok and mentions_2019:
            email_ok = True
    if email_ok:
        scores["email_contents_requirements"] = 1.0

    method_ok = False
    if methodology_path.exists():
        mtext = _read_text(methodology_path) or ""
        has_series_id = "CPIAUCSL" in mtext
        has_series_name = ("Consumer Price Index" in mtext) or ("All Urban Consumers" in mtext)
        mentions_base = "2019" in mtext and (("average" in mtext.lower()) or ("mean" in mtext.lower()))
        mentions_formula = ("/" in mtext or "amount_2019" in mtext or "usd_2019" in mtext) and ("base" in mtext.lower() or "deflat" in mtext.lower())
        mentions_repro = ("series" in mtext.lower()) or ("identifier" in mtext.lower())
        if has_series_id and has_series_name and mentions_base and mentions_formula and mentions_repro:
            method_ok = True
    if method_ok:
        scores["methodology_contents_requirements"] = 1.0

    no_urls_ok = False
    if email_path.exists() and methodology_path.exists() and manifest_path.exists():
        no_urls_ok = True
        for p in [email_path, methodology_path, manifest_path]:
            t = _read_text(p) or ""
            if re.search(r'https?://', t):
                no_urls_ok = False
                break
    if no_urls_ok:
        scores["no_direct_urls_in_outputs"] = 1.0

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()