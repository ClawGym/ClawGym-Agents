import json
import os
import sys
import csv
import re

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def parse_days_value(val):
    # Accept numeric days or strings like "7", "7d", "14 days"
    if is_number(val):
        return float(val)
    if isinstance(val, str):
        m = re.search(r"(\d+)", val)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                return None
    if isinstance(val, dict):
        # If it's a dict with 'days'
        d = val.get("days")
        if is_number(d):
            return float(d)
        if isinstance(d, str):
            return parse_days_value(d)
    return None

def placements_valid(placements):
    # Valid if:
    # - String "Automatic" (case-insensitive) or "Automatic Placements"
    # - Or array including "Feed" and one of "Stories" or "Reels"
    if isinstance(placements, str):
        p = placements.strip().lower()
        if p in ("automatic", "automatic placements"):
            return True
        return False
    if isinstance(placements, list):
        norm = {str(x).strip() for x in placements}
        has_feed = any(str(x).strip().lower() == "feed" for x in placements)
        has_stories_or_reels = any(str(x).strip().lower() in ("stories", "reels") for x in placements)
        return has_feed and has_stories_or_reels
    return False

def validate_plan(plan):
    checks = {
        "plan_exists": False,
        "plan_valid_json": False,
        "plan_has_required_top_keys": False,
        "plan_min_two_campaigns": False,
        "plan_campaign_fields_valid": False,
        "plan_campaign_names_prefixed": False,
        "plan_has_retargeting_campaign": False,
        "plan_has_adv_or_dynamic": False,
        "plan_all_adsets_requirements": False,
        "plan_has_lookalike_adset": False,
    }

    if plan is None:
        return checks

    checks["plan_exists"] = True
    if not isinstance(plan, dict):
        return checks
    checks["plan_valid_json"] = True

    # Top-level keys
    if all(k in plan for k in ("account", "campaigns", "assumptions")) and isinstance(plan.get("campaigns"), list):
        checks["plan_has_required_top_keys"] = True

    campaigns = plan.get("campaigns", [])
    if isinstance(campaigns, list) and len(campaigns) >= 2:
        checks["plan_min_two_campaigns"] = True

    # Campaign-level validations
    campaign_fields_ok = True
    names_prefixed_ok = True
    has_retargeting = False
    has_adv_or_dynamic = False
    adsets_all_ok = True
    has_lookalike_adset = False

    for camp in campaigns if isinstance(campaigns, list) else []:
        # Required fields
        name = camp.get("name")
        objective = camp.get("objective")
        purpose = camp.get("purpose")
        budget_type = camp.get("budget_type")
        budget = camp.get("budget")
        ad_sets = camp.get("ad_sets")
        learning_phase = camp.get("learning_phase")

        if not (isinstance(name, str) and isinstance(objective, str) and isinstance(purpose, str) and
                isinstance(budget_type, str) and ad_sets is not None and isinstance(ad_sets, list) and
                isinstance(learning_phase, str)):
            campaign_fields_ok = False

        # budget must be numeric (do not require positive per spec)
        if not is_number(budget):
            campaign_fields_ok = False

        # purpose must be one of required
        if purpose not in ("prospecting", "retargeting", "testing"):
            campaign_fields_ok = False

        # budget_type must be CBO or ABO
        if budget_type not in ("CBO", "ABO"):
            campaign_fields_ok = False

        # name prefix
        if not (isinstance(name, str) and name.startswith("META_")):
            names_prefixed_ok = False

        # retargeting presence
        if purpose == "retargeting":
            has_retargeting = True

        # Validate ad sets
        for ad in ad_sets if isinstance(ad_sets, list) else []:
            audience_type = ad.get("audience_type")
            placements = ad.get("placements")
            frequency_cap = ad.get("frequency_cap")
            exclusions = ad.get("exclusions")
            creative_variants = ad.get("creative_variants")
            dynamic_ads_flag = ad.get("dynamic_ads", False)

            # Advantage+ or Dynamic Ads condition
            if (isinstance(audience_type, str) and audience_type == "advantage_plus") or (isinstance(dynamic_ads_flag, bool) and dynamic_ads_flag is True):
                has_adv_or_dynamic = True

            # at least one lookalike ad set
            if isinstance(audience_type, str) and audience_type == "lookalike":
                has_lookalike_adset = True

            # audience_type must be in set
            if audience_type not in ("lookalike", "interest", "advantage_plus", "retargeting"):
                adsets_all_ok = False

            # placements validity
            if not placements_valid(placements):
                adsets_all_ok = False

            # frequency_cap number <= 3
            if not is_number(frequency_cap) or float(frequency_cap) > 3:
                adsets_all_ok = False

            # exclusions recent_converters with days >= 7
            if not isinstance(exclusions, dict) or "recent_converters" not in exclusions:
                adsets_all_ok = False
            else:
                days_val = None
                rc = exclusions.get("recent_converters")
                days_val = parse_days_value(rc if not isinstance(rc, dict) else rc.get("days", rc))
                if days_val is None or days_val < 7:
                    adsets_all_ok = False

            # creative_variants array with len 3-5
            if not isinstance(creative_variants, list) or not (3 <= len(creative_variants) <= 5):
                adsets_all_ok = False

    checks["plan_campaign_fields_valid"] = campaign_fields_ok
    checks["plan_campaign_names_prefixed"] = names_prefixed_ok
    checks["plan_has_retargeting_campaign"] = has_retargeting
    checks["plan_has_adv_or_dynamic"] = has_adv_or_dynamic
    checks["plan_all_adsets_requirements"] = adsets_all_ok
    checks["plan_has_lookalike_adset"] = has_lookalike_adset

    return checks

