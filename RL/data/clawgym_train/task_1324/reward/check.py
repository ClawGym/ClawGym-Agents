import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def extract_section(text, start_title, other_titles):
    if text is None:
        return None
    start_idx = text.find(start_title)
    if start_idx == -1:
        return None
    end_idx = len(text)
    for t in other_titles:
        idx = text.find(t, start_idx + len(start_title))
        if idx != -1:
            end_idx = min(end_idx, idx)
    return text[start_idx:end_idx]

def find_triads(text):
    # Count Gherkin triads Given -> When -> Then in order (consecutive lines preferred)
    if not text:
        return 0
    lines = [ln.strip() for ln in text.splitlines()]
    count = 0
    i = 0
    n = len(lines)
    while i < n:
        # Find Given
        while i < n and not lines[i].startswith("Given"):
            i += 1
        if i >= n:
            break
        j = i + 1
        # Find When after Given
        while j < n and not lines[j].startswith("When"):
            # stop early if another Given starts - start new triad search
            if lines[j].startswith("Given"):
                break
            j += 1
        if j >= n or not lines[j].startswith("When"):
            i += 1
            continue
        k = j + 1
        # Find Then after When
        while k < n and not lines[k].startswith("Then"):
            # stop early if another Given starts - start new triad search
            if lines[k].startswith("Given"):
                break
            k += 1
        if k < n and lines[k].startswith("Then"):
            count += 1
            i = k + 1
        else:
            i += 1
    return count

def has_priority_near(text, title, priority_value, window=1000):
    if not text:
        return False
    idx = text.find(title)
    if idx == -1:
        return False
    start = max(0, idx - window)
    end = min(len(text), idx + window)
    chunk = text[start:end]
    # Match "Priority: Must" exactly with correct capitalization
    pattern = rf"Priority:\s*{re.escape(priority_value)}\b"
    return re.search(pattern, chunk) is not None

def has_estimate_near(text, title, window=1000):
    if not text:
        return False
    idx = text.find(title)
    if idx == -1:
        return False
    start = max(0, idx - window)
    end = min(len(text), idx + window)
    chunk = text[start:end]
    return re.search(r"\bEstimate:\s*\d+(\.\d+)?\b", chunk) is not None

def triads_near_title(text, title, min_triads=2, window=2000):
    if not text:
        return False
    idx = text.find(title)
    if idx == -1:
        return False
    start = max(0, idx - window)
    end = min(len(text), idx + window)
    chunk = text[start:end]
    return find_triads(chunk) >= min_triads

def prioritize_lines_valid(ready_text):
    if not ready_text:
        return False
    # Check at least one Estimate and one Priority line in Ready section
    est_count = len(re.findall(r"^Estimate:\s*\d+(\.\d+)?\s*$", ready_text, flags=re.MULTILINE))
    prio_lines = re.findall(r"^Priority:\s*(.+?)\s*$", ready_text, flags=re.MULTILINE)
    allowed = {"Must", "Should", "Could", "Won't"}
    prio_valid = [p for p in prio_lines if p in allowed]
    # All found priorities must be allowed; and at least one exists
    return est_count >= 1 and len(prio_lines) >= 1 and len(prio_valid) == len(prio_lines)

def confetti_ok(backlog_text, parking_text):
    if not backlog_text:
        return False
    present = "Confetti animation" in backlog_text
    if not present:
        return False
    # Check if in Parking Lot section or Priority: Won't near the mention
    in_parking = False
    if parking_text and "Confetti animation" in parking_text:
        in_parking = True
    wont_near = has_priority_near(backlog_text, "Confetti animation", "Won't", window=1200)
    return in_parking or wont_near

def csv_parse_rows(text):
    if text is None:
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
    if not lines:
        return []
    header = lines[0]
    rows = []
    for ln in lines[1:]:
        # naive CSV split on comma; quotes are unlikely needed for this task
        parts = [p.strip() for p in ln.split(",")]
        rows.append(parts)
    return rows

