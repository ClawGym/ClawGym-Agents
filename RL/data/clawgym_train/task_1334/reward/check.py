import json
import os
import sys
import csv
import re

def parse_num(val):
    if isinstance(val, (int, float)):
        return float(val)
    if val is None:
        raise ValueError("None is not a number")
    s = str(val).strip()
    if s == "":
        raise ValueError("Empty string")
    divide_by_100 = False
    if "%" in s:
        s = s.replace("%", "")
        divide_by_100 = True
    s = s.replace("$", "").replace(",", "")
    # Handle parentheses for negatives e.g., (123.45)
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    f = float(s)
    if divide_by_100:
        f = f / 100.0
    return f

def read_csv_dicts(path):
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Normalize header whitespace
        fieldnames = [h.strip() if h is not None else "" for h in (reader.fieldnames or [])]
        rows = []
        for row in reader:
            # Strip keys and values whitespace
            cleaned = {}
            empty = True
            for k, v in row.items():
                key = k.strip() if k is not None else ""
                val = v.strip() if isinstance(v, str) else v
                if isinstance(val, str) and val != "":
                    empty = False
                if isinstance(val, (int, float)):
                    empty = False
                cleaned[key] = val
            if not empty:
                rows.append(cleaned)
        return fieldnames, rows

def file_nonempty(path):
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except Exception:
        return False

