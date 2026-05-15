import json
import os
import re
import sys
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except Exception:
        return None

def parse_md_headings(text):
    # Returns list of tuples: (line_index, level, title)
    headings = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r'^\s{0,3}(#{1,6})\s+(.*?)\s*$', line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            headings.append((i, level, title))
    return headings

def get_section_bounds(text, target_titles_lower):
    # target_titles_lower: list of expected titles (lowercased) to find
    # Returns dict title_lower -> (start_line_index_inclusive, end_line_index_exclusive)
    bounds = {}
    headings = parse_md_headings(text)
    lines = text.splitlines()
    # Map of normalized title to first occurrence index
    title_to_index = {}
    for idx, (_i, _lvl, title) in enumerate(headings):
        norm = title.strip().lower()
        title_to_index.setdefault(norm, idx)
    # Build ordered indices for expected headings if present
    indices = []
    for t in target_titles_lower:
        # allow exact match only (case-insensitive)
        # note: we will search heading list for exact equality ignoring case
        found_idx = None
        for idx, (_i, _lvl, title) in enumerate(headings):
            if title.strip().lower() == t:
                found_idx = idx
                break
        indices.append(found_idx)
    # Determine bounds using heading line indices
    for i, t in enumerate(target_titles_lower):
        idx = indices[i]
        if idx is None:
            continue
        start_line = headings[idx][0] + 1  # content starts after heading line
        # find next heading occurrence after this index whose title is any heading (any title)
        if i < len(target_titles_lower) - 1:
            # end at the next occurrence of any heading that is the next expected section if present,
            # otherwise at the next heading of any title after current heading
            # To isolate cleanly, we'll end at the next heading whose line index > current heading line and
            # is the heading of the next expected section title if present; else next heading of any title.
            # First, try to find the next expected title's heading index
            next_idx = indices[i+1]
            if next_idx is not None:
                end_line = headings[next_idx][0]
            else:
                # fall back to next heading after current
                # find first heading after current
                after = None
                for j in range(idx + 1, len(headings)):
                    after = headings[j][0]
                    break
                end_line = after if after is not None else len(lines)
        else:
            end_line = len(lines)
        bounds[t] = (start_line, end_line)
    return bounds

def count_bullets(lines):
    count = 0
    for l in lines:
        ls = l.lstrip()
        if ls.startswith("- ") or ls.startswith("* ") or ls.startswith("• "):
            count += 1
    return count

def find_marker_positions(section_lines, required_markers):
    # Returns dict marker_key -> line_index (relative to section start)
    positions = {}
    text = "\n".join(section_lines)
    lower_lines = [ln.lower() for ln in section_lines]
    # Build simple search for each marker set (list of alternatives)
    for key, alts in required_markers.items():
        found_pos = None
        # search line-wise for clarity
        for i, ln in enumerate(lower_lines):
            for alt in alts:
                if alt in ln:
                    found_pos = i
                    break
            if found_pos is not None:
                break
        positions[key] = found_pos
    return positions

def has_action_items_beneath(section_lines, start_idx, end_idx):
    # Check at least one bullet between (start_idx+1) and (end_idx-1)
    if start_idx is None:
        return False
    s = start_idx + 1
    e = end_idx if end_idx is not None else len(section_lines)
    e = min(e, len(section_lines))
    for i in range(s, e):
        ls = section_lines[i].lstrip()
        if ls.startswith("- ") or ls.startswith("* ") or ls.startswith("• "):
            return True
    return False

def csv_read_rows(path):
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None

