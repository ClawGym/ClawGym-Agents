import json
import os
import sys
import csv
import math
import re

def to_float(val):
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if s.startswith("$"):
            s = s[1:]
        s = s.replace(",", "")
        try:
            return float(s)
        except:
            return None
    return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        return None

def parse_performance_csv(path):
    # Expect columns like: platform, cpc, cvr (case-insensitive)
    perf = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # normalize fieldnames to lower
            # csv.DictReader already handles headers, but keys are as-is
            for row in reader:
                # normalize keys
                lower_map = {k.lower().strip(): v for k, v in row.items()}
                plat = lower_map.get("platform") or lower_map.get("channel") or lower_map.get("site")
                if not plat:
                    continue
                platform_name = normalize_platform_name(str(plat))
                cpc_raw = lower_map.get("cpc")
                cvr_raw = lower_map.get("cvr") or lower_map.get("conv_rate") or lower_map.get("conversion_rate")
                cpc = to_float(cpc_raw) if cpc_raw is not None else None
                cvr = to_float(cvr_raw) if cvr_raw is not None else None
                if cpc is None or cvr is None:
                    continue
                # Handle percent vs fraction
                if cvr > 1.0 and cvr <= 100.0:
                    cvr = cvr / 100.0
                if cvr <= 0:
                    continue
                cpa = cpc / cvr
                perf[platform_name] = {"cpc": cpc, "cvr": cvr, "cpa": cpa}
    except:
        return {}
    return perf

def normalize_platform_name(name):
    n = name.strip().lower()
    if "meta" in n or "facebook" in n or "fb" in n:
        return "Meta"
    if "tiktok" in n:
        return "TikTok"
    if "youtube" in n or "yt" in n:
        return "YouTube"
    if "google" in n and "search" in n:
        return "Google Search"
    if n == "google":
        return "Google Search"
    if "search" in n and "google" not in n:
        return "Google Search"
    # Default to original capitalized
    return name

