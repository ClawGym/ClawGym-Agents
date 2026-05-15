import csv
import json
import math
import os
import re
import sys

def load_positions_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_thresholds_yaml(path):
    # Minimal YAML parser for simple key: value pairs
    data = {}
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # handle inline comments
            if "#" in line:
                line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val.endswith(","):
                val = val[:-1].strip()
            # Remove quotes
            if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
                val = val[1:-1]
            try:
                num = float(val)
                data[key] = num
            except ValueError:
                # not numeric; ignore for our use-case
                pass
    return data

def to_float(x):
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip().replace(",", "")
        # Remove currency symbols if any slipped into CSV (should not, but robust)
        s = s.replace("$", "")
        try:
            return float(s)
        except ValueError:
            return float("nan")
    return float("nan")

def abs_close(a, b, tol=0.02):
    if math.isinf(a) and math.isinf(b):
        return True
    if math.isnan(a) or math.isnan(b):
        return False
    return abs(a - b) <= tol

def risk_from_ratio(hr, th):
    # th keys: green, yellow, orange
    g = th.get("green")
    y = th.get("yellow")
    o = th.get("orange")
    # hr can be inf when debt is 0
    if hr >= g:
        return "Green"
    elif hr >= y:
        return "Yellow"
    elif hr >= o:
        return "Orange"
    else:
        return "Red"

def compute_metrics(wallet, sol_price_now):
    collateral = float(wallet["collateral_usd"])
    debt = float(wallet["debt_usd"])
    ll = float(wallet["liquidation_ltv"])
    net = collateral - debt
    ltv_percent = (100.0 * debt / collateral) if collateral != 0 else float("inf")
    health_ratio = (ll * collateral / debt) if debt != 0 else float("inf")
    health_percent = (100.0 * (health_ratio - 1.0) / health_ratio) if not math.isinf(health_ratio) and health_ratio != 0 else 100.0
    sol_liq_price = sol_price_now * (debt / (ll * collateral)) if collateral != 0 and ll != 0 else float("inf") if debt > 0 else 0.0
    rec_deposit = max(0.0, 2.5 * debt / ll - collateral) if ll != 0 else 0.0
    rec_repay = max(0.0, debt - (collateral * ll) / 2.5)
    return {
        "net_usd": net,
        "ltv_percent": ltv_percent,
        "health_ratio": health_ratio,
        "health_percent": health_percent,
        "sol_liq_price": sol_liq_price,
        "recommendation_deposit_usd": rec_deposit,
        "recommendation_repay_usd": rec_repay,
    }

def recompute_totals_for_drop(wallets, drop_frac):
    total_deposit = 0.0
    total_repay = 0.0
    for w in wallets:
        collateral = float(w["collateral_usd"]) * (1.0 - drop_frac)
        debt = float(w["debt_usd"])
        ll = float(w["liquidation_ltv"])
        rec_dep = max(0.0, 2.5 * debt / ll - collateral) if ll != 0 else 0.0
        rec_rep = max(0.0, debt - (collateral * ll) / 2.5)
        total_deposit += rec_dep
        total_repay += rec_rep
    return total_deposit, total_repay

def find_section_lines_after(marker, lines):
    for i, ln in enumerate(lines):
        if marker in ln:
            return lines[i+1:]
    return []

def extract_amount_after_keyword(line, keyword):
    # Find the first $amount after the keyword text (case-insensitive)
    # Pattern: keyword ... $X or keyword ... X (if $ missing)
    # Prefer $ but fallback to bare numbers
    key_idx = line.lower().find(keyword.lower())
    if key_idx == -1:
        return None
    substr = line[key_idx:]
    # First try with $amount
    m = re.search(r"\$(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)", substr)
    if m:
        val = m.group(1).replace(",", "")
        try:
            return float(val)
        except:
            return None
    # Fallback: bare number (avoid percentages by excluding % right after digits)
    m2 = re.search(r"\b(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)(?!\s*%)", substr)
    if m2:
        val = m2.group(1).replace(",", "")
        try:
            return float(val)
        except:
            return None
    return None

