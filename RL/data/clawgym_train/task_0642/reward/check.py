import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        try:
            with open(path, "r", encoding="latin-1") as f:
                return f.read()
        except Exception:
            return None

def is_non_empty_file(path):
    return os.path.isfile(path) and os.path.getsize(path) > 0

def contains_any(text, patterns, case_insensitive=True):
    if text is None:
        return False
    flags = re.IGNORECASE if case_insensitive else 0
    for p in patterns:
        if re.search(p, text, flags):
            return True
    return False

def line_starts_with(text, prefix):
    if text is None:
        return False
    for line in text.splitlines():
        if line.startswith(prefix):
            return True
    return False

def has_negative_keyword_same_line(text):
    if text is None:
        return False
    for line in text.splitlines():
        if re.search(r"\bnegative\b", line, flags=re.IGNORECASE) and re.search(r"\bkeyword(s)?\b", line, flags=re.IGNORECASE):
            return True
    # fallback: within short distance in text
    return re.search(r"negative.{0,100}keyword|keyword.{0,100}negative", text, flags=re.IGNORECASE|re.DOTALL) is not None

def has_property_tax_with_2_1(text):
    if text is None:
        return False
    # Require mention of "property tax" and a 2.1 rate representation somewhere in the document
    prop = re.search(r"\bproperty tax(es)?\b", text, flags=re.IGNORECASE) is not None
    rate = re.search(r"(~?\s*2\.1\s*%|\b2\.1\s*percent\b|\b2\.1\s*per\s*cent\b)", text, flags=re.IGNORECASE) is not None
    return prop and rate

def has_90_day_or_week_by_week(text):
    if text is None:
        return False
    if re.search(r"90-day", text, flags=re.IGNORECASE):
        return True
    # Consider week-by-week if at least 3 distinct week markers exist
    weeks = re.findall(r"\bWeek\s*([0-9]{1,2})\b", text, flags=re.IGNORECASE)
    return len(set(weeks)) >= 3

def has_cost_indicators(text):
    if text is None:
        return False
    # Option A: "1BR" and "$1,800" and "$2,500"
    opt_a = (re.search(r"\b1BR\b", text, flags=re.IGNORECASE) is not None and
             "$1,800" in text and "$2,500" in text)
    # Also accept "$1800" and "$2500" without comma as a small flexibility
    if not opt_a:
        opt_a = (re.search(r"\b1BR\b", text, flags=re.IGNORECASE) is not None and
                 (re.search(r"\$\s*1,?800\b", text) is not None) and
                 (re.search(r"\$\s*2,?500\b", text) is not None))
    # Option B: "Median home" with "$550,000"
    opt_b = (re.search(r"\bMedian home\b", text, flags=re.IGNORECASE) is not None and
             re.search(r"\$\s*550,?000\b", text) is not None)
    return opt_a or opt_b

