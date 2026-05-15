import json
import os
import sys
import csv

def parse_float(val):
    if isinstance(val, (int, float)):
        return float(val)
    if val is None:
        return None
    s = str(val).strip()
    if s == "":
        return None
    # Remove percent signs and commas
    s = s.replace('%', '').replace(',', '')
    try:
        return float(s)
    except:
        return None

def parse_int(val):
    f = parse_float(val)
    if f is None:
        return None
    try:
        return int(round(f))
    except:
        return None

def normalize_header(h):
    return h.strip().lower().replace(' ', '_').replace('-', '_')

def read_csv_dicts(path):
    with open(path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = [row for row in reader]
    return headers, rows

def normalize_category(cat):
    if cat is None:
        return ''
    # Case-insensitive exact label with minor whitespace normalization
    return cat.strip().lower().replace(' ', '')

def extract_targets_and_metrics(input_targets_csv):
    headers, rows = read_csv_dicts(input_targets_csv)
    norm_headers = {h: normalize_header(h) for h in headers}
    # Build reverse map normalized -> original for lookup
    rev = {}
    for orig, norm in norm_headers.items():
        rev.setdefault(norm, orig)
    # Helper to find a column by condition on normalized header
    def find_col(predicate):
        for orig, norm in norm_headers.items():
            if predicate(norm):
                return orig
        return None

    # Try to locate necessary columns
    target_col = None
    for h in headers:
        if normalize_header(h) == 'target' or normalize_header(h) == 'name':
            target_col = h
            break

    growth_col = find_col(lambda n: 'growth' in n and ('yoy' in n or 'yo_y' in n or 'y_o_y' in n or 'y/y' in n or 'yoy_percent' in n))
    if growth_col is None:
        # fallback to any column containing 'growth' if only one
        candidates = [h for h in headers if 'growth' in normalize_header(h)]
        if len(candidates) == 1:
            growth_col = candidates[0]

    nrr_col = find_col(lambda n: 'nrr' in n)
    if nrr_col is None:
        candidates = [h for h in headers if 'nrr' in normalize_header(h)]
        if len(candidates) == 1:
            nrr_col = candidates[0]

    key_exp_col = find_col(lambda n: ('expiration' in n or 'expiry' in n) and 'month' in n)
    founder_col = find_col(lambda n: 'founder' in n and 'transition' in n and 'month' in n)
    tech_depr_col = find_col(lambda n: ('tech_deprecated' in n) or ('technology' in n and ('deprecated' in n or 'status' in n)))
    tech_status_col = None
    if tech_depr_col is None:
        tech_status_col = find_col(lambda n: 'technology' in n and 'status' in n)
    turnover_col = find_col(lambda n: ('employee' in n and 'turnover' in n) or ('turnover' in n and 'percent' in n))

    targets = []
    metrics = {}
    for row in rows:
        tname = (row.get(target_col) if target_col else None)
        if tname is None or str(tname).strip() == '':
            # skip rows without target name
            continue
        tname = str(tname).strip()
        targets.append(tname)
        growth = parse_float(row.get(growth_col)) if growth_col else None
        nrr = parse_float(row.get(nrr_col)) if nrr_col else None
        exp_m = parse_float(row.get(key_exp_col)) if key_exp_col else None
        founder_m = parse_float(row.get(founder_col)) if founder_col else None
        tech_depr_val = None
        if tech_depr_col:
            raw = row.get(tech_depr_col)
            if isinstance(raw, bool):
                tech_depr_val = raw
            else:
                s = str(raw).strip().lower()
                tech_depr_val = s in ('true', '1', 'yes', 'y', 'deprecated', 'unsupported')
        else:
            raw = row.get(tech_status_col) if tech_status_col else None
            if raw is not None:
                s = str(raw).strip().lower()
                tech_depr_val = ('deprecated' in s) or ('unsupported' in s)
        turnover = parse_float(row.get(turnover_col)) if turnover_col else None
        metrics[tname] = {
            'growth_yoy_percent': growth,
            'nrr_percent': nrr,
            'key_customer_expiration_months': exp_m,
            'founder_transition_willingness_months': founder_m,
            'tech_deprecated': tech_depr_val,
            'employee_turnover_percent': turnover,
        }
    return targets, metrics

def is_number(x):
    return isinstance(x, (int, float))

def get_number_from_json(obj, key):
    if key not in obj:
        return None
    v = obj[key]
    if isinstance(v, (int, float)):
        return float(v)
    # allow numeric strings
    f = parse_float(v)
    return f

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "scorecards_file_exists": False,
        "scorecards_header_valid": False,
        "scorecards_has_all_targets": False,
        "scorecards_weighted_score_valid": False,
        "scorecards_decisions_valid": False,

        "triangulation_file_exists": False,
        "triangulation_targets_match": False,
        "triangulation_revmult_bands_valid": False,
        "triangulation_dcf_fields_valid": False,
        "triangulation_dcf_rates_valid": False,
        "triangulation_comps_fields_valid": False,
        "triangulation_final_present": False,

        "checklist_file_exists": False,
        "checklist_header_valid": False,
        "checklist_min_rows": False,
        "checklist_category_counts_valid": False,

        "red_flags_file_exists": False,
        "red_flags_schema_valid": False,
        "red_flags_expected_included": False,

        "deal_structure_file_exists": False,
        "deal_structure_schema_valid": False,
        "deal_structure_earnout_constraints_valid": False,

        "integration_file_exists": False,
        "integration_sections_present": False,
    }

    # Load input references
    targets_csv_path = os.path.join(input_dir, "targets.csv")
    targets_list = []
    metrics_by_target = {}
    if os.path.isfile(targets_csv_path):
        try:
            targets_list, metrics_by_target = extract_targets_and_metrics(targets_csv_path)
        except Exception:
            targets_list, metrics_by_target = [], {}
    targets_set = set(targets_list)

    # 1) Screening scorecards
    scorecards_path = os.path.join(output_dir, "screening", "scorecards.csv")
    if os.path.isfile(scorecards_path):
        checks["scorecards_file_exists"] = True
        try:
            headers, rows = read_csv_dicts(scorecards_path)
            expected_header = [
                "target",
                "strategic_fit",
                "revenue_quality",
                "growth_rate",
                "gross_margin",
                "customer_retention",
                "technology_moat",
                "team_quality",
                "integration_complexity",
                "weighted_score",
                "decision",
            ]
            if headers == expected_header:
                checks["scorecards_header_valid"] = True

            # Check rows for all targets
            score_targets = set()
            weighted_valid_all = True
            decisions_valid_all = True
            for r in rows:
                t = r.get("target")
                if t is not None:
                    score_targets.add(str(t).strip())
                ws = parse_float(r.get("weighted_score"))
                if ws is None or ws < 0 or ws > 10:
                    weighted_valid_all = False
                dec = (r.get("decision") or "").strip().lower()
                if dec not in {"go", "conditional", "pass"}:
                    decisions_valid_all = False

            if targets_set and targets_set.issubset(score_targets):
                checks["scorecards_has_all_targets"] = True
            # If there are no targets in input, keep False (no positive credit)
            if weighted_valid_all and len(rows) > 0:
                checks["scorecards_weighted_score_valid"] = True
            if decisions_valid_all and len(rows) > 0:
                checks["scorecards_decisions_valid"] = True
        except Exception:
            pass

    # 2) Valuation triangulation
    triangulation_path = os.path.join(output_dir, "valuation", "triangulation.json")
    triangulation_data = None
    if os.path.isfile(triangulation_path):
        checks["triangulation_file_exists"] = True
        try:
            with open(triangulation_path, 'r', encoding='utf-8') as f:
                triangulation_data = json.load(f)
            if isinstance(triangulation_data, dict) and targets_set:
                keys_set = set(triangulation_data.keys())
                # Require exact match
                if keys_set == targets_set:
                    checks["triangulation_targets_match"] = True

                revmult_ok_all = True
                dcf_fields_ok_all = True
                dcf_rates_ok_all = True
                comps_ok_all = True
                final_ok_all = True

                for tgt in targets_set:
                    entry = triangulation_data.get(tgt, {})
                    # Revenue multiple check
                    revmult = entry.get("revenue_multiple", {})
                    applied_multiple = get_number_from_json(revmult, "applied_multiple")
                    valuation_rm = get_number_from_json(revmult, "valuation")
                    if applied_multiple is None or valuation_rm is None:
                        revmult_ok_all = False
                    else:
                        # Determine expected band from inputs
                        m = metrics_by_target.get(tgt, {})
                        growth = m.get('growth_yoy_percent')
                        nrr = m.get('nrr_percent')
                        # Default to the "otherwise 4-8x" band if missing metrics
                        low, high = 4.0, 8.0
                        if growth is not None and nrr is not None:
                            if growth >= 30.0 and nrr >= 100.0:
                                low, high = 8.0, 15.0
                        # Inclusive bounds
                        if not (low <= applied_multiple <= high):
                            revmult_ok_all = False

                    # DCF check
                    dcf = entry.get("dcf", {})
                    disc = get_number_from_json(dcf, "discount_rate")
                    term_g = get_number_from_json(dcf, "terminal_growth_rate")
                    yearly_fcfs = dcf.get("yearly_fcfs")
                    term_val = get_number_from_json(dcf, "terminal_value")
                    present_val = get_number_from_json(dcf, "present_value")
                    ev = get_number_from_json(dcf, "enterprise_value")

                    # Fields existence and types
                    yf_ok = isinstance(yearly_fcfs, list) and len(yearly_fcfs) == 5
                    if yf_ok:
                        # Ensure all are numeric or numeric strings
                        for i in range(5):
                            if parse_float(yearly_fcfs[i]) is None:
                                yf_ok = False
                                break
                    fields_ok = (disc is not None and term_g is not None and yf_ok
                                 and term_val is not None and present_val is not None and ev is not None)
                    if not fields_ok:
                        dcf_fields_ok_all = False
                    # Rates constraints
                    rates_ok = False
                    if disc is not None and term_g is not None:
                        if 0.15 <= float(disc) <= 0.25 and float(term_g) < float(disc):
                            rates_ok = True
                    if not rates_ok:
                        dcf_rates_ok_all = False

                    # Comps check
                    comps = entry.get("comps", {})
                    comps_mult = get_number_from_json(comps, "applied_multiple")
                    comps_val = get_number_from_json(comps, "valuation")
                    if comps_mult is None or comps_val is None:
                        comps_ok_all = False

                    # Final recommended valuation
                    frv = get_number_from_json(entry, "final_recommended_valuation")
                    if frv is None:
                        final_ok_all = False

                if revmult_ok_all:
                    checks["triangulation_revmult_bands_valid"] = True
                if dcf_fields_ok_all:
                    checks["triangulation_dcf_fields_valid"] = True
                if dcf_rates_ok_all:
                    checks["triangulation_dcf_rates_valid"] = True
                if comps_ok_all:
                    checks["triangulation_comps_fields_valid"] = True
                if final_ok_all:
                    checks["triangulation_final_present"] = True
        except Exception:
            pass

    # 3) Due diligence checklist
    checklist_path = os.path.join(output_dir, "diligence", "checklist.csv")
    if os.path.isfile(checklist_path):
        checks["checklist_file_exists"] = True
        try:
            headers, rows = read_csv_dicts(checklist_path)
            expected = ["category", "item", "priority", "assigned_to", "status"]
            if headers == expected:
                checks["checklist_header_valid"] = True
            # Count rows
            if len(rows) >= 65:
                checks["checklist_min_rows"] = True
            # Count by categories
            counts = {"financial": 0, "legal": 0, "operational": 0, "hr/culture": 0}
            for r in rows:
                cat = normalize_category(r.get("category"))
                # normalize "hr / culture" to "hr/culture" by removing spaces
                if cat == "financial":
                    counts["financial"] += 1
                elif cat == "legal":
                    counts["legal"] += 1
                elif cat == "operational":
                    counts["operational"] += 1
                elif cat == "hr/culture":
                    counts["hr/culture"] += 1
            if counts["financial"] >= 30 and counts["legal"] >= 15 and counts["operational"] >= 12 and counts["hr/culture"] >= 8:
                checks["checklist_category_counts_valid"] = True
        except Exception:
            pass

    # 4) Red flags
    red_flags_path = os.path.join(output_dir, "diligence", "red_flags.json")
    if os.path.isfile(red_flags_path):
        checks["red_flags_file_exists"] = True
        try:
            with open(red_flags_path, 'r', encoding='utf-8') as f:
                rf = json.load(f)
            schema_ok = isinstance(rf, dict)
            if schema_ok and targets_set:
                # ensure keys include all targets
                if not targets_set.issubset(set(rf.keys())):
                    schema_ok = False
                else:
                    # ensure values are arrays of strings
                    for tgt in targets_set:
                        arr = rf.get(tgt)
                        if not isinstance(arr, list):
                            schema_ok = False
                            break
                        for item in arr:
                            if not isinstance(item, str):
                                schema_ok = False
                                break
                        if not schema_ok:
                            break
            if schema_ok:
                checks["red_flags_schema_valid"] = True

            expected_all_included = True
            if targets_set and schema_ok:
                for tgt in targets_set:
                    m = metrics_by_target.get(tgt, {})
                    exp = []
                    # Revenue decline >10% YoY if growth_yoy_percent < -10
                    g = m.get('growth_yoy_percent')
                    if g is not None and g < -10.0:
                        exp.append("Revenue decline >10% YoY")
                    # Key customer contract expiring within 12 months if key_customer_expiration_months < 12
                    kcem = m.get('key_customer_expiration_months')
                    if kcem is not None and kcem < 12:
                        exp.append("Key customer contract expiring within 12 months")
                    # Founder unwilling to transition if founder_transition_willingness_months == 0
                    ftm = m.get('founder_transition_willingness_months')
                    if ftm is not None and float(ftm) == 0.0:
                        exp.append("Founder unwilling to transition")
                    # Deprecated technology if tech_deprecated is true
                    td = m.get('tech_deprecated')
                    if td is True:
                        exp.append("Deprecated technology")
                    # Employee turnover >30% if employee_turnover_percent > 30
                    et = m.get('employee_turnover_percent')
                    if et is not None and et > 30.0:
                        exp.append("Employee turnover >30%")
                    provided = rf.get(tgt, [])
                    # Check inclusion of all expected flags
                    for flag in exp:
                        if flag not in provided:
                            expected_all_included = False
                            break
                    if not expected_all_included:
                        break
            if expected_all_included and checks["red_flags_schema_valid"]:
                checks["red_flags_expected_included"] = True
        except Exception:
            pass

    # 5) Deal structure
    deal_path = os.path.join(output_dir, "deal", "deal_structure.json")
    if os.path.isfile(deal_path):
        checks["deal_structure_file_exists"] = True
        try:
            with open(deal_path, 'r', encoding='utf-8') as f:
                deal = json.load(f)
            schema_ok = isinstance(deal, dict)
            include_all_targets = schema_ok and targets_set.issubset(set(deal.keys())) if targets_set else False
            chosen_ok_all = True
            earnout_ok_all = True
            if schema_ok and include_all_targets:
                for tgt in targets_set:
                    entry = deal.get(tgt, {})
                    chosen = entry.get("chosen_structure")
                    if chosen not in {"asset_purchase", "stock_purchase", "merger"}:
                        chosen_ok_all = False
                    earnout = entry.get("earnout")
                    if not isinstance(earnout, dict):
                        earnout_ok_all = False
                    else:
                        used = earnout.get("used", None)
                        # used must be boolean
                        if not isinstance(used, bool):
                            earnout_ok_all = False
                        metric = earnout.get("metric", None)
                        duration = get_number_from_json(earnout, "duration_months")
                        cap = get_number_from_json(earnout, "cap_percent")
                        if used:
                            # metric must be a non-empty string
                            if not isinstance(metric, str) or len(metric.strip()) == 0:
                                earnout_ok_all = False
                            # duration and cap must be within caps
                            if duration is None or duration > 24:
                                earnout_ok_all = False
                            if cap is None or cap > 30:
                                earnout_ok_all = False
                        else:
                            # even if not used, duration and cap should be present as numbers (any values acceptable)
                            if duration is None or cap is None:
                                earnout_ok_all = False
                if include_all_targets and chosen_ok_all:
                    checks["deal_structure_schema_valid"] = True
                if include_all_targets and earnout_ok_all:
                    checks["deal_structure_earnout_constraints_valid"] = True
        except Exception:
            pass

    # 6) Integration plan
    integration_path = os.path.join(output_dir, "integration", "100_day_plan.md")
    if os.path.isfile(integration_path):
        checks["integration_file_exists"] = True
        try:
            with open(integration_path, 'r', encoding='utf-8') as f:
                content = f.read()
            c_low = content.lower()
            has_all = all([
                "day 1-7" in c_low,
                "day 8-30" in c_low,
                "day 31-60" in c_low,
                "day 61-100" in c_low
            ])
            if has_all:
                checks["integration_sections_present"] = True
        except Exception:
            pass

    # Compute reward as average of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0
    # Ensure 0..1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    # Preserve "reward" first, then checks
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()