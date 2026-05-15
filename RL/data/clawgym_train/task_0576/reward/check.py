import json
import os
import sys
import re
import csv

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return None

def parse_json_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def parse_simple_budget_cap(yaml_text):
    # Attempt to extract a total budget cap number from preferences.yaml
    # Look for lines like "budget_cap: 50000" or "total_budget: 50,000" or "budget: 50000"
    if not yaml_text:
        return None
    # Search for common keys followed by a number
    patterns = [
        r'(?i)budget\s*cap\s*:\s*\$?\s*([0-9][0-9,]*)',
        r'(?i)total\s*budget\s*:\s*\$?\s*([0-9][0-9,]*)',
        r'(?i)budget\s*:\s*\$?\s*([0-9][0-9,]*)',
        r'(?i)cap\s*:\s*\$?\s*([0-9][0-9,]*)',
    ]
    for pat in patterns:
        m = re.search(pat, yaml_text)
        if m:
            num = m.group(1).replace(',', '')
            try:
                return float(num)
            except Exception:
                continue
    # Also try to find a dollar amount near the word budget in the same line
    for line in yaml_text.splitlines():
        if re.search(r'(?i)budget', line):
            m = re.search(r'\$?\s*([0-9][0-9,]*)', line)
            if m:
                try:
                    return float(m.group(1).replace(',', ''))
                except Exception:
                    pass
    return None

def csv_read_dicts(path):
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = reader.fieldnames or []
            return headers, rows
    except Exception:
        return None, None

def normalize_header_line(line):
    # Strip leading '#' and spaces to get header text
    s = line.strip()
    s = s.lstrip('#').strip()
    return s

def contains_line_starting_with(text, label):
    # Check if any line starts with the exact label (ignoring leading spaces)
    for line in text.splitlines():
        if line.lstrip().startswith(label):
            return True
    return False

def extract_first_heading_as_name(md_text):
    if not md_text:
        return None
    for line in md_text.splitlines():
        if line.strip().startswith('#'):
            name = line.strip().lstrip('#').strip()
            if name:
                return name
    # Try to find "Event Name: ..."
    m = re.search(r'(?i)^ *event *name *: *(.+)$', md_text, flags=re.MULTILINE)
    if m:
        val = m.group(1).strip()
        if val:
            return val
    # Fallback to first non-empty line
    for line in md_text.splitlines():
        if line.strip():
            return line.strip()
    return None