def find_csv_row(rows, title):
    # CSV header is: id,title,priority,estimate,type
    for parts in rows:
        if len(parts) >= 5 and parts[1] == title:
            return parts
    return None

def is_numeric(s):
    try:
        float(s)
        return True
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # Backlog file presence and sections
        "backlog_exists": False,
        "backlog_has_ready_needs_parking": False,
        "backlog_ready_has_estimate_priority": False,
        # Must titles present with Priority: Must in backlog
        "backlog_gdpr_must": False,
        "backlog_email_must": False,
        "backlog_sso_must": False,
        # Acceptance criteria triads near titles in backlog
        "backlog_gdpr_acceptance": False,
        "backlog_email_acceptance": False,
        "backlog_sso_acceptance": False,
        # Confetti handled
        "backlog_confetti_parking_or_wont": False,

        # Sprint file presence and sections
        "sprint_exists": False,
        "sprint_has_sections": False,
        "sprint_capacity_20": False,
        "sprint_total_points_leq_20": False,
        # Committed stories and their details
        "sprint_committed_contains_titles": False,
        "sprint_gdpr_acceptance": False,
        "sprint_email_acceptance": False,
        "sprint_sso_acceptance": False,
        "sprint_committed_has_estimate_priority": False,

        # Prioritization CSV
        "prio_exists": False,
        "prio_has_header": False,
        "prio_gdpr_must_numeric": False,
        "prio_email_must_numeric": False,
        "prio_sso_must_numeric": False,
    }

    # Paths
    backlog_path = os.path.join(output_dir, "backlog", "taskflow.md")
    sprint_path = os.path.join(output_dir, "sprints", "sprint-07.md")
    prio_path = os.path.join(output_dir, "prioritization.csv")

    # Read files
    backlog_text = read_text(backlog_path)
    sprint_text = read_text(sprint_path)
    prio_text = read_text(prio_path)

    # Backlog checks
    if backlog_text is not None and os.path.isfile(backlog_path):
        checks["backlog_exists"] = True

        # Check headings
        has_ready = "Ready for Sprint" in backlog_text
        has_needs = "Needs Refinement" in backlog_text
        has_parking = "Parking Lot" in backlog_text
        checks["backlog_has_ready_needs_parking"] = has_ready and has_needs and has_parking

        # Extract sections
        ready_section = extract_section(backlog_text, "Ready for Sprint", ["Needs Refinement", "Parking Lot"])
        needs_section = extract_section(backlog_text, "Needs Refinement", ["Parking Lot"])
        parking_section = extract_section(backlog_text, "Parking Lot", [])

        # Ready section must have Estimate and Priority lines with allowed values
        checks["backlog_ready_has_estimate_priority"] = prioritize_lines_valid(ready_section or "")

        # Must-have titles with Priority: Must somewhere near
        checks["backlog_gdpr_must"] = ("GDPR consent banner" in backlog_text) and has_priority_near(backlog_text, "GDPR consent banner", "Must")
        checks["backlog_email_must"] = ("Email verification" in backlog_text) and has_priority_near(backlog_text, "Email verification", "Must")
        checks["backlog_sso_must"] = ("Fix SSO logout bug" in backlog_text) and has_priority_near(backlog_text, "Fix SSO logout bug", "Must")

        # Acceptance criteria triads (>=2) near each title
        checks["backlog_gdpr_acceptance"] = triads_near_title(backlog_text, "GDPR consent banner", min_triads=2)
        checks["backlog_email_acceptance"] = triads_near_title(backlog_text, "Email verification", min_triads=2)
        checks["backlog_sso_acceptance"] = triads_near_title(backlog_text, "Fix SSO logout bug", min_triads=2)

        # Confetti animation Won't or in Parking Lot
        checks["backlog_confetti_parking_or_wont"] = confetti_ok(backlog_text, parking_section or "")

    # Sprint checks
    if sprint_text is not None and os.path.isfile(sprint_path):
        checks["sprint_exists"] = True

        # Has required sections
        s_has_goal = "Sprint Goal" in sprint_text
        s_has_capacity = "Capacity" in sprint_text
        s_has_committed = "Committed Stories" in sprint_text
        s_has_dod = "Definition of Done" in sprint_text
        s_has_oos = "Out of Scope" in sprint_text
        checks["sprint_has_sections"] = all([s_has_goal, s_has_capacity, s_has_committed, s_has_dod, s_has_oos])

        # Capacity line exactly
        checks["sprint_capacity_20"] = "Capacity: 20" in sprint_text

        # Total Points line with N <= 20
        m = re.search(r"Total Points:\s*(\d+)\b", sprint_text)
        if m:
            try:
                total_pts = int(m.group(1))
                checks["sprint_total_points_leq_20"] = total_pts <= 20
            except Exception:
                checks["sprint_total_points_leq_20"] = False

        # Committed section extraction and checks
        committed_section = extract_section(sprint_text, "Committed Stories", ["Definition of Done", "Out of Scope"])
        if committed_section:
            titles_present = all([
                "GDPR consent banner" in committed_section,
                "Email verification" in committed_section,
                "Fix SSO logout bug" in committed_section
            ])
            checks["sprint_committed_contains_titles"] = titles_present

            # Acceptance triads near each title in committed section (>=2)
            checks["sprint_gdpr_acceptance"] = triads_near_title(committed_section, "GDPR consent banner", min_triads=2)
            checks["sprint_email_acceptance"] = triads_near_title(committed_section, "Email verification", min_triads=2)
            checks["sprint_sso_acceptance"] = triads_near_title(committed_section, "Fix SSO logout bug", min_triads=2)

            # Each committed story has Estimate and Priority near
            has_all_estimates = all([
                has_estimate_near(committed_section, "GDPR consent banner"),
                has_estimate_near(committed_section, "Email verification"),
                has_estimate_near(committed_section, "Fix SSO logout bug")
            ])
            has_all_priorities = all([
                has_priority_near(committed_section, "GDPR consent banner", "Must") or re.search(r"Priority:\s*(Must|Should|Could|Won't)", committed_section) is not None,
                has_priority_near(committed_section, "Email verification", "Must") or re.search(r"Priority:\s*(Must|Should|Could|Won't)", committed_section) is not None,
                has_priority_near(committed_section, "Fix SSO logout bug", "Must") or re.search(r"Priority:\s*(Must|Should|Could|Won't)", committed_section) is not None,
            ])
            checks["sprint_committed_has_estimate_priority"] = has_all_estimates and has_all_priorities

    # Prioritization CSV checks
    if prio_text is not None and os.path.isfile(prio_path):
        checks["prio_exists"] = True
        # Header check exact
        first_line = prio_text.splitlines()[0].strip() if prio_text.splitlines() else ""
        checks["prio_has_header"] = (first_line == "id,title,priority,estimate,type")

        rows = csv_parse_rows(prio_text)

        # For each required title, check priority Must and numeric estimate
        for title, key in [
            ("GDPR consent banner", "prio_gdpr_must_numeric"),
            ("Email verification", "prio_email_must_numeric"),
            ("Fix SSO logout bug", "prio_sso_must_numeric"),
        ]:
            ok = False
            row = find_csv_row(rows, title)
            if row and len(row) >= 5:
                priority = row[2]
                estimate = row[3]
                ok = (priority == "Must" and is_numeric(estimate))
            checks[key] = ok

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # No-op baseline: if no output files at all, reward must be 0.0
    outputs_exist = any([
        os.path.isfile(backlog_path),
        os.path.isfile(sprint_path),
        os.path.isfile(prio_path),
    ])
    reward = (passed / total_checks) if outputs_exist else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()