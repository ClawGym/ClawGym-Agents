import json
import os
import re
import sys
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_nonempty_file(path):
    return os.path.isfile(path) and os.path.getsize(path) > 0

def extract_service_names(saas_profiles):
    names = []
    if isinstance(saas_profiles, list):
        for item in saas_profiles:
            if isinstance(item, dict) and "name" in item and isinstance(item["name"], str):
                names.append(item["name"].strip())
    return names

def find_service_sections(report_text, service_names):
    # Returns dict name -> section text if present with exact header "## [Service Name] Decomposition Results"
    sections = {}
    for name in service_names:
        pattern = r"^##\s+" + re.escape(name) + r"\s+Decomposition Results\s*$"
        matches = list(re.finditer(pattern, report_text, flags=re.MULTILINE))
        if not matches:
            continue
        start_pos = matches[0].start()
        # Find next "## " header after this position
        next_header = re.search(r"^##\s+", report_text[matches[0].end():], flags=re.MULTILINE)
        if next_header:
            end_pos = matches[0].end() + next_header.start()
        else:
            end_pos = len(report_text)
        section_text = report_text[matches[0].end():end_pos]
        # Include the header line itself for completeness
        header_line_start = report_text.rfind("\n", 0, matches[0].end())
        header_line_start = 0 if header_line_start == -1 else header_line_start + 1
        header_line_end = report_text.find("\n", matches[0].start())
        header_line_end = len(report_text) if header_line_end == -1 else header_line_end
        header_line = report_text[header_line_start:header_line_end]
        sections[name] = header_line + "\n" + section_text
    return sections

def count_star_bullets(section_text):
    # Count bullet lines that contain at least one '⭐'
    if not section_text:
        return 0
    count = 0
    for line in section_text.splitlines():
        if re.match(r"^\s*[-*]\s+.*⭐+.*$", line):
            count += 1
    return count

def has_line_pattern(section_text, pattern):
    return re.search(pattern, section_text) is not None

def parse_csv(filepath):
    rows = []
    header = None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                # Skip completely empty rows
                if not row or all((c or "").strip() == "" for c in row):
                    continue
                if header is None:
                    header = row
                else:
                    rows.append(row)
    except Exception:
        return None, None
    return header, rows

def is_stars_only(s):
    if not isinstance(s, str):
        return False
    s = s.strip()
    if not s:
        return False
    # Ensure 1 to 5 star characters only
    if len(s) < 1 or len(s) > 5:
        return False
    for ch in s:
        if ch != "⭐":
            return False
    return True

def normalize_name(s):
    return (s or "").strip().lower()