def contains_case_insensitive(text, substr):
    return substr.lower() in text.lower()

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def match_channel(name, target):
    n = (name or "").strip().lower()
    t = target.strip().lower()
    if t == "google lsa":
        return ("google lsa" in n) or ("local services ads" in n) or ("lsa" in n and "google" in n)
    if t == "google business profile":
        return ("google business profile" in n) or ("gbp" in n) or ("google my business" in n)
    if t == "seo":
        return "seo" in n
    if t == "referral program":
        return "referral program" in n or "referral" in n
    return t in n

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # 1) flat_rate_book.csv checks
    flat_path = os.path.join(output_dir, "pricing", "flat_rate_book.csv")
    checks["flat_exists"] = os.path.isfile(flat_path)
    checks["flat_csv_ok"] = False
    checks["flat_columns_order_ok"] = False
    checks["flat_min_rows"] = False
    checks["flat_numeric_parseable"] = False
    checks["flat_margin_range"] = False
    checks["flat_after_hours_multiplier_range"] = False
    checks["flat_has_drain_priced_in_range"] = False
    checks["flat_has_water_heater_tank_in_range"] = False
    checks["flat_has_water_heater_tankless_in_range"] = False

    flat_rows = []
    if checks["flat_exists"]:
        try:
            fieldnames, rows = read_csv_dicts(flat_path)
            checks["flat_csv_ok"] = True
            required_order = ["task", "category", "labor_hours", "material_cost", "labor_cost", "flat_rate_price", "margin_pct", "after_hours_price"]
            # Normalize header whitespace for comparison
            if fieldnames == required_order:
                checks["flat_columns_order_ok"] = True
            # Data rows count
            if len(rows) >= 20:
                checks["flat_min_rows"] = True
            flat_rows = rows

            # Numeric parse and range checks
            numeric_ok = True
            margin_ok = True
            ah_ratio_ok = True
            drain_ok = False
            tank_ok = False
            tankless_ok = False

            for r in rows:
                try:
                    lh = parse_num(r.get("labor_hours", ""))
                    mc = parse_num(r.get("material_cost", ""))
                    lc = parse_num(r.get("labor_cost", ""))
                    fr = parse_num(r.get("flat_rate_price", ""))
                    mp = parse_num(r.get("margin_pct", ""))
                    ah = parse_num(r.get("after_hours_price", ""))
                except Exception:
                    numeric_ok = False
                    # continue to gather all failures but break not necessary
                    continue

                # margin within [0.55, 0.65]
                if not (0.55 <= mp <= 0.65):
                    margin_ok = False
                # after hours ratio within [1.5, 2.0]
                if fr == 0:
                    ah_ratio_ok = False
                else:
                    ratio = ah / fr
                    if not (1.5 <= ratio <= 2.0):
                        ah_ratio_ok = False

                task_name = (r.get("task") or "")
                # Drain cleaning task priced 150-350
                if (not drain_ok) and ("drain" in task_name.lower()):
                    try:
                        if 150 <= fr <= 350:
                            drain_ok = True
                    except Exception:
                        pass
                # Water heater tank (non-tankless)
                if (not tank_ok) and ("water heater" in task_name.lower()) and ("tankless" not in task_name.lower()):
                    try:
                        if 1200 <= fr <= 3500:
                            tank_ok = True
                    except Exception:
                        pass
                # Water heater tankless
                if (not tankless_ok) and ("water heater" in task_name.lower()) and ("tankless" in task_name.lower()):
                    try:
                        if 2500 <= fr <= 5500:
                            tankless_ok = True
                    except Exception:
                        pass

            checks["flat_numeric_parseable"] = numeric_ok and len(rows) > 0
            checks["flat_margin_range"] = margin_ok and len(rows) > 0 and numeric_ok
            checks["flat_after_hours_multiplier_range"] = ah_ratio_ok and len(rows) > 0 and numeric_ok
            checks["flat_has_drain_priced_in_range"] = drain_ok
            checks["flat_has_water_heater_tank_in_range"] = tank_ok
            checks["flat_has_water_heater_tankless_in_range"] = tankless_ok

        except Exception:
            # leave defaults as False
            pass

    # 2) assumptions.md
    assumptions_path = os.path.join(output_dir, "pricing", "assumptions.md")
    checks["assumptions_exists_nonempty"] = file_nonempty(assumptions_path)

    # 3) dispatch_sop.md
    sop_path = os.path.join(output_dir, "ops", "dispatch_sop.md")
    checks["sop_exists_nonempty"] = file_nonempty(sop_path)
    checks["sop_required_phrases_present"] = False
    if checks["sop_exists_nonempty"]:
        try:
            with open(sop_path, "r", encoding="utf-8") as f:
                content = f.read()
            c = content.lower()
            must_subs = [
                "morning huddle",
                "2-hour",
                "8-10",
                "10-12",
                "12-2",
                "2-4",
                "zone",
                "drive time",
                "callback",
            ]
            ok = all(sub in c for sub in must_subs)
            util_ok = ("75%" in c) or ("85%" in c)
            checks["sop_required_phrases_present"] = ok and util_ok
        except Exception:
            checks["sop_required_phrases_present"] = False

    # 4) truck_stock.csv
    stock_path = os.path.join(output_dir, "inventory", "truck_stock.csv")
    checks["stock_exists"] = os.path.isfile(stock_path)
    checks["stock_csv_ok"] = False
    checks["stock_required_columns_present"] = False
    checks["stock_min_rows"] = False
    checks["stock_category_coverage"] = False

    if checks["stock_exists"]:
        try:
            fieldnames, rows = read_csv_dicts(stock_path)
            checks["stock_csv_ok"] = True
            required_cols = ["item", "category", "size", "par_min", "par_max", "notes"]
            if all(col in fieldnames for col in required_cols):
                checks["stock_required_columns_present"] = True
            if len(rows) >= 15:
                checks["stock_min_rows"] = True
            # Category coverage
            targets = ["fittings", "valves", "drain supplies", "water heater parts", "fixtures", "tools"]
            seen = set()
            for r in rows:
                cat = (r.get("category") or "").lower()
                for tgt in targets:
                    if tgt in cat:
                        seen.add(tgt)
            checks["stock_category_coverage"] = len(seen) >= 5
        except Exception:
            # leave as False
            pass

    # 5) marketing/plan.json
    mkt_path = os.path.join(output_dir, "marketing", "plan.json")
    checks["mkt_exists"] = os.path.isfile(mkt_path)
    checks["mkt_json_ok"] = False
    checks["mkt_budget_total_12000"] = False
    checks["mkt_required_channels_present"] = False
    checks["mkt_channel_budgets_positive"] = False
    checks["mkt_budgets_sum_to_total"] = False
    checks["mkt_channel_kpis_valid"] = False
    checks["mkt_gbp_reviews_goal"] = False

    if checks["mkt_exists"]:
        try:
            data = load_json(mkt_path)
            checks["mkt_json_ok"] = True

            bt = data.get("budget_total", None)
            try:
                bt_num = parse_num(bt)
                checks["mkt_budget_total_12000"] = abs(bt_num - 12000.0) < 1e-6
            except Exception:
                checks["mkt_budget_total_12000"] = False
                bt_num = None

            channels = data.get("channels", [])
            # Required channel names
            required_names = ["Google LSA", "Google Business Profile", "SEO", "Referral program"]
            present = {req: False for req in required_names}
            for ch in channels:
                name = ch.get("name", "")
                for req in required_names:
                    if match_channel(name, req):
                        present[req] = True
            checks["mkt_required_channels_present"] = all(present.values()) and isinstance(channels, list) and len(channels) > 0

            # Validate budgets and KPIs
            budgets_positive = True
            kpis_valid = True
            sum_budgets = 0.0
            gbp_reviews_ok = False

            for ch in channels if isinstance(channels, list) else []:
                # budget positive
                try:
                    b = parse_num(ch.get("budget", None))
                    if b <= 0:
                        budgets_positive = False
                    sum_budgets += b
                except Exception:
                    budgets_positive = False
                # target_cpl 25-75 and target_booking_rate >= 0.75
                try:
                    cpl = parse_num(ch.get("target_cpl", None))
                    if not (25 <= cpl <= 75):
                        kpis_valid = False
                except Exception:
                    kpis_valid = False
                try:
                    br = parse_num(ch.get("target_booking_rate", None))
                    if br < 0.75:
                        kpis_valid = False
                except Exception:
                    kpis_valid = False
                # GBP reviews
                if match_channel(ch.get("name", ""), "Google Business Profile"):
                    try:
                        rg = parse_num(ch.get("reviews_goal", None))
                        if rg >= 50:
                            gbp_reviews_ok = True
                    except Exception:
                        gbp_reviews_ok = False

            checks["mkt_channel_budgets_positive"] = budgets_positive and isinstance(channels, list) and len(channels) > 0
            if bt_num is not None:
                checks["mkt_budgets_sum_to_total"] = abs(sum_budgets - bt_num) <= 1.0
            else:
                checks["mkt_budgets_sum_to_total"] = False
            checks["mkt_channel_kpis_valid"] = kpis_valid and isinstance(channels, list) and len(channels) > 0
            checks["mkt_gbp_reviews_goal"] = gbp_reviews_ok

        except Exception:
            # leave as False
            pass

    # Compute reward as average of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure baseline zero if no outputs exist (empty or missing required artifacts)
    # If none of the primary artifact existence checks are true, force reward to 0.0
    primary_exist = any([
        checks.get("flat_exists", False),
        checks.get("assumptions_exists_nonempty", False),
        checks.get("sop_exists_nonempty", False),
        checks.get("stock_exists", False),
        checks.get("mkt_exists", False),
    ])
    if not primary_exist:
        reward = 0.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()