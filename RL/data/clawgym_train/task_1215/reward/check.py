import csv
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _list_csv_files(dir_path: Path) -> List[Path]:
    if not dir_path.exists() or not dir_path.is_dir():
        return []
    return sorted([p for p in dir_path.glob("*.csv") if p.is_file()])


def _parse_config_settings_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the expected structure of config/settings.yaml.
    Supports:
      - top-level scalar key: value pairs
      - one nested mapping for 'expense_category_normalization'
    """
    text = _read_text_safe(path)
    if text is None:
        return None
    usd_to_local_rate = None
    bank_fee_flat_usd = None
    bank_fee_percent = None
    expense_norm: Dict[str, str] = {}

    lines = text.splitlines()
    i = 0
    in_norm = False
    while i < len(lines):
        line = lines[i]
        # Strip BOM if present in the first line
        if i == 0:
            line = line.lstrip("\ufeff")
        # Remove comments and trim
        if "#" in line:
            line = line.split("#", 1)[0]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        if not line.startswith(" "):  # top-level
            in_norm = False
            if stripped.endswith(":"):
                key = stripped[:-1].strip()
                if key == "expense_category_normalization":
                    in_norm = True
                    i += 1
                    # parse nested mapping
                    while i < len(lines):
                        sub = lines[i]
                        if "#" in sub:
                            sub = sub.split("#", 1)[0]
                        if not sub.strip():
                            i += 1
                            continue
                        if not sub.startswith(" "):  # new top-level key
                            i -= 1  # step back to reprocess this line at top-level
                            break
                        # expect "  Key: Value"
                        sub_stripped = sub.strip()
                        if ":" in sub_stripped:
                            k, v = sub_stripped.split(":", 1)
                            k = k.strip()
                            v = v.strip()
                            if v.startswith('"') and v.endswith('"'):
                                v = v[1:-1]
                            if v.startswith("'") and v.endswith("'"):
                                v = v[1:-1]
                            if k:
                                expense_norm[k] = v
                        i += 1
            else:
                # key: value
                if ":" in stripped:
                    key, val = stripped.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    # strip quotes
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1]
                    if val.startswith("'") and val.endswith("'"):
                        val = val[1:-1]
                    if key == "usd_to_local_rate":
                        try:
                            usd_to_local_rate = float(val)
                        except Exception:
                            usd_to_local_rate = None
                    elif key == "bank_fee_flat_usd":
                        try:
                            bank_fee_flat_usd = float(val)
                        except Exception:
                            bank_fee_flat_usd = None
                    elif key == "bank_fee_percent":
                        try:
                            bank_fee_percent = float(val)
                        except Exception:
                            bank_fee_percent = None
        else:
            # indented but not inside expense_norm - ignore
            pass
        i += 1

    result = {
        "usd_to_local_rate": usd_to_local_rate,
        "bank_fee_flat_usd": bank_fee_flat_usd,
        "bank_fee_percent": bank_fee_percent,
        "expense_category_normalization": expense_norm,
    }
    return result


def _to_month(date_str: str) -> Optional[str]:
    # Expect YYYY-MM-DD
    if not isinstance(date_str, str) or len(date_str) < 7:
        return None
    m = re.match(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$", date_str)
    if not m:
        return None
    year = m.group(1)
    month = m.group(2)
    return f"{year}-{month}"


def _round2(val: float) -> float:
    # Avoid floating point issues by rounding via quantization-like approach
    return round(val + 1e-12, 2)


def _fmt2(val: float) -> str:
    return f"{_round2(val):.2f}"


def _compute_expected(workspace: Path, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    # Load inputs
    rem_dir = workspace / "input" / "remittances"
    exp_dir = workspace / "input" / "expenses"
    rem_files = _list_csv_files(rem_dir)
    exp_files = _list_csv_files(exp_dir)
    if not rem_files and not exp_files:
        return None

    usd_to_local_rate = config.get("usd_to_local_rate")
    bank_fee_flat_usd = config.get("bank_fee_flat_usd")
    bank_fee_percent = config.get("bank_fee_percent")
    norm_map: Dict[str, str] = config.get("expense_category_normalization") or {}
    if (
        not isinstance(usd_to_local_rate, (int, float))
        or not isinstance(bank_fee_flat_usd, (int, float))
        or not isinstance(bank_fee_percent, (int, float))
    ):
        # Config missing essential numeric values
        return None

    # Gather rows
    rem_rows: List[Dict[str, str]] = []
    for p in rem_files:
        rows = _read_csv_safe(p)
        if rows is None:
            return None
        # validate headers
        required_cols = {"date", "sender", "amount_usd", "transfer_method"}
        if set(rows[0].keys()) if rows else required_cols == required_cols:
            pass  # basic check
        rem_rows.extend(rows)

    exp_rows: List[Dict[str, str]] = []
    for p in exp_files:
        rows = _read_csv_safe(p)
        if rows is None:
            return None
        # validate headers
        required_cols = {"date", "category", "description", "amount_local"}
        if set(rows[0].keys()) if rows else required_cols == required_cols:
            pass
        exp_rows.extend(rows)

    # Compute months
    months = set()
    for r in rem_rows:
        m = _to_month(r.get("date", ""))
        if m:
            months.add(m)
    for r in exp_rows:
        m = _to_month(r.get("date", ""))
        if m:
            months.add(m)
    months_sorted = sorted(months)

    # Per-transfer computations
    transfer_nets_usd: List[float] = []
    # monthly aggregates
    monthly = {}
    for m in months_sorted:
        monthly[m] = {
            "remittance_gross_usd": 0.0,
            "fees_total_usd": 0.0,
            "remittance_net_usd": 0.0,
            "remittance_net_local": 0.0,
            "expenses_total_local": 0.0,
        }

    for r in rem_rows:
        m = _to_month(r.get("date", ""))
        if not m:
            continue
        try:
            amt_usd = float(r.get("amount_usd", "0").strip())
        except Exception:
            return None
        fee = bank_fee_flat_usd + (amt_usd * (bank_fee_percent / 100.0))
        fee = _round2(fee)
        net_usd = _round2(amt_usd - fee)
        net_local = _round2(net_usd * usd_to_local_rate)
        monthly[m]["remittance_gross_usd"] += amt_usd
        monthly[m]["fees_total_usd"] += fee
        monthly[m]["remittance_net_usd"] += net_usd
        monthly[m]["remittance_net_local"] += net_local
        transfer_nets_usd.append(net_usd)

    for e in exp_rows:
        m = _to_month(e.get("date", ""))
        if not m:
            continue
        try:
            amt_local = float(e.get("amount_local", "0").strip())
        except Exception:
            return None
        monthly[m]["expenses_total_local"] += amt_local

    # Finalize sums rounding to 2 decimals
    for m in months_sorted:
        for k in ["remittance_gross_usd", "fees_total_usd", "remittance_net_usd", "remittance_net_local", "expenses_total_local"]:
            monthly[m][k] = _round2(monthly[m][k])
        monthly[m]["net_balance_local"] = _round2(monthly[m]["remittance_net_local"] - monthly[m]["expenses_total_local"])

    # Category breakdown
    category_breakdown: Dict[Tuple[str, str], float] = {}
    for e in exp_rows:
        m = _to_month(e.get("date", ""))
        if not m:
            continue
        cat = (e.get("category") or "").strip()
        norm = norm_map.get(cat, cat)
        try:
            amt_local = float(e.get("amount_local", "0").strip())
        except Exception:
            return None
        key = (m, norm)
        category_breakdown[key] = category_breakdown.get(key, 0.0) + amt_local
    # Round breakdown values
    for k in list(category_breakdown.keys()):
        category_breakdown[k] = _round2(category_breakdown[k])

    # Summary stats
    count_transfers = len(transfer_nets_usd)
    if count_transfers > 0:
        mean_net_usd = statistics.mean(transfer_nets_usd)
        median_net_usd = statistics.median(transfer_nets_usd)
    else:
        mean_net_usd = 0.0
        median_net_usd = 0.0

    total_expenses_local = _round2(sum(monthly[m]["expenses_total_local"] for m in months_sorted))
    total_net_balance_local = _round2(sum(monthly[m]["net_balance_local"] for m in months_sorted))
    summary = {
        "count_remittance_transfers": count_transfers,
        "mean_net_remittance_usd": mean_net_usd,
        "median_net_remittance_usd": median_net_usd,
        "total_expenses_local": total_expenses_local,
        "total_net_balance_local": total_net_balance_local,
        "months_covered": months_sorted,
    }

    return {
        "months": months_sorted,
        "monthly": monthly,
        "category_breakdown": category_breakdown,
        "summary": summary,
        "rem_files": rem_files,
        "exp_files": exp_files,
        "rem_rows_count": len(rem_rows),
        "exp_rows_count": len(exp_rows),
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_usd_to_local_rate_updated": 0.0,
        "config_bank_fee_flat_usd_updated": 0.0,
        "config_bank_fee_percent_updated": 0.0,
        "tool_script_exists": 0.0,
        "monthly_cashflow_exists_and_columns": 0.0,
        "monthly_cashflow_values_correct": 0.0,
        "monthly_cashflow_numeric_format": 0.0,
        "category_breakdown_exists_and_columns": 0.0,
        "category_breakdown_values_correct": 0.0,
        "summary_stats_exists_and_fields": 0.0,
        "summary_stats_values_correct": 0.0,
        "run_log_exists_and_contains_discovery": 0.0,
        "run_log_months_count_correct": 0.0,
        "architecture_doc_exists_and_contents": 0.0,
    }

    # Check config values
    config_path = workspace / "config" / "settings.yaml"
    cfg = _parse_config_settings_yaml(config_path) if config_path.exists() else None
    if cfg:
        if isinstance(cfg.get("usd_to_local_rate"), (int, float)) and abs(cfg.get("usd_to_local_rate") - 92.5) < 1e-9:
            scores["config_usd_to_local_rate_updated"] = 1.0
        if isinstance(cfg.get("bank_fee_flat_usd"), (int, float)) and abs(cfg.get("bank_fee_flat_usd") - 1.00) < 1e-9:
            scores["config_bank_fee_flat_usd_updated"] = 1.0
        if isinstance(cfg.get("bank_fee_percent"), (int, float)) and abs(cfg.get("bank_fee_percent") - 0.8) < 1e-9:
            scores["config_bank_fee_percent_updated"] = 1.0

    # Tool script existence
    tool_script = workspace / "tool" / "cashflow.py"
    if tool_script.exists() and tool_script.is_file():
        scores["tool_script_exists"] = 1.0

    # Compute expected from inputs and config (as present)
    expected = None
    if cfg:
        expected = _compute_expected(workspace, cfg)

    # Monthly cashflow checks
    monthly_csv = workspace / "output" / "monthly_cashflow.csv"
    expected_cols_monthly = [
        "month",
        "remittance_gross_usd",
        "fees_total_usd",
        "remittance_net_usd",
        "remittance_net_local",
        "expenses_total_local",
        "net_balance_local",
    ]
    monthly_rows = _read_csv_safe(monthly_csv) if monthly_csv.exists() else None
    if monthly_rows is not None and len(monthly_rows) >= 0:
        # check columns
        if list(monthly_rows[0].keys()) == expected_cols_monthly:
            scores["monthly_cashflow_exists_and_columns"] = 1.0
        # numeric format check and values
        format_ok = True
        values_ok = True
        if expected:
            # Build map for comparison
            exp_months = set(expected["months"])
            # build map from csv rows
            csv_months = set()
            for row in monthly_rows:
                month = row.get("month", "")
                csv_months.add(month)
                # numeric formatting check
                for k in expected_cols_monthly[1:]:
                    v = row.get(k, "")
                    if not re.match(r"^-?\d+\.\d{2}$", str(v).strip()):
                        format_ok = False
            # must match exact months set
            if csv_months != exp_months:
                values_ok = False
            # compare values
            for m in exp_months:
                exp_vals = expected["monthly"][m]
                # find row
                row = next((r for r in monthly_rows if r.get("month") == m), None)
                if row is None:
                    values_ok = False
                    break
                for k in expected_cols_monthly[1:]:
                    exp_val = exp_vals[k]
                    exp_str = _fmt2(exp_val)
                    if str(row.get(k, "")).strip() != exp_str:
                        values_ok = False
        else:
            # Without expected, cannot strongly validate values; only format if any rows
            for row in monthly_rows:
                for k in expected_cols_monthly[1:]:
                    v = row.get(k, "")
                    if not re.match(r"^-?\d+\.\d{2}$", str(v).strip()):
                        format_ok = False
        if values_ok:
            scores["monthly_cashflow_values_correct"] = 1.0
        if format_ok:
            scores["monthly_cashflow_numeric_format"] = 1.0

    # Category breakdown checks
    category_csv = workspace / "output" / "category_breakdown.csv"
    expected_cols_category = ["month", "normalized_category", "expenses_total_local"]
    category_rows = _read_csv_safe(category_csv) if category_csv.exists() else None
    if category_rows is not None and len(category_rows) >= 0:
        if list(category_rows[0].keys()) == expected_cols_category:
            scores["category_breakdown_exists_and_columns"] = 1.0
        values_ok = True
        if expected:
            # Build expected set
            exp_map = expected["category_breakdown"]  # keys: (month, norm), val: float
            # Build csv map
            csv_map: Dict[Tuple[str, str], str] = {}
            for row in category_rows:
                m = row.get("month", "")
                c = row.get("normalized_category", "")
                v = row.get("expenses_total_local", "")
                csv_map[(m, c)] = str(v).strip()
                # check format
                if not re.match(r"^-?\d+\.\d{2}$", str(v).strip()):
                    values_ok = False
            # Exact set match
            if set(csv_map.keys()) != set(exp_map.keys()):
                values_ok = False
            # Values correct
            for key, exp_val in exp_map.items():
                exp_str = _fmt2(exp_val)
                if csv_map.get(key) != exp_str:
                    values_ok = False
        if values_ok:
            scores["category_breakdown_values_correct"] = 1.0

    # Summary stats checks
    summary_json = workspace / "output" / "summary_stats.json"
    summary_obj = None
    if summary_json.exists():
        try:
            summary_obj = json.loads(summary_json.read_text(encoding="utf-8"))
        except Exception:
            summary_obj = None
    if isinstance(summary_obj, dict):
        required_keys = [
            "count_remittance_transfers",
            "mean_net_remittance_usd",
            "median_net_remittance_usd",
            "total_expenses_local",
            "total_net_balance_local",
            "months_covered",
        ]
        if all(k in summary_obj for k in required_keys):
            scores["summary_stats_exists_and_fields"] = 1.0
        values_ok = True
        if expected:
            exp = expected["summary"]
            # count
            if summary_obj.get("count_remittance_transfers") != exp["count_remittance_transfers"]:
                values_ok = False
            # mean and median with tolerance
            def _approx_equal(a: float, b: float, tol: float = 0.01) -> bool:
                try:
                    return abs(float(a) - float(b)) <= tol
                except Exception:
                    return False
            if not _approx_equal(summary_obj.get("mean_net_remittance_usd"), exp["mean_net_remittance_usd"]):
                values_ok = False
            if not _approx_equal(summary_obj.get("median_net_remittance_usd"), exp["median_net_remittance_usd"]):
                values_ok = False
            # totals with tolerance
            if not _approx_equal(summary_obj.get("total_expenses_local"), exp["total_expenses_local"]):
                values_ok = False
            if not _approx_equal(summary_obj.get("total_net_balance_local"), exp["total_net_balance_local"]):
                values_ok = False
            # months list exact match
            months_cov = summary_obj.get("months_covered")
            if months_cov != exp["months_covered"]:
                values_ok = False
        if values_ok:
            scores["summary_stats_values_correct"] = 1.0

    # Run log checks
    run_log = workspace / "output" / "run_log.txt"
    run_log_text = _read_text_safe(run_log) if run_log.exists() else None
    if run_log_text is not None:
        contains_ok = True
        months_ok = True
        # Discovery: should contain the discovered file paths and row counts
        # We will check for provided input files
        expected_rem = workspace / "input" / "remittances" / "remittances_2024_q1.csv"
        expected_exp = workspace / "input" / "expenses" / "expenses_2024_q1.csv"
        # Normalize to posix path substrings for matching
        rem_str = expected_rem.as_posix()
        exp_str = expected_exp.as_posix()
        lines = run_log_text.splitlines()
        def _line_has_path_and_count(path_sub: str, expected_count: int) -> bool:
            for ln in lines:
                if path_sub in ln:
                    nums = re.findall(r"\d+", ln)
                    for n in nums:
                        try:
                            if int(n) == expected_count:
                                return True
                        except Exception:
                            pass
            return False

        # Determine expected row counts from actual CSVs if available
        rem_count = None
        exp_count = None
        if expected and expected["rem_files"]:
            # If the set includes our expected file, count rows
            if (workspace / rem_str).exists():
                rows = _read_csv_safe(workspace / rem_str)
                rem_count = len(rows) if rows is not None else None
        if rem_count is None:
            # fallback to provided dataset knowledge: 6 rows
            rem_count = 6

        if expected and expected["exp_files"]:
            if (workspace / exp_str).exists():
                rows = _read_csv_safe(workspace / exp_str)
                exp_count = len(rows) if rows is not None else None
        if exp_count is None:
            exp_count = 8

        if not _line_has_path_and_count("input/remittances", rem_count):
            contains_ok = False
        if not _line_has_path_and_count("input/expenses", exp_count):
            contains_ok = False

        if contains_ok:
            scores["run_log_exists_and_contains_discovery"] = 1.0

        # Months count correct
        if expected:
            months_count = len(expected["months"])
            # search a line mentioning month(s) and the count
            found_months_line = False
            for ln in lines:
                if re.search(r"month", ln, flags=re.IGNORECASE):
                    nums = re.findall(r"\d+", ln)
                    for n in nums:
                        try:
                            if int(n) == months_count:
                                found_months_line = True
                                break
                        except Exception:
                            pass
                if found_months_line:
                    break
            if found_months_line:
                scores["run_log_months_count_correct"] = 1.0

    # ARCHITECTURE.md checks
    arch_path = workspace / "output" / "ARCHITECTURE.md"
    arch_text = _read_text_safe(arch_path) if arch_path.exists() else None
    if arch_text is not None:
        text_lower = arch_text.lower()
        ok = True
        # Must mention tool script path
        if ("tool/cashflow.py" not in arch_text) and not ("cashflow.py" in text_lower and "tool" in text_lower):
            ok = False
        # Must mention config path
        if "config/settings.yaml" not in arch_text and not ("settings.yaml" in text_lower and "config" in text_lower):
            ok = False
        # Must mention input directories
        if "input/remittances" not in arch_text or "input/expenses" not in arch_text:
            ok = False
        # Must mention scanning/discovery of directories
        if not (("scan" in text_lower) or ("scanning" in text_lower) or ("discover" in text_lower) or ("discovery" in text_lower)):
            ok = False
        # Must mention adding new CSV for next month
        if not (("csv" in text_lower) and (("add" in text_lower) or ("adding" in text_lower) or ("next month" in text_lower) or ("new" in text_lower))):
            ok = False
        if ok:
            scores["architecture_doc_exists_and_contents"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()