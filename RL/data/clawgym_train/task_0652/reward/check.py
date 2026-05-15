import csv
import json
import os
import sys
from decimal import Decimal, InvalidOperation

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def abs_path(root, *parts):
    return os.path.join(root, *parts)

def read_csv_rows(path):
    rows = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            # strip BOM from first cell if present
            if i == 0 and row:
                if row[0].startswith("\ufeff"):
                    row[0] = row[0].lstrip("\ufeff")
            rows.append(row)
    return rows

def parse_decimal_maybe(s):
    if s is None:
        return None
    s = str(s).strip()
    if s == "":
        return None
    try:
        # Only allow plain numeric strings; disallow commas, currency symbols
        # Decimal will throw on invalid formats
        return Decimal(s)
    except InvalidOperation:
        return None

def decimals_equal(a, b, tol=Decimal("0.00001")):
    try:
        da = Decimal(str(a))
        db = Decimal(str(b))
    except Exception:
        return False
    return abs(da - db) <= tol

def sum_column_as_decimal(rows, col_idx):
    total = Decimal("0")
    for r in rows:
        if col_idx < len(r):
            d = parse_decimal_maybe(r[col_idx])
            if d is not None:
                total += d
    return total

def is_non_negative_int(x):
    if isinstance(x, bool):
        return False
    if isinstance(x, int):
        return x >= 0
    # allow numeric strings representing non-negative integers
    s = str(x).strip()
    if not s.isdigit():
        return False
    try:
        v = int(s)
        return v >= 0
    except Exception:
        return False

def is_number(x):
    try:
        Decimal(str(x))
        return True
    except Exception:
        return False

def last_nonempty_line_print(payload):
    print(json.dumps(payload))