def parse_constraints_yaml(path):
    # Minimal, tolerant parser: extract known scalars and blocks with indentation.
    scalars = {}
    blocks = {}
    lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except:
        return {
            "total_budget": None,
            "weeks": None,
            "contingency_min_pct": None,
            "contingency_max_pct": None,
            "increase_cap_pct": None,
            "ad_counts": {}
        }

    # Extract top-level scalars of form key: value
    for i, line in enumerate(lines):
        m = re.match(r"^\s*([A-Za-z0-9_\- ]+)\s*:\s*([^\#\n\r]+)", line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            # if value seems to start a block (i.e., empty or just '|' or '>'), skip
            if val == "" or val == "|" or val == ">" or val == "{}":
                continue
            # remove quotes
            val = val.strip().strip('"').strip("'")
            # store raw
            scalars[key] = val

    # Extract blocks for contingency, ad_sets, ad_groups, adset_counts
    def parse_block(start_key_variants):
        for i, line in enumerate(lines):
            for k in start_key_variants:
                if re.match(r"^\s*"+re.escape(k)+r"\s*:\s*$", line):
                    parent_indent = len(line) - len(line.lstrip(" "))
                    block = {}
                    j = i + 1
                    while j < len(lines):
                        l = lines[j]
                        if l.strip() == "" or l.strip().startswith("#"):
                            j += 1
                            continue
                        indent = len(l) - len(l.lstrip(" "))
                        if indent <= parent_indent:
                            break
                        m2 = re.match(r"^\s*([A-Za-z0-9_\- \/\%]+)\s*:\s*([^\#\n\r]+)", l)
                        if m2:
                            subk = m2.group(1).strip()
                            subv = m2.group(2).strip()
                            subv = subv.strip().strip('"').strip("'")
                            block[subk] = subv
                        j += 1
                    if block:
                        return block
        return None

    contingency_block = parse_block(["contingency", "contingency_bounds"])
    ad_sets_block = parse_block(["ad_sets", "ad_groups", "adset_counts", "ad_group_counts", "adsets"])

    # Resolve values
    total_budget = None
    weeks = None
    increase_cap_pct = None
    cont_min = None
    cont_max = None
    ad_counts = {}

    # Total budget
    for k in ["total_budget", "budget_total", "totalBudget", "budget"]:
        if k in scalars:
            total_budget = to_float(scalars[k])
            if total_budget is not None:
                break

    # Weeks
    for k in ["weeks", "num_weeks", "total_weeks"]:
        if k in scalars:
            w = to_float(scalars[k])
            if w is not None:
                weeks = int(round(w))
                break

    # Increase cap pct
    candidate_keys = [
        "week_over_week_increase_cap_pct",
        "increase_cap_pct",
        "wow_cap_pct",
        "max_weekly_increase_pct",
        "week_over_week_cap_pct",
        "weekly_increase_cap_pct"
    ]
    for k in candidate_keys:
        if k in scalars:
            increase_cap_pct = to_float(scalars[k])
            break
    if increase_cap_pct is None:
        # Try a generic search for keys containing both 'increase' and 'cap'
        for k, v in scalars.items():
            lk = k.lower()
            if ("increase" in lk or "growth" in lk) and "cap" in lk:
                increase_cap_pct = to_float(v)
                if increase_cap_pct is not None:
                    break

    # Contingency bounds
    # direct scalars
    direct_min_keys = ["contingency_min_pct", "contingencyMinPct", "contingency_pct_min"]
    direct_max_keys = ["contingency_max_pct", "contingencyMaxPct", "contingency_pct_max"]
    for k in direct_min_keys:
        if k in scalars and cont_min is None:
            cont_min = to_float(scalars[k])
    for k in direct_max_keys:
        if k in scalars and cont_max is None:
            cont_max = to_float(scalars[k])

    if contingency_block:
        # Possible keys: min_pct, max_pct, min, max
        for k in ["min_pct", "min"]:
            if k in contingency_block and cont_min is None:
                cont_min = to_float(contingency_block[k])
        for k in ["max_pct", "max"]:
            if k in contingency_block and cont_max is None:
                cont_max = to_float(contingency_block[k])

    # If percentages provided as 20-30, convert 20 to 0.2 if >1
    if cont_min is not None and cont_min > 1.0:
        cont_min = cont_min / 100.0
    if cont_max is not None and cont_max > 1.0:
        cont_max = cont_max / 100.0
    if increase_cap_pct is not None and increase_cap_pct > 1.0:
        increase_cap_pct = increase_cap_pct / 100.0

    # ad counts
    if ad_sets_block:
        for pk, pv in ad_sets_block.items():
            val = to_float(pv)
            if val is None:
                continue
            platform = normalize_platform_name(pk)
            ad_counts[platform] = int(round(val))

    # fallback: scan scalars for platform counts like meta_ad_sets: 3
    for k, v in scalars.items():
        lk = k.lower()
        if "ad" in lk and ("set" in lk or "group" in lk or "adset" in lk):
            # try to find platform in key
            platform = None
            if "meta" in lk or "facebook" in lk or "fb" in lk:
                platform = "Meta"
            elif "tiktok" in lk:
                platform = "TikTok"
            elif "youtube" in lk or "yt" in lk:
                platform = "YouTube"
            elif "google" in lk and "search" in lk:
                platform = "Google Search"
            elif "search" in lk and "google" not in lk:
                platform = "Google Search"
            if platform:
                num = to_float(v)
                if num is not None:
                    ad_counts[platform] = int(round(num))

    return {
        "total_budget": total_budget,
        "weeks": weeks,
        "contingency_min_pct": cont_min,
        "contingency_max_pct": cont_max,
        "increase_cap_pct": increase_cap_pct,
        "ad_counts": ad_counts
    }

def approx_equal(a, b, tol=0.5):
    if a is None or b is None:
        return False
    return abs(a - b) <= tol

def read_budget_model_csv(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except:
        return None, None

def get_weekly_budgets_from_media_plan(media_plan):
    wb = media_plan.get("weekly_budgets", {})
    weekly = {}
    for i in range(1, 14):
        key = f"week_{i}"
        if key in wb and isinstance(wb[key], dict):
            weekly[key] = wb[key]
    return weekly

def sum_weekly_budgets(weekly):
    total = 0.0
    for w, d in weekly.items():
        for p in ["Meta", "Google Search", "TikTok", "YouTube"]:
            v = to_float(d.get(p, 0))
            if v is None:
                v = 0.0
            total += v
    return total

def validate_non_negative_budgets(weekly):
    for w, d in weekly.items():
        for p in ["Meta", "Google Search", "TikTok", "YouTube"]:
            v = d.get(p, 0)
            fv = to_float(v)
            if fv is None or fv < 0:
                return False
    return True

def compute_week_conversions(week_budget, cpa):
    # conversions = budget / cpa
    conv = {}
    for p in ["Meta", "Google Search", "TikTok", "YouTube"]:
        b = to_float(week_budget.get(p, 0)) or 0.0
        c = cpa.get(p, None)
        if c is None or c <= 0:
            conv[p] = None
        else:
            conv[p] = b / c
    return conv

def validate_week_over_week_cap(weekly, cap_pct):
    # For each platform and week i>1: budget_i <= budget_(i-1) * (1 + cap_pct) + tolerance
    if cap_pct is None:
        return False
    for p in ["Meta", "Google Search", "TikTok", "YouTube"]:
        prev = None
        for i in range(1, 14):
            wk = f"week_{i}"
            amt = to_float(weekly.get(wk, {}).get(p, 0)) or 0.0
            if prev is not None:
                allowed = prev * (1.0 + cap_pct) + 0.5  # allow small absolute tolerance
                if amt > allowed + 1e-9:
                    return False
            prev = amt
    return True

def parse_budget_model_rows(rows):
    # Return mapping week->dict of platforms, and contingency amount
    weekly = {}
    contingency_val = None
    for r in rows:
        week_label = (r.get("week") or r.get("Week") or r.get("WEEK") or "").strip()
        # gather platform columns
        meta = to_float(r.get("Meta")) if r.get("Meta") is not None else None
        goog = to_float(r.get("Google Search") or r.get("Google") or r.get("Search"))
        tiktok = to_float(r.get("TikTok") or r.get("Tiktok"))
        yt = to_float(r.get("YouTube") or r.get("Youtube") or r.get("YT"))
        week_total = to_float(r.get("week_total") or r.get("Week Total") or r.get("total") or r.get("Total"))
        if week_label.lower() == "contingency":
            # pick any non-null among values
            vals = [v for v in [meta, goog, tiktok, yt, week_total] if isinstance(v, float)]
            contingency_val = vals[0] if vals else None
        elif week_label.lower().startswith("week_") or week_label.lower().startswith("week"):
            # normalize to week_i
            m = re.search(r"([0-9]+)", week_label)
            if m:
                i = int(m.group(1))
                key = f"week_{i}"
                weekly[key] = {
                    "Meta": meta if meta is not None else 0.0,
                    "Google Search": goog if goog is not None else 0.0,
                    "TikTok": tiktok if tiktok is not None else 0.0,
                    "YouTube": yt if yt is not None else 0.0,
                    "_week_total": week_total
                }
    return weekly, contingency_val

def check_kpi_targets(kpi):
    # Returns tuple of booleans for structure and constraints
    if not isinstance(kpi, dict):
        return False, False, False
    global_ok = False
    platforms_ok = False
    attribution_ok = False

    gl = kpi.get("global")
    if isinstance(gl, dict):
        cac = gl.get("cac_target")
        payback = gl.get("payback_days_target")
        freq = gl.get("frequency_cap_per_week")
        testdur = gl.get("test_duration_weeks")
        if all(to_float(x) is not None for x in [cac, payback, freq, testdur]):
            cac = to_float(cac); payback = to_float(payback); freq = to_float(freq); testdur = to_float(testdur)
            if cac <= 45 and payback <= 45 and freq <= 4 and testdur >= 2:
                global_ok = True

    plats = kpi.get("platforms")
    if isinstance(plats, dict):
        req = ["Meta", "Google Search", "TikTok", "YouTube"]
        ok = True
        for p in req:
            obj = plats.get(p)
            if not isinstance(obj, dict):
                ok = False
                break
            if to_float(obj.get("cac_target")) is None or to_float(obj.get("roas_target")) is None:
                ok = False
                break
        platforms_ok = ok

    att = kpi.get("attribution_windows")
    if isinstance(att, dict):
        ok = True
        for p in ["Meta", "Google Search", "TikTok", "YouTube"]:
            o = att.get(p)
            if not isinstance(o, dict):
                ok = False
                break
            c = to_float(o.get("click"))
            v = to_float(o.get("view"))
            if c is None or v is None:
                ok = False
                break
        attribution_ok = ok

    return True, global_ok, (platforms_ok and attribution_ok)

def check_creative_briefs_text(text):
    if not isinstance(text, str):
        return False
    low = text.lower()
    conditions = [
        ("one variable per test" in low),
        ("ugc" in low),
        ("headline" in low),  # "headlines" or "headline"
        ("3-second hook" in low or "3 second hook" in low),
        ("skip rate" in low),
        ("learning phase" in low),
        ("search intent" in low),
    ]
    return all(conditions)

def compute_governance_scores(survey_json):
    # Expect keys for six domains with 8 control scores each (0-3)
    domains = [
        "Data Quality",
        "Data Cataloging",
        "Access Control",
        "Compliance Mapping",
        "Retention & Lifecycle",
        "AI/Agent Data Governance",
    ]
    domain_scores = {}
    ok = True
    for d in domains:
        arr = survey_json.get(d)
        if not isinstance(arr, list) or len(arr) != 8:
            ok = False
            domain_scores[d] = None
            continue
        try:
            vals = [float(x) for x in arr]
        except:
            ok = False
            domain_scores[d] = None
            continue
        score = (sum(vals) / 24.0) * 100.0
        domain_scores[d] = score
    if not ok:
        return None
    overall = sum(domain_scores.values()) / len(domain_scores)
    return domain_scores, overall

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        # media plan
        "media_plan_exists": False,
        "media_plan_structure_valid": False,
        "media_plan_budgets_non_negative": False,
        "media_plan_total_matches_budget": False,
        "media_plan_contingency_within_bounds": False,
        "media_plan_week1_conversions_threshold": False,
        "media_plan_week_over_week_cap_respected": False,
        # budget model
        "budget_model_exists": False,
        "budget_model_structure_rows": False,
        "budget_model_matches_media_plan": False,
        "budget_model_contingency_matches": False,
        # kpi targets
        "kpi_targets_exists": False,
        "kpi_global_bounds_valid": False,
        "kpi_platforms_and_attribution_valid": False,
        # creative briefs
        "creative_briefs_exists": False,
        "creative_briefs_required_phrases": False,
        # governance roadmap
        "governance_roadmap_exists": False,
        "governance_domain_scores_match": False,
        "governance_overall_score_matches": False,
        "governance_priority_order_correct": False,
        "governance_remediation_first_three_categories": False,
    }

    # Load inputs
    constraints_path = os.path.join(input_dir, "constraints.yaml")
    performance_path = os.path.join(input_dir, "performance.csv")
    governance_survey_path = os.path.join(input_dir, "governance_survey.json")

    constraints = parse_constraints_yaml(constraints_path)
    performance = parse_performance_csv(performance_path)
    governance_survey = load_json(governance_survey_path) or {}

    # MEDIA PLAN
    media_plan_path = os.path.join(output_dir, "media_plan.json")
    media_plan = load_json(media_plan_path)
    if media_plan is not None:
        checks["media_plan_exists"] = True
        # validate structure
        wb = media_plan.get("weekly_budgets")
        contingency = media_plan.get("contingency")
        if isinstance(wb, dict) and to_float(contingency) is not None:
            weeks_present = all(f"week_{i}" in wb for i in range(1, 14))
            platforms_ok = True
            if weeks_present:
                for i in range(1, 14):
                    d = wb.get(f"week_{i}", {})
                    if not isinstance(d, dict):
                        platforms_ok = False
                        break
                    for p in ["Meta", "Google Search", "TikTok", "YouTube"]:
                        if p not in d:
                            platforms_ok = False
                            break
                        if to_float(d.get(p)) is None:
                            platforms_ok = False
                            break
                    if not platforms_ok:
                        break
            checks["media_plan_structure_valid"] = bool(weeks_present and platforms_ok)

            # non-negative budgets
            weekly = get_weekly_budgets_from_media_plan(media_plan)
            if weekly:
                checks["media_plan_budgets_non_negative"] = validate_non_negative_budgets(weekly)

                # total equals budget with contingency within bounds
                total_spend = sum_weekly_budgets(weekly)
                contingency_val = to_float(contingency) or 0.0
                total_budget = constraints.get("total_budget")
                if total_budget is not None:
                    sum_ok = approx_equal(total_spend + contingency_val, total_budget, tol=0.5)
                    checks["media_plan_total_matches_budget"] = sum_ok
                    # contingency bounds
                    cmin = constraints.get("contingency_min_pct")
                    cmax = constraints.get("contingency_max_pct")
                    if cmin is not None and cmax is not None and total_budget and total_budget > 0:
                        ratio = contingency_val / float(total_budget)
                        checks["media_plan_contingency_within_bounds"] = (ratio + 1e-12 >= cmin - 1e-12) and (ratio - 1e-12 <= cmax + 1e-12)

                # week 1 conversions threshold
                # Require CPA from performance and ad set counts
                cpa_map = {p: performance.get(p, {}).get("cpa") for p in ["Meta", "Google Search", "TikTok", "YouTube"]}
                ad_counts = constraints.get("ad_counts") or {}
                week1 = weekly.get("week_1", {})
                conv = compute_week_conversions(week1, cpa_map)
                ok_conv = True
                for p in ["Meta", "Google Search", "TikTok", "YouTube"]:
                    needed = ad_counts.get(p)
                    if needed is None:
                        ok_conv = False
                        break
                    needed_convs = 50 * int(needed)
                    if conv.get(p) is None or conv.get(p) + 1e-9 < needed_convs - 1e-9:
                        ok_conv = False
                        break
                checks["media_plan_week1_conversions_threshold"] = ok_conv

                # week-over-week increase cap
                cap_pct = constraints.get("increase_cap_pct")
                checks["media_plan_week_over_week_cap_respected"] = validate_week_over_week_cap(weekly, cap_pct)

    # BUDGET MODEL
    budget_model_path = os.path.join(output_dir, "budget_model.csv")
    if os.path.isfile(budget_model_path):
        checks["budget_model_exists"] = True
        headers, rows = read_budget_model_csv(budget_model_path)
        if headers is not None and rows is not None:
            # At least header + 13 weeks + contingency row
            # Count week rows
            week_rows = 0
            has_contingency = False
            for r in rows:
                wl = (r.get("week") or r.get("Week") or r.get("WEEK") or "").strip().lower()
                if wl == "contingency":
                    has_contingency = True
                elif wl.startswith("week"):
                    week_rows += 1
            checks["budget_model_structure_rows"] = (week_rows >= 13 and has_contingency)

            # Compare to media_plan.json if available
            if checks["media_plan_structure_valid"]:
                weekly_media = get_weekly_budgets_from_media_plan(media_plan)
                contingency_media = to_float(media_plan.get("contingency"))
                weekly_csv, cont_row_val = parse_budget_model_rows(rows)
                match_all_weeks = True
                for i in range(1, 14):
                    wk = f"week_{i}"
                    csv_week = weekly_csv.get(wk)
                    mp_week = weekly_media.get(wk)
                    if not csv_week or not mp_week:
                        match_all_weeks = False
                        break
                    s_csv = (to_float(csv_week["Meta"]) or 0) + (to_float(csv_week["Google Search"]) or 0) + (to_float(csv_week["TikTok"]) or 0) + (to_float(csv_week["YouTube"]) or 0)
                    s_mp = (to_float(mp_week["Meta"]) or 0) + (to_float(mp_week["Google Search"]) or 0) + (to_float(mp_week["TikTok"]) or 0) + (to_float(mp_week["YouTube"]) or 0)
                    # Per-platform match
                    for p in ["Meta", "Google Search", "TikTok", "YouTube"]:
                        if not approx_equal(to_float(csv_week[p]) or 0.0, to_float(mp_week[p]) or 0.0, tol=0.5):
                            match_all_weeks = False
                            break
                    if not approx_equal(s_csv, s_mp, tol=0.5):
                        match_all_weeks = False
                    # If week_total provided, verify
                    if csv_week.get("_week_total") is not None:
                        if not approx_equal(to_float(csv_week.get("_week_total")) or 0.0, s_mp, tol=0.5):
                            match_all_weeks = False
                    if not match_all_weeks:
                        break
                checks["budget_model_matches_media_plan"] = match_all_weeks
                if contingency_media is not None and cont_row_val is not None:
                    checks["budget_model_contingency_matches"] = approx_equal(cont_row_val, contingency_media, tol=0.5)

    # KPI TARGETS
    kpi_targets_path = os.path.join(output_dir, "kpi_targets.json")
    kpi = load_json(kpi_targets_path)
    if kpi is not None:
        checks["kpi_targets_exists"] = True
        struct_ok, global_ok, plat_ok = check_kpi_targets(kpi)
        if struct_ok:
            checks["kpi_global_bounds_valid"] = global_ok
            checks["kpi_platforms_and_attribution_valid"] = plat_ok

    # CREATIVE BRIEFS
    creative_path = os.path.join(output_dir, "creative_briefs.md")
    creative_text = read_text(creative_path)
    if creative_text is not None:
        checks["creative_briefs_exists"] = True
        checks["creative_briefs_required_phrases"] = check_creative_briefs_text(creative_text)

    # GOVERNANCE ROADMAP
    governance_path = os.path.join(output_dir, "governance_roadmap.json")
    governance = load_json(governance_path)
    if governance is not None:
        checks["governance_roadmap_exists"] = True
        # compute expected scores
        comp = compute_governance_scores(governance_survey)
        if comp is not None:
            expected_domain_scores, expected_overall = comp
            # domain_scores present and match
            dom_scores_out = governance.get("domain_scores")
            if isinstance(dom_scores_out, dict):
                match_domains = True
                for d, exp in expected_domain_scores.items():
                    val = dom_scores_out.get(d)
                    if to_float(val) is None or abs(to_float(val) - exp) > 0.1:
                        match_domains = False
                        break
                checks["governance_domain_scores_match"] = match_domains
                # overall
                overall_out = governance.get("overall_score")
                if to_float(overall_out) is not None and abs(to_float(overall_out) - expected_overall) <= 0.1:
                    checks["governance_overall_score_matches"] = True
            # priority order exact
            target_order = ["Compliance Mapping", "Access Control", "AI/Agent Data Governance", "Data Quality", "Data Cataloging", "Retention & Lifecycle"]
            po = governance.get("priority_order")
            if isinstance(po, list) and po == target_order:
                checks["governance_priority_order_correct"] = True
            # remediation tasks
            rem = governance.get("remediation")
            if isinstance(rem, list) and len(rem) >= 3:
                ok3 = True
                categories = []
                for i in range(3):
                    item = rem[i]
                    if isinstance(item, dict):
                        cat = item.get("category") or item.get("domain")
                        categories.append(cat)
                    else:
                        categories.append(None)
                expect = ["Compliance Mapping", "Access Control", "AI/Agent Data Governance"]
                for i in range(3):
                    if categories[i] != expect[i]:
                        ok3 = False
                        break
                checks["governance_remediation_first_three_categories"] = ok3

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
    # Explicit no-op baseline: if output dir missing or empty, reward 0
    if not os.path.isdir(output_dir) or len(os.listdir(output_dir)) == 0:
        reward = 0.0

    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()