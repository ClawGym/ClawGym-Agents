import json
import os
import sys
import re
import csv
from typing import Any, Dict, List, Tuple

def get_workspace_root() -> str:
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_time_str(s: str) -> bool:
    return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s or ""))

def time_to_minutes(s: str) -> int:
    hh, mm = s.split(":")
    return int(hh) * 60 + int(mm)

def minutes_diff(start: str, end: str) -> int:
    return time_to_minutes(end) - time_to_minutes(start)

def normalize_text(s: str) -> str:
    return (s or "").strip().lower().replace("’", "'").replace("–", "-").replace("—", "-")

def parse_calendar(csv_path: str) -> List[Dict[str, str]]:
    meetings: List[Dict[str, str]] = []
    if not os.path.isfile(csv_path):
        return meetings
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            sniffer_sample = f.read(2048)
            f.seek(0)
            dialect = None
            try:
                dialect = csv.Sniffer().sniff(sniffer_sample)
            except Exception:
                pass
            reader = csv.reader(f, dialect) if dialect else csv.reader(f)
            rows = list(reader)
    except Exception:
        return meetings
    if not rows:
        return meetings
    # Try to detect header
    header = [h.strip().lower() for h in rows[0]] if rows else []
    start_idx = end_idx = title_idx = None
    if any("start" in h for h in header) and any("end" in h for h in header):
        # Map columns
        for i, h in enumerate(header):
            if start_idx is None and ("start_time" in h or h == "start"):
                start_idx = i
            if end_idx is None and ("end_time" in h or h == "end"):
                end_idx = i
            if title_idx is None and ("title" in h or "name" in h or "summary" in h):
                title_idx = i
        data_rows = rows[1:]
        for row in data_rows:
            try:
                start = row[start_idx] if start_idx is not None and start_idx < len(row) else ""
                end = row[end_idx] if end_idx is not None and end_idx < len(row) else ""
                # If not found, scan row for first two HH:MM
                if not is_time_str(start) or not is_time_str(end):
                    times = [cell for cell in row if is_time_str(cell)]
                    if len(times) >= 2:
                        start, end = times[0], times[1]
                title = row[title_idx] if title_idx is not None and title_idx < len(row) else ""
                if is_time_str(start) and is_time_str(end):
                    meetings.append({"start_time": start, "end_time": end, "title": title})
            except Exception:
                continue
    else:
        # No clear header; parse each row for two HH:MM times and optional title
        for row in rows:
            times = [cell for cell in row if is_time_str(cell)]
            if len(times) >= 2:
                start, end = times[0], times[1]
                non_time_cells = [cell for cell in row if not is_time_str(cell)]
                title = " ".join(non_time_cells).strip()
                meetings.append({"start_time": start, "end_time": end, "title": title})
    return meetings

def extract_tasks_from_user_context(data: Any) -> Dict[str, float]:
    tasks: Dict[str, float] = {}

    def get_name(obj: Dict[str, Any]) -> str:
        for key in ("name", "title", "task", "label"):
            if isinstance(obj.get(key), str) and obj.get(key).strip():
                return obj[key].strip()
        # fallback to id if string
        if isinstance(obj.get("id"), str):
            return obj["id"].strip()
        return ""

    def get_naive_minutes(obj: Dict[str, Any]) -> float:
        for key in ("naive_estimate_minutes", "naive_minutes", "estimate_minutes", "estimate", "time_minutes", "duration"):
            val = obj.get(key)
            if isinstance(val, (int, float)):
                return float(val)
        return float("nan")

    # Primary: top-level "tasks" list
    if isinstance(data, dict) and isinstance(data.get("tasks"), list):
        for item in data["tasks"]:
            if isinstance(item, dict):
                name = get_name(item)
                naive = get_naive_minutes(item)
                if name and isinstance(naive, float) and not (naive != naive):  # not NaN
                    tasks[name] = naive

    # Fallback: recursive search for dicts with a name and a numeric naive estimate
    def walk(obj: Any):
        if isinstance(obj, dict):
            name = get_name(obj)
            naive = get_naive_minutes(obj)
            if name and isinstance(naive, float) and not (naive != naive):
                tasks.setdefault(name, naive)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    if not tasks:
        walk(data)

    return tasks