def any_number_matches_value(text, target, tol=0.01):
    # Find all numbers (optionally prefixed by $ or ~) and check if any ~ target
    nums = re.findall(r"[~$]?\s*(-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)", text)
    for s in nums:
        try:
            v = float(s.replace(",", ""))
            if abs(v - target) <= tol:
                return True
        except:
            continue
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir not used but defined for completeness
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "csv_exists": False,
        "csv_has_required_columns": False,
        "csv_row_count_match": False,
        "csv_values_correct": False,
        "csv_risk_levels_correct": False,
        "report_exists": False,
        "report_has_global_summary": False,
        "report_contains_addresses": False,
        "report_contains_sol_price_now": False,
        "report_has_if_sol_drops": False,
        "report_has_10_percent_line": False,
        "report_has_20_percent_line": False,
        "what_if_10_percent_totals_match": False,
        "what_if_20_percent_totals_match": False,
        "disclaimer_present": False,
    }

    # Load inputs
    positions_path = os.path.join(input_dir, "positions.json")
    thresholds_path = os.path.join(input_dir, "thresholds.yaml")

    # If inputs are missing, we still cannot give positive rewards (but they should exist per task)
    try:
        positions = load_positions_json(positions_path)
        sol_price_now = float(positions.get("sol_price_now"))
        wallets = positions.get("wallets", [])
    except Exception:
        positions = None
        sol_price_now = None
        wallets = []

    try:
        thresholds = parse_thresholds_yaml(thresholds_path)
    except Exception:
        thresholds = {}

    # CSV checks
    csv_path = os.path.join(output_dir, "summary.csv")
    if os.path.isfile(csv_path):
        checks["csv_exists"] = True
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                header = reader.fieldnames or []
                required_cols = [
                    "address",
                    "collateral_usd",
                    "debt_usd",
                    "net_usd",
                    "ltv_percent",
                    "health_ratio",
                    "health_percent",
                    "sol_price_now",
                    "sol_liq_price",
                    "recommendation_deposit_usd",
                    "recommendation_repay_usd",
                    "risk_level",
                ]
                if all(col in header for col in required_cols):
                    checks["csv_has_required_columns"] = True
                rows = list(reader)
            if positions is not None and len(rows) == len(wallets):
                checks["csv_row_count_match"] = True

            # Build wallet map by address
            wallet_map = {w["address"]: w for w in wallets} if positions is not None else {}
            all_values_ok = True
            all_risks_ok = True

            for row in rows:
                addr = row.get("address", "")
                if addr not in wallet_map:
                    all_values_ok = False
                    all_risks_ok = False
                    break
                w = wallet_map[addr]
                # Parse provided numbers
                row_coll = to_float(row.get("collateral_usd", "nan"))
                row_debt = to_float(row.get("debt_usd", "nan"))
                row_net = to_float(row.get("net_usd", "nan"))
                row_ltv = to_float(row.get("ltv_percent", "nan"))
                row_hr = to_float(row.get("health_ratio", "nan"))
                row_hp = to_float(row.get("health_percent", "nan"))
                row_spn = to_float(row.get("sol_price_now", "nan"))
                row_slp = to_float(row.get("sol_liq_price", "nan"))
                row_dep = to_float(row.get("recommendation_deposit_usd", "nan"))
                row_rep = to_float(row.get("recommendation_repay_usd", "nan"))
                row_risk = (row.get("risk_level") or "").strip()

                # Compute expected
                expected = compute_metrics(w, sol_price_now if sol_price_now is not None else 0.0)

                # Compare base fields equality
                if not abs_close(row_coll, float(w["collateral_usd"]), 0.02): all_values_ok = False
                if not abs_close(row_debt, float(w["debt_usd"]), 0.02): all_values_ok = False
                if not abs_close(row_net, expected["net_usd"], 0.02): all_values_ok = False
                if not abs_close(row_ltv, expected["ltv_percent"], 0.02): all_values_ok = False
                if not abs_close(row_hr, expected["health_ratio"], 0.02): all_values_ok = False
                if not abs_close(row_hp, expected["health_percent"], 0.02): all_values_ok = False
                if sol_price_now is None or not abs_close(row_spn, sol_price_now, 0.02): all_values_ok = False
                if not abs_close(row_slp, expected["sol_liq_price"], 0.02): all_values_ok = False
                if not abs_close(row_dep, expected["recommendation_deposit_usd"], 0.02): all_values_ok = False
                if not abs_close(row_rep, expected["recommendation_repay_usd"], 0.02): all_values_ok = False

                # Risk label
                # If thresholds missing, cannot validate positively
                if thresholds and isinstance(row_hr, float) and not math.isnan(row_hr):
                    # When row_hr is inf due to debt 0, passing thresholds should be Green
                    computed_risk = risk_from_ratio(row_hr, thresholds)
                    if row_risk != computed_risk:
                        all_risks_ok = False
                else:
                    all_risks_ok = False

            if all_values_ok:
                checks["csv_values_correct"] = True
            if all_risks_ok:
                checks["csv_risk_levels_correct"] = True
        except Exception:
            pass

    # Report checks
    report_path = os.path.join(output_dir, "report.txt")
    report_text = ""
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_text = f.read()
            if "GLOBAL SUMMARY" in report_text:
                checks["report_has_global_summary"] = True
            # Addresses present
            if positions is not None:
                present_all = True
                for w in wallets:
                    if w.get("address") not in report_text:
                        present_all = False
                        break
                if present_all:
                    checks["report_contains_addresses"] = True
            # sol_price_now value mentioned (as a number somewhere)
            if positions is not None and sol_price_now is not None:
                if any_number_matches_value(report_text, sol_price_now, tol=0.01):
                    checks["report_contains_sol_price_now"] = True
            # "If SOL drops:" section
            if "If SOL drops:" in report_text:
                checks["report_has_if_sol_drops"] = True
                lines = report_text.splitlines()
                tail_lines = find_section_lines_after("If SOL drops:", lines)

                # Find lines containing 10% and 20%
                ten_line = None
                twenty_line = None
                for ln in tail_lines:
                    if "10%" in ln:
                        if ten_line is None:
                            ten_line = ln
                    if "20%" in ln:
                        if twenty_line is None:
                            twenty_line = ln
                    # Stop early if both found
                    if ten_line and twenty_line:
                        break
                if ten_line is not None:
                    checks["report_has_10_percent_line"] = True
                if twenty_line is not None:
                    checks["report_has_20_percent_line"] = True

                # Validate totals within ±2%
                def within_two_percent(reported, expected):
                    if expected == 0:
                        return abs(reported - expected) <= 0.02
                    return abs(reported - expected) <= 0.02 * abs(expected)

                if positions is not None and wallets:
                    # 10%
                    if ten_line is not None:
                        dep_val = extract_amount_after_keyword(ten_line, "deposit")
                        rep_val = extract_amount_after_keyword(ten_line, "repay")
                        exp_dep, exp_rep = recompute_totals_for_drop(wallets, 0.10)
                        if dep_val is not None and rep_val is not None:
                            if within_two_percent(dep_val, exp_dep) and within_two_percent(rep_val, exp_rep):
                                checks["what_if_10_percent_totals_match"] = True
                    # 20%
                    if twenty_line is not None:
                        dep_val = extract_amount_after_keyword(twenty_line, "deposit")
                        rep_val = extract_amount_after_keyword(twenty_line, "repay")
                        exp_dep, exp_rep = recompute_totals_for_drop(wallets, 0.20)
                        if dep_val is not None and rep_val is not None:
                            if within_two_percent(dep_val, exp_dep) and within_two_percent(rep_val, exp_rep):
                                checks["what_if_20_percent_totals_match"] = True

            # Disclaimer
            if re.search(r"not\s+financial\s+advice", report_text, flags=re.IGNORECASE):
                checks["disclaimer_present"] = True
        except Exception:
            pass

    # Compute reward: average of passed checks (booleans)
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # Ensure no-op baseline yields 0.0 when outputs missing
    if not os.path.isdir(output_dir) or (not checks["csv_exists"] and not checks["report_exists"]):
        reward = 0.0

    # Print final JSON (reward first key)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()