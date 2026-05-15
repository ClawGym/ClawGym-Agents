import json
import os
import sys
import re
import csv
from datetime import datetime

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_time_hhmm(s):
    # Extract HH:MM from strings that may include date or extra text
    if s is None:
        return None
    s = s.strip()
    # If contains space and a time, take last HH:MM pattern
    m = re.search(r"(\d{2}):(\d{2})", s)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    return hh * 60 + mm

def fmt_time(minutes):
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"

def parse_energy_yaml(path):
    # Minimal parser for expected keys without external libs
    result = {
        "day_start": None,
        "day_end": None,
        "morning_priming_minutes": None,
        "windows": {
            "peak": {"start": None, "end": None},
            "secondary": {"start": None, "end": None},
            "recovery": {"start": None, "end": None},
            "wind_down": {"start": None, "end": None},
        },
    }
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return result

    cur_section = None
    cur_window = None
    indent_stack = []

    def clean_val(v):
        v = v.strip()
        if v.startswith(("'", '"')) and v.endswith(("'", '"')) and len(v) >= 2:
            v = v[1:-1]
        return v.strip()

    for raw in lines:
        if "#" in raw:
            raw = raw.split("#", 1)[0]
        if not raw.strip():
            continue
        # Track indentation
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = clean_val(val)

        # Section handling
        if indent == 0:
            cur_section = None
            cur_window = None
            if key in ("day_start", "day_end"):
                if val:
                    result[key] = val
            elif key in ("morning_priming_minutes", "morning_priming_min"):
                try:
                    result["morning_priming_minutes"] = int(val)
                except Exception:
                    pass
            elif key == "windows":
                cur_section = "windows"
            elif key == "morning_priming":
                cur_section = "morning_priming"
        else:
            # Nested levels
            if cur_section == "windows":
                if key in ("peak", "secondary", "recovery", "wind_down"):
                    cur_window = key
                elif key in ("start", "end") and cur_window:
                    result["windows"][cur_window][key] = val
            elif cur_section == "morning_priming":
                if key in ("minutes", "mins", "duration_minutes", "duration"):
                    try:
                        result["morning_priming_minutes"] = int(val)
                    except Exception:
                        pass
            else:
                # Top-level alternative keys with indentation
                if key in ("day_start", "day_end"):
                    if val:
                        result[key] = val
                elif key in ("morning_priming_minutes", "morning_priming_min"):
                    try:
                        result["morning_priming_minutes"] = int(val)
                    except Exception:
                        pass

    return result

def parse_commitments_csv(path):
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            # Try csv reader
            reader = csv.DictReader(f)
            headers = [h.lower() for h in reader.fieldnames] if reader.fieldnames else []
            title_key = None
            start_key = None
            end_key = None
            # Determine keys
            for h in headers:
                if title_key is None and "title" in h:
                    title_key = h
                if start_key is None and ("start" == h or "start_time" in h):
                    start_key = h
                if end_key is None and ("end" == h or "end_time" in h):
                    end_key = h
            # Fallback rough detection
            for row in reader:
                if not title_key or not start_key or not end_key:
                    # attempt alternative keys per row
                    keys = {k.lower(): k for k in row.keys()}
                    if not title_key:
                        for c in ("title", "name", "meeting", "appointment"):
                            if c in keys:
                                title_key = c
                                break
                    if not start_key:
                        for c in ("start", "start_time", "from"):
                            if c in keys:
                                start_key = c
                                break
                    if not end_key:
                        for c in ("end", "end_time", "to", "until"):
                            if c in keys:
                                end_key = c
                                break
                t = row.get(title_key if title_key else "title", "") if row else ""
                s = row.get(start_key if start_key else "start", "") if row else ""
                e = row.get(end_key if end_key else "end", "") if row else ""
                if t or s or e:
                    out.append({
                        "title": (t or "").strip(),
                        "start": (s or "").strip(),
                        "end": (e or "").strip(),
                    })
    except Exception:
        # Fallback naive parsing
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            if not lines:
                return out
            header = [h.strip().lower() for h in lines[0].split(",")]
            for ln in lines[1:]:
                parts = [p.strip() for p in ln.split(",")]
                row = {}
                for i, p in enumerate(parts):
                    if i < len(header):
                        row[header[i]] = p
                title = row.get("title") or row.get("name") or ""
                start = row.get("start") or row.get("start_time") or row.get("from") or ""
                end = row.get("end") or row.get("end_time") or row.get("to") or row.get("until") or ""
                if title or start or end:
                    out.append({"title": title, "start": start, "end": end})
        except Exception:
            return []
    return out

