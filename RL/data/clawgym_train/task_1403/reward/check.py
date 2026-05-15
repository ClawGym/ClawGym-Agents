import json
import os
import re
import sys

def load_json_safe(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def iter_emails(tiers_obj):
    # Yield (tier_name, email_obj) for all emails across tiers
    for tier_name in ["Tier1", "Tier2", "Tier3"]:
        tier = tiers_obj.get(tier_name, {})
        for email in tier.get("emails", []):
            yield tier_name, email

def collect_urls_and_meeting_links(obj, parent_key=""):
    urls = set()
    meeting_urls = set()
    scheduling_keywords = ["schedule", "scheduling", "meeting", "meetings", "calendar", "calendly"]
    if isinstance(obj, dict):
        for k, v in obj.items():
            k_str = str(k).lower()
            child_urls, child_meetings = collect_urls_and_meeting_links(v, k_str)
            urls |= child_urls
            meeting_urls |= child_meetings
    elif isinstance(obj, list):
        for item in obj:
            child_urls, child_meetings = collect_urls_and_meeting_links(item, parent_key)
            urls |= child_urls
            meeting_urls |= child_meetings
    elif isinstance(obj, str):
        s = obj.strip()
        if s.startswith("http://") or s.startswith("https://"):
            urls.add(s)
            parent = (parent_key or "").lower()
            if any(kw in parent for kw in scheduling_keywords):
                meeting_urls.add(s)
    return urls, meeting_urls

def get_lead_counts(leads_json):
    # Try to extract Hot/Warm/Cold counts from various possible structures
    counts = {"Hot": None, "Warm": None, "Cold": None}
    if not isinstance(leads_json, (dict, list)):
        return counts
    # Direct keys
    for key in list(leads_json.keys()) if isinstance(leads_json, dict) else []:
        lk = key.lower()
        val = leads_json.get(key)
        if isinstance(val, dict):
            # If nested dict with 'count' or similar
            if "count" in val and isinstance(val["count"], (int, float)):
                if lk == "hot":
                    counts["Hot"] = int(val["count"])
                elif lk == "warm":
                    counts["Warm"] = int(val["count"])
                elif lk == "cold":
                    counts["Cold"] = int(val["count"])
        if isinstance(val, (int, float)):
            if lk == "hot":
                counts["Hot"] = int(val)
            elif lk == "warm":
                counts["Warm"] = int(val)
            elif lk == "cold":
                counts["Cold"] = int(val)
    # Try alternative top-level mapping like {"Tier1": n, ...}
    if isinstance(leads_json, dict):
        for key, val in leads_json.items():
            lk = key.lower()
            if isinstance(val, (int, float)):
                if lk in ("tier1", "t1"):
                    counts["Hot"] = int(val)
                elif lk in ("tier2", "t2"):
                    counts["Warm"] = int(val)
                elif lk in ("tier3", "t3"):
                    counts["Cold"] = int(val)
            if isinstance(val, dict) and "lead_count" in val and isinstance(val["lead_count"], (int, float)):
                if lk in ("tier1", "t1", "hot"):
                    counts["Hot"] = int(val["lead_count"])
                elif lk in ("tier2", "t2", "warm"):
                    counts["Warm"] = int(val["lead_count"])
                elif lk in ("tier3", "t3", "cold"):
                    counts["Cold"] = int(val["lead_count"])
    # If list of items with type/label
    if isinstance(leads_json, list):
        for item in leads_json:
            if isinstance(item, dict):
                label = str(item.get("label") or item.get("tier") or item.get("name") or "").lower()
                count_val = item.get("count") or item.get("lead_count")
                if isinstance(count_val, (int, float)):
                    if "hot" in label or label in ("tier1", "t1"):
                        counts["Hot"] = int(count_val)
                    elif "warm" in label or label in ("tier2", "t2"):
                        counts["Warm"] = int(count_val)
                    elif "cold" in label or label in ("tier3", "t3"):
                        counts["Cold"] = int(count_val)
    return counts

def contains_bracket_token(text):
    if not isinstance(text, str):
        return False
    return re.search(r"\[[^\]]+\]", text) is not None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "file_exists": False,
        "json_valid": False,
        "top_level_keys": False,
        "show_crm_product_ok": False,
        "lead_counts_match": False,
        "tier1_schedule_and_emails": False,
        "tier2_schedule_and_emails": False,
        "tier3_schedule_abtest": False,
        "personalization_tokens_all_emails": False,
        "hubspot_tag_present": False,
        "no_attachments": False,
        "asset_links_valid": False,
        "cta_requirements": False,
        "tier3_phrase_required": False,
        "handoff_summary_valid": False,
        "meeting_link_in_tier1_and_tier2": False,
    }

    # Paths
    output_path = os.path.join(output_dir, "sequences.json")
    show_brief_path = os.path.join(input_dir, "show_brief.json")
    leads_breakdown_path = os.path.join(input_dir, "leads_breakdown.json")
    resources_path = os.path.join(input_dir, "resources.json")

    # Load inputs
    show_brief = load_json_safe(show_brief_path)
    leads_breakdown = load_json_safe(leads_breakdown_path)
    resources = load_json_safe(resources_path)

    # Evaluate only if output exists and parses
    if os.path.isfile(output_path):
        checks["file_exists"] = True
        data = load_json_safe(output_path)
        if isinstance(data, dict):
            checks["json_valid"] = True
        else:
            data = None
    else:
        data = None

    if not checks["json_valid"]:
        # Print result with 0 reward if invalid or missing
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = 0.0 if not checks["file_exists"] else 0.0
        print(json.dumps({"reward": reward, **checks}))
        return

    # Check top-level keys and tiers presence
    required_top = {"show_name", "product", "crm", "tiers", "handoff_summary"}
    tiers_required = {"Tier1", "Tier2", "Tier3"}
    top_ok = set(data.keys()) >= required_top and isinstance(data.get("tiers"), dict) and tiers_required <= set(data.get("tiers", {}).keys())
    checks["top_level_keys"] = bool(top_ok)

    # show_name and crm, product mention identity/governance
    show_name_ok = (str(data.get("show_name", "")) == "RSA Conference 2026")
    crm_ok = (str(data.get("crm", "")) == "HubSpot")
    product_str = str(data.get("product", "") or "")
    product_ok = bool(product_str) and (("identity" in product_str.lower()) or ("governance" in product_str.lower()))
    checks["show_crm_product_ok"] = bool(show_name_ok and crm_ok and product_ok)

    # Lead counts match inputs
    expected_counts = get_lead_counts(leads_breakdown if isinstance(leads_breakdown, (dict, list)) else {})
    t1_count = data.get("tiers", {}).get("Tier1", {}).get("lead_count")
    t2_count = data.get("tiers", {}).get("Tier2", {}).get("lead_count")
    t3_count = data.get("tiers", {}).get("Tier3", {}).get("lead_count")
    if all(isinstance(x, int) for x in [t1_count, t2_count, t3_count]) and all(expected_counts.get(k) is not None for k in ["Hot", "Warm", "Cold"]):
        checks["lead_counts_match"] = (t1_count == expected_counts["Hot"] and t2_count == expected_counts["Warm"] and t3_count == expected_counts["Cold"])

    tiers = data.get("tiers", {})

    # Tier1: emails and schedule
    tier1 = tiers.get("Tier1", {})
    t1_sched = tier1.get("schedule")
    t1_emails = tier1.get("emails")
    t1_ok = (
        isinstance(t1_sched, list) and t1_sched == [1, 4, 10] and
        isinstance(t1_emails, list) and len(t1_emails) == 3 and
        sorted([e.get("send_day") for e in t1_emails]) == [1, 4, 10]
    )
    checks["tier1_schedule_and_emails"] = bool(t1_ok)

    # Tier2: emails and schedule
    tier2 = tiers.get("Tier2", {})
    t2_sched = tier2.get("schedule")
    t2_emails = tier2.get("emails")
    t2_ok = (
        isinstance(t2_sched, list) and t2_sched == [2, 7] and
        isinstance(t2_emails, list) and len(t2_emails) == 2 and
        sorted([e.get("send_day") for e in t2_emails]) == [2, 7]
    )
    checks["tier2_schedule_and_emails"] = bool(t2_ok)

    # Tier3: emails, schedule, ab_test_subjects
    tier3 = tiers.get("Tier3", {})
    t3_sched = tier3.get("schedule")
    t3_emails = tier3.get("emails")
    ab_subjects = tier3.get("ab_test_subjects")
    t3_emails_ok = isinstance(t3_emails, list) and len(t3_emails) == 2
    t3_first_day_ok = False
    t3_sched_ok = False
    if t3_emails_ok:
        e1_day = t3_emails[0].get("send_day")
        e2_day = t3_emails[1].get("send_day")
        t3_first_day_ok = isinstance(e1_day, int) and e1_day in [3, 4, 5] and e2_day == 14
        if isinstance(t3_sched, list) and len(t3_sched) == 2 and t3_first_day_ok:
            t3_sched_ok = (t3_sched[0] == e1_day and t3_sched[1] == 14)
    ab_ok = isinstance(ab_subjects, list) and len(ab_subjects) == 2 and all(isinstance(s, str) and s.strip() for s in ab_subjects)
    checks["tier3_schedule_abtest"] = bool(t3_emails_ok and t3_first_day_ok and t3_sched_ok and ab_ok)

    # Personalization tokens in every email body
    all_bodies_have_brackets = True
    for _, email in iter_emails(tiers):
        body = email.get("body", "")
        if not (isinstance(body, str) and body.strip() and contains_bracket_token(body)):
            all_bodies_have_brackets = False
            break
    checks["personalization_tokens_all_emails"] = bool(all_bodies_have_brackets)

    # HubSpot merge tag presence anywhere in subject or body
    hubspot_tag_found = False
    for tier_name, email in iter_emails(tiers):
        subj = str(email.get("subject", "") or "")
        body = str(email.get("body", "") or "")
        if "{{contact.firstname}}" in subj or "{{contact.firstname}}" in body:
            hubspot_tag_found = True
            break
    checks["hubspot_tag_present"] = bool(hubspot_tag_found)

    # No 'attach' or 'attachment' in any body
    no_attach = True
    for _, email in iter_emails(tiers):
        body = str(email.get("body", "") or "")
        if re.search(r"attach|attachment", body, flags=re.IGNORECASE):
            no_attach = False
            break
    checks["no_attachments"] = bool(no_attach)

    # Asset links valid against resources.json
    allowed_urls, meeting_urls = collect_urls_and_meeting_links(resources if isinstance(resources, (dict, list)) else {})
    all_assets_valid = True
    non_empty_subj_body = True
    for _, email in iter_emails(tiers):
        asset = email.get("asset_link")
        subj = email.get("subject")
        body = email.get("body")
        if not (isinstance(subj, str) and subj.strip() and isinstance(body, str) and body.strip()):
            non_empty_subj_body = False
        if not (isinstance(asset, str) and asset in allowed_urls):
            all_assets_valid = False
            break
    checks["asset_links_valid"] = bool(all_assets_valid and non_empty_subj_body)

    # CTA requirements
    # Tier1: at least one cta contains "book" or "schedule"
    # Tier2: at least one cta contains "demo" or "guide"
    # Tier3: at least one cta contains one of "resource","intro","opt-in","call"
    def cta_contains_any(emails, keywords):
        for e in emails or []:
            cta = str(e.get("cta", "")).lower()
            if any(kw in cta for kw in keywords):
                return True
        return False

    t1_cta_ok = cta_contains_any(tier1.get("emails"), ["book", "schedule"])
    t2_cta_ok = cta_contains_any(tier2.get("emails"), ["demo", "guide"])
    t3_cta_ok = cta_contains_any(tier3.get("emails"), ["resource", "intro", "opt-in", "call"])
    checks["cta_requirements"] = bool(t1_cta_ok and t2_cta_ok and t3_cta_ok)

    # Tier3 Email 1 specific phrase requirement
    t3_phrase_ok = False
    if t3_emails_ok:
        body1 = str(t3_emails[0].get("body", "") or "")
        if "We connected briefly at RSA Conference 2026" in body1:
            t3_phrase_ok = True
    checks["tier3_phrase_required"] = bool(t3_phrase_ok)

    # Handoff summary validation
    handoff = data.get("handoff_summary", {})
    handoff_ok = True
    if not isinstance(handoff, dict):
        handoff_ok = False
    else:
        for tier_key, owner_cue in [("Tier1", "AE"), ("Tier2", "SDR"), ("Tier3", "Marketing")]:
            tier_info = handoff.get(tier_key)
            if not isinstance(tier_info, dict):
                handoff_ok = False
                break
            owner = tier_info.get("owner")
            send_window = tier_info.get("send_window")
            first_asset = tier_info.get("first_asset")
            if not (isinstance(owner, str) and owner_cue in owner):
                handoff_ok = False
                break
            if not (isinstance(send_window, str) and "Day" in send_window):
                handoff_ok = False
                break
            if not (isinstance(first_asset, str) and first_asset in allowed_urls):
                handoff_ok = False
                break
    checks["handoff_summary_valid"] = bool(handoff_ok)

    # Scheduling link presence in at least one Tier1 and one Tier2 email body
    meeting_link_ok = False
    if meeting_urls:
        t1_has = False
        t2_has = False
        for e in tier1.get("emails", []):
            body = str(e.get("body", "") or "")
            if any(m in body for m in meeting_urls):
                t1_has = True
                break
        for e in tier2.get("emails", []):
            body = str(e.get("body", "") or "")
            if any(m in body for m in meeting_urls):
                t2_has = True
                break
        meeting_link_ok = t1_has and t2_has
    checks["meeting_link_in_tier1_and_tier2"] = bool(meeting_link_ok)

    # Compute reward as fraction of checks passed; no-op baseline gets 0.0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = round(passed / total_checks, 6) if checks["file_exists"] and checks["json_valid"] else 0.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()