def parse_task_estimates(plan_task_estimates: Any) -> Dict[str, Tuple[float, float]]:
    result: Dict[str, Tuple[float, float]] = {}
    if isinstance(plan_task_estimates, dict):
        for name, obj in plan_task_estimates.items():
            if isinstance(obj, dict):
                naive = obj.get("naive_estimate_minutes")
                adjusted = obj.get("adjusted_estimate_minutes")
                if isinstance(naive, (int, float)) and isinstance(adjusted, (int, float)):
                    result[str(name)] = (float(naive), float(adjusted))
    elif isinstance(plan_task_estimates, list):
        for item in plan_task_estimates:
            if isinstance(item, dict):
                name = None
                for key in ("name", "task", "title", "label"):
                    if isinstance(item.get(key), str) and item.get(key).strip():
                        name = item[key].strip()
                        break
                naive = item.get("naive_estimate_minutes")
                adjusted = item.get("adjusted_estimate_minutes")
                if name and isinstance(naive, (int, float)) and isinstance(adjusted, (int, float)):
                    result[name] = (float(naive), float(adjusted))
    return result

def validate_time_blocks(blocks: Any) -> Tuple[bool, List[Dict[str, Any]]]:
    if not isinstance(blocks, list):
        return False, []
    ok = True
    allowed_types = {"meeting", "task", "buffer", "break"}
    cleaned: List[Dict[str, Any]] = []
    for b in blocks:
        if not isinstance(b, dict):
            ok = False
            continue
        start = b.get("start_time")
        end = b.get("end_time")
        t = b.get("type")
        label = b.get("label")
        if not (isinstance(start, str) and isinstance(end, str) and is_time_str(start) and is_time_str(end)):
            ok = False
        else:
            if minutes_diff(start, end) <= 0:
                ok = False
        if t not in allowed_types:
            ok = False
        if not isinstance(label, str):
            ok = False
        cleaned.append({"start_time": start, "end_time": end, "type": t, "label": label})
    return ok, cleaned

def line_has_time_range(line: str) -> bool:
    return bool(re.search(r"\b([01]\d|2[0-3]):[0-5]\d\s*[-–]\s*([01]\d|2[0-3]):[0-5]\d\b", line))