def load_tasks_json(path):
    try:
        import json as _json
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and "tasks" in data and isinstance(data["tasks"], list):
                return data["tasks"]
            else:
                return []
    except Exception:
        return []

def extract_schedule_blocks(content, start_idx, end_idx):
    # Parse blocks in the Time-Blocked Schedule section
    blocks = []
    block_pattern = re.compile(r'^###\s+(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2}):\s*(.+)$')
    section_lines = content[start_idx:end_idx] if end_idx is not None else content[start_idx:]
    indices = []
    for i, line in enumerate(section_lines):
        m = block_pattern.match(line)
        if m:
            indices.append((i, m))
    for idx, m in enumerate(indices):
        i, match = m
        start_hh = int(match.group(1))
        start_mm = int(match.group(2))
        end_hh = int(match.group(3))
        end_mm = int(match.group(4))
        name = match.group(5).strip()
        start_min = start_hh * 60 + start_mm
        end_min = end_hh * 60 + end_mm
        # content until next header or end of section
        next_i = indices[idx + 1][0] if idx + 1 < len(indices) else len(section_lines)
        block_lines = section_lines[i + 1:next_i]
        blocks.append({
            "start_min": start_min,
            "end_min": end_min,
            "name": name,
            "lines": block_lines,
            "header_line": section_lines[i],
        })
    return blocks

def find_section_indices(lines, heading):
    # Find the index of a "## <heading>" line
    for idx, line in enumerate(lines):
        if line.strip().lower() == f"## {heading}".lower():
            return idx
    return None

def find_subsection_indices(lines, start_idx, heading_prefix="### "):
    # Return indices of all subsections "### ..."
    out = []
    for i in range(start_idx, len(lines)):
        if lines[i].startswith(heading_prefix):
            out.append(i)
    return out

def within_window(block_start, block_end, window_start, window_end):
    return block_start >= window_start and block_end <= window_end

def parse_iso_date(date_str):
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except Exception:
        return None

