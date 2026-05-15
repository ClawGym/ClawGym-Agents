import json
import os
import re
import sys
from datetime import datetime

# Attempt to import YAML parser, fall back to JSON for simple cases
def load_yaml(path):
    try:
        import yaml  # type: ignore
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        # Fallback: try JSON if YAML module is unavailable or parsing fails
        try:
            import json as _json
            with open(path, "r", encoding="utf-8") as f:
                return _json.loads(f.read())
        except Exception:
            return None

def is_valid_date(date_str):
    if not isinstance(date_str, str):
        return False
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except Exception:
        return False

def rating_from_score(score):
    try:
        s = int(score)
    except Exception:
        return None
    if 1 <= s <= 5:
        return "Low"
    if 6 <= s <= 11:
        return "Medium"
    if 12 <= s <= 19:
        return "High"
    if 20 <= s <= 25:
        return "Critical"
    return None

def find_key_recursive(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = find_key_recursive(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_key_recursive(item, key)
            if found is not None:
                return found
    return None

def get_scenarios_list(obj):
    # Accept either top-level list or dict with 'scenarios' as a list
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        if isinstance(obj.get("scenarios"), list):
            return obj.get("scenarios")
    return None

def read_file_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    ensure_dir(reward_dir)  # Not required, but safe

    checks = {
        # Risk register checks
        "has_risk_register_file": False,
        "valid_yaml_risk_register": False,
        "risk_register_len_ge_12": False,
        "risk_ids_unique_and_prefixed": False,
        "risk_entries_valid": False,
        "categories_covered_all_8": False,
        "highcrit_outside_appetite_ge_3": False,
        "highcrit_controls_defense_in_depth": False,

        # Interconnections
        "has_interconnections_file": False,
        "valid_yaml_interconnections": False,
        "interconnections_cover_all_highcrit": False,
        "interconnections_two_distinct_cascades": False,

        # KRI dashboard
        "has_kri_dashboard_file": False,
        "valid_yaml_kri_dashboard": False,
        "kri_period_matches_context": False,
        "kri_total_kris_ge_20": False,
        "kri_category_summary_keys": False,

        # Board report
        "has_board_report_file": False,
        "board_report_contains_sections": False,

        # Scenario tests
        "has_scenario_tests_file": False,
        "valid_yaml_scenarios": False,
        "scenarios_count_ge_2": False,
        "scenarios_fields_complete": False,
    }

    # Paths
    rr_path = os.path.join(output_dir, "risk_register.yaml")
    ric_path = os.path.join(output_dir, "risk_interconnections.yaml")
    kri_path = os.path.join(output_dir, "kri_dashboard.yaml")
    rep_path = os.path.join(output_dir, "board_risk_report.md")
    scn_path = os.path.join(output_dir, "scenario_tests.yaml")
    org_ctx_path = os.path.join(input_dir, "org_context.yaml")

    # Risk register validations
    risk_register = None
    if os.path.isfile(rr_path):
        checks["has_risk_register_file"] = True
        risk_register_doc = load_yaml(rr_path)
        if isinstance(risk_register_doc, dict) and isinstance(risk_register_doc.get("risk_register"), list):
            checks["valid_yaml_risk_register"] = True
            risk_register = risk_register_doc.get("risk_register")

            # Length >= 12
            if len(risk_register) >= 12:
                checks["risk_register_len_ge_12"] = True

            # IDs unique and prefixed 'R-'
            ids = []
            ids_ok = True
            for r in risk_register:
                rid = r.get("id") if isinstance(r, dict) else None
                if not isinstance(rid, str) or not rid.startswith("R-"):
                    ids_ok = False
                    break
                ids.append(rid)
            if ids_ok and len(ids) == len(set(ids)):
                checks["risk_ids_unique_and_prefixed"] = True

            # Validate entries fields and scoring/rating consistency
            fields_ok = True
            categories = set()
            highcrit_ids = []
            highcrit_outside = 0
            defense_in_depth_ok = True
            allowed_categories = {"Strategic", "Financial", "Operational", "Compliance", "Cyber", "Reputational", "People", "External"}
            for r in risk_register:
                if not isinstance(r, dict):
                    fields_ok = False
                    break
                # Required top-level fields
                required_fields = [
                    "id", "title", "category", "description", "cause", "consequence",
                    "affected_objectives", "owner", "identified_date",
                    "inherent_likelihood", "inherent_impact", "inherent_score", "inherent_rating",
                    "controls",
                    "residual_likelihood", "residual_impact", "residual_score", "residual_rating",
                    "treatment_strategy", "action_plans", "key_risk_indicators",
                    "review_date", "trend", "velocity", "outside_appetite"
                ]
                for f in required_fields:
                    if f not in r:
                        fields_ok = False
                        break
                if not fields_ok:
                    break

                # Category coverage
                cat = r.get("category")
                if isinstance(cat, str):
                    categories.add(cat)

                # Date validation for identified_date & review_date
                if not is_valid_date(r.get("identified_date")) or not is_valid_date(r.get("review_date")):
                    fields_ok = False
                    break

                # Likelihood/impact and scores
                il = r.get("inherent_likelihood")
                ii = r.get("inherent_impact")
                iscore = r.get("inherent_score")
                rl = r.get("residual_likelihood")
                ri = r.get("residual_impact")
                rscore = r.get("residual_score")
                try:
                    il_ok = isinstance(il, int) and 1 <= il <= 5
                    ii_ok = isinstance(ii, int) and 1 <= ii <= 5
                    rl_ok = isinstance(rl, int) and 1 <= rl <= 5
                    ri_ok = isinstance(ri, int) and 1 <= ri <= 5
                    if not (il_ok and ii_ok and rl_ok and ri_ok):
                        fields_ok = False
                        break
                    if iscore != il * ii or rscore != rl * ri:
                        fields_ok = False
                        break
                except Exception:
                    fields_ok = False
                    break

                # Rating correctness
                inherent_rating = r.get("inherent_rating")
                residual_rating = r.get("residual_rating")
                if rating_from_score(iscore) != inherent_rating or rating_from_score(rscore) != residual_rating:
                    fields_ok = False
                    break

                # Controls existence
                controls = r.get("controls")
                if not isinstance(controls, list) or len(controls) < 1:
                    fields_ok = False
                    break
                # For High/Critical residual, require defense-in-depth: Preventive, Detective, Corrective
                if residual_rating in ("High", "Critical"):
                    highcrit_ids.append(r.get("id"))
                    # Count outside appetite
                    if r.get("outside_appetite") is True:
                        highcrit_outside += 1
                    types_present = set()
                    for c in controls:
                        if isinstance(c, dict):
                            t = c.get("type")
                            if isinstance(t, str):
                                types_present.add(t)
                    needed = {"Preventive", "Detective", "Corrective"}
                    if not needed.issubset(types_present):
                        defense_in_depth_ok = False

            if fields_ok:
                checks["risk_entries_valid"] = True

            # Categories coverage
            if allowed_categories.issubset(categories):
                checks["categories_covered_all_8"] = True

            # At least 3 risks High/Critical and outside_appetite = true
            if highcrit_outside >= 3:
                checks["highcrit_outside_appetite_ge_3"] = True

            if defense_in_depth_ok and checks["risk_entries_valid"]:
                # Only set this if entries are otherwise valid
                if len(highcrit_ids) > 0:
                    checks["highcrit_controls_defense_in_depth"] = True
                else:
                    # If there are no high/critical risks, this check should be false (per requirement)
                    checks["highcrit_controls_defense_in_depth"] = False

    # Risk interconnections validations (dependent on risk register to know high/critical IDs)
    risk_interconnections = None
    highcrit_list = []
    if checks["valid_yaml_risk_register"] and checks["risk_entries_valid"]:
        # Collect high/critical IDs from risk register
        highcrit_list = []
        for r in risk_register:
            if isinstance(r, dict) and r.get("residual_rating") in ("High", "Critical"):
                rid = r.get("id")
                if isinstance(rid, str):
                    highcrit_list.append(rid)

    if os.path.isfile(ric_path):
        checks["has_interconnections_file"] = True
        ric_doc = load_yaml(ric_path)
        if isinstance(ric_doc, dict) and isinstance(ric_doc.get("risk_interconnections"), list):
            checks["valid_yaml_interconnections"] = True
            risk_interconnections = ric_doc.get("risk_interconnections")

            # For each High/Critical risk in register, ensure presence with cascade_scenario non-empty
            cover_ok = True
            cascades = set()
            present_primary = set()
            for item in risk_interconnections:
                if not isinstance(item, dict):
                    continue
                pr = item.get("primary_risk")
                cs = item.get("cascade_scenario")
                if isinstance(pr, str):
                    present_primary.add(pr)
                if isinstance(cs, str) and cs.strip():
                    cascades.add(cs.strip())
            if highcrit_list:
                for hid in highcrit_list:
                    if hid not in present_primary:
                        cover_ok = False
                        break
            else:
                # If no high/critical risks, per requirements there should be none to cover; mark false to avoid vacuous pass
                cover_ok = False
            if cover_ok:
                checks["interconnections_cover_all_highcrit"] = True
            if len(cascades) >= 2:
                checks["interconnections_two_distinct_cascades"] = True

    # KRI dashboard validations
    kri_doc = None
    if os.path.isfile(kri_path):
        checks["has_kri_dashboard_file"] = True
        kri_doc = load_yaml(kri_path)
        if isinstance(kri_doc, dict) and isinstance(kri_doc.get("kri_dashboard"), dict):
            checks["valid_yaml_kri_dashboard"] = True
            kd = kri_doc.get("kri_dashboard")
            # Period matches org_context current_period
            org_ctx = load_yaml(org_ctx_path) if os.path.isfile(org_ctx_path) else None
            current_period = None
            if isinstance(org_ctx, dict):
                current_period = find_key_recursive(org_ctx, "current_period")
            period_ok = False
            if isinstance(kd.get("period"), str) and isinstance(current_period, str) and kd.get("period") == current_period:
                period_ok = True
            if period_ok:
                checks["kri_period_matches_context"] = True

            # total_kris >= 20
            summary = kd.get("summary")
            if isinstance(summary, dict):
                total_kris = summary.get("total_kris")
                try:
                    if int(total_kris) >= 20:
                        checks["kri_total_kris_ge_20"] = True
                except Exception:
                    pass

            # category_summary keys present
            cat_sum = kd.get("category_summary")
            needed_keys = {"strategic", "financial", "operational", "compliance", "cyber", "people"}
            if isinstance(cat_sum, dict) and needed_keys.issubset(set(cat_sum.keys())):
                checks["kri_category_summary_keys"] = True

    # Board risk report validations
    if os.path.isfile(rep_path):
        checks["has_board_report_file"] = True
        content = read_file_text(rep_path)
        if isinstance(content, str):
            cl = content.lower()
            if ("top 5 risks" in cl) and ("appetite breaches" in cl) and ("mitigation actions" in cl) and ("scenarios and stress tests" in cl):
                checks["board_report_contains_sections"] = True

    # Scenario tests validations
    if os.path.isfile(scn_path):
        checks["has_scenario_tests_file"] = True
        scn_doc = load_yaml(scn_path)
        scenarios = get_scenarios_list(scn_doc)
        if isinstance(scenarios, list):
            checks["valid_yaml_scenarios"] = True
            # Count >= 2
            if len(scenarios) >= 2:
                checks["scenarios_count_ge_2"] = True
            # Fields completeness
            fields_ok = True
            for s in scenarios:
                if not isinstance(s, dict):
                    fields_ok = False
                    break
                required = ["name", "category", "narrative", "trigger", "timeline", "severity", "impacts", "current_preparedness", "recommended_actions"]
                for f in required:
                    if f not in s:
                        fields_ok = False
                        break
                if not fields_ok:
                    break
                # impacts must include financial, operational, reputational, regulatory
                impacts = s.get("impacts")
                if not (isinstance(impacts, dict) and all(k in impacts for k in ["financial", "operational", "reputational", "regulatory"])):
                    fields_ok = False
                    break
                # current_preparedness must include existing_controls, gaps_identified, response_plan_status
                cp = s.get("current_preparedness")
                if not (isinstance(cp, dict) and "existing_controls" in cp and "gaps_identified" in cp and "response_plan_status" in cp):
                    fields_ok = False
                    break
                # recommended_actions must be a list (non-empty not mandated, just list)
                ra = s.get("recommended_actions")
                if not isinstance(ra, list):
                    fields_ok = False
                    break
                # Optionally check each recommended action has priority and timeline
                for a in ra:
                    if not isinstance(a, dict) or "priority" not in a or "timeline" not in a:
                        fields_ok = False
                        break
                if not fields_ok:
                    break
            if fields_ok:
                checks["scenarios_fields_complete"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Print result JSON with 'reward' first
    result = {"reward": round(reward, 6)}
    result.update(checks)
    # Ensure exactly one JSON object on last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()