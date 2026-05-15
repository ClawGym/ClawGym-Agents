import csv
import json
import math
import os
import re
import sys
from collections import defaultdict, OrderedDict
from datetime import datetime

def parse_float(s):
    try:
        if isinstance(s, (int, float)):
            return float(s)
        s = (s or "").strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None

def is_iso_date(s):
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except Exception:
        return False

def read_csv_dicts(path):
    with open(path, "r", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        rows = list(rdr)
        headers = rdr.fieldnames if rdr.fieldnames is not None else []
        return headers, rows

def file_nonempty(path):
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default)
    checks = OrderedDict()
    def add_check(name, value=False):
        checks[name] = bool(value)

    # Forecasts checks
    add_check("forecasts_exists")
    add_check("forecasts_has_rows")
    add_check("forecasts_headers_ok")
    add_check("forecasts_min_rows_per_pair")
    add_check("forecasts_total_equals_sum")
    add_check("forecasts_week_start_iso")
    add_check("forecasts_method_nonempty")

    # Safety stock checks
    add_check("safety_exists")
    add_check("safety_has_rows")
    add_check("safety_headers_ok")
    add_check("safety_nonnegatives")
    add_check("safety_lower_bound_ok")
    add_check("safety_formula_nonempty")

    # Replenishment checks
    add_check("replenishment_exists")
    add_check("replenishment_has_rows")
    add_check("replenishment_headers_ok")
    add_check("replenishment_case_pack_valid")
    add_check("replenishment_thresholds_ok")
    add_check("replenishment_reco_logic")
    add_check("replenishment_multiple_of_case_pack")

    # Classification checks
    add_check("classification_exists")
    add_check("classification_has_rows")
    add_check("classification_headers_ok")
    add_check("classification_classes_ok")
    add_check("classification_cv_nonneg")

    # Recommendations memo checks
    add_check("recommendations_exists")
    add_check("recommendations_headings_ok")
    add_check("recommendations_keywords_ok")
    add_check("recommendations_bullets_ok")

    # Cross-file checks
    add_check("cross_repl_subset_of_forecast_and_safety")
    add_check("cross_common_pair_present")

    # Paths
    forecasts_path = os.path.join(output_dir, "forecasts.csv")
    safety_path = os.path.join(output_dir, "safety_stock.csv")
    replen_path = os.path.join(output_dir, "replenishment.csv")
    classif_path = os.path.join(output_dir, "classification.csv")
    memo_path = os.path.join(output_dir, "recommendations.md")
    inventory_path = os.path.join(input_dir, "inventory.csv")

    # Load inventory pairs (sku, location)
    inventory_pairs = set()
    if os.path.isfile(inventory_path):
        try:
            inv_headers, inv_rows = read_csv_dicts(inventory_path)
            for r in inv_rows:
                sku = (r.get("sku") or "").strip()
                loc = (r.get("location") or "").strip()
                if sku and loc:
                    inventory_pairs.add((sku, loc))
        except Exception:
            # If cannot read, leave empty (dependent checks will fail)
            inventory_pairs = set()

    # Forecasts
    expected_forecast_headers = ["sku", "location", "week_start", "baseline_fcst_units", "promo_lift_units", "total_fcst_units", "lower_ci", "upper_ci", "method"]
    forecasts_headers = []
    forecasts_rows = []
    if file_nonempty(forecasts_path):
        add_check("forecasts_exists", True)
        try:
            forecasts_headers, forecasts_rows = read_csv_dicts(forecasts_path)
            # has rows?
            if len(forecasts_rows) > 0:
                add_check("forecasts_has_rows", True)
            # headers ok
            if forecasts_headers == expected_forecast_headers:
                add_check("forecasts_headers_ok", True)
            # Validate per-row arithmetic and fields
            tol = 1e-6
            all_sum_ok = True
            all_dates_ok = True
            all_methods_ok = True
            for r in forecasts_rows:
                b = parse_float(r.get("baseline_fcst_units"))
                l = parse_float(r.get("promo_lift_units"))
                t = parse_float(r.get("total_fcst_units"))
                if b is None or l is None or t is None or not math.isfinite(b) or not math.isfinite(l) or not math.isfinite(t):
                    all_sum_ok = False
                else:
                    if abs((b + l) - t) > tol:
                        all_sum_ok = False
                ws = (r.get("week_start") or "").strip()
                if not is_iso_date(ws):
                    all_dates_ok = False
                method = (r.get("method") or "").strip()
                if method == "":
                    all_methods_ok = False
            if all_sum_ok:
                add_check("forecasts_total_equals_sum", True)
            if all_dates_ok:
                add_check("forecasts_week_start_iso", True)
            if all_methods_ok:
                add_check("forecasts_method_nonempty", True)
            # rows per pair (for inventory pairs)
            if inventory_pairs:
                counts = defaultdict(int)
                for r in forecasts_rows:
                    sku = (r.get("sku") or "").strip()
                    loc = (r.get("location") or "").strip()
                    if sku and loc and (sku, loc) in inventory_pairs:
                        counts[(sku, loc)] += 1
                min8 = True
                for pair in inventory_pairs:
                    if counts.get(pair, 0) < 8:
                        min8 = False
                        break
                if min8:
                    add_check("forecasts_min_rows_per_pair", True)
        except Exception:
            # If parsing fails, leave specific checks as False
            pass

    # Safety stock
    expected_safety_headers = ["sku", "location", "service_level", "z", "demand_sigma_weekly", "lead_time_days", "lead_time_sigma_days", "review_period_days", "safety_stock_units", "formula_used"]
    safety_headers = []
    safety_rows = []
    if file_nonempty(safety_path):
        add_check("safety_exists", True)
        try:
            safety_headers, safety_rows = read_csv_dicts(safety_path)
            if len(safety_rows) > 0:
                add_check("safety_has_rows", True)
            if safety_headers == expected_safety_headers:
                add_check("safety_headers_ok", True)
            # Validate rows
            tol = 1e-6
            all_nonneg = True
            all_lb_ok = True
            all_formula_nonempty = True
            for r in safety_rows:
                z = parse_float(r.get("z"))
                sigma = parse_float(r.get("demand_sigma_weekly"))
                lt_days = parse_float(r.get("lead_time_days"))
                rp_days = parse_float(r.get("review_period_days"))
                ss = parse_float(r.get("safety_stock_units"))
                # Nonnegatives as specified
                if z is None or sigma is None or lt_days is None or rp_days is None or ss is None:
                    all_nonneg = False
                else:
                    if z < 0 or sigma < 0 or lt_days < 0 or rp_days < 0 or ss < 0:
                        all_nonneg = False
                # Lower bound check
                if z is None or sigma is None or lt_days is None or rp_days is None or ss is None:
                    all_lb_ok = False
                else:
                    risk_weeks = max((lt_days + rp_days) / 7.0, 1e-9)
                    lb = z * sigma * math.sqrt(risk_weeks)
                    if ss + tol < lb:
                        all_lb_ok = False
                # formula used
                formula_used = (r.get("formula_used") or "").strip()
                if formula_used == "":
                    all_formula_nonempty = False
            if all_nonneg:
                add_check("safety_nonnegatives", True)
            if all_lb_ok:
                add_check("safety_lower_bound_ok", True)
            if all_formula_nonempty:
                add_check("safety_formula_nonempty", True)
        except Exception:
            pass

    # Replenishment
    expected_replen_headers = ["sku", "location", "inventory_position_units", "reorder_point_units", "order_up_to_units", "eoq_units", "case_pack", "recommended_order_units", "policy"]
    replen_headers = []
    replen_rows = []
    if file_nonempty(replen_path):
        add_check("replenishment_exists", True)
        try:
            replen_headers, replen_rows = read_csv_dicts(replen_path)
            if len(replen_rows) > 0:
                add_check("replenishment_has_rows", True)
            if replen_headers == expected_replen_headers:
                add_check("replenishment_headers_ok", True)
            # Validate rows
            tol = 1e-6
            cp_valid_all = True
            thresholds_all_ok = True
            reco_logic_all_ok = True
            multiple_all_ok = True
            for r in replen_rows:
                ip = parse_float(r.get("inventory_position_units"))
                rop = parse_float(r.get("reorder_point_units"))
                out = parse_float(r.get("order_up_to_units"))
                eoq = parse_float(r.get("eoq_units"))
                cp_raw = parse_float(r.get("case_pack"))
                rec = parse_float(r.get("recommended_order_units"))
                # Case pack: treat <=0 as 1 for divisibility; check valid numeric
                if cp_raw is None or not math.isfinite(cp_raw):
                    cp_valid_all = False
                    cp_val = 1
                else:
                    cp_val = int(round(cp_raw))
                    if cp_val < 1:
                        cp_val = 1
                # Thresholds
                if ip is None or rop is None or out is None or eoq is None:
                    thresholds_all_ok = False
                else:
                    if rop < 0 or out < rop - tol or eoq < -tol:
                        thresholds_all_ok = False
                # Multiple of case pack and reco logic
                if rec is None or ip is None or rop is None:
                    reco_logic_all_ok = False
                    multiple_all_ok = False
                else:
                    # reco logic
                    if ip + tol >= rop:
                        if abs(rec) > tol:
                            reco_logic_all_ok = False
                    else:
                        if rec <= tol:
                            reco_logic_all_ok = False
                    # multiple
                    # Check rec is a multiple of cp_val
                    if cp_val <= 0:
                        cp_val = 1
                    k = round(rec / cp_val) if cp_val != 0 else 0
                    if abs(rec - k * cp_val) > 1e-6:
                        multiple_all_ok = False
            if cp_valid_all:
                add_check("replenishment_case_pack_valid", True)
            if thresholds_all_ok:
                add_check("replenishment_thresholds_ok", True)
            if reco_logic_all_ok:
                add_check("replenishment_reco_logic", True)
            if multiple_all_ok:
                add_check("replenishment_multiple_of_case_pack", True)
        except Exception:
            pass

    # Classification
    expected_classif_headers = ["sku", "abc_class", "xyz_class", "margin_contribution_dollars", "cv_demand"]
    classif_headers = []
    classif_rows = []
    if file_nonempty(classif_path):
        add_check("classification_exists", True)
        try:
            classif_headers, classif_rows = read_csv_dicts(classif_path)
            if len(classif_rows) > 0:
                add_check("classification_has_rows", True)
            if classif_headers == expected_classif_headers:
                add_check("classification_headers_ok", True)
            classes_ok = True
            cv_ok = True
            for r in classif_rows:
                a = (r.get("abc_class") or "").strip()
                x = (r.get("xyz_class") or "").strip()
                if a not in {"A", "B", "C"} or x not in {"X", "Y", "Z"}:
                    classes_ok = False
                cv = parse_float(r.get("cv_demand"))
                if cv is None or cv < 0:
                    cv_ok = False
                # margin_contribution_dollars: any real number, ensure parsable
                m = parse_float(r.get("margin_contribution_dollars"))
                if m is None and (r.get("margin_contribution_dollars") or "").strip() != "":
                    # non-numeric string provided
                    classes_ok = False
            if classes_ok:
                add_check("classification_classes_ok", True)
            if cv_ok:
                add_check("classification_cv_nonneg", True)
        except Exception:
            pass

    # Recommendations memo
    if file_nonempty(memo_path):
        add_check("recommendations_exists", True)
        try:
            with open(memo_path, "r", encoding="utf-8") as f:
                memo = f.read()
            lines = memo.splitlines()
            # Headings check (case-insensitive), lines starting with # or ##
            required_headings = [
                "Assumptions",
                "Forecast Method Choices",
                "Promo Plan",
                "Markdown Recommendations",
                "Slow-Mover Actions",
                "Risks & Escalations",
            ]
            headings_found = {h: False for h in required_headings}
            for ln in lines:
                s = ln.strip()
                if s.startswith("#"):
                    # strip leading #'s and spaces
                    s2 = s.lstrip("#").strip()
                    for h in required_headings:
                        if s2.lower() == h.lower():
                            headings_found[h] = True
            if all(headings_found.values()):
                add_check("recommendations_headings_ok", True)
            # Keywords
            memo_lc = memo.lower()
            kw_ok = ("cannibalization" in memo_lc) and ("post-promo dip" in memo_lc) and (("weeks of supply" in memo_lc) or ("wos" in memo_lc))
            if kw_ok:
                add_check("recommendations_keywords_ok", True)
            # Bullets: lines starting with '-' or '*'
            bullet_count = 0
            for ln in lines:
                s = ln.lstrip()
                if s.startswith("-") or s.startswith("*"):
                    bullet_count += 1
            if bullet_count >= 5:
                add_check("recommendations_bullets_ok", True)
        except Exception:
            pass

    # Cross-file integrity
    # replenishment pairs subset of forecasts and safety
    forecast_pairs = set()
    for r in forecasts_rows:
        sku = (r.get("sku") or "").strip()
        loc = (r.get("location") or "").strip()
        if sku and loc:
            forecast_pairs.add((sku, loc))
    safety_pairs = set()
    for r in safety_rows:
        sku = (r.get("sku") or "").strip()
        loc = (r.get("location") or "").strip()
        if sku and loc:
            safety_pairs.add((sku, loc))
    replen_pairs = set()
    for r in replen_rows:
        sku = (r.get("sku") or "").strip()
        loc = (r.get("location") or "").strip()
        if sku and loc:
            replen_pairs.add((sku, loc))

    if replen_pairs:
        subset_ok = replen_pairs.issubset(forecast_pairs) and replen_pairs.issubset(safety_pairs)
        if subset_ok:
            add_check("cross_repl_subset_of_forecast_and_safety", True)
        # Common pair across all three
        common = forecast_pairs & safety_pairs & replen_pairs
        if len(common) >= 1:
            add_check("cross_common_pair_present", True)

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks
    # Ensure no-op baseline yields 0.0: if no output files exist, reward must be 0.0
    outputs_exist = any(os.path.isfile(p) for p in [forecasts_path, safety_path, replen_path, classif_path, memo_path])
    if not outputs_exist:
        reward = 0.0

    # Print JSON with "reward" first
    result = OrderedDict()
    result["reward"] = round(float(reward), 6)
    for k, v in checks.items():
        result[k] = v
    print(json.dumps(result))

if __name__ == "__main__":
    main()