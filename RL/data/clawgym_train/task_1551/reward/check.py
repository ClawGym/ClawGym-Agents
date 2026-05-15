import json
import os
import sys
import csv
from typing import Any, Dict, List, Optional, Tuple

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_csv(path: str) -> List[Dict[str, str]]:
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for r in rdr:
                # Normalize keys and strip values
                rr = {}
                for k, v in r.items():
                    if k is None:
                        continue
                    kk = k.strip()
                    rr[kk] = v.strip() if isinstance(v, str) else v
                rows.append(rr)
    except Exception:
        return []
    return rows

def parse_time_hhmm(s: str) -> Optional[int]:
    try:
        s = s.strip()
        if not s:
            return None
        parts = s.split(":")
        if len(parts) != 2:
            return None
        hh = int(parts[0])
        mm = int(parts[1])
        if hh < 0 or hh > 23 or mm < 0 or mm > 59:
            return None
        return hh * 60 + mm
    except Exception:
        return None

def minutes_to_hhmm(m: int) -> str:
    h = m // 60
    mm = m % 60
    return f"{h:02d}:{mm:02d}"

def simple_yaml_parse(text: str) -> Dict[str, Any]:
    """
    Minimal YAML parser for simple key/value and nested mappings with spaces.
    Supports:
    - top-level scalars: key: value
    - nested mappings:
      parent:
        child: value
    - does not support sequences or complex types.
    """
    result: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, result)]
    lines = text.splitlines()
    for line in lines:
        raw = line
        line = line.rstrip("\n\r")
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        if ":" not in content:
            # skip unsupported lines
            continue
        key, val = content.split(":", 1)
        key = key.strip()
        val = val.strip()
        # adjust stack by indentation
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1] if stack else result
        if val == "":
            # start of a nested mapping
            new_map: Dict[str, Any] = {}
            parent[key] = new_map
            stack.append((indent, new_map))
        else:
            # scalar; try to keep as string
            # strip surrounding quotes
            if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
                val = val[1:-1]
            parent[key] = val
    return result

def find_in_dict_case_insensitive(d: Dict[str, Any], key_candidates: List[str]) -> Optional[Any]:
    # search top-level for any candidate
    lower_map = {k.lower(): k for k in d.keys()}
    for cand in key_candidates:
        if cand in lower_map:
            return d[lower_map[cand]]
    # also try exact
    for k in d.keys():
        if k in key_candidates:
            return d[k]
    return None

