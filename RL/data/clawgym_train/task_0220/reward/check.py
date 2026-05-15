import json
import re
import sys
import csv
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Dict, Any, List


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[dict]:
    try:
        txt = read_text_safe(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def parse_yaml_keys(yaml_text: str) -> Optional[List[str]]:
    """
    Minimal YAML key parser for simple top-level mappings (no nested structures needed).
    We avoid external libraries; only parse top-level keys (key: value) or key: newline list.
    """
    try:
        keys: List[str] = []
        for line in yaml_text.splitlines():
            # Ignore empty lines and comments
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            # Top-level key: value (no indentation)
            if re.match(r"^[A-Za-z0-9_\-]+\s*:", line):
                key = line.split(":", 1)[0].strip()
                if key and key not in keys:
                    keys.append(key)
        return keys
    except Exception:
        return None


def extract_script_cfg_keys(py_text: str) -> Optional[List[str]]:
    """
    Extract keys accessed via cfg['key'] and cfg.get('key', ...) from Python source text.
    """
    try:
        keys = set()
        # cfg['key']
        for m in re.finditer(r"cfg\[\s*['\"]([^'\"]+)['\"]\s*\]", py_text):
            keys.add(m.group(1))
        # cfg.get('key'
        for m in re.finditer(r"cfg\.get\(\s*['\"]([^'\"]+)['\"]", py_text):
            keys.add(m.group(1))
        return list(keys)
    except Exception:
        return None


def safe_parse_bool(s: str) -> Optional[bool]:
    if s is None:
        return None
    val = s.strip().lower()
    if val in ("true", "t", "yes", "1"):
        return True
    if val in ("false", "f", "no", "0"):
        return False
    return None


def parse_csv_log(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        rows: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required_cols = ["date", "activity", "type", "duration_min", "grade", "notes", "completed"]
            if reader.fieldnames is None or any(col not in reader.fieldnames for col in required_cols):
                return None
            for r in reader:
                try:
                    date_obj = datetime.strptime(r["date"].strip(), "%Y-%m-%d").date()
                    activity = r["activity"].strip()
                    duration = int(r["duration_min"].strip())
                    grade = r["grade"].strip()
                    completed = safe_parse_bool(r["completed"])
                    if completed is None:
                        return None
                    rows.append({
                        "date": date_obj,
                        "activity": activity,
                        "type": r["type"].strip(),
                        "duration_min": duration,
                        "grade": grade,
                        "notes": r["notes"],
                        "completed": completed,
                    })
                except Exception:
                    return None
        return rows
    except Exception:
        return None


def compute_expected_consistency(script_text: Optional[str], yaml_text: Optional[str]) -> Optional[Dict[str, List[str]]]:
    if script_text is None or yaml_text is None:
        return None
    script_keys_used = extract_script_cfg_keys(script_text)
    config_keys_present = parse_yaml_keys(yaml_text)
    if script_keys_used is None or config_keys_present is None:
        return None
    script_set = set(script_keys_used)
    config_set = set(config_keys_present)
    missing_in_config = sorted(list(script_set - config_set))
    unused_in_config = sorted(list(config_set - script_set))
    return {
        "script_keys_used": sorted(list(script_set)),
        "config_keys_present": sorted(list(config_set)),
        "missing_in_config": missing_in_config,
        "unused_in_config": unused_in_config,
    }


def parse_meeting_notes_sections(text: str) -> Dict[str, Tuple[int, int]]:
    """
    Find sections by their headers in meeting notes.
    Returns mapping header_lower -> (start_index, end_index) character positions.
    Sections detected: progress summary, key observations, proposed action items, sessions_per_week region.
    """
    sections = {}
    headers = [
        "progress summary",
        "key observations",
        "proposed action items",
        "sessions_per_week",
    ]
    lower_text = text.lower()
    positions = {}
    for h in headers:
        idx = lower_text.find(h)
        if idx != -1:
            positions[h] = idx
    # Determine region ranges by next header boundary
    indexed = sorted(positions.items(), key=lambda x: x[1])
    for i, (h, start) in enumerate(indexed):
        end = len(text)
        if i + 1 < len(indexed):
            end = indexed[i + 1][1]
        sections[h] = (start, end)
    return sections


def find_label_value(text: str, label: str) -> Optional[str]:
    """
    Find value following a label like 'label:' possibly with spaces.
    Returns the captured value (up to line end).
    """
    pattern = re.compile(rf"{re.escape(label)}\s*:\s*(.+)", re.IGNORECASE)
    for line in text.splitlines():
        m = pattern.search(line)
        if m:
            return m.group(1).strip()
    return None


def extract_number_from_text(s: str) -> Optional[float]:
    if s is None:
        return None
    m = re.search(r"[-+]?\d+(\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def parse_hardest_grade_value(s: str) -> Optional[int]:
    """
    Accepts 'V4', '4', 'v4'. Returns int 4, etc.
    """
    if s is None:
        return None
    m = re.search(r"[Vv]?\s*(\d+)", s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def compute_hardest_grade(rows: List[Dict[str, Any]]) -> Optional[int]:
    max_grade = None
    for r in rows:
        grade = r["grade"]
        if grade is None or grade.strip() == "-" or grade.strip() == "":
            continue
        # Extract numbers like V3 or V2-V3; take highest
        parts = re.findall(r"[Vv]?\s*(\d+)", grade)
        nums = [int(p) for p in parts] if parts else []
        if not nums:
            continue
        g = max(nums)
        if max_grade is None or g > max_grade:
            max_grade = g
    return max_grade


def compute_sessions_per_week(rows: List[Dict[str, Any]]) -> Dict[int, int]:
    counts: Dict[int, int] = {}
    for r in rows:
        if r["completed"] and r["activity"] != "Rest":
            week = r["date"].isocalendar()[1]
            counts[week] = counts.get(week, 0) + 1
    return counts


def count_bullets_in_section(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if re.match(r"\s*[-*]\s+\S+", line):
            count += 1
    return count


def detect_time_windows(text: str) -> int:
    """
    Detect  time windows like '3-5pm', '3pm-5pm', '15:00-17:00', '3 to 5pm'.
    We'll count '- or –' separated times, permissive.
    """
    # Common patterns: h[:mm][am/pm] - h[:mm][am/pm]
    pattern = re.compile(
        r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*[-–]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b",
        re.IGNORECASE
    )
    return len(pattern.findall(text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_consistency_json_structure": 0.0,
        "config_consistency_json_values_correct": 0.0,
        "inspection_report_mismatches_covered": 0.0,
        "inspection_report_logic_pitfalls": 0.0,
        "inspection_report_suggestions_present": 0.0,
        "json_and_report_agree_on_mismatches": 0.0,
        "meeting_notes_progress_summary_values": 0.0,
        "meeting_notes_sessions_per_week_note": 0.0,
        "meeting_notes_observations_count": 0.0,
        "meeting_notes_action_items_count": 0.0,
        "email_rewrite_requirements": 0.0,
    }

    # Paths
    input_script = workspace / "input" / "training_plan.py"
    input_yaml = workspace / "input" / "training_config.yaml"
    input_csv = workspace / "input" / "training_log.csv"
    input_email = workspace / "input" / "email_draft.txt"

    out_config_json = workspace / "outputs" / "config_consistency.json"
    out_report_md = workspace / "outputs" / "inspection_report.md"
    out_meeting_notes_md = workspace / "outputs" / "meeting_notes.md"
    out_email_txt = workspace / "outputs" / "email_to_mentor.txt"

    # Load inputs safely
    script_text = read_text_safe(input_script)
    yaml_text = read_text_safe(input_yaml)
    csv_rows = parse_csv_log(input_csv) if input_csv.exists() else None

    # A) Validate config_consistency.json structure
    ccj = load_json_safe(out_config_json)
    if isinstance(ccj, dict):
        required_fields = ["script_keys_used", "config_keys_present", "missing_in_config", "unused_in_config"]
        types_ok = all(
            (k in ccj and isinstance(ccj[k], list) and all(isinstance(x, str) for x in ccj[k]))
            for k in required_fields
        )
        if types_ok:
            scores["config_consistency_json_structure"] = 1.0

    # B) Validate config_consistency.json values against recomputation
    expected_consistency = compute_expected_consistency(script_text, yaml_text) if script_text and yaml_text else None
    if expected_consistency and isinstance(ccj, dict):
        try:
            def as_set_list(lst): return set(lst if isinstance(lst, list) else [])
            match = (
                as_set_list(ccj.get("script_keys_used", [])) == set(expected_consistency["script_keys_used"]) and
                as_set_list(ccj.get("config_keys_present", [])) == set(expected_consistency["config_keys_present"]) and
                as_set_list(ccj.get("missing_in_config", [])) == set(expected_consistency["missing_in_config"]) and
                as_set_list(ccj.get("unused_in_config", [])) == set(expected_consistency["unused_in_config"])
            )
            if match:
                scores["config_consistency_json_values_correct"] = 1.0
        except Exception:
            pass

    # C) Inspection report checks
    report_text = read_text_safe(out_report_md)
    if report_text:
        # Mismatches coverage: must mention hangboard_minutes vs hangboard_time_min AND rest_days vs rest_day
        mentions_hangboard_pair = ("hangboard_minutes" in report_text and "hangboard_time_min" in report_text)
        mentions_rest_pair = ("rest_days" in report_text and "rest_day" in report_text)
        if mentions_hangboard_pair and mentions_rest_pair:
            scores["inspection_report_mismatches_covered"] = 1.0

        # Logic pitfalls: mention default/fallback masking and list vs string for rest days
        pitfalls = 0
        if ("default" in report_text.lower() or "fallback" in report_text.lower()) and "hangboard_minutes" in report_text:
            pitfalls += 1
        if ("list" in report_text.lower() and "string" in report_text.lower() and "rest" in report_text.lower()):
            pitfalls += 1
        if pitfalls == 2:
            scores["inspection_report_logic_pitfalls"] = 1.0

        # Suggestions present: look for verbs and key names indicating concrete fixes
        suggestion_keywords = ["rename", "change", "update", "align", "use", "match", "fix", "modify"]
        has_suggestion = any(word in report_text.lower() for word in suggestion_keywords)
        # Ensure suggestions relate to the mismatched keys
        mentions_any_key = any(k in report_text for k in ["hangboard_minutes", "hangboard_time_min", "rest_days", "rest_day"])
        if has_suggestion and mentions_any_key:
            scores["inspection_report_suggestions_present"] = 1.0

    # D) JSON and report agreement on mismatches
    if expected_consistency and report_text and isinstance(ccj, dict):
        report_ok = ("hangboard_minutes" in report_text and "hangboard_time_min" in report_text and
                     "rest_days" in report_text and "rest_day" in report_text)
        json_ok = (set(ccj.get("missing_in_config", [])) == set(expected_consistency["missing_in_config"]) and
                   set(ccj.get("unused_in_config", [])) == set(expected_consistency["unused_in_config"]))
        if report_ok and json_ok:
            scores["json_and_report_agree_on_mismatches"] = 1.0

    # E) Meeting notes checks
    notes_text = read_text_safe(out_meeting_notes_md)
    if notes_text and csv_rows and yaml_text:
        # Compute expected values
        # YAML values
        yaml_keys = parse_yaml_keys(yaml_text) or []
        yaml_map = {}
        # Minimal parse of scalar values for known keys using regex
        for key in ["hangboard_time_min", "weekly_sessions"]:
            m = re.search(rf"^{key}\s*:\s*([^\n#]+)", yaml_text, flags=re.MULTILINE)
            if m:
                yaml_map[key] = m.group(1).strip()
        try:
            hangboard_threshold = int(yaml_map.get("hangboard_time_min", "").split()[0])
        except Exception:
            hangboard_threshold = None
        try:
            weekly_target = int(yaml_map.get("weekly_sessions", "").split()[0])
        except Exception:
            weekly_target = None

        non_rest = [r for r in csv_rows if r["completed"] and r["activity"] != "Rest"]
        total_sessions_logged = len(non_rest)
        avg_duration = None
        if total_sessions_logged > 0:
            avg_duration = sum(r["duration_min"] for r in non_rest) / total_sessions_logged
        hardest_grade = compute_hardest_grade(csv_rows)
        hangboard_below = None
        if hangboard_threshold is not None:
            hangboard_below = sum(1 for r in csv_rows if r["activity"] == "Hangboard" and r["completed"] and r["duration_min"] < hangboard_threshold)
        sessions_per_week = compute_sessions_per_week(csv_rows)

        # Validate presence and correctness of labeled items
        labels_ok = True

        # total_sessions_logged
        val = find_label_value(notes_text, "total_sessions_logged")
        if val is None or extract_number_from_text(val) is None:
            labels_ok = False
        else:
            if int(extract_number_from_text(val)) != total_sessions_logged:
                labels_ok = False

        # average_session_duration_min
        val = find_label_value(notes_text, "average_session_duration_min")
        if val is None or extract_number_from_text(val) is None or avg_duration is None:
            labels_ok = False
        else:
            reported = extract_number_from_text(val)
            if reported is None or abs(reported - avg_duration) > 1e-6:
                labels_ok = False

        # hardest_grade_attempted
        val = find_label_value(notes_text, "hardest_grade_attempted")
        if val is None or hardest_grade is None:
            labels_ok = False
        else:
            hg = parse_hardest_grade_value(val)
            if hg is None or hg != hardest_grade:
                labels_ok = False

        # hangboard_sessions_below_threshold
        val = find_label_value(notes_text, "hangboard_sessions_below_threshold")
        if val is None or hangboard_below is None or extract_number_from_text(val) is None:
            labels_ok = False
        else:
            if int(extract_number_from_text(val)) != hangboard_below:
                labels_ok = False

        # sessions_per_week mapping presence
        # Ensure "sessions_per_week" appears and each (week, count) is mentioned
        spw_section = None
        sections = parse_meeting_notes_sections(notes_text)
        if "sessions_per_week" in sections:
            s, e = sections["sessions_per_week"]
            spw_section = notes_text[s:e]
        else:
            # try to find line containing label
            spw_label_idx = notes_text.lower().find("sessions_per_week")
            if spw_label_idx != -1:
                spw_section = notes_text[spw_label_idx: spw_label_idx + 500]

        if spw_section is None:
            labels_ok = False
        else:
            # every week,count pair must appear
            for wk, cnt in sessions_per_week.items():
                pattern = re.compile(rf"\b{wk}\b.*\b{cnt}\b")
                if not pattern.search(spw_section):
                    labels_ok = False
                    break

        if labels_ok:
            scores["meeting_notes_progress_summary_values"] = 1.0

        # Sessions per week under/over note presence
        note_ok = False
        if spw_section:
            low = spw_section.lower()
            if "under" in low or "over" in low or "on target" in low or "on-target" in low:
                # Optionally ensure it reflects comparison with weekly target if available
                note_ok = True
        if note_ok:
            scores["meeting_notes_sessions_per_week_note"] = 1.0

        # Key observations count: 2-4 bullets
        obs_section = ""
        if "key observations" in sections:
            s, e = sections["key observations"]
            obs_section = notes_text[s:e]
        obs_bullets = count_bullets_in_section(obs_section)
        if 2 <= obs_bullets <= 4:
            scores["meeting_notes_observations_count"] = 1.0

        # Proposed action items count: 3-5 bullets
        act_section = ""
        if "proposed action items" in sections:
            s, e = sections["proposed action items"]
            act_section = notes_text[s:e]
        act_bullets = count_bullets_in_section(act_section)
        if 3 <= act_bullets <= 5:
            scores["meeting_notes_action_items_count"] = 1.0

    # F) Email rewrite checks
    email_text = read_text_safe(out_email_txt)
    if email_text:
        # clear ask to meet
        ask_ok = any(kw in email_text.lower() for kw in ["meet", "meeting", "chat", "call"]) and any(
            kw in email_text.lower() for kw in ["could", "would", "can", "schedule", "set up", "time to"]
        )
        # 2-3 time windows
        windows = detect_time_windows(email_text)
        windows_ok = 2 <= windows <= 3
        # goals mention: check for focus skills or grade goal
        goals_ok = any(kw in email_text for kw in ["V5", "footwork", "body tension", "grade goal", "max grade"])
        # mention meeting notes reference
        notes_ref_ok = "outputs/meeting_notes.md" in email_text

        if ask_ok and windows_ok and goals_ok and notes_ref_ok:
            scores["email_rewrite_requirements"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()