import sys
import os
import json
import csv
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_number(x):
    if isinstance(x, (int, float)):
        return True
    try:
        float(x)
        return True
    except Exception:
        return False

def normalize(s):
    return re.sub(r"\s+", " ", s or "").strip().lower()

def contains_any(s, needles):
    s_norm = s.lower()
    return any(n.lower() in s_norm for n in needles)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # KPI file checks
        "kpis_file_exists": False,
        "kpis_has_required_headers": False,
        "kpis_has_production_gp_row": False,
        "kpis_has_production_hygienist_row": False,
        "kpis_has_hygiene_prod_ratio": False,
        "kpis_has_collection_rate": False,
        "kpis_has_no_show_rate": False,
        "kpis_has_ar_90plus": False,
        "kpis_has_assessment_markers": False,

        # PPO file checks
        "ppo_file_exists": False,
        "ppo_is_valid_array": False,
        "ppo_has_required_keys_objects": False,

        # Action plan checks
        "action_plan_exists": False,
        "action_has_block_scheduling": False,
        "action_has_high_production_or_morning_afternoon": False,
        "action_has_no_show_with_timings_and_target": False,
        "action_has_ucr_threshold_string": False,
        "action_has_cdt_code": False,
        "action_has_osha_hipaa": False,
    }

    # 1) Check output/kpis.csv
    kpis_path = os.path.join(output_dir, "kpis.csv")
    if os.path.isfile(kpis_path):
        checks["kpis_file_exists"] = True
        try:
            with open(kpis_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                header_lc = [h.strip().lower() for h in (reader.fieldnames or [])]
                # Must include at least kpi and value. Target and assessment should also exist.
                if "kpi" in header_lc and "value" in header_lc and "target" in header_lc and "assessment" in header_lc:
                    checks["kpis_has_required_headers"] = True

                rows = []
                for row in reader:
                    # Normalize keys to lower
                    row_norm = { (k or "").strip().lower(): (v or "").strip() for k, v in row.items() if k is not None }
                    rows.append(row_norm)

                # Helper: find rows by kpi content
                def kpi_rows_matching(predicate):
                    matched = []
                    for r in rows:
                        kpi = r.get("kpi", "")
                        if predicate(kpi):
                            matched.append(r)
                    return matched

                # Production per provider/day - GP
                prod_pred = lambda s: ("production per provider" in s.lower() and "day" in s.lower())
                prod_rows = kpi_rows_matching(prod_pred)

                for r in prod_rows:
                    k = r.get("kpi", "").lower()
                    if ("gp" in k) or ("general" in k) or ("dentist" in k):
                        checks["kpis_has_production_gp_row"] = True
                    if "hygienist" in k or "hygiene" in k:
                        checks["kpis_has_production_hygienist_row"] = True

                # Hygiene production ratio
                if kpi_rows_matching(lambda s: "hygiene production ratio" in s.lower()):
                    checks["kpis_has_hygiene_prod_ratio"] = True

                # Collection rate
                if kpi_rows_matching(lambda s: "collection rate" in s.lower()):
                    checks["kpis_has_collection_rate"] = True

                # No-show rate (handle both "no-show" and "no show")
                if kpi_rows_matching(lambda s: "no-show rate" in s.lower() or "no show rate" in s.lower()):
                    checks["kpis_has_no_show_rate"] = True

                # AR >90 days: accept variations like "AR >90 days" or "AR 90+"
                def ar_90_pred(s):
                    sl = s.lower()
                    return ("ar" in sl) and (">90" in sl or "90+" in sl)
                if kpi_rows_matching(ar_90_pred):
                    checks["kpis_has_ar_90plus"] = True

                # Assessment markers: check required KPI rows have on_target or needs_attention markers
                assessment_ok = True
                required_predicates = [
                    # GP Production per provider/day
                    lambda s: ("production per provider" in s.lower() and "day" in s.lower() and ("gp" in s.lower() or "general" in s.lower() or "dentist" in s.lower())),
                    # Hygienist Production per provider/day
                    lambda s: ("production per provider" in s.lower() and "day" in s.lower() and ("hygienist" in s.lower() or "hygiene" in s.lower())),
                    # Hygiene production ratio
                    lambda s: "hygiene production ratio" in s.lower(),
                    # Collection rate
                    lambda s: "collection rate" in s.lower(),
                    # No-show rate
                    lambda s: "no-show rate" in s.lower() or "no show rate" in s.lower(),
                    # AR >90
                    ar_90_pred
                ]
                # For each required KPI concept, find a row and check assessment marker
                def has_marker(val):
                    valn = (val or "").strip().lower().replace("-", " ").replace("_", " ")
                    return ("on target" in valn) or ("needs attention" in valn) or ("on_target" in (val or "").lower()) or ("needs_attention" in (val or "").lower())

                for pred in required_predicates:
                    matched = kpi_rows_matching(pred)
                    if not matched:
                        assessment_ok = False
                        break
                    # Choose any one matched row to check marker
                    marker_found = False
                    for r in matched:
                        a = r.get("assessment", "")
                        if has_marker(a):
                            marker_found = True
                            break
                    if not marker_found:
                        assessment_ok = False
                        break

                if assessment_ok:
                    checks["kpis_has_assessment_markers"] = True

        except Exception:
            # Parsing failed; leave KPI checks as is
            pass

    # 2) Check output/ppo_drop_candidates.json
    ppo_path = os.path.join(output_dir, "ppo_drop_candidates.json")
    if os.path.isfile(ppo_path):
        checks["ppo_file_exists"] = True
        data = load_json(ppo_path)
        if isinstance(data, list) and len(data) >= 1:
            checks["ppo_is_valid_array"] = True
            required_ok_all = True
            allowed_recos = {"drop", "renegotiate", "monitor"}
            for obj in data:
                if not isinstance(obj, dict):
                    required_ok_all = False
                    break
                if "plan_name" not in obj or "reimbursement_below_65pct" not in obj or "codes_below_threshold" not in obj or "patient_share_pct" not in obj or "recommendation" not in obj:
                    required_ok_all = False
                    break
                if not isinstance(obj["plan_name"], str):
                    required_ok_all = False
                    break
                if not isinstance(obj["reimbursement_below_65pct"], bool):
                    required_ok_all = False
                    break
                if not isinstance(obj["codes_below_threshold"], list):
                    required_ok_all = False
                    break
                if not is_number(obj["patient_share_pct"]):
                    required_ok_all = False
                    break
                if not isinstance(obj["recommendation"], str) or obj["recommendation"].lower() not in allowed_recos:
                    required_ok_all = False
                    break
            if required_ok_all:
                checks["ppo_has_required_keys_objects"] = True

    # 3) Check output/action_plan.md
    ap_path = os.path.join(output_dir, "action_plan.md")
    if os.path.isfile(ap_path):
        checks["action_plan_exists"] = True
        text = read_text(ap_path)
        text_l = text.lower()

        # Block Scheduling mention
        if "block scheduling" in text_l:
            checks["action_has_block_scheduling"] = True

        # HIGH production block or morning/afternoon high-production window
        if "high production block" in text_l:
            checks["action_has_high_production_or_morning_afternoon"] = True
        else:
            # Fallback: both morning and afternoon appear and "high" and "production" appear
            if ("morning" in text_l and "afternoon" in text_l and "high" in text_l and "production" in text_l):
                checks["action_has_high_production_or_morning_afternoon"] = True

        # No-Show and timing with target <5%
        has_no_show = "no-show" in text_l or "no show" in text_l
        has_48 = "48-hour" in text_l or "48hr" in text_l or "48 hour" in text_l
        has_24 = "24-hour" in text_l or "24hr" in text_l or "24 hour" in text_l
        has_2 = "2-hour" in text_l or "2hr" in text_l or "2 hour" in text_l
        has_target_lt5 = "<5%" in text or "less than 5%" in text_l or "< 5%" in text
        if has_no_show and has_48 and has_24 and has_2 and has_target_lt5:
            checks["action_has_no_show_with_timings_and_target"] = True

        # "<65% of UCR"
        if "<65% of ucr" in text_l:
            checks["action_has_ucr_threshold_string"] = True

        # CDT code mention among D0120, D2750, D3330
        if any(code.lower() in text_l for code in ["d0120", "d2750", "d3330"]):
            checks["action_has_cdt_code"] = True

        # OSHA and HIPAA
        if "osha" in text_l and "hipaa" in text_l:
            checks["action_has_osha_hipaa"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks

    # Ensure no-op empty outputs get exactly 0.0
    if not os.path.isdir(output_dir) or len([n for n in os.listdir(output_dir)]) == 0:
        reward = 0.0

    # Print JSON result
    out = {"reward": float(round(reward, 6))}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()