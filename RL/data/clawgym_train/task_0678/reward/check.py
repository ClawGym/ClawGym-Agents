import json
import os
import sys
import csv
from collections import Counter

def isclose(a, b, tol=0.005):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "ledger_export_exists": False,
        "ledger_export_header_ok": False,
        "ledger_export_line_count_ok": False,
        "ledger_export_values_ok": False,
        "cleaned_expenses_exists": False,
        "cleaned_expenses_valid_json": False,
        "cleaned_expenses_len_ok": False,
        "cleaned_expenses_schema_ok": False,
        "cleaned_expenses_content_ok": False,
        "categories_summary_exists": False,
        "categories_summary_valid_json": False,
        "categories_summary_content_ok": False,
        "summary_md_exists": False,
        "summary_required_lines_present": False,
    }

    # Expected data
    expected_values = [
        "2026-03-01 | Safeway | -54.32 | [Groceries]",
        "2026-03-02 | Uber | -37.80 | [Transport]",
        "2026-03-03 | PG&E | -92.10 | [Utilities]",
        "2026-03-04 | Netflix | -15.49 | [Entertainment]",
        "2026-03-06 | Whole Foods | -76.88 | [Groceries]",
        "2026-03-07 | Caltrain | -87.00 | [Transport]",
        "2026-03-09 | Trader Joe's | -34.16 | [Groceries]",
        "2026-03-10 | Shell | -52.40 | [Transport]",
        "2026-03-11 | Blue Bottle | -7.50 | [Dining]",
    ]
    expected_items = [
        {"date": "2026-03-01", "merchant": "Safeway", "description": "Groceries", "amount": -54.32, "category": "Groceries"},
        {"date": "2026-03-02", "merchant": "Uber", "description": "Airport ride", "amount": -37.80, "category": "Transport"},
        {"date": "2026-03-03", "merchant": "PG&E", "description": "Electric bill", "amount": -92.10, "category": "Utilities"},
        {"date": "2026-03-04", "merchant": "Netflix", "description": "Subscription", "amount": -15.49, "category": "Entertainment"},
        {"date": "2026-03-06", "merchant": "Whole Foods", "description": "Groceries", "amount": -76.88, "category": "Groceries"},
        {"date": "2026-03-07", "merchant": "Caltrain", "description": "Monthly pass", "amount": -87.00, "category": "Transport"},
        {"date": "2026-03-09", "merchant": "Trader Joe's", "description": "Groceries", "amount": -34.16, "category": "Groceries"},
        {"date": "2026-03-10", "merchant": "Shell", "description": "Gasoline", "amount": -52.40, "category": "Transport"},
        {"date": "2026-03-11", "merchant": "Blue Bottle", "description": "Coffee", "amount": -7.50, "category": "Dining"},
    ]
    expected_by_category = {
        "Groceries": -165.36,
        "Transport": -177.20,
        "Utilities": -92.10,
        "Entertainment": -15.49,
        "Dining": -7.50,
    }
    expected_total = -457.65

    # 1) Check output/ledger-export.csv
    ledger_csv_path = os.path.join(output_dir, "ledger-export.csv")
    if os.path.isfile(ledger_csv_path):
        checks["ledger_export_exists"] = True
        try:
            # header exact line check and line count
            with open(ledger_csv_path, "r", encoding="utf-8", newline="") as ftxt:
                lines = ftxt.read().splitlines()
            if lines and lines[0] == "timestamp,command,value":
                checks["ledger_export_header_ok"] = True
            if len(lines) == 10:
                checks["ledger_export_line_count_ok"] = True

            # CSV parse to check 3rd column values
            values = []
            with open(ledger_csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
                if rows:
                    data_rows = rows[1:]
                    for row in data_rows:
                        if len(row) >= 3:
                            values.append(row[2])
            if len(values) == 9:
                expected_counter = Counter(expected_values)
                found_counter = Counter(values)
                if found_counter == expected_counter:
                    checks["ledger_export_values_ok"] = True
        except Exception:
            pass

    # 2) Check output/cleaned_expenses.json
    cleaned_json_path = os.path.join(output_dir, "cleaned_expenses.json")
    cleaned_data = None
    if os.path.isfile(cleaned_json_path):
        checks["cleaned_expenses_exists"] = True
        try:
            with open(cleaned_json_path, "r", encoding="utf-8") as f:
                cleaned_data = json.load(f)
            checks["cleaned_expenses_valid_json"] = True

            if isinstance(cleaned_data, list) and len(cleaned_data) == 9:
                checks["cleaned_expenses_len_ok"] = True

            schema_ok = True
            if isinstance(cleaned_data, list):
                for item in cleaned_data:
                    if not isinstance(item, dict):
                        schema_ok = False
                        break
                    for key in ["date", "merchant", "description", "amount", "category"]:
                        if key not in item:
                            schema_ok = False
                            break
                    if not schema_ok:
                        break
                    if not isinstance(item["date"], str): schema_ok = False
                    if not isinstance(item["merchant"], str): schema_ok = False
                    if not isinstance(item["description"], str): schema_ok = False
                    if not isinstance(item["category"], str): schema_ok = False
                    if not isinstance(item["amount"], (int, float)): schema_ok = False
                    if not schema_ok:
                        break
            if schema_ok and cleaned_data is not None:
                checks["cleaned_expenses_schema_ok"] = True

            # Content check: match all tuples exactly (order-insensitive)
            if cleaned_data and isinstance(cleaned_data, list):
                expected_tuples = set(
                    (e["date"], e["merchant"], e["description"], round(float(e["amount"]), 2), e["category"])
                    for e in expected_items
                )
                found_tuples = set()
                amounts_match = True
                for it in cleaned_data:
                    tup = (it["date"], it["merchant"], it["description"], round(float(it["amount"]), 2), it["category"])
                    found_tuples.add(tup)
                # Compare sets; amounts compared at 2 decimals
                if found_tuples == expected_tuples:
                    checks["cleaned_expenses_content_ok"] = True
        except Exception:
            pass

    # 3) Check output/categories_summary.json
    cats_path = os.path.join(output_dir, "categories_summary.json")
    if os.path.isfile(cats_path):
        checks["categories_summary_exists"] = True
        try:
            with open(cats_path, "r", encoding="utf-8") as f:
                cats = json.load(f)
            checks["categories_summary_valid_json"] = True

            if isinstance(cats, dict) and "by_category" in cats and "total" in cats:
                by_cat = cats["by_category"]
                total = cats["total"]
                content_ok = True
                # by_category must have exactly the expected keys
                if not isinstance(by_cat, dict):
                    content_ok = False
                else:
                    if set(by_cat.keys()) != set(expected_by_category.keys()):
                        content_ok = False
                    else:
                        for k, exp_val in expected_by_category.items():
                            if k not in by_cat:
                                content_ok = False
                                break
                            if not isclose(by_cat[k], exp_val, tol=0.005):
                                content_ok = False
                                break
                if not isclose(total, expected_total, tol=0.005):
                    content_ok = False
                if content_ok:
                    checks["categories_summary_content_ok"] = True
        except Exception:
            pass

    # 4) Check output/summary.md
    summary_path = os.path.join(output_dir, "summary.md")
    if os.path.isfile(summary_path):
        checks["summary_md_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_text = f.read()
            line1 = "Excluded reimbursable entries: 2"
            line2 = "Total posted: 9"
            if (line1 in summary_text) and (line2 in summary_text):
                checks["summary_required_lines_present"] = True
        except Exception:
            pass

    # Compute reward: proportion of passed checks; ensure 0.0 if no outputs produced
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if passed > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()