def extract_function_names_from_report(section_text):
    names = set()
    if not section_text:
        return names
    for line in section_text.splitlines():
        if re.match(r"^\s*[-*]\s+", line) and "⭐" in line:
            # Capture text after bullet up to first delimiter
            m = re.match(r"^\s*[-*]\s+(.+?)(?:\s*(?:\(|—|->|→|$))", line)
            if m:
                name = m.group(1).strip()
                if name:
                    names.add(normalize_name(name))
    return names

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    saas_profiles_path = os.path.join(input_dir, "saas_profiles.json")
    report_path = os.path.join(output_dir, "report.md")
    comparison_path = os.path.join(output_dir, "comparison.csv")
    roadmap_path = os.path.join(output_dir, "roadmap.json")

    # Initialize checks
    checks = {
        "has_report": False,
        "has_comparison": False,
        "has_roadmap": False,
        "report_sections_for_all_services": False,
        "report_function_list_bullets_per_service": False,
        "report_rate_line_per_service": False,
        "report_new_skills_line_per_service": False,
        "report_dev_time_line_per_service": False,
        "csv_header_valid": False,
        "csv_min_5_rows": False,
        "csv_yes_no_values": False,
        "csv_stars_valid": False,
        "roadmap_valid_json": False,
        "roadmap_services_coverage": False,
        "roadmap_phases_valid": False,
        "roadmap_costs_valid": False,
        "cross_file_services_consistent": False,
        "cross_file_functions_consistent_min3": False
    }

    # Read input services
    saas_profiles = read_json(saas_profiles_path)
    service_names = extract_service_names(saas_profiles) if saas_profiles else []

    # Existence checks
    checks["has_report"] = is_nonempty_file(report_path)
    checks["has_comparison"] = is_nonempty_file(comparison_path)
    checks["has_roadmap"] = is_nonempty_file(roadmap_path)

    # Report checks
    report_text = read_text(report_path) if checks["has_report"] else None
    sections = {}
    if report_text and service_names:
        sections = find_service_sections(report_text, service_names)
        # All services must have sections
        if set(sections.keys()) == set(service_names) and len(sections) == len(service_names):
            checks["report_sections_for_all_services"] = True

        # For each service, validate bullets and lines
        bullets_ok = True
        rate_ok = True
        newskills_ok = True
        devtime_ok = True
        for name in service_names:
            st = sections.get(name, "")
            # Function List subsection present
            if re.search(r"Function List", st, flags=re.IGNORECASE) is None:
                bullets_ok = False
            # At least 3 bullet lines with stars
            if count_star_bullets(st) < 3:
                bullets_ok = False
            # AI Replacement Rate: <number>%
            if not has_line_pattern(st, r"AI Replacement Rate:\s*\d+%"):
                rate_ok = False
            # New Skills Needed: <integer>
            if not has_line_pattern(st, r"New Skills Needed:\s*\d+"):
                newskills_ok = False
            # Estimated Development Time: <int> weeks
            if not has_line_pattern(st, r"Estimated Development Time:\s*\d+\s+weeks"):
                devtime_ok = False
        if bullets_ok and checks["report_sections_for_all_services"]:
            checks["report_function_list_bullets_per_service"] = True
        if rate_ok and checks["report_sections_for_all_services"]:
            checks["report_rate_line_per_service"] = True
        if newskills_ok and checks["report_sections_for_all_services"]:
            checks["report_new_skills_line_per_service"] = True
        if devtime_ok and checks["report_sections_for_all_services"]:
            checks["report_dev_time_line_per_service"] = True

    # CSV checks
    header, rows = (None, None)
    if checks["has_comparison"]:
        header, rows = parse_csv(comparison_path)
        if header and service_names:
            header_first_ok = header[0] == "Function"
            header_last_ok = header[-1] == "AI_Replacement_Stars"
            middle = header[1:-1]
            middle_set = set([h.strip() for h in middle])
            expected_set = set([s.strip() for s in service_names])
            # The header must have exactly all service names in any order
            if header_first_ok and header_last_ok and middle_set == expected_set and len(middle) == len(service_names):
                checks["csv_header_valid"] = True

        # At least 5 data rows
        if rows is not None:
            nonempty_rows = [r for r in rows if any((c or "").strip() != "" for c in r)]
            if len(nonempty_rows) >= 5:
                checks["csv_min_5_rows"] = True

        # Values Yes/No and stars validation
        yes_no_ok = True
        stars_ok = True
        if header and rows is not None and len(header) >= 3:
            service_col_indices = list(range(1, len(header) - 1))
            star_idx = len(header) - 1
            for r in rows or []:
                # Pad row if shorter
                if len(r) < len(header):
                    r = r + [""] * (len(header) - len(r))
                for idx in service_col_indices:
                    val = (r[idx] or "").strip()
                    if val not in ("Yes", "No"):
                        yes_no_ok = False
                        break
                star_val = (r[star_idx] or "").strip()
                if not is_stars_only(star_val):
                    stars_ok = False
            if yes_no_ok and checks["csv_header_valid"]:
                checks["csv_yes_no_values"] = True
            if stars_ok and checks["csv_header_valid"]:
                checks["csv_stars_valid"] = True

    # Roadmap JSON checks
    roadmap = read_json(roadmap_path) if checks["has_roadmap"] else None
    if isinstance(roadmap, dict) and "services" in roadmap and isinstance(roadmap["services"], list):
        checks["roadmap_valid_json"] = True
        services_list = roadmap["services"]
        names_in_roadmap = []
        coverage_ok = True
        phases_ok = True
        costs_ok = True
        for srv in services_list:
            if not isinstance(srv, dict):
                coverage_ok = False
                phases_ok = False
                costs_ok = False
                break
            nm = srv.get("name")
            if not isinstance(nm, str):
                coverage_ok = False
            else:
                names_in_roadmap.append(nm.strip())

            # Phases
            phases = srv.get("phases")
            if not isinstance(phases, list) or len(phases) != 3:
                phases_ok = False
            else:
                expected_phase_names = ["Phase 1: Quick Wins", "Phase 2: New Skill Development", "Phase 3: Infrastructure"]
                for i, ph in enumerate(phases):
                    if not isinstance(ph, dict):
                        phases_ok = False
                        break
                    if ph.get("name") != expected_phase_names[i]:
                        phases_ok = False
                    dur = ph.get("duration_weeks")
                    items = ph.get("items")
                    if not isinstance(dur, int) or dur <= 0:
                        phases_ok = False
                    if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
                        phases_ok = False

            # Costs
            cc = srv.get("cost_comparison")
            if not isinstance(cc, dict):
                costs_ok = False
            else:
                sm = cc.get("saas_monthly")
                am = cc.get("ai_monthly")
                sp = cc.get("savings_pct")
                if not (isinstance(sm, (int, float)) and isinstance(am, (int, float)) and isinstance(sp, (int, float))):
                    costs_ok = False
                else:
                    if not (0 <= sp <= 100):
                        costs_ok = False

        # Coverage: exactly one object per input service
        if service_names:
            if set(names_in_roadmap) == set(service_names) and len(names_in_roadmap) == len(service_names):
                checks["roadmap_services_coverage"] = True
        if phases_ok and checks["roadmap_services_coverage"]:
            checks["roadmap_phases_valid"] = True
        if costs_ok and checks["roadmap_services_coverage"]:
            checks["roadmap_costs_valid"] = True

    # Cross-file service consistency
    services_in_report_ok = False
    services_in_csv_ok = False
    services_in_roadmap_ok = False
    if service_names:
        # Report
        if checks["report_sections_for_all_services"]:
            services_in_report_ok = True
        # CSV
        if checks["csv_header_valid"]:
            services_in_csv_ok = True
        # Roadmap
        if checks["roadmap_services_coverage"]:
            services_in_roadmap_ok = True
    if services_in_report_ok and services_in_csv_ok and services_in_roadmap_ok:
        checks["cross_file_services_consistent"] = True

    # Cross-file functions consistency: at least 3 function names in CSV also appear in any Function List in report
    if checks["has_comparison"] and checks["has_report"]:
        csv_header, csv_rows = header, rows
        if csv_header and csv_rows:
            func_idx = 0  # first column
            csv_func_names = set()
            for r in csv_rows:
                if len(r) > func_idx:
                    val = (r[func_idx] or "").strip()
                    if val:
                        csv_func_names.add(normalize_name(val))
            # Gather report function names
            report_func_names = set()
            for name in service_names:
                st = sections.get(name, "") if sections else ""
                report_func_names |= extract_function_names_from_report(st)
            if len(csv_func_names) > 0 and len(report_func_names) > 0:
                if len(csv_func_names & report_func_names) >= 3:
                    checks["cross_file_functions_consistent_min3"] = True

    # Compute reward
    total_checks = len(checks)
    true_checks = sum(1 for v in checks.values() if v)
    # No-op baseline: if none of the required outputs exist, reward is exactly 0.0
    if not (checks["has_report"] or checks["has_comparison"] or checks["has_roadmap"]):
        reward = 0.0
    else:
        reward = true_checks / total_checks if total_checks > 0 else 0.0
        # Clamp between 0 and 1
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Print result JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()