def month_name(dt):
    return dt.strftime("%B")

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "plan_file_exists": False,
        "heading_date_match": False,
        "sections_in_order": False,
        "top3_count_three": False,
        "top3_correct_selection": False,
        "morning_priming_block_correct": False,
        "morning_priming_no_tasks": False,
        "commitments_blocks_present": False,
        "lunch_in_recovery_30min": False,
        "buffer_block_present": False,
        "top3_scheduled_in_correct_windows": False,
        "success_criteria_contains_top3": False,
        "evening_checkin_three_lines": False,
        "block_headers_format": False,
        "all_blocks_have_focus_and_target": False,
    }

    # Load inputs
    date_path = os.path.join(input_dir, "date.txt")
    energy_path = os.path.join(input_dir, "energy.yaml")
    commitments_path = os.path.join(input_dir, "commitments.csv")
    tasks_path = os.path.join(input_dir, "tasks.json")
    plan_path = os.path.join(output_dir, "daily_plan.md")

    plan_text = read_text(plan_path)
    if plan_text is None:
        # If no output artifact, reward must be 0.0
        result = {"reward": 0.0, **checks}
        print(json.dumps(result))
        return

    checks["plan_file_exists"] = True

    lines = plan_text.splitlines()

    # Heading date match
    plan_date_text = read_text(date_path) or ""
    plan_date = parse_iso_date(plan_date_text) if plan_date_text else None
    heading_line = None
    if lines:
        # Look for first line beginning with "# Daily Plan"
        for ln in lines:
            if ln.strip().startswith("# Daily Plan"):
                heading_line = ln.strip()
                break
    if heading_line and plan_date:
        # Accept either ISO date or Month Day present
        month_str = month_name(plan_date)
        day_num = plan_date.day
        year_num = plan_date.year
        has_iso = plan_date_text.strip() in heading_line
        has_month_day = (month_str in heading_line) and (str(day_num) in heading_line)
        if has_iso or has_month_day:
            checks["heading_date_match"] = True

    # Sections order
    def find_line_idx_exact(prefix):
        for i, ln in enumerate(lines):
            if ln.strip().lower() == prefix.lower():
                return i
        return None

    idx_mission = find_line_idx_exact("## Today's Mission")
    idx_top3 = find_line_idx_exact("## Top 3 Priorities")
    idx_schedule = find_line_idx_exact("## Time-Blocked Schedule")
    idx_success = find_line_idx_exact("## Success Criteria")
    idx_evening = find_line_idx_exact("## Evening Check-In")

    subsections_ok = False
    if idx_success is not None:
        # Check for Must-Have, Should-Have, Nice-to-Have within success criteria range
        end_success = None
        for j in range(idx_success + 1, len(lines)):
            if lines[j].startswith("## "):
                end_success = j
                break
        success_lines = lines[idx_success + 1:end_success] if end_success else lines[idx_success + 1:]
        mh = any(ln.strip().lower().startswith("### must-have") for ln in success_lines)
        sh = any(ln.strip().lower().startswith("### should-have") for ln in success_lines)
        nh = any(ln.strip().lower().startswith("### nice-to-have") for ln in success_lines)
        subsections_ok = mh and sh and nh

    if None not in (idx_mission, idx_top3, idx_schedule, idx_success, idx_evening) and subsections_ok:
        if idx_mission < idx_top3 < idx_schedule < idx_success < idx_evening:
            checks["sections_in_order"] = True

    # Parse tasks.json
    tasks = load_tasks_json(tasks_path)
    task_titles = [t.get("title", "").strip() for t in tasks if t.get("title")]
    tasks_by_title = {t.get("title", "").strip(): t for t in tasks if t.get("title")}

    # Extract Top 3 lines
    top3_titles_found = []
    if idx_top3 is not None:
        # lines after idx_top3 until next "## "
        end_top3 = None
        for j in range(idx_top3 + 1, len(lines)):
            if lines[j].startswith("## "):
                end_top3 = j
                break
        top3_lines = lines[idx_top3 + 1:end_top3] if end_top3 else lines[idx_top3 + 1:]
        # Collect first three numbered list items
        for ln in top3_lines:
            m = re.match(r'^\s*\d+\.\s+(.*)$', ln)
            if m:
                text = m.group(1).strip()
                # Try to map to a task title by containment
                # Prefer exact title match if present
                matched_title = None
                for title in task_titles:
                    if title and title in text:
                        matched_title = title
                        break
                top3_titles_found.append(matched_title if matched_title else text)
        if len([ln for ln in top3_lines if re.match(r'^\s*\d+\.\s+', ln)]) == 3:
            checks["top3_count_three"] = True

    # Compute expected Top 3 selection set
    expected_top3_set = set()
    if plan_date and tasks:
        # Required: include all must_do tasks due on plan date
        must_due_today = [t for t in tasks if bool(t.get("must_do")) and t.get("due_date") == plan_date_text.strip()]
        # Sort by due_date ascending
        def due_key(t):
            try:
                return datetime.strptime(t.get("due_date", ""), "%Y-%m-%d").date()
            except Exception:
                return datetime.max.date()
        must_due_today_sorted = sorted(must_due_today, key=due_key)
        selected = []
        for t in must_due_today_sorted:
            if t.get("title"):
                selected.append(t)
        # If less than 3, fill remaining slots by earliest due_date across remaining tasks
        remaining = [t for t in tasks if t not in selected]
        remaining_sorted = sorted(remaining, key=due_key)
        for t in remaining_sorted:
            if len(selected) >= 3:
                break
            if t.get("title"):
                selected.append(t)
        expected_top3_set = set([t.get("title", "").strip() for t in selected[:3] if t.get("title")])

    # Verify Top 3 selection against expected rule
    if expected_top3_set and top3_titles_found:
        top3_set = set([t for t in top3_titles_found[:3] if t])
        # Check that all required due-today must_do tasks are included, and top3 length is 3
        required_titles = set([t.get("title", "").strip() for t in tasks if bool(t.get("must_do")) and t.get("due_date") == plan_date_text.strip()])
        includes_required = required_titles.issubset(top3_set)
        # Check that the chosen set equals the computed expected set (len 3)
        if includes_required and len(top3_set) == 3 and top3_set == expected_top3_set:
            checks["top3_correct_selection"] = True

    # Parse energy.yaml
    energy = parse_energy_yaml(energy_path)
    day_start_str = energy.get("day_start")
    day_end_str = energy.get("day_end")
    mp_minutes = energy.get("morning_priming_minutes")
    windows = energy.get("windows", {})
    # Convert window times to minutes
    win_minutes = {}
    for w in ("peak", "secondary", "recovery", "wind_down"):
        ws = windows.get(w, {}).get("start")
        we = windows.get(w, {}).get("end")
        win_minutes[w] = (parse_time_hhmm(ws), parse_time_hhmm(we))

    # Parse schedule blocks
    schedule_idx = idx_schedule
    next_major_idx = None
    if schedule_idx is not None:
        for j in range(schedule_idx + 1, len(lines)):
            if lines[j].startswith("## ") and j > schedule_idx:
                next_major_idx = j
                break
    blocks = extract_schedule_blocks(lines, schedule_idx + 1 if schedule_idx is not None else 0, next_major_idx) if schedule_idx is not None else []

    checks["block_headers_format"] = True if blocks else False

    # All blocks have Focus and Target lines
    if blocks:
        all_have = True
        for b in blocks:
            focus_ok = any(ln.strip().startswith("Focus:") for ln in b["lines"])
            target_ok = any(ln.strip().startswith("Target:") for ln in b["lines"])
            if not (focus_ok and target_ok):
                all_have = False
                break
        checks["all_blocks_have_focus_and_target"] = all_have

    # Morning Priming block correctness
    if blocks and day_start_str and mp_minutes:
        first_block = blocks[0]
        day_start_min = parse_time_hhmm(day_start_str)
        if day_start_min is not None:
            expected_end = day_start_min + int(mp_minutes)
            name_ok = (first_block["name"].strip() == "Morning Priming")
            timing_ok = (first_block["start_min"] == day_start_min and first_block["end_min"] == expected_end)
            if name_ok and timing_ok:
                checks["morning_priming_block_correct"] = True
            # ensure no task titles in priming block checklist
            if task_titles:
                has_any_task = False
                for ln in first_block["lines"]:
                    if "- [ ]" in ln:
                        for t in task_titles:
                            if t and t in ln:
                                has_any_task = True
                                break
                    if has_any_task:
                        break
                checks["morning_priming_no_tasks"] = (not has_any_task)
            else:
                # If no tasks input, consider it passes the no-tasks check
                checks["morning_priming_no_tasks"] = True

    # Commitments honored
    commitments = parse_commitments_csv(commitments_path)
    if blocks and commitments:
        all_commitments_ok = True
        for c in commitments:
            title = c.get("title", "").strip()
            s = parse_time_hhmm(c.get("start", ""))
            e = parse_time_hhmm(c.get("end", ""))
            if not title or s is None or e is None:
                all_commitments_ok = False
                break
            found = False
            for b in blocks:
                if b["start_min"] == s and b["end_min"] == e and (title.lower() in b["name"].lower()):
                    found = True
                    break
            if not found:
                all_commitments_ok = False
                break
        checks["commitments_blocks_present"] = all_commitments_ok

    # Lunch in recovery window and >= 30 minutes
    rec_start, rec_end = win_minutes.get("recovery", (None, None))
    if blocks and rec_start is not None and rec_end is not None:
        lunch_ok = False
        for b in blocks:
            if b["name"].strip().lower() == "lunch":
                dur = b["end_min"] - b["start_min"]
                in_window = within_window(b["start_min"], b["end_min"], rec_start, rec_end)
                if dur >= 30 and in_window:
                    lunch_ok = True
                    break
        checks["lunch_in_recovery_30min"] = lunch_ok

    # Buffer block >= 15 minutes anywhere
    if blocks:
        buf_ok = False
        for b in blocks:
            if "buffer" in b["name"].lower():
                dur = b["end_min"] - b["start_min"]
                if dur >= 15:
                    buf_ok = True
                    break
        checks["buffer_block_present"] = buf_ok

    # Top 3 scheduled in appropriate energy windows and listed in checklists
    if blocks and top3_titles_found and any(win_minutes[w][0] is not None for w in ("peak", "secondary", "recovery", "wind_down")):
        # Map difficulty to window
        diff_to_window = {"deep": "peak", "focus": "secondary", "light": "wind_down"}
        sched_all_ok = True
        # Only consider the first three parsed top3 titles mapped to actual task titles
        actual_top3_titles = []
        for t in top3_titles_found[:3]:
            # Already matched to titles where possible
            if t in tasks_by_title:
                actual_top3_titles.append(t)
            else:
                # Try exact match
                if t in tasks_by_title:
                    actual_top3_titles.append(t)
                else:
                    # Try find by containment
                    match = None
                    for title in task_titles:
                        if title and title in t:
                            match = title
                            break
                    if match:
                        actual_top3_titles.append(match)
                    else:
                        # Cannot map to a known task; fail this check
                        actual_top3_titles.append(t)

        for title in actual_top3_titles:
            task = tasks_by_title.get(title)
            if not task:
                sched_all_ok = False
                break
            diff = str(task.get("difficulty", "")).strip().lower()
            req_window = diff_to_window.get(diff)
            if not req_window:
                sched_all_ok = False
                break
            win_s, win_e = win_minutes.get(req_window, (None, None))
            if win_s is None or win_e is None:
                sched_all_ok = False
                break
            # Find a block that lists this task title in its checklist and lies fully within window
            found_ok = False
            for b in blocks:
                # Search for checklist line containing the title
                has_title = any(("- [ ]" in ln and title in ln) for ln in b["lines"])
                if has_title and within_window(b["start_min"], b["end_min"], win_s, win_e):
                    found_ok = True
                    break
            if not found_ok:
                sched_all_ok = False
                break
        checks["top3_scheduled_in_correct_windows"] = sched_all_ok

    # Success Criteria Must-Have includes checkboxes for the Top 3 titles
    if idx_success is not None and top3_titles_found:
        end_success = None
        for j in range(idx_success + 1, len(lines)):
            if lines[j].startswith("## "):
                end_success = j
                break
        success_lines = lines[idx_success + 1:end_success] if end_success else lines[idx_success + 1:]
        # Find Must-Have subsection range
        mh_start = None
        mh_end = None
        for i, ln in enumerate(success_lines):
            if ln.strip().lower().startswith("### must-have"):
                mh_start = i + 1
                break
        if mh_start is not None:
            for i in range(mh_start, len(success_lines)):
                if success_lines[i].strip().startswith("### "):
                    mh_end = i
                    break
            mh_lines = success_lines[mh_start:mh_end] if mh_end is not None else success_lines[mh_start:]
            must_have_text = "\n".join(mh_lines)
            # Confirm each of the first three top3 titles appear in a checkbox line
            mh_ok = True
            mapped_titles = []
            for t in top3_titles_found[:3]:
                # Map to known titles if possible
                title = t
                if t not in tasks_by_title:
                    # try find by containment
                    for tt in task_titles:
                        if tt and tt in t:
                            title = tt
                            break
                pattern = re.compile(r'-\s*\[\s*\]\s*.*' + re.escape(title))
                if not pattern.search(must_have_text):
                    mh_ok = False
                    break
                mapped_titles.append(title)
            checks["success_criteria_contains_top3"] = mh_ok

    # Evening Check-In lines
    if idx_evening is not None:
        end_evening = None
        for j in range(idx_evening + 1, len(lines)):
            if lines[j].startswith("## ") and j > idx_evening:
                end_evening = j
                break
        ev_lines = lines[idx_evening + 1:end_evening] if end_evening else lines[idx_evening + 1:]
        # Match exact three lines, allow leading/trailing spaces
        want = [
            r'^\s*-\s*\[\s*\]\s*Priority 1 done\?\s*YES\s*/\s*NO\s*$',
            r'^\s*-\s*\[\s*\]\s*Priority 2 done\?\s*YES\s*/\s*NO\s*$',
            r'^\s*-\s*\[\s*\]\s*Priority 3 done\?\s*YES\s*/\s*NO\s*$',
        ]
        found = [False, False, False]
        for ln in ev_lines:
            for i, pat in enumerate(want):
                if re.match(pat, ln):
                    found[i] = True
        checks["evening_checkin_three_lines"] = all(found)

    # Compute reward as fraction of passed checks, but zero if plan file missing
    passed = sum(1 for v in checks.values() if v)
    total_checks = len(checks)
    if not checks["plan_file_exists"]:
        reward = 0.0
    else:
        # Normalize by total number of checks
        reward = passed / total_checks if total_checks > 0 else 0.0
    # Ensure reward between 0 and 1
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()