def count_bullets(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if re.match(r"^\s*[-\*\u2022]\s+", line):
            count += 1
    return count

def has_forbidden_words(text: str) -> bool:
    return bool(re.search(r"\b(very|really|just)\b", text, flags=re.IGNORECASE))

def find_section_headings(text: str) -> List[str]:
    # Return normalized headings found (lines that look like headings with # or exact word lines)
    headings: List[str] = []
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if not stripped:
            continue
        # Consider standalone words as possible headings if line has no punctuation and <= 4 words
        if re.fullmatch(r"[A-Za-z ]{2,}", stripped):
            headings.append(stripped.lower())
    return headings

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    plan_path = os.path.join(output_dir, "plan.json")
    agenda_path = os.path.join(output_dir, "agenda.md")
    dopam_edit_path = os.path.join(output_dir, "dopamine_menu_edited.md")
    user_ctx_path = os.path.join(input_dir, "user_context.json")
    calendar_path = os.path.join(input_dir, "calendar.csv")

    checks: Dict[str, bool] = {
        # plan.json checks
        "plan_exists": False,
        "plan_valid_json": False,
        "plan_has_required_keys": False,
        "plan_fields_types_valid": False,
        "time_blocks_format_valid": False,
        "all_meetings_present": False,
        "buffer_after_each_meeting": False,
        "at_least_two_named_transition_buffers": False,
        "task_estimates_covers_all_tasks": False,
        "task_estimates_3x_rule": False,
        "executive_support_contains_required": False,
        # agenda.md checks
        "agenda_exists": False,
        "agenda_has_three_sections": False,
        "agenda_has_time_range": False,
        "agenda_has_dopamine_menu_headings": False,
        "agenda_has_shutdown_ritual_5_steps": False,
        # dopamine_menu_edited.md checks
        "dopamine_menu_exists": False,
        "dopamine_menu_has_four_headings": False,
        "dopamine_menu_bullets_leq_15": False,
        "dopamine_menu_size_leq_2000": False,
        "dopamine_menu_no_forbidden_words": False,
        "dopamine_menu_only_allowed_headings": False,
    }

    plan = None
    time_blocks_clean: List[Dict[str, Any]] = []
    calendar_meetings: List[Dict[str, str]] = []

    # plan.json existence and parse
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        plan = load_json(plan_path)
        if isinstance(plan, dict):
            checks["plan_valid_json"] = True
            required_keys = {"date", "the_thing", "would_be_nice", "if_crushing_it", "task_estimates", "time_blocks", "executive_support"}
            if required_keys.issubset(set(plan.keys())):
                checks["plan_has_required_keys"] = True
                # Validate field types
                the_thing_ok = isinstance(plan.get("the_thing"), str)
                would_ok = isinstance(plan.get("would_be_nice"), list)
                if_ok = isinstance(plan.get("if_crushing_it"), list)
                exec_ok = isinstance(plan.get("executive_support"), list) and len(plan.get("executive_support")) >= 2
                tb_ok, time_blocks_clean = validate_time_blocks(plan.get("time_blocks"))
                checks["time_blocks_format_valid"] = tb_ok
                checks["plan_fields_types_valid"] = all([the_thing_ok, would_ok, if_ok, exec_ok, isinstance(plan.get("task_estimates"), (list, dict)), isinstance(plan.get("date"), str)])

                # Executive support content
                exec_support = plan.get("executive_support") if isinstance(plan.get("executive_support"), list) else []
                normalized_exec = [normalize_text(x) for x in exec_support if isinstance(x, str)]
                has_two_minute_start = any("2 minute start" in e or "2-minute start" in e for e in normalized_exec)
                has_body_or_tempt = any(("body doubling" in e) or ("temptation bundling" in e) for e in normalized_exec)
                checks["executive_support_contains_required"] = bool(has_two_minute_start and has_body_or_tempt)

    # Meetings parsing
    calendar_meetings = parse_calendar(calendar_path)

    # Meeting presence in time_blocks
    if checks["time_blocks_format_valid"]:
        # Build set of (start,end,type) for meeting blocks
        meeting_blocks_indices = []
        for idx, b in enumerate(time_blocks_clean):
            if b.get("type") == "meeting":
                meeting_blocks_indices.append((idx, b["start_time"], b["end_time"], b.get("label", "")))
        # For each expected meeting, ensure present
        all_present = True
        indices_for_calendar_meetings: List[int] = []
        for m in calendar_meetings:
            found_idx = None
            for idx, s, e, _ in meeting_blocks_indices:
                if s == m["start_time"] and e == m["end_time"]:
                    found_idx = idx
                    break
            if found_idx is None:
                all_present = False
            else:
                indices_for_calendar_meetings.append(found_idx)
        if not calendar_meetings:
            # Vacuously true if no meetings
            checks["all_meetings_present"] = True
            checks["buffer_after_each_meeting"] = True
        else:
            checks["all_meetings_present"] = all_present
            # For each matched meeting index, check buffer immediately following
            buf_ok = True
            if all_present:
                for idx in indices_for_calendar_meetings:
                    next_idx = idx + 1
                    if next_idx >= len(time_blocks_clean):
                        buf_ok = False
                        break
                    nb = time_blocks_clean[next_idx]
                    if nb.get("type") != "buffer":
                        buf_ok = False
                        break
                    # Duration between its own start and end
                    try:
                        dur = minutes_diff(nb["start_time"], nb["end_time"])
                        if not (10 <= dur <= 20):
                            buf_ok = False
                            break
                    except Exception:
                        buf_ok = False
                        break
            checks["buffer_after_each_meeting"] = buf_ok

        # Named transition buffers (label contains "transition")
        transition_buffers = [b for b in time_blocks_clean if b.get("type") == "buffer" and isinstance(b.get("label"), str) and ("transition" in b["label"].lower())]
        checks["at_least_two_named_transition_buffers"] = len(transition_buffers) >= 2

    # Task estimates checks
    if plan and isinstance(plan.get("task_estimates"), (list, dict)):
        user_ctx = load_json(user_ctx_path)
        input_tasks = extract_tasks_from_user_context(user_ctx) if user_ctx is not None else {}
        plan_estimates = parse_task_estimates(plan.get("task_estimates"))
        # Coverage
        if input_tasks:
            covers_all = set(input_tasks.keys()).issubset(set(plan_estimates.keys()))
            checks["task_estimates_covers_all_tasks"] = covers_all
            # 3x rule only for those input tasks
            rule_ok = True
            if covers_all:
                for name, naive in input_tasks.items():
                    if name not in plan_estimates:
                        rule_ok = False
                        break
                    naive_plan, adjusted_plan = plan_estimates[name]
                    # Naive must be numeric; adjusted >= naive*3
                    try:
                        if adjusted_plan < naive * 3 or naive_plan < naive:
                            # ensure naive_plan from output is at least the input naive (but spec doesn't require equal, only present)
                            # Only enforce adjusted >= naive*3
                            if adjusted_plan < naive * 3:
                                rule_ok = False
                                break
                        # Also check within plan item: adjusted >= naive*3 based on that item's naive
                        if adjusted_plan < naive_plan * 3:
                            rule_ok = False
                            break
                    except Exception:
                        rule_ok = False
                        break
            else:
                rule_ok = False
            checks["task_estimates_3x_rule"] = rule_ok
        else:
            # If no tasks parsed from input, we cannot verify coverage; keep as False
            pass

    # agenda.md checks
    if os.path.isfile(agenda_path):
        checks["agenda_exists"] = True
        agenda_text = read_text(agenda_path)
        ag_norm = normalize_text(agenda_text)
        # Sections: THE Thing, Would Be Nice, If I'm On Fire
        has_the_thing = "the thing" in ag_norm
        has_would = "would be nice" in ag_norm
        # Support both apostrophes
        has_if_fire = ("if i'm on fire" in ag_norm) or ("if i’m on fire" in ag_norm)
        checks["agenda_has_three_sections"] = all([has_the_thing, has_would, has_if_fire])
        # Time range line
        checks["agenda_has_time_range"] = any(line_has_time_range(line) for line in agenda_text.splitlines())
        # Dopamine menu headings
        has_app = "appetizers" in ag_norm
        has_start = "starters" in ag_norm
        has_main = "main courses" in ag_norm
        has_dess = "desserts" in ag_norm
        checks["agenda_has_dopamine_menu_headings"] = all([has_app, has_start, has_main, has_dess])
        # Shutdown ritual with at least 5 numbered steps
        has_shutdown = "shutdown ritual" in ag_norm
        numbered_steps = [ln for ln in agenda_text.splitlines() if re.match(r"^\s*\d+\.\s", ln)]
        checks["agenda_has_shutdown_ritual_5_steps"] = bool(has_shutdown and len(numbered_steps) >= 5)

    # dopamine_menu_edited.md checks
    if os.path.isfile(dopam_edit_path):
        checks["dopamine_menu_exists"] = True
        d_text = read_text(dopam_edit_path)
        d_norm = normalize_text(d_text)
        # Headings presence (case-insensitive)
        need_heads = {"appetizers", "starters", "main courses", "desserts"}
        found_heads_in_lines = set()
        for line in d_text.splitlines():
            stripped = line.strip().lstrip("#").strip().lower()
            if stripped in need_heads:
                found_heads_in_lines.add(stripped)
        checks["dopamine_menu_has_four_headings"] = (found_heads_in_lines == need_heads) or (need_heads.issubset(found_heads_in_lines))
        # Bullet count <= 15
        checks["dopamine_menu_bullets_leq_15"] = count_bullets(d_text) <= 15
        # Size <= 2000 chars
        checks["dopamine_menu_size_leq_2000"] = len(d_text) <= 2000
        # No forbidden words
        checks["dopamine_menu_no_forbidden_words"] = not has_forbidden_words(d_text)
        # Only allowed headings when using markdown '#' headings
        only_allowed = True
        for line in d_text.splitlines():
            if line.strip().startswith("#"):
                stripped = line.strip().lstrip("#").strip().lower()
                if stripped and stripped not in need_heads:
                    only_allowed = False
                    break
        checks["dopamine_menu_only_allowed_headings"] = only_allowed

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # No-op baseline: if output dir missing or no required files, reward must be 0.0
    required_outputs_exist = checks["plan_exists"] and checks["agenda_exists"] and checks["dopamine_menu_exists"]
    if not required_outputs_exist:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0
        # Bound between 0 and 1
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()