def validate_audiences(aud):
    checks = {
        "audiences_exists": False,
        "audiences_valid_json": False,
        "audiences_has_required_keys": False,
        "audiences_has_high_ltv_1pct": False,
        "audiences_retargeting_has_window_and_exclusions": False,
    }
    if aud is None:
        return checks
    checks["audiences_exists"] = True
    if not isinstance(aud, dict):
        return checks
    checks["audiences_valid_json"] = True

    lookalikes = aud.get("lookalikes")
    interests = aud.get("interests")
    retargeting = aud.get("retargeting")
    if isinstance(lookalikes, list) and isinstance(interests, list) and isinstance(retargeting, list):
        checks["audiences_has_required_keys"] = True

    # high LTV 1% lookalike
    high_ltv_ok = False
    for item in lookalikes if isinstance(lookalikes, list) else []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", ""))
        pct = item.get("percentage")
        source_l = source.lower()
        if ("ltv" in source_l) or ("high_ltv_customers" in source_l):
            # normalize percentage
            pct_val = None
            if is_number(pct):
                pct_val = float(pct)
            elif isinstance(pct, str):
                m = re.search(r"(\d+(\.\d+)?)", pct)
                if m:
                    try:
                        pct_val = float(m.group(1))
                    except Exception:
                        pct_val = None
            # Accept <= 1 (interpreted as 1%)
            if pct_val is not None and pct_val <= 1.0:
                high_ltv_ok = True
                break
    checks["audiences_has_high_ltv_1pct"] = high_ltv_ok

    # retargeting with window_days and exclusions including recent_converters
    r_ok = False
    for r in retargeting if isinstance(retargeting, list) else []:
        if not isinstance(r, dict):
            continue
        window_days = r.get("window_days")
        exclusions = r.get("exclusions")
        if is_number(window_days) and isinstance(exclusions, dict) and "recent_converters" in exclusions:
            r_ok = True
            break
    checks["audiences_retargeting_has_window_and_exclusions"] = r_ok

    return checks

def validate_naming_csv(path):
    checks = {
        "naming_exists": False,
        "naming_csv_header_valid": False,
        "naming_min_three_rows": False,
        "naming_name_format_valid": False,
    }
    if not os.path.isfile(path):
        return checks
    checks["naming_exists"] = True
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return checks
    if not rows:
        return checks
    header = [h.strip() for h in rows[0]]
    expected_header = ["name", "objective", "audience", "offer", "date"]
    if header == expected_header:
        checks["naming_csv_header_valid"] = True

    data_rows = rows[1:]
    if len(data_rows) >= 3:
        checks["naming_min_three_rows"] = True

    # Validate name column format
    name_format_ok = True
    for row in data_rows:
        if not row or len(row) < 1:
            name_format_ok = False
            break
        name_val = row[0].strip() if len(row) >= 1 else ""
        if not name_val.startswith("META_"):
            name_format_ok = False
            break
        parts = name_val.split("_")
        if len(parts) != 5 or parts[0] != "META":
            name_format_ok = False
            break
    checks["naming_name_format_valid"] = name_format_ok

    return checks

def validate_creative_briefs(path):
    checks = {
        "creative_briefs_exists": False,
        "creative_briefs_has_sections": False,
    }
    if not os.path.isfile(path):
        return checks
    checks["creative_briefs_exists"] = True
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return checks
    t = text.lower()
    hook_count = t.count("hook")
    problem_count = t.count("problem")
    solution_count = t.count("solution")
    cta_count = t.count("cta")
    if hook_count >= 3 and problem_count >= 3 and solution_count >= 3 and cta_count >= 3:
        checks["creative_briefs_has_sections"] = True
    return checks

def validate_tracking(path):
    checks = {
        "tracking_checklist_exists": False,
        "tracking_has_pixel_and_capi": False,
    }
    if not os.path.isfile(path):
        return checks
    checks["tracking_checklist_exists"] = True
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return checks
    t = text.lower()
    if ("meta pixel" in t) and ("conversions api" in t):
        checks["tracking_has_pixel_and_capi"] = True
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    plan_path = os.path.join(output_dir, "META_campaign_plan.json")
    aud_path = os.path.join(output_dir, "META_audience_definitions.json")
    naming_path = os.path.join(output_dir, "META_naming_examples.csv")
    briefs_path = os.path.join(output_dir, "META_creative_briefs.md")
    tracking_path = os.path.join(output_dir, "META_tracking_checklist.md")

    # Load and validate plan
    plan_json, plan_loaded = load_json_file(plan_path) if os.path.isfile(plan_path) else (None, False)
    plan_checks = validate_plan(plan_json if plan_loaded else None)

    # Load and validate audiences
    aud_json, aud_loaded = load_json_file(aud_path) if os.path.isfile(aud_path) else (None, False)
    audience_checks = validate_audiences(aud_json if aud_loaded else None)

    # Naming CSV
    naming_checks = validate_naming_csv(naming_path)

    # Creative briefs
    briefs_checks = validate_creative_briefs(briefs_path)

    # Tracking checklist
    tracking_checks = validate_tracking(tracking_path)

    # Aggregate checks
    all_checks = {}
    all_checks.update(plan_checks)
    all_checks.update(audience_checks)
    all_checks.update(naming_checks)
    all_checks.update(briefs_checks)
    all_checks.update(tracking_checks)

    total = len(all_checks)
    passed = sum(1 for v in all_checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # Ensure reward is 0.0 when there are no outputs at all (no-op baseline)
    # If none of the key files exist, reward should be 0.0 (already ensured by passed==0)
    result = {"reward": round(reward, 6)}
    result.update(all_checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()