def get_working_hours(pref: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    # Try typical structures
    # working_hours: { start: "08:00", end: "18:00" }
    wh = None
    for k in ["working_hours", "work_hours", "workinghours", "workday", "workingDay", "working-day"]:
        v = find_in_dict_case_insensitive(pref, [k, k.lower()])
        if isinstance(v, dict):
            wh = v
            break
    if isinstance(wh, dict):
        start = find_in_dict_case_insensitive(wh, ["start", "start_time", "begin"])
        end = find_in_dict_case_insensitive(wh, ["end", "end_time", "finish"])
        if isinstance(start, str) and isinstance(end, str):
            return start.strip(), end.strip()
    # flat keys
    start = find_in_dict_case_insensitive(pref, ["work_start", "working_start", "start_work"])
    end = find_in_dict_case_insensitive(pref, ["work_end", "working_end", "end_work"])
    s = start.strip() if isinstance(start, str) else None
    e = end.strip() if isinstance(end, str) else None
    return s, e

def get_lunch(pref: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    ln = None
    for k in ["lunch", "midday_break", "noon_break"]:
        v = find_in_dict_case_insensitive(pref, [k, k.lower()])
        if isinstance(v, dict):
            ln = v
            break
    if isinstance(ln, dict):
        start = find_in_dict_case_insensitive(ln, ["start", "start_time", "begin"])
        end = find_in_dict_case_insensitive(ln, ["end", "end_time", "finish"])
        if isinstance(start, str) and isinstance(end, str):
            return start.strip(), end.strip()
    return None, None

def get_date(pref: Dict[str, Any]) -> Optional[str]:
    # Try keys: date, day, target_date
    for k in ["date", "day", "target_date", "targetDate"]:
        v = find_in_dict_case_insensitive(pref, [k, k.lower()])
        if isinstance(v, str):
            v = v.strip()
            return v
    return None

def compute_top3(tasks_csv_path: str) -> Tuple[List[Dict[str, Any]], bool]:
    rows = parse_csv(tasks_csv_path)
    ok = True if rows else False
    tasks = []
    # Identify column names
    # name/title/task, impact, urgency, effort_minutes
    for r in rows:
        keys_lower = {k.lower(): k for k in r.keys()}
        name_key = None
        for k in ["name", "task", "title"]:
            if k in keys_lower:
                name_key = keys_lower[k]
                break
        impact_key = None
        urgency_key = None
        effort_key = None
        for k in ["impact"]:
            if k in keys_lower:
                impact_key = keys_lower[k]
                break
        for k in ["urgency"]:
            if k in keys_lower:
                urgency_key = keys_lower[k]
                break
        for k in ["effort_minutes", "effort", "effortmins", "effort-minutes"]:
            if k in keys_lower:
                effort_key = keys_lower[k]
                break
        if not (name_key and impact_key and urgency_key and effort_key):
            continue
        name = r[name_key].strip()
        try:
            impact = int(float(r[impact_key]))
            urgency = int(float(r[urgency_key]))
            effort = int(float(r[effort_key]))
        except Exception:
            continue
        score = impact * urgency
        tasks.append({
            "name": name,
            "impact": impact,
            "urgency": urgency,
            "effort": effort,
            "score": score
        })
    # sort by score desc, impact desc, effort asc, name asc
    tasks_sorted = sorted(tasks, key=lambda x: (-x["score"], -x["impact"], x["effort"], x["name"]))
    top3 = tasks_sorted[:3]
    # add rank
    for i, t in enumerate(top3, start=1):
        t["rank"] = i
    return top3, ok

def find_meeting_for_date(commitments_csv_path: str, date_str: str) -> Tuple[Optional[Dict[str, str]], bool]:
    rows = parse_csv(commitments_csv_path)
    if not rows or not date_str:
        return None, False
    # Try to detect columns
    chosen = None
    had_any = False
    for r in rows:
        keys_lower = {k.lower(): k for k in r.keys()}
        date_key = None
        start_key = None
        end_key = None
        title_key = None
        for k in ["date", "day"]:
            if k in keys_lower:
                date_key = keys_lower[k]
                break
        for k in ["start", "start_time", "begin"]:
            if k in keys_lower:
                start_key = keys_lower[k]
                break
        for k in ["end", "end_time", "finish"]:
            if k in keys_lower:
                end_key = keys_lower[k]
                break
        for k in ["title", "name", "meeting"]:
            if k in keys_lower:
                title_key = keys_lower[k]
                break
        if not (date_key and start_key and end_key and title_key):
            continue
        had_any = True
        if r[date_key].strip() == date_str:
            # Prefer specific expected time 15:15-15:45 if present
            st = r[start_key].strip()
            en = r[end_key].strip()
            if st == "15:15" and en == "15:45":
                return {"date": r[date_key].strip(), "start": st, "end": en, "title": r[title_key].strip()}, True
            if chosen is None:
                chosen = {"date": r[date_key].strip(), "start": st, "end": en, "title": r[title_key].strip()}
    return (chosen, True) if chosen else (None, had_any)

def index_of_block(blocks: List[Dict[str, Any]], block_id: str) -> int:
    # helper to return index if block_id stored in temp mapping, but here unused
    return -1

def block_matches(b: Dict[str, Any], start: str, end: str, type_: str) -> bool:
    try:
        return b.get("start") == start and b.get("end") == end and b.get("type") == type_
    except Exception:
        return False

def label_contains(b: Dict[str, Any], needle: str) -> bool:
    lab = b.get("label")
    if not isinstance(lab, str):
        return False
    return needle.lower() in lab.lower()

def run_checker(workspace_root: str) -> Dict[str, Any]:
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    tasks_csv = os.path.join(input_dir, "tasks.csv")
    commitments_csv = os.path.join(input_dir, "commitments.csv")
    preferences_yaml = os.path.join(input_dir, "preferences.yaml")
    plan_md_path = os.path.join(output_dir, "plan.md")
    sched_json_path = os.path.join(output_dir, "schedule.json")

    checks: Dict[str, bool] = {
        "has_plan_md": False,
        "has_schedule_json": False,
        "date_match": False,
        "top3_correct": False,
        "block_morning_prime": False,
        "block_p1": False,
        "block_break_1100": False,
        "block_lunch": False,
        "block_p3": False,
        "block_break_1500": False,
        "block_meeting": False,
        "block_p2": False,
        "block_admin_comm": False,
        "block_wrap_up": False,
        "blocks_in_order": False,
        "plan_has_required_headings": False,
        "plan_has_top3_names": False,
        "plan_has_meeting_in_schedule_section": False,
        "buffer_rule_ok": False,
    }

    # Existence checks
    if os.path.isfile(plan_md_path):
        checks["has_plan_md"] = True
        plan_md_text = read_text(plan_md_path) or ""
    else:
        plan_md_text = ""

    schedule_json = None
    if os.path.isfile(sched_json_path):
        checks["has_schedule_json"] = True
        schedule_json = load_json(sched_json_path)

    # If schedule.json not present, early compute nothing else
    if not schedule_json or not isinstance(schedule_json, dict):
        # Still check headings if plan exists; reward should stay 0 if core files missing
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        return {"reward": 0.0, **checks}

    # Load preferences.yaml
    pref_text = read_text(preferences_yaml) or ""
    pref_dict: Dict[str, Any] = {}
    if pref_text:
        try:
            pref_dict = simple_yaml_parse(pref_text)
        except Exception:
            pref_dict = {}

    # Get date
    pref_date = get_date(pref_dict)
    if isinstance(schedule_json.get("date"), str) and pref_date and schedule_json.get("date") == pref_date:
        checks["date_match"] = True

    # Compute top3 expected
    expected_top3, tasks_ok = compute_top3(tasks_csv)
    # Validate schedule_json top_priorities
    top_prios = schedule_json.get("top_priorities")
    top3_ok = False
    if isinstance(top_prios, list) and len(top_prios) >= 3 and expected_top3:
        # Map by rank
        by_rank = {p.get("rank"): p for p in top_prios if isinstance(p, dict) and "rank" in p}
        ranks_needed = [1, 2, 3]
        if all(r in by_rank for r in ranks_needed):
            names_match = True
            scores_match = True
            for exp in expected_top3:
                got = by_rank.get(exp["rank"])
                if not got:
                    names_match = False
                    scores_match = False
                    break
                if not isinstance(got.get("name"), str) or got.get("name") != exp["name"]:
                    names_match = False
                if not isinstance(got.get("score"), (int, float)) or int(got.get("score")) != int(exp["score"]):
                    scores_match = False
            if names_match and scores_match:
                top3_ok = True
    checks["top3_correct"] = top3_ok

    # Meeting info
    meeting_info, had_commitments = find_meeting_for_date(commitments_csv, pref_date or "")
    # Expected timeline slots (from task rules)
    # We will search the blocks for these required items in order, allowing extra blocks elsewhere.
    blocks = schedule_json.get("blocks")
    required_indices = []

    if isinstance(blocks, list):
        # 1) Morning Prime 08:00-09:00 routine
        idx_mp = None
        for i, b in enumerate(blocks):
            if not isinstance(b, dict):
                continue
            if block_matches(b, "08:00", "09:00", "routine") and label_contains(b, "Morning Prime"):
                idx_mp = i
                break
        checks["block_morning_prime"] = idx_mp is not None
        if idx_mp is not None:
            required_indices.append(idx_mp)

        # 2) Priority #1 09:00-11:00 work priority=1, label contains top1 name
        idx_p1 = None
        top1_name = expected_top3[0]["name"] if expected_top3 else None
        for i, b in enumerate(blocks):
            if not isinstance(b, dict):
                continue
            if block_matches(b, "09:00", "11:00", "work") and b.get("priority") == 1:
                if top1_name is None or label_contains(b, top1_name):
                    idx_p1 = i
                    break
        checks["block_p1"] = idx_p1 is not None
        if idx_p1 is not None:
            required_indices.append(idx_p1)

        # 3) Break 11:00-11:15
        idx_brk1 = None
        for i, b in enumerate(blocks):
            if not isinstance(b, dict):
                continue
            if block_matches(b, "11:00", "11:15", "break"):
                idx_brk1 = i
                break
        checks["block_break_1100"] = idx_brk1 is not None
        if idx_brk1 is not None:
            required_indices.append(idx_brk1)

        # 4) Lunch 12:30-13:30 break
        idx_lunch = None
        for i, b in enumerate(blocks):
            if not isinstance(b, dict):
                continue
            if block_matches(b, "12:30", "13:30", "break"):
                # Prefer labels that indicate lunch if present
                lab = b.get("label", "")
                if isinstance(lab, str):
                    if "lunch" in lab.lower():
                        idx_lunch = i
                        break
                # Accept any break at these times
                idx_lunch = i
                break
        checks["block_lunch"] = idx_lunch is not None
        if idx_lunch is not None:
            required_indices.append(idx_lunch)

        # 5) Priority #3 13:30-15:00 priority=3 work
        idx_p3 = None
        top3_name = expected_top3[2]["name"] if len(expected_top3) >= 3 else None
        for i, b in enumerate(blocks):
            if not isinstance(b, dict):
                continue
            if block_matches(b, "13:30", "15:00", "work") and b.get("priority") == 3:
                if top3_name is None or label_contains(b, top3_name):
                    idx_p3 = i
                    break
        checks["block_p3"] = idx_p3 is not None
        if idx_p3 is not None:
            required_indices.append(idx_p3)

        # 6) Break 15:00-15:15
        idx_brk2 = None
        for i, b in enumerate(blocks):
            if not isinstance(b, dict):
                continue
            if block_matches(b, "15:00", "15:15", "break"):
                idx_brk2 = i
                break
        checks["block_break_1500"] = idx_brk2 is not None
        if idx_brk2 is not None:
            required_indices.append(idx_brk2)

        # 7) Meeting 15:15-15:45 meeting label exactly commitment title
        idx_meeting = None
        meeting_title = meeting_info["title"] if isinstance(meeting_info, dict) else None
        meeting_start = meeting_info["start"] if isinstance(meeting_info, dict) else "15:15"
        meeting_end = meeting_info["end"] if isinstance(meeting_info, dict) else "15:45"
        # The reward summary expects 15:15-15:45; we still try to match exact.
        for i, b in enumerate(blocks):
            if not isinstance(b, dict):
                continue
            if block_matches(b, meeting_start, meeting_end, "meeting"):
                if isinstance(meeting_title, str):
                    if b.get("label") == meeting_title:
                        idx_meeting = i
                        break
                else:
                    # If no title known, accept any label at exact time
                    idx_meeting = i
                    break
        checks["block_meeting"] = idx_meeting is not None
        if idx_meeting is not None:
            required_indices.append(idx_meeting)

        # 8) Priority #2 15:45-16:45 priority=2 work
        idx_p2 = None
        top2_name = expected_top3[1]["name"] if len(expected_top3) >= 2 else None
        for i, b in enumerate(blocks):
            if not isinstance(b, dict):
                continue
            if block_matches(b, "15:45", "16:45", "work") and b.get("priority") == 2:
                if top2_name is None or label_contains(b, top2_name):
                    idx_p2 = i
                    break
        checks["block_p2"] = idx_p2 is not None
        if idx_p2 is not None:
            required_indices.append(idx_p2)

        # 9) Admin & Communication 16:45-17:30 work
        idx_admin = None
        for i, b in enumerate(blocks):
            if not isinstance(b, dict):
                continue
            if block_matches(b, "16:45", "17:30", "work"):
                lab = b.get("label")
                if isinstance(lab, str) and lab.strip().lower() == "admin & communication":
                    idx_admin = i
                    break
        checks["block_admin_comm"] = idx_admin is not None
        if idx_admin is not None:
            required_indices.append(idx_admin)

        # 10) Planning & Wrap-Up 17:30-18:00 work
        idx_wrap = None
        for i, b in enumerate(blocks):
            if not isinstance(b, dict):
                continue
            if block_matches(b, "17:30", "18:00", "work"):
                lab = b.get("label")
                if isinstance(lab, str) and lab.strip().lower() == "planning & wrap-up":
                    idx_wrap = i
                    break
        checks["block_wrap_up"] = idx_wrap is not None
        if idx_wrap is not None:
            required_indices.append(idx_wrap)

        # Check increasing order for the found required blocks
        if len(required_indices) >= 2:
            in_order = all(required_indices[i] < required_indices[i+1] for i in range(len(required_indices)-1))
            checks["blocks_in_order"] = in_order
        else:
            checks["blocks_in_order"] = False

        # Buffer rule: <= 80% of working hours for work+meeting blocks
        work_start_s, work_end_s = get_working_hours(pref_dict)
        if work_start_s and work_end_s:
            ws = parse_time_hhmm(work_start_s)
            we = parse_time_hhmm(work_end_s)
            if isinstance(ws, int) and isinstance(we, int) and we > ws:
                total_work_minutes = we - ws
                scheduled_wm = 0
                for b in blocks:
                    if not isinstance(b, dict):
                        continue
                    t = b.get("type")
                    if t in ("work", "meeting"):
                        st = parse_time_hhmm(str(b.get("start", "")))
                        en = parse_time_hhmm(str(b.get("end", "")))
                        if isinstance(st, int) and isinstance(en, int) and en >= st:
                            scheduled_wm += (en - st)
                # Exclude "routine" and "break" by only summing work+meeting above
                max_allowed = int(0.8 * total_work_minutes + 0.0001)
                if scheduled_wm <= max_allowed:
                    checks["buffer_rule_ok"] = True

    # Plan headings checks
    if plan_md_text:
        has_headings = all(h in plan_md_text for h in [
            "Daily Plan -",
            "Today's Mission",
            "Top 3 Priorities",
            "Time-Blocked Schedule",
            "Success Criteria",
            "Evening Check-In",
        ])
        checks["plan_has_required_headings"] = has_headings

        # Top 3 names present
        names_ok = True
        if expected_top3:
            for t in expected_top3:
                if t["name"] not in plan_md_text:
                    names_ok = False
                    break
        else:
            names_ok = False
        checks["plan_has_top3_names"] = names_ok

        # Meeting title appears in schedule section (after "Time-Blocked Schedule")
        meeting_ok = False
        if isinstance(meeting_info, dict) and isinstance(meeting_info.get("title"), str):
            schedule_pos = plan_md_text.find("Time-Blocked Schedule")
            meet_pos = plan_md_text.find(meeting_info["title"])
            if schedule_pos != -1 and meet_pos != -1 and meet_pos > schedule_pos:
                meeting_ok = True
        checks["plan_has_meeting_in_schedule_section"] = meeting_ok

    # Compute reward as fraction of passed checks
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = 0.0
    # No-op baseline: if required outputs missing, reward remains 0.0
    if checks["has_plan_md"] and checks["has_schedule_json"]:
        reward = passed / total if total > 0 else 0.0
    else:
        reward = 0.0

    return {"reward": reward, **checks}

if __name__ == "__main__":
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    result = run_checker(workspace_root)
    print(json.dumps(result))