def validate_checklist_schema(data):
    # Top-level keys
    required_keys = ["timeline_start", "timeline_end", "relocation_tasks", "launch_tasks", "ads_tasks"]
    if not isinstance(data, dict):
        return False, False, False
    has_keys = all(k in data for k in required_keys)
    if not has_keys:
        return False, False, False

    arrays_ok = True
    tasks_ok = True

    for key in ["relocation_tasks", "launch_tasks", "ads_tasks"]:
        arr = data.get(key)
        if not isinstance(arr, list) or len(arr) < 8:
            arrays_ok = False
        else:
            # Validate each item
            for item in arr:
                if not isinstance(item, dict):
                    tasks_ok = False
                    break
                if not all(field in item for field in ["task", "owner", "due_day"]):
                    tasks_ok = False
                    break
                if not isinstance(item["task"], str):
                    tasks_ok = False
                    break
                if not isinstance(item["owner"], str):
                    tasks_ok = False
                    break
                # due_day must be number (int/float). Accept ints and floats, but typical will be int.
                if not isinstance(item["due_day"], (int, float)):
                    tasks_ok = False
                    break
            # continue checking other arrays even if failed to set all flags accurately
    return has_keys, arrays_ok, tasks_ok

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    relocation_path = os.path.join(output_dir, "relocation", "relocation_guide.md")
    prfaq_path = os.path.join(output_dir, "product", "PRFAQ.md")
    ads_path = os.path.join(output_dir, "ads", "amazon_ad_strategy.md")
    checklist_path = os.path.join(output_dir, "plan", "checklist.json")

    checks = {}

    # 1) Relocation guide checks
    checks["relocation_exists"] = is_non_empty_file(relocation_path)
    relocation_text = read_text(relocation_path) if checks["relocation_exists"] else None

    # transportation reality mention
    transport_patterns = [
        r"\bcar-?centric\b",
        r"\bCapMetro\b",
        r"\bMetroRail\b",
        r"\bI-?35\b",
    ]
    checks["relocation_transportation_reality"] = checks["relocation_exists"] and contains_any(relocation_text, transport_patterns)

    # weather/allergy: heat and cedar fever
    heat_patterns = [
        r"\b100\s*F\b", r"\b100F\b",
        r"\b38\s*C\b", r"\b38C\b",
        r"\b40\s*C\b", r"\b40C\b"
    ]
    has_heat = checks["relocation_exists"] and contains_any(relocation_text, heat_patterns)
    has_cedar = checks["relocation_exists"] and re.search(r"\bcedar fever\b", relocation_text, flags=re.IGNORECASE) is not None
    checks["relocation_weather_allergy"] = bool(has_heat and has_cedar)

    # cost-of-living indicators
    checks["relocation_cost_indicators"] = checks["relocation_exists"] and has_cost_indicators(relocation_text)

    # tax reality
    has_no_income_tax = checks["relocation_exists"] and re.search(r"\bno state income tax\b", relocation_text, flags=re.IGNORECASE) is not None
    has_prop_tax = checks["relocation_exists"] and has_property_tax_with_2_1(relocation_text)
    checks["relocation_tax_reality"] = bool(has_no_income_tax and has_prop_tax)

    # 90-day move checklist reference
    checks["relocation_90_day_checklist"] = checks["relocation_exists"] and has_90_day_or_week_by_week(relocation_text)

    # 2) PRFAQ checks
    checks["prfaq_exists"] = is_non_empty_file(prfaq_path)
    prfaq_text = read_text(prfaq_path) if checks["prfaq_exists"] else None

    # "PRESS RELEASE" line start
    checks["prfaq_press_release_header"] = checks["prfaq_exists"] and line_starts_with(prfaq_text or "", "PRESS RELEASE")

    # headers containing "Customer" and "Internal"
    has_customer = checks["prfaq_exists"] and re.search(r"Customer", prfaq_text or "", flags=re.IGNORECASE) is not None
    has_internal = checks["prfaq_exists"] and re.search(r"Internal", prfaq_text or "", flags=re.IGNORECASE) is not None
    checks["prfaq_customer_header"] = bool(has_customer)
    checks["prfaq_internal_header"] = bool(has_internal)

    # Mentions of MBE, MEE, MPT, IRAC
    mentions_mbe = checks["prfaq_exists"] and re.search(r"\bMBE\b", prfaq_text or "") is not None
    mentions_mee = checks["prfaq_exists"] and re.search(r"\bMEE\b", prfaq_text or "") is not None
    mentions_mpt = checks["prfaq_exists"] and re.search(r"\bMPT\b", prfaq_text or "") is not None
    mentions_irac = checks["prfaq_exists"] and re.search(r"\bIRAC\b", prfaq_text or "", flags=re.IGNORECASE) is not None
    checks["prfaq_mentions_components"] = bool(mentions_mbe and mentions_mee and mentions_mpt and mentions_irac)

    # At least one price indicator "$"
    checks["prfaq_has_price_indicator"] = checks["prfaq_exists"] and ("$" in (prfaq_text or ""))

    # Contains "Austin"
    checks["prfaq_has_austin"] = checks["prfaq_exists"] and re.search(r"\bAustin\b", prfaq_text or "") is not None

    # 3) Amazon ad strategy checks
    checks["ads_exists"] = is_non_empty_file(ads_path)
    ads_text = read_text(ads_path) if checks["ads_exists"] else None

    # Campaign types
    has_sp = checks["ads_exists"] and re.search(r"\bSponsored Products\b", ads_text or "", flags=re.IGNORECASE) is not None
    has_sb = checks["ads_exists"] and re.search(r"\bSponsored Brands\b", ads_text or "", flags=re.IGNORECASE) is not None
    has_sd = checks["ads_exists"] and re.search(r"\bSponsored Display\b", ads_text or "", flags=re.IGNORECASE) is not None
    checks["ads_campaign_types"] = bool(has_sp and has_sb and has_sd)

    # Match types: auto, broad, phrase, exact
    has_auto = checks["ads_exists"] and re.search(r"\bauto\b", ads_text or "", flags=re.IGNORECASE) is not None
    has_broad = checks["ads_exists"] and re.search(r"\bbroad\b", ads_text or "", flags=re.IGNORECASE) is not None
    has_phrase = checks["ads_exists"] and re.search(r"\bphrase\b", ads_text or "", flags=re.IGNORECASE) is not None
    has_exact = checks["ads_exists"] and re.search(r"\bexact\b", ads_text or "", flags=re.IGNORECASE) is not None
    checks["ads_match_types"] = bool(has_auto and has_broad and has_phrase and has_exact)

    # ACoS and percent
    has_acos = checks["ads_exists"] and re.search(r"\bACoS\b", ads_text or "") is not None
    has_percent = checks["ads_exists"] and re.search(r"%", ads_text or "") is not None
    checks["ads_acos_and_percent"] = bool(has_acos and has_percent)

    # negative near keyword (same line or within 100 chars)
    checks["ads_negative_keyword"] = checks["ads_exists"] and has_negative_keyword_same_line(ads_text or "")

    # Week 1..4
    weeks = all([
        checks["ads_exists"] and re.search(r"\bWeek\s*1\b", ads_text or "", flags=re.IGNORECASE) is not None,
        checks["ads_exists"] and re.search(r"\bWeek\s*2\b", ads_text or "", flags=re.IGNORECASE) is not None,
        checks["ads_exists"] and re.search(r"\bWeek\s*3\b", ads_text or "", flags=re.IGNORECASE) is not None,
        checks["ads_exists"] and re.search(r"\bWeek\s*4\b", ads_text or "", flags=re.IGNORECASE) is not None,
    ])
    checks["ads_week_by_week"] = weeks

    # 4) Checklist JSON checks
    checks["checklist_exists"] = os.path.isfile(checklist_path)
    checks["checklist_valid_json"] = False
    checks["checklist_has_keys"] = False
    checks["checklist_task_arrays_len"] = False
    checks["checklist_task_items_valid"] = False
    if checks["checklist_exists"]:
        try:
            with open(checklist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            checks["checklist_valid_json"] = True
            has_keys, arrays_ok, tasks_ok = validate_checklist_schema(data)
            checks["checklist_has_keys"] = has_keys
            checks["checklist_task_arrays_len"] = arrays_ok
            checks["checklist_task_items_valid"] = tasks_ok
        except Exception:
            # leave False
            pass

    # Compute reward: fraction of deterministic checks passed.
    # Define which checks are deterministic and should count.
    deterministic_keys = [
        # relocation
        "relocation_exists",
        "relocation_transportation_reality",
        "relocation_weather_allergy",
        "relocation_cost_indicators",
        "relocation_tax_reality",
        "relocation_90_day_checklist",
        # prfaq
        "prfaq_exists",
        "prfaq_press_release_header",
        "prfaq_customer_header",
        "prfaq_internal_header",
        "prfaq_mentions_components",
        "prfaq_has_price_indicator",
        "prfaq_has_austin",
        # ads
        "ads_exists",
        "ads_campaign_types",
        "ads_match_types",
        "ads_acos_and_percent",
        "ads_negative_keyword",
        "ads_week_by_week",
        # checklist
        "checklist_exists",
        "checklist_valid_json",
        "checklist_has_keys",
        "checklist_task_arrays_len",
        "checklist_task_items_valid",
    ]

    passed = sum(1 for k in deterministic_keys if checks.get(k, False))
    total = len(deterministic_keys)

    # No-op baseline: if output is empty/missing required artifacts -> score 0.0 (already ensured by ratio)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # Ensure reward within [0,1]
    reward = max(0.0, min(1.0, float(reward)))

    result = {"reward": reward}
    # Merge checks into output
    result.update({k: bool(v) for k, v in checks.items()})

    print(json.dumps(result))

if __name__ == "__main__":
    main()