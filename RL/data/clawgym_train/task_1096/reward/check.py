import json
import os
import sys
import csv
import re
from datetime import datetime, date

def parse_date(s):
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    # Try common formats
    fmts = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dZ",
    ]
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            return dt.date()
        except Exception:
            continue
    # Fallback: try first 10 chars if ISO-like
    try:
        return datetime.fromisoformat(s[:19]).date()
    except Exception:
        pass
    return None

def to_float(s):
    try:
        if s is None or s == "":
            return None
        return float(str(s).replace(",", "").strip())
    except Exception:
        return None

def to_int(s):
    try:
        if s is None or s == "":
            return None
        return int(float(str(s).strip()))
    except Exception:
        return None

def truthy(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in ("true", "yes", "y", "1")

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def safe_read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_csv_dicts(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            rows.append({k: (v if v is not None else "") for k, v in r.items()})
    return rows

def date_in_range(d, start, end):
    if d is None or start is None or end is None:
        return False
    return start <= d <= end

def count_question_marks(s):
    return s.count("?")

def find_prospect(prospects, company_sub, last_name_sub):
    # Case-insensitive contains matching for company and last name
    for p in prospects:
        company = (p.get("Company") or p.get("company") or "").strip()
        role = (p.get("Role") or p.get("role") or "").strip()
        name = (p.get("Name") or p.get("name") or "").strip()
        first = (p.get("FirstName") or p.get("first_name") or p.get("first") or "").strip()
        last = (p.get("LastName") or p.get("last_name") or p.get("last") or "").strip()

        # Determine last name robustly
        ln = last
        if not ln:
            parts = name.split()
            if len(parts) >= 1:
                ln = parts[-1]
        if company.lower().find(company_sub.lower()) != -1 and ln.lower().find(last_name_sub.lower()) != -1:
            return p
    return None

def extract_last_name(p):
    last = (p.get("LastName") or p.get("last_name") or p.get("last") or "").strip()
    if last:
        return last
    name = (p.get("Name") or p.get("name") or "").strip()
    if name:
        parts = name.split()
        if len(parts) >= 1:
            return parts[-1]
    first = (p.get("FirstName") or p.get("first_name") or p.get("first") or "").strip()
    # If only first exists, return it as a fallback
    return last or first or ""

def compute_expected(pipeline_rows, meta):
    # Extract meta fields
    as_of = meta.get("as_of_date") or meta.get("asOfDate")
    as_of_date = parse_date(as_of)
    quota = meta.get("quota")
    if quota is None and "forecast" in meta:
        quota = meta["forecast"].get("quota")
    quota_val = to_float(quota) if quota is not None else None

    period_start = meta.get("period_start") or meta.get("forecast_start") or None
    period_end = meta.get("period_end") or meta.get("forecast_end") or None
    if period_start is None and "forecast_period" in meta and isinstance(meta["forecast_period"], dict):
        period_start = meta["forecast_period"].get("start")
        period_end = meta["forecast_period"].get("end")
    ps_date = parse_date(period_start)
    pe_date = parse_date(period_end)

    # Compute average_cycle_days for Closed Won deals
    cycle_days = []
    for r in pipeline_rows:
        stage = (r.get("Stage") or "").strip()
        if stage == "Closed Won":
            ft = parse_date(r.get("FirstTouchDate") or r.get("First Touch Date") or r.get("FirstTouch"))
            pc = parse_date(r.get("PlannedCloseDate") or r.get("Planned Close Date") or r.get("CloseDate"))
            if ft and pc:
                delta = (pc - ft).days
                cycle_days.append(delta)
    if cycle_days:
        avg_cycle = round(sum(cycle_days) / len(cycle_days))
    else:
        avg_cycle = 0

    # Identify open deals
    open_rows = []
    for r in pipeline_rows:
        stage = (r.get("Stage") or "").strip()
        if stage not in ("Closed Won", "Closed Lost"):
            open_rows.append(r)

    # Compute open_pipeline_period_amount
    open_sum = 0.0
    for r in open_rows:
        pc = parse_date(r.get("PlannedCloseDate") or r.get("Planned Close Date") or r.get("CloseDate"))
        if date_in_range(pc, ps_date, pe_date):
            amt = to_float(r.get("Amount"))
            if amt is not None:
                open_sum += amt
    coverage_ratio = None
    if quota_val is not None and quota_val != 0:
        coverage_ratio = open_sum / quota_val

    # Compute red flags for open deals
    expected_red_flags = {}  # deal -> set(flags)
    for r in open_rows:
        deal = (r.get("DealName") or r.get("Name") or r.get("Deal") or "").strip()
        flags = set()
        # no_activity_14d
        last_act = parse_date(r.get("LastActivityDate") or r.get("Last Activity Date") or r.get("LastActivity"))
        if as_of_date and last_act:
            if (as_of_date - last_act).days > 14:
                flags.add("no_activity_14d")
        # single_threaded
        cc = to_int(r.get("ContactsCount") or r.get("Contacts") or r.get("ContactCount"))
        if cc is not None and cc < 2:
            flags.add("single_threaded")
        # cycle_gt_3x
        ft = parse_date(r.get("FirstTouchDate") or r.get("First Touch Date") or r.get("FirstTouch"))
        if as_of_date and ft and avg_cycle and avg_cycle > 0:
            if (as_of_date - ft).days > 3 * avg_cycle:
                flags.add("cycle_gt_3x")
        expected_red_flags[deal] = flags

    # Determine commit deals per minimal rule
    expected_categories = {}
    allowed = {"commit", "best_case", "pipeline", "omit"}
    for r in pipeline_rows:
        deal = (r.get("DealName") or r.get("Name") or r.get("Deal") or "").strip()
        stage = (r.get("Stage") or "").strip()
        if stage == "Closed Lost":
            expected_categories[deal] = "omit"
            continue
        # Commit rule
        eb = truthy(r.get("EconBuyerMet"))
        met = truthy(r.get("MetricsConfirmed"))
        pain = truthy(r.get("PainDocumented"))
        dck = truthy(r.get("DecisionCriteriaKnown"))
        dp = truthy(r.get("DecisionProcessKnown"))
        champ = truthy(r.get("ChampionIdentified"))
        paper = truthy(r.get("PaperProcessKnown"))
        comp = truthy(r.get("CompetitionKnown"))
        if all([eb, met, pain, dck, dp, champ, paper, comp]) and stage in ("Negotiation", "Proposal", "Verbal"):
            expected_categories[deal] = "commit"
        else:
            # We do not deterministically classify others; mark as placeholder
            expected_categories.setdefault(deal, None)

    # Determine top 3 largest Amount open deals in period
    period_open = []
    for r in open_rows:
        pc = parse_date(r.get("PlannedCloseDate") or r.get("Planned Close Date") or r.get("CloseDate"))
        if date_in_range(pc, ps_date, pe_date):
            amt = to_float(r.get("Amount"))
            if amt is None:
                amt = 0.0
            deal = (r.get("DealName") or r.get("Name") or r.get("Deal") or "").strip()
            cc = to_int(r.get("ContactsCount") or r.get("Contacts") or r.get("ContactCount")) or 0
            period_open.append((deal, amt, cc))
    period_open.sort(key=lambda x: x[1], reverse=True)
    top3 = [d for d, _, _ in period_open[:3]]
    top3_multi_threaded = {d: (cc >= 2) for d, _, cc in period_open[:3]}

    # Special deals mentioned in validation
    special_expected_flags = {
        "LegacyTel - Security RFP": {"no_activity_14d", "single_threaded", "cycle_gt_3x"},
        "Orion Manufacturing - IoT Rollout": {"no_activity_14d", "single_threaded"},
        "Voyage Logistics - TMS Integration": {"no_activity_14d"},
    }

    return {
        "as_of_date": as_of_date,
        "period_start": ps_date,
        "period_end": pe_date,
        "quota": quota_val,
        "avg_cycle": avg_cycle,
        "open_pipeline_sum": open_sum,
        "coverage_ratio": coverage_ratio,
        "expected_red_flags": expected_red_flags,
        "expected_categories": expected_categories,
        "top3": top3,
        "top3_multi_threaded": top3_multi_threaded,
        "special_expected_flags": special_expected_flags,
    }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "has_pipeline_review_file": False,
        "pipeline_review_json_valid": False,
        "average_cycle_match": False,
        "pipeline_coverage_match": False,
        "red_flags_minimums_met": False,
        "forecast_categories_presence": False,
        "forecast_commit_rule_met": False,
        "forecast_closed_lost_omit": False,
        "has_stakeholder_maps_file": False,
        "stakeholder_maps_json_valid": False,
        "stakeholder_maps_top3_present": False,
        "stakeholder_maps_multi_threaded_correct": False,
        "has_email_apex": False,
        "email_apex_valid": False,
        "has_email_orion": False,
        "email_orion_valid": False,
        "has_email_voyage": False,
        "email_voyage_valid": False,
        "has_mutual_action_plan": False,
        "map_six_dated_steps_in_period": False,
        "map_required_sections_present": False,
    }

    # Read inputs
    pipeline_path = os.path.join(input_dir, "pipeline.csv")
    meta_path = os.path.join(input_dir, "meta.json")
    prospects_path = os.path.join(input_dir, "prospects.csv")
    case_studies_path = os.path.join(input_dir, "case_studies.md")

    try:
        pipeline_rows = read_csv_dicts(pipeline_path)
        meta = read_json(meta_path)
    except Exception:
        # If inputs missing or unparsable, no positive checks should pass
        pipeline_rows = []
        meta = {}

    expected = compute_expected(pipeline_rows, meta)

    # 1) Pipeline review
    pr_path = os.path.join(output_dir, "pipeline_review.json")
    if os.path.isfile(pr_path):
        checks["has_pipeline_review_file"] = True
        try:
            pr = read_json(pr_path)
            # Validate structure
            required_top = ["as_of_date", "average_cycle_days", "pipeline_coverage", "red_flags", "forecast_categories"]
            if all(k in pr for k in required_top):
                pc = pr.get("pipeline_coverage", {})
                pc_keys_ok = all(k in pc for k in ["period_start", "period_end", "quota", "open_pipeline_period_amount", "coverage_ratio"])
                if isinstance(pr.get("red_flags"), list) and isinstance(pr.get("forecast_categories"), dict) and pc_keys_ok:
                    checks["pipeline_review_json_valid"] = True

            # Compare average_cycle_days
            if checks["pipeline_review_json_valid"]:
                avg_agent = pr.get("average_cycle_days")
                if isinstance(avg_agent, (int, float)):
                    if int(round(avg_agent)) == int(expected["avg_cycle"]):
                        checks["average_cycle_match"] = True

                # Compare pipeline coverage
                pc_agent = pr.get("pipeline_coverage", {})
                # Dates must match meta (string compare)
                ps = pc_agent.get("period_start")
                pe = pc_agent.get("period_end")
                quota_agent = pc_agent.get("quota")
                open_sum_agent = pc_agent.get("open_pipeline_period_amount")
                cov_agent = pc_agent.get("coverage_ratio")

                # Convert expected dates to string YYYY-MM-DD for compare
                def date_to_str(d):
                    return d.strftime("%Y-%m-%d") if isinstance(d, date) else None

                ps_match = (ps == date_to_str(expected["period_start"]))
                pe_match = (pe == date_to_str(expected["period_end"]))
                quota_match = (isinstance(quota_agent, (int, float)) and isinstance(expected["quota"], (int, float)) and float(quota_agent) == float(expected["quota"]))
                amount_match = isinstance(open_sum_agent, (int, float)) and abs(float(open_sum_agent) - float(expected["open_pipeline_sum"])) < 1e-6
                ratio_match = isinstance(cov_agent, (int, float)) and expected["coverage_ratio"] is not None and abs(float(cov_agent) - float(expected["coverage_ratio"])) <= 0.01

                if ps_match and pe_match and quota_match and amount_match and ratio_match:
                    checks["pipeline_coverage_match"] = True

                # Red flags minimums
                # Build a map from agent red_flags to sets
                agent_rf_list = pr.get("red_flags", [])
                agent_rf_map = {}
                for item in agent_rf_list:
                    deal = (item.get("deal") or "").strip()
                    flags = item.get("flags") or []
                    agent_rf_map[deal] = set(flags)

                specials_ok = True
                for deal_name, required_flags in expected["special_expected_flags"].items():
                    # Only check if that deal appears in expected open list (i.e., in expected red flags computation)
                    if deal_name in expected["expected_red_flags"]:
                        agent_flags = agent_rf_map.get(deal_name)
                        if not agent_flags or not required_flags.issubset(agent_flags):
                            specials_ok = False
                            break
                checks["red_flags_minimums_met"] = specials_ok

                # Forecast categories presence and validity
                fc = pr.get("forecast_categories", {})
                # Ensure all deals present
                all_deals = set()
                for r in pipeline_rows:
                    dn = (r.get("DealName") or r.get("Name") or r.get("Deal") or "").strip()
                    if dn:
                        all_deals.add(dn)
                present_all = all(d in fc for d in all_deals)
                allowed_vals = {"commit", "best_case", "pipeline", "omit"}
                values_valid = all(v in allowed_vals for v in fc.values())
                if present_all and values_valid:
                    checks["forecast_categories_presence"] = True

                # Commit rule met for those that satisfy minimal rule in data
                commit_ok = True
                for deal, cat in expected["expected_categories"].items():
                    if cat == "commit":
                        if fc.get(deal) != "commit":
                            commit_ok = False
                            break
                checks["forecast_commit_rule_met"] = commit_ok

                # Closed Lost are omit
                closed_lost_ok = True
                for r in pipeline_rows:
                    stage = (r.get("Stage") or "").strip()
                    deal = (r.get("DealName") or r.get("Name") or r.get("Deal") or "").strip()
                    if stage == "Closed Lost":
                        if fc.get(deal) != "omit":
                            closed_lost_ok = False
                            break
                checks["forecast_closed_lost_omit"] = closed_lost_ok

        except Exception:
            # JSON parse or comparison errors -> remain False
            pass

    # 2) Stakeholder maps
    sm_path = os.path.join(output_dir, "stakeholder_maps.json")
    if os.path.isfile(sm_path):
        checks["has_stakeholder_maps_file"] = True
        try:
            sm = read_json(sm_path)
            if isinstance(sm, dict):
                checks["stakeholder_maps_json_valid"] = True
                # Verify top3 present
                top3 = expected["top3"]
                top3_present = all(k in sm for k in top3) if top3 else False
                checks["stakeholder_maps_top3_present"] = top3_present
                # Verify subkeys and multi_threaded correctness
                mt_ok = True
                for d in top3:
                    if d not in sm:
                        mt_ok = False
                        break
                    entry = sm.get(d) or {}
                    # Required subkeys
                    needed = ["champion", "economic_buyer", "technical_evaluator", "end_users", "multi_threaded"]
                    if not all(k in entry for k in needed):
                        mt_ok = False
                        break
                    # multi_threaded
                    expected_mt = expected["top3_multi_threaded"].get(d, False)
                    if entry.get("multi_threaded") is not expected_mt:
                        mt_ok = False
                        break
                    # end_users as list
                    if not isinstance(entry.get("end_users"), list):
                        mt_ok = False
                        break
                checks["stakeholder_maps_multi_threaded_correct"] = mt_ok
        except Exception:
            pass

    # 3) Outreach emails
    try:
        prospects = read_csv_dicts(prospects_path)
    except Exception:
        prospects = []

    # Find specific prospects for mapping
    apex_p = find_prospect(prospects, "Apex Retail", "Schultz")
    orion_p = find_prospect(prospects, "Orion Manufacturing", "Alvarez")
    voyage_p = find_prospect(prospects, "Voyage Logistics", "Nair")

    emails = [
        ("email_apex_schultz.txt", apex_p, "Apex Retail", "Schultz", "apex"),
        ("email_orion_alvarez.txt", orion_p, "Orion Manufacturing", "Alvarez", "orion"),
        ("email_voyage_nair.txt", voyage_p, "Voyage Logistics", "Nair", "voyage"),
    ]
    for filename, prospect, company_label, last_label, key in emails:
        path = os.path.join(output_dir, "outreach", filename)
        has_key = f"has_email_{key}"
        valid_key = f"email_{key}_valid"
        if os.path.isfile(path):
            checks[has_key] = True
            try:
                content = safe_read_text(path) or ""
                # Contains "Subject:"
                cond_subject = "Subject:" in content
                # Contains last name and company (case-insensitive)
                ln = extract_last_name(prospect) if prospect else last_label
                comp = (prospect.get("Company") if prospect else company_label) if prospect else company_label
                cond_name_company = (ln and ln.lower() in content.lower()) and (comp and comp.lower() in content.lower())
                # Contains exact Trigger string
                trig = (prospect.get("Trigger") or prospect.get("trigger") or "").strip() if prospect else ""
                cond_trigger = (trig in content) if trig else False
                # Exactly one question mark
                cond_one_q = count_question_marks(content) == 1
                # Not contain banned phrase
                cond_no_banned = "i hope this email finds you well" not in content.lower()
                # Contains Result: with a percentage
                # Look for a line with "Result:" and a percentage like 23%
                has_result_pct = False
                for line in content.splitlines():
                    if "Result:" in line:
                        if re.search(r"Result:\s*[^%\n]*\d+\s*%", line):
                            has_result_pct = True
                            break
                if cond_subject and cond_name_company and cond_trigger and cond_one_q and cond_no_banned and has_result_pct:
                    checks[valid_key] = True
            except Exception:
                pass
        else:
            checks[has_key] = False
            checks[valid_key] = False

    # 4) Mutual Action Plan
    map_path = os.path.join(output_dir, "mutual_action_plan_apex_retail.md")
    if os.path.isfile(map_path):
        checks["has_mutual_action_plan"] = True
        try:
            text = safe_read_text(map_path) or ""
            # Count lines that start with "- [ ] " and contain Due: YYYY-MM-DD within forecast period
            ps = expected["period_start"]
            pe = expected["period_end"]
            count_ok = 0
            for line in text.splitlines():
                if line.strip().startswith("- [ ] "):
                    m = re.search(r"Due:\s*(\d{4}-\d{2}-\d{2})", line)
                    if m:
                        d = parse_date(m.group(1))
                        if date_in_range(d, ps, pe):
                            count_ok += 1
            if count_ok >= 6:
                checks["map_six_dated_steps_in_period"] = True
            # Contains substrings Security, and either Legal or Procurement, and Economic Buyer
            has_security = "security" in text.lower()
            has_legal_or_proc = ("legal" in text.lower()) or ("procurement" in text.lower())
            has_econ_buyer = "economic buyer" in text.lower()
            if has_security and has_legal_or_proc and has_econ_buyer:
                checks["map_required_sections_present"] = True
        except Exception:
            pass

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or empty of required artifacts, reward must be 0.0
    # If none of the main output files exist, force reward 0.0
    main_outputs_exist = any([
        checks["has_pipeline_review_file"],
        checks["has_stakeholder_maps_file"],
        checks["has_email_apex"],
        checks["has_email_orion"],
        checks["has_email_voyage"],
        checks["has_mutual_action_plan"],
    ])
    if not main_outputs_exist:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()