def parse_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except UnicodeDecodeError:
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            return None
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # offboarding_package.md checks
        "offboarding_package_exists": False,
        "offboarding_package_nonempty": False,
        "offboarding_package_mentions_name": False,
        "offboarding_package_headings_ordered": False,
        "it_section_min_7_bullets": False,
        "it_section_mentions_3_systems": False,
        "timeline_has_T_minus_14": False,
        "timeline_has_T_minus_7": False,
        "timeline_has_T_minus_3": False,
        "timeline_has_T_minus_1": False,
        "timeline_has_last_day_or_T0": False,
        "timeline_has_T_plus_7": False,
        "timeline_T_minus_14_has_actions": False,
        "timeline_T_minus_7_has_actions": False,
        "timeline_T_minus_3_has_actions": False,
        "timeline_T_minus_1_has_actions": False,
        "timeline_last_day_has_actions": False,
        "timeline_T_plus_7_has_actions": False,
        "ktp_has_min_3_sessions_in_md": False,

        # offboarding_tasks.csv checks
        "tasks_csv_exists": False,
        "tasks_csv_parses": False,
        "tasks_csv_has_required_headers": False,
        "tasks_csv_min_10_rows": False,
        "tasks_csv_min_5_allowed_owners": False,

        # knowledge_transfer_schedule.json checks
        "schedule_json_exists": False,
        "schedule_json_parses": False,
        "schedule_json_is_array_len_ge_3": False,
        "schedule_json_items_have_keys": False,
        "schedule_json_some_attendees_len_ge_3": False,

        # manager_comms.md checks
        "manager_comms_exists": False,
        "manager_comms_nonempty": False,
        "manager_comms_has_internal_team": False,
        "manager_comms_has_external_partners": False,
    }

    # Paths
    offboarding_md_path = os.path.join(output_dir, "offboarding_package.md")
    tasks_csv_path = os.path.join(output_dir, "offboarding_tasks.csv")
    schedule_json_path = os.path.join(output_dir, "knowledge_transfer_schedule.json")
    comms_md_path = os.path.join(output_dir, "manager_comms.md")

    # 1) offboarding_package.md
    md_text = None
    if os.path.isfile(offboarding_md_path):
        checks["offboarding_package_exists"] = True
        md_text = read_text(offboarding_md_path)
        if md_text is not None and len(md_text.strip()) > 0:
            checks["offboarding_package_nonempty"] = True

    if checks["offboarding_package_nonempty"]:
        lower_md = md_text.lower()
        if "michael ortega" in lower_md:
            checks["offboarding_package_mentions_name"] = True

        # Heading order
        expected_titles = [
            "IT & Access Revocation Checklist",
            "Knowledge Transfer Plan",
            "HR & Compliance Checklist",
            "Manager Transition Plan",
            "Timeline",
        ]
        expected_lower = [t.lower() for t in expected_titles]
        headings = parse_md_headings(md_text)
        # Build sequence of normalized titles
        norm_titles = [t.strip().lower() for (_i, _lvl, t) in headings]
        # For each expected, find first index
        indices = []
        for t in expected_lower:
            try:
                indices.append(norm_titles.index(t))
            except ValueError:
                indices.append(None)
        if all(idx is not None for idx in indices):
            # check strictly increasing
            checks["offboarding_package_headings_ordered"] = indices == sorted(indices)

        # Extract section contents for IT and Timeline and Knowledge Transfer
        bounds = get_section_bounds(md_text, expected_lower)
        lines = md_text.splitlines()

        # IT section checks
        it_key = expected_lower[0]
        if it_key in bounds:
            s, e = bounds[it_key]
            s = max(0, min(s, len(lines)))
            e = max(0, min(e, len(lines)))
            it_lines = lines[s:e]
            # At least 7 bullet items
            bullet_count = count_bullets(it_lines)
            if bullet_count >= 7:
                checks["it_section_min_7_bullets"] = True
            # Mentions at least 3 systems
            systems = ["aws", "github", "google workspace", "slack", "jira", "okta", "figma", "vpn"]
            it_text_lower = "\n".join(it_lines).lower()
            mentioned = set()
            for sys_name in systems:
                if sys_name in it_text_lower:
                    mentioned.add(sys_name)
            if len(mentioned) >= 3:
                checks["it_section_mentions_3_systems"] = True

        # Timeline section checks
        timeline_key = expected_lower[4]
        if timeline_key in bounds:
            s, e = bounds[timeline_key]
            s = max(0, min(s, len(lines)))
            e = max(0, min(e, len(lines)))
            tl_lines = lines[s:e]
            # Define markers with alternative tokens to detect
            required_markers = {
                "T-14": ["t-14"],
                "T-7": ["t-7"],
                "T-3": ["t-3"],
                "T-1": ["t-1"],
                "LAST": ["last day", "t0", "t-0"],
                "T+7": ["t+7"],
            }
            positions = find_marker_positions(tl_lines, required_markers)

            # Presence checks
            if positions["T-14"] is not None:
                checks["timeline_has_T_minus_14"] = True
            if positions["T-7"] is not None:
                checks["timeline_has_T_minus_7"] = True
            if positions["T-3"] is not None:
                checks["timeline_has_T_minus_3"] = True
            if positions["T-1"] is not None:
                checks["timeline_has_T_minus_1"] = True
            if positions["LAST"] is not None:
                checks["timeline_has_last_day_or_T0"] = True
            if positions["T+7"] is not None:
                checks["timeline_has_T_plus_7"] = True

            # Determine action items under each marker until the next marker occurrence
            # Build ordered list of markers as they appear
            # Map each marker key to its first occurrence index; filter None, then sort by position
            present_markers = [(k, positions[k]) for k in ["T-14", "T-7", "T-3", "T-1", "LAST", "T+7"] if positions[k] is not None]
            present_markers_sorted = sorted(present_markers, key=lambda kv: kv[1])
            # Build end index mapping: for a marker at index i, end at next marker line index
            end_map = {}
            for idx, (k, pos) in enumerate(present_markers_sorted):
                if idx + 1 < len(present_markers_sorted):
                    end_map[k] = present_markers_sorted[idx + 1][1]
                else:
                    end_map[k] = None  # till end of section

            # Now check actions beneath
            if positions["T-14"] is not None:
                if has_action_items_beneath(tl_lines, positions["T-14"], end_map.get("T-14")):
                    checks["timeline_T_minus_14_has_actions"] = True
            if positions["T-7"] is not None:
                if has_action_items_beneath(tl_lines, positions["T-7"], end_map.get("T-7")):
                    checks["timeline_T_minus_7_has_actions"] = True
            if positions["T-3"] is not None:
                if has_action_items_beneath(tl_lines, positions["T-3"], end_map.get("T-3")):
                    checks["timeline_T_minus_3_has_actions"] = True
            if positions["T-1"] is not None:
                if has_action_items_beneath(tl_lines, positions["T-1"], end_map.get("T-1")):
                    checks["timeline_T_minus_1_has_actions"] = True
            if positions["LAST"] is not None:
                if has_action_items_beneath(tl_lines, positions["LAST"], end_map.get("LAST")):
                    checks["timeline_last_day_has_actions"] = True
            if positions["T+7"] is not None:
                if has_action_items_beneath(tl_lines, positions["T+7"], end_map.get("T+7")):
                    checks["timeline_T_plus_7_has_actions"] = True

        # Knowledge Transfer Plan sessions count in MD
        ktp_key = expected_lower[1]
        if ktp_key in bounds:
            s, e = bounds[ktp_key]
            s = max(0, min(s, len(lines)))
            e = max(0, min(e, len(lines)))
            ktp_lines = lines[s:e]
            session_count = 0
            for l in ktp_lines:
                ll = l.strip().lower()
                # Must include some session/handover indicator and a topic-like separator or time/date
                has_indicator = any(w in ll for w in ["session", "handover", "meeting", "walkthrough"])
                has_topic_sep = (":" in l or " - " in l or " — " in l)
                has_date = bool(re.search(r'\b\d{4}-\d{2}-\d{2}\b', l))
                has_time = bool(re.search(r'\b\d{1,2}:\d{2}\b', l)) or ("am" in ll or "pm" in ll)
                if has_indicator and (has_topic_sep or has_date or has_time):
                    session_count += 1
            if session_count >= 3:
                checks["ktp_has_min_3_sessions_in_md"] = True

    # 2) offboarding_tasks.csv
    if os.path.isfile(tasks_csv_path):
        checks["tasks_csv_exists"] = True
        rows = csv_read_rows(tasks_csv_path)
        if rows is not None and isinstance(rows, list) and len(rows) >= 1:
            checks["tasks_csv_parses"] = True
            header = rows[0]
            header_lower = [h.strip().lower() for h in header]
            required_cols = ["task", "owner", "duedate", "status"]
            if all(rc in header_lower for rc in required_cols):
                checks["tasks_csv_has_required_headers"] = True
                data_rows = rows[1:]
                # Filter out empty rows
                data_rows = [r for r in data_rows if any(cell.strip() for cell in r)]
                if len(data_rows) >= 10:
                    checks["tasks_csv_min_10_rows"] = True
                # Owners check
                try:
                    owner_idx = header_lower.index("owner")
                except ValueError:
                    owner_idx = None
                if owner_idx is not None:
                    allowed = {"it ops", "security", "manager", "people ops", "data platform", "sre"}
                    count_allowed = 0
                    for r in data_rows:
                        if owner_idx < len(r):
                            if r[owner_idx].strip().lower() in allowed:
                                count_allowed += 1
                    if count_allowed >= 5:
                        checks["tasks_csv_min_5_allowed_owners"] = True

    # 3) knowledge_transfer_schedule.json
    if os.path.isfile(schedule_json_path):
        checks["schedule_json_exists"] = True
        obj = parse_json_file(schedule_json_path)
        if obj is not None:
            checks["schedule_json_parses"] = True
            if isinstance(obj, list) and len(obj) >= 3:
                checks["schedule_json_is_array_len_ge_3"] = True
                # Every item has required keys
                all_have_keys = True
                some_attendees_ge3 = False
                for item in obj:
                    if not isinstance(item, dict):
                        all_have_keys = False
                        break
                    keys_ok = all(k in item for k in ["session", "date", "topic", "attendees"])
                    if not keys_ok:
                        all_have_keys = False
                        break
                    attendees = item.get("attendees")
                    if isinstance(attendees, list) and len(attendees) >= 3:
                        some_attendees_ge3 = True
                if all_have_keys:
                    checks["schedule_json_items_have_keys"] = True
                if some_attendees_ge3:
                    checks["schedule_json_some_attendees_len_ge_3"] = True

    # 4) manager_comms.md
    if os.path.isfile(comms_md_path):
        checks["manager_comms_exists"] = True
        comms_text = read_text(comms_md_path)
        if comms_text is not None and len(comms_text.strip()) > 0:
            checks["manager_comms_nonempty"] = True
            lt = comms_text.lower()
            # Internal team presence
            if "internal team" in lt or ("internal" in lt and "team" in lt):
                checks["manager_comms_has_internal_team"] = True
            # External partners presence
            if "external partners" in lt or "external partner" in lt:
                checks["manager_comms_has_external_partners"] = True

    # Compute reward as average of passed checks; ensure 0.0 if nothing produced
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if passed > 0 else 0.0

    # Print result JSON with "reward" first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()