def extract_emails(text):
    if not text:
        return []
    return re.findall(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', text)

def strip_currency_to_int(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(round(val))
    s = str(val)
    s = s.replace(',', '').replace('$', '').strip()
    # Extract first integer-like substring
    m = re.search(r'(-?\d+)', s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None

def parse_percent(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    s = s.replace('%', '').strip()
    try:
        return float(s)
    except Exception:
        return None

def count_bullets_between_sections(md_text, start_title, next_titles):
    if not md_text:
        return 0
    lines = md_text.splitlines()
    # Find start index
    start_idx = None
    for i, line in enumerate(lines):
        header = normalize_header_line(line)
        if header == start_title:
            start_idx = i + 1
            break
    if start_idx is None:
        return 0
    # Find end index as the next occurrence of any of the next_titles
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        header = normalize_header_line(lines[j])
        if header in next_titles:
            end_idx = j
            break
    # Count bullet lines
    count = 0
    for k in range(start_idx, end_idx):
        l = lines[k].lstrip()
        if l.startswith('-') or l.startswith('*'):
            count += 1
    return count

def validate_due_date(date_str):
    if not isinstance(date_str, str):
        return False
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}$', date_str))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Prepare input references
    brief_path = os.path.join(input_dir, "brief.md")
    preferences_path = os.path.join(input_dir, "preferences.yaml")
    venue_json_path = os.path.join(input_dir, "venue_shortlist.json")

    brief_text = read_text(brief_path)
    preferences_text = read_text(preferences_path)
    venue_list = parse_json_file(venue_json_path)

    event_name = extract_first_heading_as_name(brief_text) if brief_text else None
    emails_in_brief = extract_emails(brief_text) if brief_text else []
    rsvp_email = emails_in_brief[0] if emails_in_brief else None
    total_budget_cap = parse_simple_budget_cap(preferences_text)

    # Collect venue names and addresses from shortlist
    venue_names = set()
    venue_addresses = set()
    if isinstance(venue_list, list):
        for v in venue_list:
            if isinstance(v, dict):
                # case-insensitive access
                name = None
                addr = None
                for k, val in v.items():
                    kl = str(k).lower()
                    if kl == 'name':
                        name = str(val)
                    if kl == 'address':
                        addr = str(val)
                if name:
                    venue_names.add(name.strip())
                if addr:
                    venue_addresses.add(addr.strip())

    # PLAN.MD checks
    plan_path = os.path.join(output_dir, "plan.md")
    checks["has_plan_md"] = False
    checks["plan_headers_ok"] = False
    checks["plan_timeline_markers"] = False
    checks["plan_mentions_september"] = False
    checks["plan_mentions_two_venue_names"] = False
    checks["plan_mentions_one_venue_address"] = False

    if os.path.isfile(plan_path):
        checks["has_plan_md"] = True
        plan_text = read_text(plan_path) or ""
        # Headers
        required_headers = [
            "Date & Time",
            "Venue (Primary & Backup)",
            "Expected Attendance",
            "Budget Summary",
            "Theme",
            "Timeline",
        ]
        header_hits = []
        for h in required_headers:
            found = False
            for line in plan_text.splitlines():
                hdr = normalize_header_line(line)
                if hdr == h:
                    found = True
                    break
            header_hits.append(found)
        checks["plan_headers_ok"] = all(header_hits)

        # Timeline markers
        tl_labels = ["8 weeks:", "6 weeks:", "4 weeks:", "2 weeks:", "1 week:", "Day of:"]
        tl_ok = True
        for label in tl_labels:
            if not contains_line_starting_with(plan_text, label):
                tl_ok = False
                break
        checks["plan_timeline_markers"] = tl_ok

        # Mentions September
        checks["plan_mentions_september"] = bool(re.search(r'\bseptember\b', plan_text, flags=re.IGNORECASE))

        # Venue names and address presence
        # Check at least two distinct venue names present in plan.md
        names_found = set()
        lower_plan = plan_text.lower()
        for nm in venue_names:
            if nm and nm.strip() and nm.lower() in lower_plan:
                names_found.add(nm)
        checks["plan_mentions_two_venue_names"] = len(names_found) >= 2

        address_found = False
        for addr in venue_addresses:
            if addr and addr.strip() and addr in plan_text:
                address_found = True
                break
        checks["plan_mentions_one_venue_address"] = address_found

    # BUDGET.CSV checks
    budget_path = os.path.join(output_dir, "budget.csv")
    checks["has_budget_csv"] = False
    checks["budget_headers_ok"] = False
    checks["budget_categories_present"] = False
    checks["budget_percent_sum_100"] = False
    checks["budget_percent_ranges_ok"] = False
    checks["budget_amounts_match_total"] = False

    if os.path.isfile(budget_path):
        checks["has_budget_csv"] = True
        headers, rows = csv_read_dicts(budget_path)
        if headers is not None and rows is not None:
            headers_lower = [h.strip().lower() for h in headers]
            checks["budget_headers_ok"] = headers_lower == ["category", "percent", "amount_usd"]

            # Required categories
            required_cats = ["venue", "catering", "photography", "floral/decor", "misc"]
            # Build map of category -> percent, amount
            cat_map = {}
            sum_percent = 0.0
            amounts_match = True
            for r in rows:
                cat = (r.get("category") or r.get("Category") or "").strip()
                pct = parse_percent(r.get("percent") or r.get("Percent"))
                amt = strip_currency_to_int(r.get("amount_usd") or r.get("Amount_usd") or r.get("Amount_USD") or r.get("amount"))
                if pct is not None:
                    sum_percent += pct
                if cat:
                    cat_map[cat.lower()] = {"percent": pct, "amount": amt}
            # Categories present
            checks["budget_categories_present"] = all(rc in cat_map for rc in required_cats)
            # Sum percent
            if sum_percent is not None:
                checks["budget_percent_sum_100"] = abs(sum_percent - 100.0) <= 0.1
            # Percent ranges
            ranges = {
                "venue": (30.0, 40.0),
                "catering": (25.0, 35.0),
                "photography": (10.0, 15.0),
                "floral/decor": (5.0, 10.0),
                "misc": (10.0, 15.0),
            }
            pr_ok = True
            for cat, (lo, hi) in ranges.items():
                if cat not in cat_map or cat_map[cat]["percent"] is None:
                    pr_ok = False
                    break
                pval = cat_map[cat]["percent"]
                if not (lo <= pval <= hi):
                    pr_ok = False
                    break
            checks["budget_percent_ranges_ok"] = pr_ok

            # Amounts match total budget
            if total_budget_cap is not None:
                for cat_key, data in cat_map.items():
                    pct = data["percent"]
                    amt = data["amount"]
                    if pct is None or amt is None:
                        amounts_match = False
                        break
                    expected = int(round(total_budget_cap * pct / 100.0))
                    if abs(expected - amt) > 1:
                        amounts_match = False
                        break
                checks["budget_amounts_match_total"] = amounts_match
            else:
                checks["budget_amounts_match_total"] = False

    # CHECKLIST.MD checks
    checklist_path = os.path.join(output_dir, "checklist.md")
    checks["has_checklist_md"] = False
    checks["checklist_sections_ok"] = False
    checks["checklist_pre_event_min4"] = False
    checks["checklist_day_of_min4"] = False
    checks["checklist_post_event_min4"] = False

    if os.path.isfile(checklist_path):
        checks["has_checklist_md"] = True
        cl_text = read_text(checklist_path) or ""
        sections = ["Pre-Event", "Day-Of", "Post-Event"]
        sec_found = []
        for s in sections:
            found = False
            for line in cl_text.splitlines():
                hdr = normalize_header_line(line)
                if hdr == s:
                    found = True
                    break
            sec_found.append(found)
        checks["checklist_sections_ok"] = all(sec_found)

        pre_cnt = count_bullets_between_sections(cl_text, "Pre-Event", ["Day-Of", "Post-Event"])
        day_cnt = count_bullets_between_sections(cl_text, "Day-Of", ["Post-Event"])
        post_cnt = count_bullets_between_sections(cl_text, "Post-Event", [])
        checks["checklist_pre_event_min4"] = pre_cnt >= 4
        checks["checklist_day_of_min4"] = day_cnt >= 4
        checks["checklist_post_event_min4"] = post_cnt >= 4

    # INVITATION_TEXT.MD checks
    invite_path = os.path.join(output_dir, "invitation_text.md")
    checks["has_invitation_md"] = False
    checks["invitation_has_event_name"] = False
    checks["invitation_has_september"] = False
    checks["invitation_has_rsvp_email"] = False
    checks["invitation_has_venue_address"] = False

    if os.path.isfile(invite_path):
        checks["has_invitation_md"] = True
        inv_text = read_text(invite_path) or ""
        # Event name presence
        if event_name:
            checks["invitation_has_event_name"] = event_name in inv_text
        else:
            checks["invitation_has_event_name"] = False
        # September
        checks["invitation_has_september"] = bool(re.search(r'\bseptember\b', inv_text, flags=re.IGNORECASE))
        # RSVP email
        if rsvp_email:
            checks["invitation_has_rsvp_email"] = rsvp_email in inv_text
        else:
            checks["invitation_has_rsvp_email"] = False
        # Venue address from shortlist
        addr_present = False
        for addr in venue_addresses:
            if addr and addr in inv_text:
                addr_present = True
                break
        checks["invitation_has_venue_address"] = addr_present

    # VENDOR_LIST.CSV checks
    vendor_path = os.path.join(output_dir, "vendor_list.csv")
    checks["has_vendor_csv"] = False
    checks["vendor_headers_ok"] = False
    checks["vendor_min_rows_10"] = False
    checks["vendor_category_coverage"] = False
    checks["vendor_all_contacts_nonempty"] = False
    checks["vendor_all_notes_nonempty"] = False

    if os.path.isfile(vendor_path):
        checks["has_vendor_csv"] = True
        headers, rows = csv_read_dicts(vendor_path)
        if headers is not None and rows is not None:
            headers_lower = [h.strip().lower() for h in headers]
            checks["vendor_headers_ok"] = headers_lower == ["name", "category", "contact", "notes"]
            checks["vendor_min_rows_10"] = len(rows) >= 10

            # Category coverage
            required_vendor_cats = {"catering", "photography", "floral", "av", "venue"}
            seen_cats = set()
            all_contacts = True
            all_notes = True
            for r in rows:
                cat_val = (r.get("category") or r.get("Category") or "").strip().lower()
                if cat_val:
                    seen_cats.add(cat_val)
                contact = (r.get("contact") or r.get("Contact") or "").strip()
                notes = (r.get("notes") or r.get("Notes") or "").strip()
                if contact == "":
                    all_contacts = False
                if notes == "":
                    all_notes = False

            checks["vendor_category_coverage"] = all(any(cat == rc or rc in cat for cat in seen_cats) for rc in required_vendor_cats)
            checks["vendor_all_contacts_nonempty"] = all_contacts
            checks["vendor_all_notes_nonempty"] = all_notes

    # TASKS.JSON checks
    tasks_path = os.path.join(output_dir, "tasks.json")
    checks["has_tasks_json"] = False
    checks["tasks_json_valid"] = False
    checks["tasks_min_count_15"] = False
    checks["tasks_fields_valid"] = False
    checks["tasks_stats_total_matches"] = False
    checks["tasks_stats_by_status_valid"] = False
    checks["tasks_stats_by_priority_valid"] = False

    if os.path.isfile(tasks_path):
        checks["has_tasks_json"] = True
        tasks_data = parse_json_file(tasks_path)
        if isinstance(tasks_data, dict):
            if "tasks" in tasks_data and "stats" in tasks_data and isinstance(tasks_data.get("tasks"), list) and isinstance(tasks_data.get("stats"), dict):
                checks["tasks_json_valid"] = True
                tasks = tasks_data["tasks"]
                stats = tasks_data["stats"]
                checks["tasks_min_count_15"] = len(tasks) >= 15

                # Validate each task fields
                valid_tasks = True
                for t in tasks:
                    if not isinstance(t, dict):
                        valid_tasks = False
                        break
                    # Required keys
                    req_keys = ["title", "due_date", "priority", "status", "owner", "tags"]
                    if not all(k in t for k in req_keys):
                        valid_tasks = False
                        break
                    if not isinstance(t["title"], str) or t["title"].strip() == "":
                        valid_tasks = False
                        break
                    if not validate_due_date(t["due_date"]):
                        valid_tasks = False
                        break
                    if t["priority"] not in {"low", "medium", "high"}:
                        valid_tasks = False
                        break
                    if t["status"] not in {"todo", "in_progress", "done"}:
                        valid_tasks = False
                        break
                    if not isinstance(t["owner"], str) or t["owner"].strip() == "":
                        valid_tasks = False
                        break
                    if not isinstance(t["tags"], list):
                        valid_tasks = False
                        break
                checks["tasks_fields_valid"] = valid_tasks

                # Stats validations
                total = stats.get("total")
                by_status = stats.get("by_status")
                by_priority = stats.get("by_priority")

                if isinstance(total, int) and total == len(tasks):
                    checks["tasks_stats_total_matches"] = True

                bs_ok = False
                if isinstance(by_status, dict):
                    needed_status = {"todo", "in_progress", "done"}
                    if needed_status.issubset(by_status.keys()):
                        try:
                            sum_status = sum(int(by_status[k]) for k in needed_status)
                            bs_ok = (isinstance(total, int) and sum_status == total)
                        except Exception:
                            bs_ok = False
                checks["tasks_stats_by_status_valid"] = bs_ok

                bp_ok = False
                if isinstance(by_priority, dict):
                    needed_pri = {"low", "medium", "high"}
                    if needed_pri.issubset(by_priority.keys()):
                        try:
                            sum_pri = sum(int(by_priority[k]) for k in needed_pri)
                            bp_ok = (isinstance(total, int) and sum_pri == total)
                        except Exception:
                            bp_ok = False
                checks["tasks_stats_by_priority_valid"] = bp_ok

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks
    # Ensure 0 reward for no-op baseline when no outputs exist
    # If none of the "has_*" output files exist, force reward to 0.0
    has_any_output = any([
        checks.get("has_plan_md", False),
        checks.get("has_budget_csv", False),
        checks.get("has_checklist_md", False),
        checks.get("has_invitation_md", False),
        checks.get("has_vendor_csv", False),
        checks.get("has_tasks_json", False),
    ])
    if not has_any_output:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()