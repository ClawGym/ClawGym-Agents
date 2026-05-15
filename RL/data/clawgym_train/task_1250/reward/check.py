import json
import os
import sys
import csv
import re

def parse_float(v):
    try:
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            s = v.strip().replace(",", "")
            # remove currency symbols
            s = re.sub(r"^[\$\£\€]", "", s)
            return float(s)
    except Exception:
        return None
    return None

def last_non_empty_line(text):
    for line in reversed(text.splitlines()):
        if line.strip():
            return line
    return ""

def detect_cpi_keys(scenarios_dict):
    # Return a dict mapping normalized keys {'2.5','4','6'} to actual keys found
    keys_map = {}
    if not isinstance(scenarios_dict, dict):
        return keys_map
    for k in scenarios_dict.keys():
        lk = str(k).lower()
        # find 2.5
        if re.search(r'\b2\.?5\b', lk) or re.search(r'\b25\b', lk):
            keys_map.setdefault('2.5', k)
        if re.search(r'\b4(\.0)?\b', lk):
            keys_map.setdefault('4', k)
        if re.search(r'\b6(\.0)?\b', lk):
            keys_map.setdefault('6', k)
        # common explicit keys like cpi_25, cpi_4, cpi_6 handled by above
    return keys_map

def scenario_has_totals(value):
    # Acceptable:
    # - number
    # - dict with "total" number
    # - list of numbers
    # - list of dicts with "total" numbers
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, dict):
        if 'total' in value and isinstance(value['total'], (int, float)):
            return True
        # alternatively, allow array under key like "projection"
        if 'projection' in value and isinstance(value['projection'], list):
            nums = []
            for item in value['projection']:
                if isinstance(item, (int, float)):
                    nums.append(float(item))
                elif isinstance(item, dict):
                    t = item.get('total')
                    if isinstance(t, (int, float)):
                        nums.append(float(t))
            return len(nums) > 0
        return False
    if isinstance(value, list):
        nums = 0
        for item in value:
            if isinstance(item, (int, float)):
                nums += 1
            elif isinstance(item, dict):
                t = item.get('total')
                if isinstance(t, (int, float)):
                    nums += 1
        return nums > 0
    return False

def check_projection_array(proj):
    # Returns (valid, is_increasing, nondecreasing_all)
    if not isinstance(proj, list) or len(proj) < 3:
        return False, False, False
    totals = []
    for elem in proj:
        if not isinstance(elem, dict):
            return False, False, False
        year = elem.get('year')
        base_rent = elem.get('base_rent')
        cam = elem.get('cam')
        total = elem.get('total')
        if not isinstance(year, int):
            # allow numeric strings convertible
            yf = parse_float(year)
            if yf is None or int(yf) != yf:
                return False, False, False
        if not isinstance(base_rent, (int, float)):
            if parse_float(base_rent) is None:
                return False, False, False
        if not isinstance(cam, (int, float)):
            if parse_float(cam) is None:
                return False, False, False
        if not isinstance(total, (int, float)):
            t = parse_float(total)
            if t is None:
                return False, False, False
            total = t
        totals.append(float(total))
    nondecreasing = all(totals[i] <= totals[i+1] for i in range(len(totals)-1))
    increasing = totals[-1] > totals[0]
    return True, increasing, nondecreasing

def check_true_cost(tc):
    if not isinstance(tc, dict):
        return False
    ok = True
    for k in ["monthly", "annual", "full_term"]:
        v = tc.get(k)
        if not isinstance(v, (int, float)):
            v2 = parse_float(v)
            if v2 is None:
                ok = False
    return ok