def main():
    workspace_root = get_workspace_root()
    input_dir = abs_path(workspace_root, "input")
    output_dir = abs_path(workspace_root, "output")
    reward_dir = abs_path(workspace_root, "reward")

    # Initialize all checks to False
    checks = {
        # Existence checks
        "exists_recon_summary_json": False,
        "exists_recon_results_csv": False,
        "exists_unreconciled_bank_csv": False,
        "exists_unreconciled_gl_csv": False,

        # recon_summary.json structure/value checks
        "summary_json_valid": False,
        "summary_has_required_keys_exact": False,
        "summary_threshold_is_050": False,
        "summary_rows_fields_valid_ints": False,
        "summary_totals_fields_valid_numbers": False,
        "summary_matched_diff_consistent": False,
        "summary_counts_positive": False,

        # recon_results.csv checks
        "results_header_ok": False,
        "results_has_data_rows": False,
        "results_has_key_based_match": False,
        "results_has_ai_semantic_match": False,
        "results_has_diff_note": False,
        "results_amounts_numeric": False,

        # unreconciled_bank.csv checks
        "unrec_bank_header_ok": False,
        "unrec_bank_row_count_matches": False,
        "unrec_bank_total_matches": False,

        # unreconciled_gl.csv checks
        "unrec_gl_header_ok": False,
        "unrec_gl_row_count_matches": False,
        "unrec_gl_total_matches": False,
    }

    # Expected paths
    path_summary = abs_path(output_dir, "recon_summary.json")
    path_results = abs_path(output_dir, "recon_results.csv")
    path_unrec_bank = abs_path(output_dir, "unreconciled_bank.csv")
    path_unrec_gl = abs_path(output_dir, "unreconciled_gl.csv")

    # Existence
    if os.path.isfile(path_summary):
        checks["exists_recon_summary_json"] = True
    if os.path.isfile(path_results):
        checks["exists_recon_results_csv"] = True
    if os.path.isfile(path_unrec_bank):
        checks["exists_unreconciled_bank_csv"] = True
    if os.path.isfile(path_unrec_gl):
        checks["exists_unreconciled_gl_csv"] = True

    # Parse summary JSON if exists
    summary = None
    required_keys = {
        "threshold",
        "matched_bank_rows",
        "matched_gl_rows",
        "unreconciled_bank_rows",
        "unreconciled_gl_rows",
        "matched_bank_total",
        "matched_gl_total",
        "matched_total_difference",
        "unreconciled_bank_total",
        "unreconciled_gl_total",
    }
    if checks["exists_recon_summary_json"]:
        try:
            with open(path_summary, "r", encoding="utf-8") as f:
                summary = json.load(f)
            checks["summary_json_valid"] = True
            if isinstance(summary, dict) and set(summary.keys()) == required_keys:
                checks["summary_has_required_keys_exact"] = True

            if isinstance(summary, dict):
                # Threshold validation to equal 0.50 (numeric 0.5 acceptable)
                thr = summary.get("threshold")
                try:
                    thr_val = Decimal(str(thr))
                    if abs(thr_val - Decimal("0.50")) <= Decimal("0.00001"):
                        checks["summary_threshold_is_050"] = True
                except Exception:
                    checks["summary_threshold_is_050"] = False

                # *_rows non-negative integers
                rows_fields_ok = True
                for k in ["matched_bank_rows", "matched_gl_rows", "unreconciled_bank_rows", "unreconciled_gl_rows"]:
                    if not is_non_negative_int(summary.get(k)):
                        rows_fields_ok = False
                        break
                checks["summary_rows_fields_valid_ints"] = rows_fields_ok

                # *_total numeric
                totals_fields_ok = True
                for k in ["matched_bank_total", "matched_gl_total", "matched_total_difference", "unreconciled_bank_total", "unreconciled_gl_total"]:
                    if not is_number(summary.get(k)):
                        totals_fields_ok = False
                        break
                checks["summary_totals_fields_valid_numbers"] = totals_fields_ok

                # Consistency: matched_total_difference equals |matched_bank_total - matched_gl_total| within 0.01
                try:
                    mbt = Decimal(str(summary.get("matched_bank_total")))
                    mgt = Decimal(str(summary.get("matched_gl_total")))
                    mtd = Decimal(str(summary.get("matched_total_difference")))
                    if abs(mtd - abs(mbt - mgt)) <= Decimal("0.01"):
                        checks["summary_matched_diff_consistent"] = True
                except Exception:
                    checks["summary_matched_diff_consistent"] = False

                # Sum of counts > 0 for both bank and GL
                try:
                    mbc = int(summary.get("matched_bank_rows"))
                    ubc = int(summary.get("unreconciled_bank_rows"))
                    mgc = int(summary.get("matched_gl_rows"))
                    ugc = int(summary.get("unreconciled_gl_rows"))
                    if (mbc + ubc) > 0 and (mgc + ugc) > 0:
                        checks["summary_counts_positive"] = True
                except Exception:
                    checks["summary_counts_positive"] = False

        except Exception:
            checks["summary_json_valid"] = False

    # Parse recon_results.csv if exists
    results_rows = []
    if checks["exists_recon_results_csv"]:
        try:
            results_rows = read_csv_rows(path_results)
            # Header exact
            expected_header = [
                "Bank Date",
                "Bank Amount",
                "Bank Desc",
                "GL Date",
                "GL Amount",
                "GL Memo",
                "Match Basis",
                "Notes",
            ]
            if results_rows and results_rows[0] == expected_header:
                checks["results_header_ok"] = True

            data_rows = results_rows[1:] if len(results_rows) > 1 else []
            if len(data_rows) >= 1:
                checks["results_has_data_rows"] = True

            # Presence of required match types and notes and numeric amounts
            has_key_based = False
            has_ai_semantic = False
            has_diff_note = False
            amounts_numeric = True

            for r in data_rows:
                # Ensure length
                row = r + [""] * (8 - len(r))
                bank_amt = row[1]
                gl_amt = row[4]
                mbasis = row[6]
                notes = row[7]

                # Key-based match detection
                if mbasis == "1:1 Match" or mbasis.startswith("1:") or mbasis.endswith(":1") or mbasis.startswith("Group Match ("):
                    has_key_based = True

                # AI semantic match detection
                if mbasis.startswith("AI Semantic Match:"):
                    has_ai_semantic = True

                # Diff note
                if isinstance(notes, str) and notes.startswith("Diff:"):
                    has_diff_note = True

                # Amount numeric check: allow blanks, but non-empty must parse
                if str(bank_amt).strip() != "":
                    if parse_decimal_maybe(bank_amt) is None:
                        amounts_numeric = False
                if str(gl_amt).strip() != "":
                    if parse_decimal_maybe(gl_amt) is None:
                        amounts_numeric = False

            checks["results_has_key_based_match"] = has_key_based
            checks["results_has_ai_semantic_match"] = has_ai_semantic
            checks["results_has_diff_note"] = has_diff_note
            checks["results_amounts_numeric"] = amounts_numeric

        except Exception:
            # leave defaults as False
            pass

    # Parse unreconciled bank/gl CSVs if exist and compare to summary
    if checks["exists_unreconciled_bank_csv"]:
        try:
            ub_rows = read_csv_rows(path_unrec_bank)
            # Header exact
            expected_ub_header = ["date", "transaction amount", "description"]
            if ub_rows and ub_rows[0] == expected_ub_header:
                checks["unrec_bank_header_ok"] = True

            data_ub = ub_rows[1:] if len(ub_rows) > 1 else []
            # Row count matches summary
            if summary and checks["summary_rows_fields_valid_ints"]:
                try:
                    expected_count = int(summary["unreconciled_bank_rows"])
                    if len(data_ub) == expected_count:
                        checks["unrec_bank_row_count_matches"] = True
                except Exception:
                    pass
            # Sum matches total within 0.01
            if summary and checks["summary_totals_fields_valid_numbers"]:
                try:
                    calc_total = Decimal("0")
                    for r in data_ub:
                        # column 1 = "transaction amount"
                        amt = r[1] if len(r) > 1 else ""
                        d = parse_decimal_maybe(amt)
                        if d is not None:
                            calc_total += d
                    expected_total = Decimal(str(summary["unreconciled_bank_total"]))
                    if abs(calc_total - expected_total) <= Decimal("0.01"):
                        checks["unrec_bank_total_matches"] = True
                except Exception:
                    pass
        except Exception:
            pass

    if checks["exists_unreconciled_gl_csv"]:
        try:
            ug_rows = read_csv_rows(path_unrec_gl)
            # Header exact
            expected_ug_header = ["date", "amount", "G/L memo"]
            if ug_rows and ug_rows[0] == expected_ug_header:
                checks["unrec_gl_header_ok"] = True

            data_ug = ug_rows[1:] if len(ug_rows) > 1 else []
            # Row count matches summary
            if summary and checks["summary_rows_fields_valid_ints"]:
                try:
                    expected_count = int(summary["unreconciled_gl_rows"])
                    if len(data_ug) == expected_count:
                        checks["unrec_gl_row_count_matches"] = True
                except Exception:
                    pass
            # Sum matches total within 0.01
            if summary and checks["summary_totals_fields_valid_numbers"]:
                try:
                    calc_total = Decimal("0")
                    for r in data_ug:
                        amt = r[1] if len(r) > 1 else ""
                        d = parse_decimal_maybe(amt)
                        if d is not None:
                            calc_total += d
                    expected_total = Decimal(str(summary["unreconciled_gl_total"]))
                    if abs(calc_total - expected_total) <= Decimal("0.01"):
                        checks["unrec_gl_total_matches"] = True
                except Exception:
                    pass
        except Exception:
            pass

    # Compute reward
    # If output directory is empty or any required file missing, overall reward must be exactly 0.0
    required_exists = (
        checks["exists_recon_summary_json"]
        and checks["exists_recon_results_csv"]
        and checks["exists_unreconciled_bank_csv"]
        and checks["exists_unreconciled_gl_csv"]
    )

    if not required_exists:
        reward = 0.0
    else:
        # Score as fraction of checks passed (excluding existence gating already satisfied)
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total if total > 0 else 0.0
        # Cap to [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    result = {"reward": float(reward)}
    result.update(checks)
    last_nonempty_line_print(result)

if __name__ == "__main__":
    main()