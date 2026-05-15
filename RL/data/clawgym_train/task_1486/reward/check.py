import json
import os
import sys
import csv
import math
from statistics import median

def parse_int(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    s = str(value).strip()
    if s == "":
        return None
    # Remove common formatting characters
    s = s.replace(",", "").replace("$", "").replace("COP", "").replace(" ", "")
    # Remove any non-digit except leading minus
    sign = -1 if s.startswith("-") else 1
    s = s.lstrip("+-")
    digits = "".join(ch for ch in s if ch.isdigit())
    if digits == "":
        return None
    return sign * int(digits)

def parse_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("%", "")
    s = s.replace(",", "")  # assume dot as decimal separator; commas are thousand separators
    try:
        return float(s)
    except:
        # Try to extract digits, dot, minus
        cleaned = "".join(ch for ch in s if (ch.isdigit() or ch in ".-"))
        try:
            return float(cleaned)
        except:
            return None

def read_csv_rows(path):
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader), reader.fieldnames

def read_price_median_from_input(input_prices_csv):
    try:
        rows, headers = read_csv_rows(input_prices_csv)
        if "price_cop" not in (headers or []):
            return None
        prices = []
        for r in rows:
            p = parse_int(r.get("price_cop"))
            if p is not None:
                prices.append(p)
        if not prices:
            return None
        med = median(prices)
        # If even number of values, median may be float; use nearest integer for COP comparisons
        med_int = int(round(med))
        return med_int
    except Exception:
        return None

def read_price_comparison(csv_path):
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            content = f.read().splitlines()
        if not content:
            return None, None, None
        header_line = content[0].strip()
        reader = csv.DictReader(content)
        rows = list(reader)
        return rows, reader.fieldnames, header_line
    except Exception:
        return None, None, None

def mean(values):
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)

def approx_equal(a, b, rel_tol=0.0, abs_tol=0.0):
    if a is None or b is None:
        return False
    return math.isclose(float(a), float(b), rel_tol=rel_tol, abs_tol=abs_tol)

def amortization_monthly_payment(A, r_percent, n_months):
    r = (r_percent or 0.0) / 100.0
    n = int(n_months or 0)
    if n <= 0:
        return None
    if r == 0:
        return A / n
    try:
        payment = A * r / (1 - (1 + r) ** (-n))
        return payment
    except Exception:
        return None