def parse_markdown_top3(md_text):
    # find lines starting with 1., 2., 3.
    lines = [ln for ln in md_text.splitlines()]
    starts = [ln.strip() for ln in lines if ln.strip()]
    count_1 = sum(1 for ln in starts if ln.startswith("1."))
    count_2 = sum(1 for ln in starts if ln.startswith("2."))
    count_3 = sum(1 for ln in starts if ln.startswith("3."))
    total_numbered = count_1 + count_2 + count_3
    return (count_1 == 1 and count_2 == 1 and count_3 == 1 and total_numbered == 3)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_analysis_json": False,
        "analysis_json_valid": False,
        "analysis_top_level_fields": False,
        "analysis_verdict_valid": False,
        "analysis_market_leverage_present": False,
        "analysis_options_count": False,
        "analysis_option_fields_complete": False,
        "analysis_true_cost_fields": False,
        "analysis_projection_length_and_fields": False,
        "analysis_projection_escalation_increasing": False,
        "analysis_projection_monotonic_nondecreasing": False,
        "analysis_load_factor_consistent": False,
        "analysis_financial_metrics_present": False,
        "analysis_negotiation_priorities_ok": False,
        "analysis_scenarios_present_and_valid": False,
        "has_comparison_csv": False,
        "comparison_header_ok": False,
        "comparison_rows_count_ok": False,
        "has_report_md": False,
        "report_has_header_line": False,
        "report_has_verdict_line": False,
        "report_sections_present": False,
        "report_top3_numbered_lines_ok": False
    }

    # Paths
    analysis_path = os.path.join(output_dir, "analysis.json")
    comparison_path = os.path.join(output_dir, "comparison.csv")
    report_path = os.path.join(output_dir, "report.md")

    # Check analysis.json
    analysis = None
    if os.path.isfile(analysis_path):
        checks["has_analysis_json"] = True
        try:
            with open(analysis_path, "r", encoding="utf-8") as f:
                analysis = json.load(f)
            checks["analysis_json_valid"] = isinstance(analysis, dict)
        except Exception:
            checks["analysis_json_valid"] = False

    if checks["analysis_json_valid"]:
        # top-level fields
        verdict = analysis.get("verdict")
        options = analysis.get("options")
        market_leverage = analysis.get("market_leverage")
        if verdict is not None and options is not None and market_leverage is not None:
            checks["analysis_top_level_fields"] = True

        if isinstance(verdict, str) and verdict in {"FAVORABLE", "NEGOTIATE", "WALK AWAY"}:
            checks["analysis_verdict_valid"] = True

        if isinstance(market_leverage, (str, dict)):
            checks["analysis_market_leverage_present"] = True

        if isinstance(options, list) and len(options) >= 2:
            checks["analysis_options_count"] = True

            # Iterate options and validate required structure
            opt_fields_ok = True
            true_cost_ok = True
            projection_ok = True
            projection_increasing_all = True
            projection_nondecreasing_all = True
            load_factor_ok_all = True
            fin_ok_all = True
            nego_ok_all = True
            scenarios_ok_all = True

            for opt in options:
                # Required keys per option
                req_keys = [
                    "name", "property_type", "cost_structure",
                    "usable_sf", "rentable_sf", "load_factor",
                    "true_cost", "red_flags", "yellow_flags", "green_terms",
                    "negotiation_priorities", "projection", "financial_metrics", "scenarios"
                ]
                if not all(k in opt for k in req_keys):
                    opt_fields_ok = False
                    continue

                # true_cost structure
                if not check_true_cost(opt.get("true_cost")):
                    true_cost_ok = False

                # projection validation
                proj = opt.get("projection")
                val, inc, nondec = check_projection_array(proj)
                if not val:
                    projection_ok = False
                if not inc:
                    projection_increasing_all = False
                if not nondec:
                    projection_nondecreasing_all = False

                # load factor consistent
                usable = parse_float(opt.get("usable_sf"))
                rentable = parse_float(opt.get("rentable_sf"))
                reported_lf = parse_float(opt.get("load_factor"))
                lf_ok = False
                if usable is not None and rentable is not None and usable > 0 and reported_lf is not None:
                    computed = rentable / usable
                    if abs(computed - reported_lf) <= 0.01:
                        lf_ok = True
                if not lf_ok:
                    load_factor_ok_all = False

                # financial metrics
                fin = opt.get("financial_metrics")
                fin_ok = isinstance(fin, dict) and all(
                    isinstance(fin.get(k), (int, float)) or parse_float(fin.get(k)) is not None
                    for k in ["lease_liability", "npv", "cost_per_employee", "cost_per_revenue_dollar"]
                )
                if not fin_ok:
                    fin_ok_all = False

                # negotiation priorities
                negl = opt.get("negotiation_priorities")
                local_nego_ok = True
                if not isinstance(negl, list) or len(negl) < 3:
                    local_nego_ok = False
                else:
                    for item in negl[:3]:
                        if not isinstance(item, dict):
                            local_nego_ok = False
                            break
                        if not isinstance(item.get("item"), str):
                            local_nego_ok = False
                            break
                        est = item.get("estimated_savings")
                        if isinstance(est, (int, float)):
                            continue
                        elif isinstance(est, str):
                            if parse_float(est) is None:
                                local_nego_ok = False
                                break
                        else:
                            local_nego_ok = False
                            break
                if not local_nego_ok:
                    nego_ok_all = False

                # scenarios presence and validity
                scenarios = opt.get("scenarios")
                local_scen_ok = False
                if isinstance(scenarios, dict):
                    keys_map = detect_cpi_keys(scenarios)
                    if all(k in keys_map for k in ['2.5', '4', '6']):
                        # validate each scenario content
                        s_ok = True
                        for norm in ['2.5', '4', '6']:
                            k = keys_map[norm]
                            val_s = scenarios.get(k)
                            if not scenario_has_totals(val_s):
                                s_ok = False
                                break
                        local_scen_ok = s_ok
                if not local_scen_ok:
                    scenarios_ok_all = False

            checks["analysis_option_fields_complete"] = opt_fields_ok
            checks["analysis_true_cost_fields"] = true_cost_ok
            checks["analysis_projection_length_and_fields"] = projection_ok
            checks["analysis_projection_escalation_increasing"] = projection_increasing_all
            checks["analysis_projection_monotonic_nondecreasing"] = projection_nondecreasing_all
            checks["analysis_load_factor_consistent"] = load_factor_ok_all
            checks["analysis_financial_metrics_present"] = fin_ok_all
            checks["analysis_negotiation_priorities_ok"] = nego_ok_all
            checks["analysis_scenarios_present_and_valid"] = scenarios_ok_all

    # Check comparison.csv
    if os.path.isfile(comparison_path):
        checks["has_comparison_csv"] = True
        try:
            with open(comparison_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Check header exact match
            first_line = content.splitlines()[0].strip() if content.splitlines() else ""
            expected_header = "Option,Effective Rent ($/SF),Total Term Cost ($),TI Allowance ($/SF),Free Rent (months),Escalation Type/Rate,Termination Option,Load Factor,Parking Ratio,Verdict"
            if first_line == expected_header:
                checks["comparison_header_ok"] = True
            # Count data rows
            reader = csv.reader(content.splitlines())
            rows = list(reader)
            if len(rows) >= 4:  # header + at least 3 data rows
                checks["comparison_rows_count_ok"] = True
        except Exception:
            pass

    # Check report.md
    if os.path.isfile(report_path):
        checks["has_report_md"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                md = f.read()
            # Header line starting with "LEASE ANALYSIS:"
            has_header = any(line.startswith("LEASE ANALYSIS:") for line in md.splitlines())
            checks["report_has_header_line"] = has_header
            # Verdict line
            verdict_lines = [line for line in md.splitlines() if line.startswith("VERDICT:")]
            verdict_ok = False
            if verdict_lines:
                vline = verdict_lines[0].strip()
                for v in ["FAVORABLE", "NEGOTIATE", "WALK AWAY"]:
                    if vline == f"VERDICT: {v}":
                        verdict_ok = True
                        break
            checks["report_has_verdict_line"] = verdict_ok
            # Sections present
            sections_ok = all(s in md for s in ["TRUE COST", "RED FLAGS", "TOP 3 NEGOTIATION PRIORITIES", "YEAR-BY-YEAR PROJECTION"])
            checks["report_sections_present"] = sections_ok
            # Top 3 numbered lines exactly
            checks["report_top3_numbered_lines_ok"] = parse_markdown_top3(md)
        except Exception:
            pass

    # Compute reward
    required_files_present = checks["has_analysis_json"] and checks["has_comparison_csv"] and checks["has_report_md"]
    # Fractional reward only if all required files exist
    if not required_files_present:
        reward = 0.0
    else:
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Exclude the three "has_*" from denominator? Keep them included; they are true here.
        reward = passed / total_checks if total_checks > 0 else 0.0
        # Ensure within [0,1]
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()