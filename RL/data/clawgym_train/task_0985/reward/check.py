import csv
import json
import os
import sys
from decimal import Decimal, ROUND_HALF_UP

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_csv(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.reader(f))

def load_csv_dict(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))

def clean_header(fieldnames):
    # Trim whitespace around header names, keep case
    return [fn.strip() if isinstance(fn, str) else fn for fn in fieldnames or []]

def to_float(val):
    if val is None:
        return None
    s = str(val).strip()
    if s.endswith("%"):
        s = s[:-1]
    s = s.replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except Exception:
        return None

def round_nearest_dollar(value):
    # Round half up to nearest whole dollar
    d = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)

def compute_category(food_cost_percent, menu_mix_percent):
    # Strict inequalities per spec
    if food_cost_percent is None or menu_mix_percent is None:
        return None
    fcp = float(food_cost_percent)
    mmp = float(menu_mix_percent)
    if fcp < 30 and mmp > 15:
        return "Star"
    if fcp > 30 and mmp > 15:
        return "Plowhorse"
    if fcp < 30 and mmp < 15:
        return "Puzzle"
    if fcp > 30 and mmp < 15:
        return "Dog"
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        # menu_engineering.csv checks
        "menu_engineering_exists": False,
        "menu_engineering_header_ok": False,
        "menu_engineering_all_items_present": False,
        "menu_engineering_no_duplicate_items": False,
        "menu_engineering_categories_correct": False,

        # targets.json checks
        "targets_exists": False,
        "targets_values_correct": False,

        # revenue_forecast.csv checks
        "revenue_forecast_exists": False,
        "revenue_forecast_header_ok": False,
        "revenue_forecast_12_rows": False,
        "revenue_forecast_calendar_order": False,
        "revenue_forecast_indices_correct": False,
        "revenue_forecast_midpoints_correct": False,
        "revenue_forecast_values_correct": False,

        # ops_plan.md checks
        "ops_plan_exists": False,
        "ops_plan_keywords_present": False,
    }

    # Paths
    menu_input_path = os.path.join(input_dir, "menu_items.csv")
    ctx_path = os.path.join(input_dir, "restaurant_context.json")

    menu_out_path = os.path.join(output_dir, "menu_engineering.csv")
    targets_out_path = os.path.join(output_dir, "targets.json")
    forecast_out_path = os.path.join(output_dir, "revenue_forecast.csv")
    ops_plan_path = os.path.join(output_dir, "ops_plan.md")

    # Preload input references (do not score for this alone)
    input_menu_items = []
    input_items_by_name = {}
    if os.path.isfile(menu_input_path):
        try:
            input_rows = load_csv_dict(menu_input_path)
            for row in input_rows:
                # Normalize keys by stripping spaces
                normalized = { (k.strip() if isinstance(k, str) else k): v for k, v in row.items() }
                item_name = (normalized.get("Item") or "").strip()
                price = to_float(normalized.get("Price"))
                fcp = to_float(normalized.get("FoodCostPercent"))
                mmp = to_float(normalized.get("MenuMixPercent"))
                if item_name:
                    rec = {"Item": item_name, "Price": price, "FoodCostPercent": fcp, "MenuMixPercent": mmp}
                    input_menu_items.append(rec)
                    input_items_by_name[item_name] = rec
        except Exception:
            input_menu_items = []
            input_items_by_name = {}

    base_monthly_revenue = None
    if os.path.isfile(ctx_path):
        try:
            ctx = read_json(ctx_path)
            base_monthly_revenue = ctx.get("base_monthly_revenue")
            if isinstance(base_monthly_revenue, str):
                base_monthly_revenue = to_float(base_monthly_revenue)
        except Exception:
            base_monthly_revenue = None

    # 1) menu_engineering.csv validations
    if os.path.isfile(menu_out_path):
        checks["menu_engineering_exists"] = True
        try:
            out_rows_dict = load_csv_dict(menu_out_path)
            fieldnames = out_rows_dict[0].keys() if out_rows_dict else []
            cleaned = clean_header(fieldnames)
            expected_cols = {"Item", "Price", "FoodCostPercent", "MenuMixPercent", "Category"}
            if expected_cols.issubset(set(cleaned)):
                checks["menu_engineering_header_ok"] = True

            # Build mapping from Item to row and track duplicates
            seen_items = []
            duplicates = False
            output_items_set = set()
            categories_ok = True

            for row in out_rows_dict:
                # Normalize key access using stripped names
                normalized = { (k.strip() if isinstance(k, str) else k): v for k, v in row.items() }
                item = (normalized.get("Item") or "").strip()
                category = (normalized.get("Category") or "").strip()
                if not item:
                    categories_ok = False
                    continue
                if item in output_items_set:
                    duplicates = True
                output_items_set.add(item)
                seen_items.append(item)

                # Compare expected category computed from INPUT values
                if item not in input_items_by_name:
                    categories_ok = False
                    continue
                inp = input_items_by_name[item]
                expected_cat = compute_category(inp["FoodCostPercent"], inp["MenuMixPercent"])
                if expected_cat is None or category != expected_cat:
                    categories_ok = False

            # All items present exactly once
            input_items_set = set([rec["Item"] for rec in input_menu_items])
            if output_items_set == input_items_set and len(seen_items) == len(input_menu_items):
                checks["menu_engineering_all_items_present"] = True
            if not duplicates and len(seen_items) == len(output_items_set):
                checks["menu_engineering_no_duplicate_items"] = True
            if categories_ok and checks["menu_engineering_all_items_present"]:
                checks["menu_engineering_categories_correct"] = True
        except Exception:
            # If parsing failed, leave checks as False
            pass

    # 2) targets.json validations
    if os.path.isfile(targets_out_path):
        checks["targets_exists"] = True
        try:
            data = read_json(targets_out_path)
            ok = (
                isinstance(data, dict)
                and data.get("food_cost_target") == "28-35%"
                and data.get("labor_cost_target") == "25-30%"
                and data.get("prime_cost_target") == "55-65%"
                and isinstance(data.get("food_cost_target"), str)
                and isinstance(data.get("labor_cost_target"), str)
                and isinstance(data.get("prime_cost_target"), str)
            )
            if ok:
                checks["targets_values_correct"] = True
        except Exception:
            pass

    # 3) revenue_forecast.csv validations
    month_order = [
        "January","February","March","April","May","June",
        "July","August","September","October","November","December"
    ]
    month_ranges = {
        "January": (80, 85),
        "February": (85, 95),
        "March": (95, 100),
        "April": (100, 105),
        "May": (105, 115),
        "June": (105, 110),
        "July": (100, 105),
        "August": (95, 100),
        "September": (95, 100),
        "October": (100, 105),
        "November": (105, 115),
        "December": (110, 120),
    }

    if os.path.isfile(forecast_out_path):
        checks["revenue_forecast_exists"] = True
        try:
            rows = load_csv_dict(forecast_out_path)
            # Header check
            fieldnames = rows[0].keys() if rows else []
            cleaned = clean_header(fieldnames)
            expected_cols = {"Month", "IndexLow", "IndexHigh", "IndexMidpoint", "ForecastRevenue"}
            if expected_cols.issubset(set(cleaned)):
                checks["revenue_forecast_header_ok"] = True

            # 12 rows check
            if len(rows) == 12:
                checks["revenue_forecast_12_rows"] = True

            # Calendar order and values checks
            order_ok = True
            indices_ok = True
            mid_ok = True
            forecast_ok = True

            for idx, row in enumerate(rows):
                normalized = { (k.strip() if isinstance(k, str) else k): v for k, v in row.items() }
                month = (normalized.get("Month") or "").strip()
                if idx < len(month_order):
                    if month != month_order[idx]:
                        order_ok = False
                else:
                    order_ok = False

                if month in month_ranges:
                    low_expected, high_expected = month_ranges[month]
                    low_val = to_float(normalized.get("IndexLow"))
                    high_val = to_float(normalized.get("IndexHigh"))
                    mid_val = to_float(normalized.get("IndexMidpoint"))
                    fr_val = to_float(normalized.get("ForecastRevenue"))
                    # Indices exact match
                    if low_val is None or high_val is None:
                        indices_ok = False
                    else:
                        if abs(low_val - low_expected) > 1e-6 or abs(high_val - high_expected) > 1e-6:
                            indices_ok = False
                    # Midpoint check
                    if mid_val is None:
                        mid_ok = False
                    else:
                        expected_mid = (low_expected + high_expected) / 2.0
                        if abs(mid_val - expected_mid) > 1e-6:
                            mid_ok = False
                    # Forecast check
                    if base_monthly_revenue is None or fr_val is None:
                        forecast_ok = False
                    else:
                        expected_mid = (low_expected + high_expected) / 2.0
                        expected_forecast = round_nearest_dollar(float(base_monthly_revenue) * (expected_mid / 100.0))
                        # Accept both int and float formatted values as long as numerically equal
                        try:
                            if int(round_nearest_dollar(fr_val)) != expected_forecast:
                                forecast_ok = False
                        except Exception:
                            forecast_ok = False
                else:
                    indices_ok = False
                    mid_ok = False
                    forecast_ok = False

            if order_ok:
                checks["revenue_forecast_calendar_order"] = True
            if indices_ok:
                checks["revenue_forecast_indices_correct"] = True
            if mid_ok:
                checks["revenue_forecast_midpoints_correct"] = True
            if forecast_ok:
                checks["revenue_forecast_values_correct"] = True
        except Exception:
            pass

    # 4) ops_plan.md validations
    if os.path.isfile(ops_plan_path):
        checks["ops_plan_exists"] = True
        try:
            with open(ops_plan_path, "r", encoding="utf-8") as f:
                content = f.read()
            required_phrases = [
                "Stars",
                "Plowhorses",
                "Puzzles",
                "Dogs",
                "RevPASH",
                "Prime cost",
                "Servers",
                "Bartender",
                "Host",
                "Busser",
                "Manager",
                "Promote",
                "Re-engineer",
                "Reposition",
                "Remove",
            ]
            if all(p in content for p in required_phrases):
                checks["ops_plan_keywords_present"] = True
        except Exception:
            pass

    # Compute reward
    required_files_exist = (
        checks["menu_engineering_exists"] and
        checks["targets_exists"] and
        checks["revenue_forecast_exists"] and
        checks["ops_plan_exists"]
    )

    # Define which checks contribute to score (exclude pure existence flags to avoid double punishment)
    scored_flags = [
        "menu_engineering_header_ok",
        "menu_engineering_all_items_present",
        "menu_engineering_no_duplicate_items",
        "menu_engineering_categories_correct",
        "targets_values_correct",
        "revenue_forecast_header_ok",
        "revenue_forecast_12_rows",
        "revenue_forecast_calendar_order",
        "revenue_forecast_indices_correct",
        "revenue_forecast_midpoints_correct",
        "revenue_forecast_values_correct",
        "ops_plan_keywords_present",
    ]

    if not required_files_exist:
        reward = 0.0
    else:
        total = len(scored_flags)
        passed = sum(1 for k in scored_flags if checks.get(k, False))
        reward = (passed / total) if total > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()