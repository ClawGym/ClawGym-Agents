import json
import os
import sys

def load_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def parse_json_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def normalize_heading(s):
    s = s.strip()
    # Remove leading markdown heading markers if present
    while s.startswith("#"):
        s = s.lstrip("#").strip()
    return s

def find_heading_indices(lines, headings):
    indices = []
    last_idx = -1
    for heading in headings:
        found_idx = None
        for i in range(last_idx + 1, len(lines)):
            if normalize_heading(lines[i]) == heading:
                found_idx = i
                break
        if found_idx is None:
            return None  # missing heading
        indices.append(found_idx)
        last_idx = found_idx
    return indices

def get_section_slice(lines, heading, headings_order):
    # Find start and end lines for a given heading based on headings_order
    idx_map = {}
    for h in headings_order:
        # find first occurrence of each heading
        for i, line in enumerate(lines):
            if normalize_heading(line) == h and h not in idx_map:
                idx_map[h] = i
                break
    if heading not in idx_map:
        return []
    start = idx_map[heading] + 1
    # find next heading that appears after this one
    following_indices = [idx_map[h] for h in headings_order if h in idx_map and idx_map[h] > idx_map[heading]]
    end = min(following_indices) if following_indices else len(lines)
    return lines[start:end]

def count_bullets_in_section(section_lines):
    count = 0
    for line in section_lines:
        if line.lstrip().startswith("-"):
            count += 1
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "brief_exists": False,
        "brief_nonempty": False,
        "brief_has_headings_ordered": False,
        "brief_mentions_company": False,
        "brief_mentions_executive": False,
        "brief_citations_count_ge6": False,
        "brief_fit_assessment_contains": False,
        "brief_conversation_angles_2to3": False,
        "extracts_exists": False,
        "extracts_valid_json": False,
        "extracts_has_required_fields": False,
        "extracts_company_name_correct": False,
        "extracts_products_include_watchtower_pulse": False,
        "extracts_target_customers_include": False,
        "extracts_executive_contact_correct": False,
        "extracts_competitors_include": False,
        "extracts_review_pain_points_requirements": False,
        "extracts_job_signals_contains_required": False,
        "extracts_key_events_requirements": False,
        "extracts_fit_assessment_valid": False,
        "extracts_conversation_angles_2to3": False,
    }

    # Paths
    brief_path = os.path.join(output_dir, "brief.md")
    extracts_path = os.path.join(output_dir, "extracts.json")

    # Brief checks
    brief_text = None
    if os.path.isfile(brief_path):
        checks["brief_exists"] = True
        brief_text = load_text(brief_path)
        if brief_text is not None and len(brief_text.strip()) > 0:
            checks["brief_nonempty"] = True

    required_headings = [
        "Business Fundamentals",
        "Company Trajectory",
        "Executive / Contact Background",
        "Industry Signals",
        "Recent Activity (Last 90 Days)",
        "Fit Assessment",
        "Conversation Angles",
    ]

    if checks["brief_nonempty"]:
        lines = brief_text.splitlines()
        indices = find_heading_indices(lines, required_headings)
        if indices is not None and indices == sorted(indices):
            checks["brief_has_headings_ordered"] = True

            # Mentions company and executive
            if "Northwind Analytics" in brief_text:
                checks["brief_mentions_company"] = True
            if "Maya Patel" in brief_text:
                checks["brief_mentions_executive"] = True

            # Citations
            expected_sources = [
                "input/company_profile.json",
                "input/trajectory.json",
                "input/executive_maya_patel.txt",
                "input/job_postings.csv",
                "input/competitors.yaml",
                "input/reviews.json",
                "input/recent_news.jsonl",
                "input/website_updates.md",
            ]
            found_sources = set()
            for src in expected_sources:
                token = f"[source: {src}]"
                if token in brief_text:
                    found_sources.add(src)
            if len(found_sources) >= 6:
                checks["brief_citations_count_ge6"] = True

            # Fit Assessment section contains Strong/Moderate/Weak
            fit_section_lines = get_section_slice(lines, "Fit Assessment", required_headings)
            fit_text = "\n".join(fit_section_lines)
            if any(word in fit_text for word in ["Strong", "Moderate", "Weak"]):
                checks["brief_fit_assessment_contains"] = True

            # Conversation Angles section bullet count 2 or 3
            ca_section_lines = get_section_slice(lines, "Conversation Angles", required_headings)
            bullet_count = count_bullets_in_section(ca_section_lines)
            if bullet_count in (2, 3):
                checks["brief_conversation_angles_2to3"] = True

    # Extracts checks
    data = None
    if os.path.isfile(extracts_path):
        checks["extracts_exists"] = True
        data, err = parse_json_file(extracts_path)
        if data is not None and isinstance(data, dict):
            checks["extracts_valid_json"] = True

            # Required fields presence
            has_fields = True
            required_top = [
                "company_name",
                "products",
                "target_customers",
                "executive_contact",
                "key_events_last_12_months",
                "competitors",
                "review_pain_points",
                "job_signals",
                "fit_assessment",
                "conversation_angles",
            ]
            for k in required_top:
                if k not in data:
                    has_fields = False
                    break
            if has_fields:
                # nested executive_contact fields
                ec = data.get("executive_contact", {})
                if not isinstance(ec, dict) or "name" not in ec or "role" not in ec:
                    has_fields = False
            checks["extracts_has_required_fields"] = has_fields

            # company_name exact
            if data.get("company_name") == "Northwind Analytics":
                checks["extracts_company_name_correct"] = True

            # products include both
            products = data.get("products") if isinstance(data.get("products"), list) else []
            products_lc = [str(x).lower() for x in products]
            if "northwind watchtower".lower() in products_lc and "northwind pulse".lower() in products_lc:
                checks["extracts_products_include_watchtower_pulse"] = True

            # target_customers include one of specified
            targets = data.get("target_customers") if isinstance(data.get("target_customers"), list) else []
            targets_lc = [str(x).lower() for x in targets]
            tc_ok = any(
                ("mid-market e-commerce brands" in t) or ("digital marketplaces" in t)
                for t in targets_lc
            )
            if tc_ok:
                checks["extracts_target_customers_include"] = True

            # executive_contact correct
            ec = data.get("executive_contact", {})
            if isinstance(ec, dict):
                if ec.get("name") == "Maya Patel" and ec.get("role") == "CTO":
                    checks["extracts_executive_contact_correct"] = True

            # competitors include both
            competitors = data.get("competitors") if isinstance(data.get("competitors"), list) else []
            comp_lc = [str(x).lower() for x in competitors]
            if "datastreamiq" in comp_lc and "signalfloe" in comp_lc:
                checks["extracts_competitors_include"] = True

            # review pain points include Shopify and noisy/noise
            rpps = data.get("review_pain_points") if isinstance(data.get("review_pain_points"), list) else []
            rpps_lc = [str(x).lower() for x in rpps]
            has_shopify = any("shopify" in x for x in rpps_lc)
            has_noise = any(("noisy" in x) or ("noise" in x) for x in rpps_lc)
            if has_shopify and has_noise:
                checks["extracts_review_pain_points_requirements"] = True

            # job signals include at least one of specified
            jobs = data.get("job_signals") if isinstance(data.get("job_signals"), list) else []
            jobs_lc = [str(x).lower() for x in jobs]
            job_ok = any(
                s in jobs_lc for s in [
                    "partner manager",
                    "senior solutions architect",
                    "developer relations engineer"
                ]
            )
            if job_ok:
                checks["extracts_job_signals_contains_required"] = True

            # key events: at least 3 items and titles containing TinyETL, Pulse, SOC 2
            events = data.get("key_events_last_12_months")
            key_events_ok = False
            if isinstance(events, list) and len(events) >= 3:
                titles = []
                for ev in events:
                    if isinstance(ev, dict):
                        title = ev.get("title")
                        if isinstance(title, str):
                            titles.append(title.lower())
                if titles:
                    has_tinyetl = any("tinyetl" in t for t in titles)
                    has_pulse = any("pulse" in t for t in titles)
                    # support "soc 2" and "soc2"
                    has_soc2 = any(("soc 2" in t) or ("soc2" in t) for t in titles)
                    if has_tinyetl and has_pulse and has_soc2:
                        key_events_ok = True
            if key_events_ok:
                checks["extracts_key_events_requirements"] = True

            # fit_assessment valid value
            if data.get("fit_assessment") in ("Strong", "Moderate", "Weak"):
                checks["extracts_fit_assessment_valid"] = True

            # conversation_angles length 2 or 3
            conv = data.get("conversation_angles")
            if isinstance(conv, list) and len(conv) in (2, 3):
                checks["extracts_conversation_angles_2to3"] = True

    # Compute reward
    bool_checks = [v for v in checks.values() if isinstance(v, bool)]
    total = sum(1 for v in bool_checks if v)
    denom = len(bool_checks) if bool_checks else 1
    reward = total / denom if total > 0 else 0.0

    # Emit single JSON line
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()