def last_non_empty_print(obj):
    print(json.dumps(obj, ensure_ascii=False))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # price comparison CSV
        "price_csv_exists": False,
        "price_csv_header_ok": False,
        "price_csv_median_matches_input": False,
        "price_csv_diff_percent_ok": False,
        # decision.json
        "decision_exists": False,
        "decision_recommendation_valid": False,
        "decision_budget_units_ok": False,
        "decision_median_matches_csv": False,
        "decision_red_flags_nonempty": False,
        "decision_scams_risk_valid": False,
        "decision_walk_away_present": False,
        "decision_avg_vs_median_percent_ok": False,
        # negotiation scripts
        "scripts_exists": False,
        "scripts_has_bottom_line": False,
        "scripts_has_3_principles": False,
        # financing plan
        "financing_exists": False,
        "financing_entries_match_banks": False,
        "financing_fields_present": False,
        "financing_amount_correct": False,
        "financing_monthly_payment_ok": False,
        "financing_totals_consistent": False,
        # loop history
        "loop_history_exists": False,
        "loop_max_iterations_ok": False,
        "loop_iterations_len_ok": False,
        "loop_status_valid": False,
        "loop_criteria_contains_target": False,
        # research notes
        "research_notes_exists": False,
        "research_notes_nonempty": False,
    }

    # Paths
    input_prices_csv = os.path.join(input_dir, "recent_sold_prices.csv")
    input_financial_csv = os.path.join(input_dir, "financial_options.csv")
    price_csv_path = os.path.join(output_dir, "price_comparison.csv")
    decision_json_path = os.path.join(output_dir, "decision.json")
    scripts_md_path = os.path.join(output_dir, "negotiation_scripts.md")
    financing_json_path = os.path.join(output_dir, "financing_plan.json")
    loop_history_json_path = os.path.join(output_dir, "loop", "history.json")
    research_notes_md_path = os.path.join(output_dir, "research_notes.md")

    # Compute reference market median
    market_median_input = None
    if os.path.isfile(input_prices_csv):
        market_median_input = read_price_median_from_input(input_prices_csv)

    # 1) price_comparison.csv
    price_rows = None
    price_header = None
    price_header_line = None
    if os.path.isfile(price_csv_path):
        checks["price_csv_exists"] = True
        price_rows, price_header, price_header_line = read_price_comparison(price_csv_path)
        expected_header = "id,title,model,ram_gb,storage_gb,condition,price_cop,seller_rating,link,market_median_cop,market_value_diff_percent"
        if price_header_line == expected_header:
            checks["price_csv_header_ok"] = True

        # Validate median and diff percent
        if price_rows is not None and market_median_input is not None:
            all_medians_match = True
            all_diff_ok = True
            prices_for_avg = []
            for r in price_rows:
                try:
                    row_median = parse_int(r.get("market_median_cop"))
                    # Allow ±1 COP tolerance
                    if row_median is None or abs(row_median - market_median_input) > 1:
                        all_medians_match = False
                    price = parse_int(r.get("price_cop"))
                    if price is not None:
                        prices_for_avg.append(price)
                    # diff percent
                    diff_field = r.get("market_value_diff_percent")
                    diff_value = parse_float(diff_field)
                    if price is None or market_median_input in (None, 0):
                        all_diff_ok = False
                    else:
                        expected_diff = 100.0 * (price - market_median_input) / market_median_input
                        expected_rounded = round(expected_diff, 1)
                        # Tolerance ±0.1
                        if diff_value is None or abs(diff_value - expected_rounded) > 0.1 + 1e-9:
                            all_diff_ok = False
                except Exception:
                    all_medians_match = False
                    all_diff_ok = False
                    break
            if all_medians_match:
                checks["price_csv_median_matches_input"] = True
            if all_diff_ok:
                checks["price_csv_diff_percent_ok"] = True
    # Compute avg listing price for later checks
    avg_listing_price = None
    if checks["price_csv_exists"]:
        try:
            prices = [parse_int(r.get("price_cop")) for r in (price_rows or [])]
            prices = [p for p in prices if p is not None]
            if prices:
                avg_listing_price = sum(prices) / len(prices)
        except Exception:
            avg_listing_price = None

    # 2) decision.json
    decision_data = None
    if os.path.isfile(decision_json_path):
        checks["decision_exists"] = True
        try:
            with open(decision_json_path, "r", encoding="utf-8") as f:
                decision_data = json.load(f)
        except Exception:
            decision_data = None

        if isinstance(decision_data, dict):
            # recommendation
            rec = decision_data.get("recommendation")
            if isinstance(rec, str) and rec.lower() in {"buy", "wait", "walk"}:
                checks["decision_recommendation_valid"] = True
            # budget and units
            budget = parse_int(decision_data.get("budget_cap_cop"))
            units = parse_int(decision_data.get("units"))
            if budget == 18000000 and units == 12:
                checks["decision_budget_units_ok"] = True
            # scam_risk
            sr = decision_data.get("scam_risk")
            if isinstance(sr, str) and sr.lower() in {"low", "medium", "high"}:
                checks["decision_scams_risk_valid"] = True
            # red_flags non-empty array
            rf = decision_data.get("red_flags")
            if isinstance(rf, list) and len(rf) > 0:
                checks["decision_red_flags_nonempty"] = True
            # walk away present
            wau = parse_int(decision_data.get("walk_away_unit_price_cop"))
            if isinstance(wau, int) and wau > 0:
                checks["decision_walk_away_present"] = True
            # median matches csv
            dec_median = parse_int(decision_data.get("market_median_cop"))
            # Use csv median derived from input to avoid circular dependency; fall back to parsed from price CSV rows if available
            target_median = market_median_input
            if target_median is None and checks["price_csv_exists"]:
                try:
                    if price_rows:
                        some_row = price_rows[0]
                        target_median = parse_int(some_row.get("market_median_cop"))
                except Exception:
                    target_median = None
            if dec_median is not None and target_median is not None and abs(dec_median - target_median) <= 1:
                checks["decision_median_matches_csv"] = True
            # avg vs median percent
            dec_avg = decision_data.get("avg_listing_price_cop")
            dec_avg_num = parse_int(dec_avg)
            dec_pvm = decision_data.get("priced_vs_median_percent")
            dec_pvm_num = parse_float(dec_pvm)
            if avg_listing_price is not None and target_median not in (None, 0):
                expected_avg = avg_listing_price
                expected_percent = 100.0 * (expected_avg - target_median) / target_median
                # Accept 1% tolerance for avg due to rounding and parsing
                if dec_avg_num is not None and math.isfinite(expected_avg):
                    # Use relative tolerance 1% or abs 1 COP
                    if approx_equal(dec_avg_num, expected_avg, rel_tol=0.01, abs_tol=1.0):
                        # Now verify priced_vs_median_percent with ±0.1 tolerance
                        if dec_pvm_num is not None and abs(dec_pvm_num - round(expected_percent, 1)) <= 0.1 + 1e-9:
                            checks["decision_avg_vs_median_percent_ok"] = True

    # 3) negotiation_scripts.md
    if os.path.isfile(scripts_md_path):
        checks["scripts_exists"] = True
        try:
            with open(scripts_md_path, "r", encoding="utf-8") as f:
                scripts_text = f.read()
            if "Bottom Line →" in scripts_text:
                checks["scripts_has_bottom_line"] = True
            principles = ["anchoring", "loss aversion", "social proof", "scarcity", "reciprocity"]
            count_found = 0
            lower = scripts_text.lower()
            for p in principles:
                if p in lower:
                    count_found += 1
            if count_found >= 3:
                checks["scripts_has_3_principles"] = True
        except Exception:
            pass

    # 4) financing_plan.json
    finance_rows_in_input = []
    if os.path.isfile(input_financial_csv):
        try:
            finance_rows_in_input, fin_headers = read_csv_rows(input_financial_csv)
        except Exception:
            finance_rows_in_input = []
    financing_data = None
    if os.path.isfile(financing_json_path):
        checks["financing_exists"] = True
        try:
            with open(financing_json_path, "r", encoding="utf-8") as f:
                financing_data = json.load(f)
        except Exception:
            financing_data = None
        if isinstance(financing_data, list) and finance_rows_in_input:
            # Check count matches number of banks (per row)
            try:
                banks_input = [row.get("bank") or row.get("Bank") or row.get("name") for row in finance_rows_in_input]
                banks_input = [b for b in banks_input if b is not None]
                banks_output = [row.get("bank") for row in financing_data if isinstance(row, dict)]
                if len(financing_data) == len(finance_rows_in_input):
                    checks["financing_entries_match_banks"] = True
                # fields present
                fields_ok = True
                for row in financing_data:
                    if not isinstance(row, dict):
                        fields_ok = False
                        break
                    req_fields = ["bank", "financed_amount_cop", "term_months", "monthly_rate_percent", "monthly_payment_cop", "total_interest_cop", "total_pay_cop"]
                    for rf in req_fields:
                        if rf not in row:
                            fields_ok = False
                            break
                    if not fields_ok:
                        break
                if fields_ok:
                    checks["financing_fields_present"] = True
            except Exception:
                pass

            # financed amount correct
            financed_amount_expected = None
            if avg_listing_price is not None:
                financed_amount_expected = int(round(0.5 * avg_listing_price * 12))
            if financed_amount_expected is not None:
                try:
                    all_amounts_ok = True
                    for row in financing_data:
                        famt = parse_int(row.get("financed_amount_cop"))
                        if famt is None or abs(famt - financed_amount_expected) > 1:
                            all_amounts_ok = False
                            break
                    if all_amounts_ok:
                        checks["financing_amount_correct"] = True
                except Exception:
                    pass

            # monthly payment check and totals consistency
            mp_all_ok = True
            totals_ok = True
            for row in financing_data or []:
                try:
                    A = parse_int(row.get("financed_amount_cop"))
                    term = parse_int(row.get("term_months"))
                    rate = parse_float(row.get("monthly_rate_percent"))
                    mp = parse_float(row.get("monthly_payment_cop"))
                    tp = parse_float(row.get("total_pay_cop"))
                    ti = parse_float(row.get("total_interest_cop"))
                    if None in (A, term, rate, mp, tp, ti) or term <= 0:
                        mp_all_ok = False
                        totals_ok = False
                        break
                    expected_mp = amortization_monthly_payment(A, rate, term)
                    if expected_mp is None or expected_mp <= 0:
                        mp_all_ok = False
                        break
                    # Allow 1% tolerance
                    if not approx_equal(mp, expected_mp, rel_tol=0.01, abs_tol=1.0):
                        mp_all_ok = False
                        break
                    # Totals: total_pay ≈ monthly_payment * term
                    expected_total_pay = mp * term
                    if not approx_equal(tp, expected_total_pay, rel_tol=0.01, abs_tol=10.0):
                        totals_ok = False
                        break
                    # total_interest ≈ total_pay - A
                    expected_ti = tp - A
                    # Allow 2% of A tolerance
                    if not approx_equal(ti, expected_ti, rel_tol=0.02, abs_tol=10.0):
                        totals_ok = False
                        break
                except Exception:
                    mp_all_ok = False
                    totals_ok = False
                    break
            if mp_all_ok:
                checks["financing_monthly_payment_ok"] = True
            if totals_ok:
                checks["financing_totals_consistent"] = True

    # 5) loop/history.json
    if os.path.isfile(loop_history_json_path):
        checks["loop_history_exists"] = True
        try:
            with open(loop_history_json_path, "r", encoding="utf-8") as f:
                loop_data = json.load(f)
            if isinstance(loop_data, dict):
                max_iter = loop_data.get("max_iterations")
                if isinstance(max_iter, int) and 1 <= max_iter <= 5:
                    checks["loop_max_iterations_ok"] = True
                iters = loop_data.get("iterations")
                if isinstance(iters, list) and isinstance(max_iter, int):
                    if 3 <= len(iters) <= max_iter:
                        checks["loop_iterations_len_ok"] = True
                status = loop_data.get("status")
                if isinstance(status, str) and status in {"complete", "stopped"}:
                    checks["loop_status_valid"] = True
                criteria = loop_data.get("criteria")
                if isinstance(criteria, str) and ("1,300,000 COP" in criteria):
                    checks["loop_criteria_contains_target"] = True
        except Exception:
            pass

    # 6) research_notes.md
    if os.path.isfile(research_notes_md_path):
        checks["research_notes_exists"] = True
        try:
            with open(research_notes_md_path, "r", encoding="utf-8") as f:
                txt = f.read()
            if isinstance(txt, str) and txt.strip() != "":
                checks["research_notes_nonempty"] = True
        except Exception:
            pass

    # No-op baseline: if output/ missing or empty, reward must be 0.0
    # This will naturally happen because checks remain False.

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Clamp between 0 and 1
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    last_non_empty_print(result)

if __name__ == "__main__":
    main()