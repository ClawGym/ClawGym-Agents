import json
import csv
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _parse_scalar(value: str) -> Any:
    v = value.strip()
    if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
        return v[1:-1]
    low = v.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if re.fullmatch(r"-?\d+", v):
        try:
            return int(v)
        except Exception:
            pass
    if re.fullmatch(r"-?\d+\.\d+", v):
        try:
            return float(v)
        except Exception:
            pass
    return v


def _parse_yaml_minimal(text: str) -> Optional[Dict[str, Any]]:
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    for raw_line in lines:
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent % 2 != 0:
            return None
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        current = stack[-1][1]
        stripped = line.lstrip()
        if ":" not in stripped:
            return None
        key, _, rest = stripped.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest == "":
            if key in current and not isinstance(current[key], dict):
                return None
            new_dict: Dict[str, Any] = {}
            current[key] = new_dict
            stack.append((indent, new_dict))
        else:
            current[key] = _parse_scalar(rest)
    return root


def _parse_python_constants(text: str, names: List[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    pattern = re.compile(r'^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.+?)\s*(#.*)?$')
    for line in text.splitlines():
        m = pattern.match(line)
        if not m:
            continue
        const, val_str, _ = m.groups()
        if const not in names:
            continue
        val = _parse_scalar(val_str)
        result[const] = val
    return result


def _safe_parse_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _compute_expected_from_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    yaml_path = workspace / "config" / "study_space.yaml"
    code_path = workspace / "scripts" / "room_monitor.py"
    csv_path = workspace / "data" / "checkins.csv"
    yaml_text = _safe_read_text(yaml_path)
    code_text = _safe_read_text(code_path)
    rows = _safe_parse_csv_rows(csv_path)
    if yaml_text is None or code_text is None or rows is None:
        return None

    yaml_parsed = _parse_yaml_minimal(yaml_text)
    if yaml_parsed is None:
        return None

    def _get_nested(d: Dict[str, Any], keys: List[str]) -> Any:
        cur: Any = d
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return None
            cur = cur[k]
        return cur

    yaml_fields = {
        "quiet_hours.enabled": _get_nested(yaml_parsed, ["quiet_hours", "enabled"]),
        "quiet_hours.start": _get_nested(yaml_parsed, ["quiet_hours", "start"]),
        "quiet_hours.end": _get_nested(yaml_parsed, ["quiet_hours", "end"]),
        "noise_monitor.enabled": _get_nested(yaml_parsed, ["noise_monitor", "enabled"]),
        "noise_monitor.max_noise_db": _get_nested(yaml_parsed, ["noise_monitor", "max_noise_db"]),
        "break_policy.break_minutes": _get_nested(yaml_parsed, ["break_policy", "break_minutes"]),
    }

    const_names = [
        "QUIET_HOURS_ENABLED",
        "QUIET_HOURS_START",
        "QUIET_HOURS_END",
        "NOISE_MONITOR_ENABLED",
        "MAX_NOISE_DB",
    ]
    code_consts = _parse_python_constants(code_text, const_names)

    pairs = [
        ("quiet_hours.enabled", "QUIET_HOURS_ENABLED"),
        ("quiet_hours.start", "QUIET_HOURS_START"),
        ("quiet_hours.end", "QUIET_HOURS_END"),
        ("noise_monitor.enabled", "NOISE_MONITOR_ENABLED"),
        ("noise_monitor.max_noise_db", "MAX_NOISE_DB"),
    ]
    mismatches = []
    for yk, ck in pairs:
        yv = yaml_fields.get(yk, None)
        cv = code_consts.get(ck, None)
        if yv != cv:
            mismatches.append({
                "key": f"{yk}↔{ck}",
                "yaml_value": yv,
                "code_value": cv,
            })

    sessions: Dict[str, Dict[str, Any]] = {}
    unique_students: set = set()
    all_arrivals: List[float] = []
    dates_set: set = set()
    for r in rows:
        try:
            sid = r["session_id"]
            date = r["date"]
            student = r["student_id"]
            arr = float(r["arrived_minute"])
        except Exception:
            return None
        dates_set.add(date)
        unique_students.add(student)
        all_arrivals.append(arr)
        if sid not in sessions:
            sessions[sid] = {
                "date": date,
                "students": set(),
                "arrivals": [],
            }
        sessions[sid]["students"].add(student)
        sessions[sid]["arrivals"].append(arr)

    def _round2(x: float) -> float:
        return round(x, 2)

    expected_attendance_rows: Dict[str, Dict[str, Any]] = {}
    for sid, info in sessions.items():
        attendees = len(info["students"])
        avg_delay = _round2(sum(info["arrivals"]) / len(info["arrivals"])) if info["arrivals"] else 0.0
        expected_attendance_rows[sid] = {
            "session_id": sid,
            "date": info["date"],
            "attendees": attendees,
            "avg_arrival_delay_minutes": avg_delay,
        }

    total_sessions = len(expected_attendance_rows)
    total_unique_students = len(unique_students)
    overall_avg = _round2(sum(all_arrivals) / len(all_arrivals)) if all_arrivals else 0.0
    earliest = min(dates_set) if dates_set else None
    latest = max(dates_set) if dates_set else None

    return {
        "yaml_fields": yaml_fields,
        "code_consts": code_consts,
        "mismatches": mismatches,
        "expected_attendance_rows": expected_attendance_rows,
        "total_sessions": total_sessions,
        "total_unique_students": total_unique_students,
        "overall_avg": overall_avg,
        "earliest_date": earliest,
        "latest_date": latest,
    }


def _load_artifacts(workspace: Path) -> Dict[str, Any]:
    artifacts: Dict[str, Any] = {}
    artifacts["config_consistency"] = _safe_load_json(workspace / "output" / "config_consistency.json")
    artifacts["attendance_stats_rows"] = _safe_parse_csv_rows(workspace / "output" / "attendance_stats.csv")
    artifacts["overall_stats"] = _safe_load_json(workspace / "output" / "overall_stats.json")
    artifacts["meeting_notes"] = _safe_read_text(workspace / "output" / "meeting_notes.md")
    return artifacts


def _compare_dicts_exact(d1: Dict[str, Any], d2: Dict[str, Any]) -> bool:
    if set(d1.keys()) != set(d2.keys()):
        return False
    for k in d1:
        if d1[k] != d2[k]:
            return False
    return True


def _mismatches_equal(m1: List[Dict[str, Any]], m2: List[Dict[str, Any]]) -> bool:
    def norm_list(lst: List[Dict[str, Any]]) -> List[Tuple[str, Any, Any]]:
        res = []
        for d in lst:
            key = d.get("key")
            yv = d.get("yaml_value")
            cv = d.get("code_value")
            res.append((key, yv, cv))
        return sorted(res, key=lambda x: x[0])
    return norm_list(m1) == norm_list(m2)


def _rows_to_attendance_map(rows: List[Dict[str, str]]) -> Optional[Dict[str, Dict[str, Any]]]:
    required_headers = ["session_id", "date", "attendees", "avg_arrival_delay_minutes"]
    if not rows:
        return None
    first_row = rows[0]
    if list(first_row.keys()) != required_headers:
        return None
    result: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        try:
            sid = r["session_id"]
            date = r["date"]
            attendees = int(r["attendees"])
            avg = float(r["avg_arrival_delay_minutes"])
        except Exception:
            return None
        result[sid] = {
            "session_id": sid,
            "date": date,
            "attendees": attendees,
            "avg_arrival_delay_minutes": round(avg, 2),
        }
    return result


def _find_section_indices(lines: List[str], titles: List[str]) -> Optional[Dict[str, Tuple[int, int]]]:
    indices: Dict[str, Tuple[int, int]] = {}
    last_idx = -1
    found_positions: List[int] = []
    for title in titles:
        found = -1
        for i in range(last_idx + 1, len(lines)):
            s = lines[i].strip()
            s = s.lstrip('#').strip()
            if s.lower() == title.lower():
                found = i
                break
        if found == -1:
            return None
        found_positions.append(found)
        last_idx = found
    for idx, start in enumerate(found_positions):
        if idx < len(found_positions) - 1:
            end = found_positions[idx + 1]
        else:
            end = len(lines)
        indices[titles[idx]] = (start, end)
    return indices


def _section_text(lines: List[str], start: int, end: int) -> str:
    return "\n".join(lines[start + 1:end]).strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_consistency_json_exists_and_valid": 0.0,
        "config_yaml_fields_match_expected": 0.0,
        "config_code_constants_match_expected": 0.0,
        "config_mismatches_match_expected": 0.0,
        "attendance_stats_csv_correct_header_and_rows": 0.0,
        "overall_stats_json_correct_values": 0.0,
        "meeting_notes_sections_order": 0.0,
        "meeting_notes_context_includes_files_and_dates": 0.0,
        "meeting_notes_findings_section_mentions_mismatches": 0.0,
        "meeting_notes_attendance_summary_matches_artifacts": 0.0,
        "meeting_notes_action_items_follow_rules": 0.0,
    }

    expected = _compute_expected_from_inputs(workspace)
    artifacts = _load_artifacts(workspace)

    cc = artifacts["config_consistency"]
    if isinstance(cc, dict) and "yaml" in cc and "code" in cc and "mismatches" in cc and isinstance(cc["yaml"], dict) and isinstance(cc["code"], dict) and isinstance(cc["mismatches"], list):
        scores["config_consistency_json_exists_and_valid"] = 1.0

    if expected is not None and isinstance(cc, dict):
        exp_yaml = expected["yaml_fields"]
        if isinstance(cc.get("yaml"), dict) and _compare_dicts_exact(cc["yaml"], exp_yaml):
            scores["config_yaml_fields_match_expected"] = 1.0
        exp_code = expected["code_consts"]
        if isinstance(cc.get("code"), dict) and _compare_dicts_exact(cc["code"], exp_code):
            scores["config_code_constants_match_expected"] = 1.0
        if isinstance(cc.get("mismatches"), list) and _mismatches_equal(cc["mismatches"], expected["mismatches"]):
            scores["config_mismatches_match_expected"] = 1.0

    attendance_rows = artifacts["attendance_stats_rows"]
    attendance_ok = False
    if isinstance(attendance_rows, list) and len(attendance_rows) > 0:
        att_map = _rows_to_attendance_map(attendance_rows)
        if att_map is not None and expected is not None:
            exp_rows = expected["expected_attendance_rows"]
            if set(att_map.keys()) == set(exp_rows.keys()):
                same = True
                for sid, exp in exp_rows.items():
                    got = att_map[sid]
                    if got["date"] != exp["date"]:
                        same = False
                        break
                    if int(got["attendees"]) != int(exp["attendees"]):
                        same = False
                        break
                    if float(got["avg_arrival_delay_minutes"]) != float(exp["avg_arrival_delay_minutes"]):
                        same = False
                        break
                if same:
                    attendance_ok = True
    scores["attendance_stats_csv_correct_header_and_rows"] = 1.0 if attendance_ok else 0.0

    overall = artifacts["overall_stats"]
    overall_ok = False
    if expected is not None and isinstance(overall, dict):
        if (
            overall.get("total_sessions") == expected["total_sessions"]
            and overall.get("total_unique_students") == expected["total_unique_students"]
            and isinstance(overall.get("overall_avg_arrival_delay_minutes"), (int, float))
            and round(float(overall.get("overall_avg_arrival_delay_minutes")), 2) == float(expected["overall_avg"])
        ):
            overall_ok = True
    scores["overall_stats_json_correct_values"] = 1.0 if overall_ok else 0.0

    notes_text = artifacts["meeting_notes"]
    notes_lines = notes_text.splitlines() if isinstance(notes_text, str) else []
    titles = ["Context", "Config Consistency Findings", "Attendance Statistics Summary", "Action Items"]
    sections = _find_section_indices(notes_lines, titles) if notes_lines else None
    if sections is not None:
        scores["meeting_notes_sections_order"] = 1.0

    context_ok = False
    if sections is not None:
        ctx_start, ctx_end = sections["Context"]
        ctx_text = _section_text(notes_lines, ctx_start, ctx_end)
        if expected is not None:
            earliest = expected["earliest_date"]
            latest = expected["latest_date"]
        else:
            checkins = _safe_parse_csv_rows(workspace / "data" / "checkins.csv")
            if checkins:
                try:
                    dates = {r["date"] for r in checkins if "date" in r}
                    earliest = min(dates) if dates else None
                    latest = max(dates) if dates else None
                except Exception:
                    earliest = None
                    latest = None
            else:
                earliest = None
                latest = None
        if earliest and latest:
            mentions_dates = (earliest in ctx_text) and (latest in ctx_text)
        else:
            mentions_dates = False
        mentions_audit = "audit" in ctx_text.lower()
        mentions_files = all(p in ctx_text for p in ["config/study_space.yaml", "scripts/room_monitor.py", "data/checkins.csv"])
        if mentions_dates and mentions_audit and mentions_files:
            context_ok = True
    scores["meeting_notes_context_includes_files_and_dates"] = 1.0 if context_ok else 0.0

    findings_ok = False
    if sections is not None:
        f_start, f_end = sections["Config Consistency Findings"]
        f_text = _section_text(notes_lines, f_start, f_end)
        f_bullets = [ln.strip() for ln in f_text.splitlines() if ln.strip().startswith(("-", "*"))]
        if isinstance(cc, dict) and isinstance(cc.get("mismatches"), list):
            mismatches = cc["mismatches"]
            if mismatches:
                ok_count = 0
                for m in mismatches:
                    key = m.get("key", "")
                    parts = key.split("↔")
                    if len(parts) == 2:
                        yk, ck = parts[0], parts[1]
                        found = False
                        for bl in f_bullets:
                            if yk in bl and ck in bl:
                                found = True
                                break
                        if found:
                            ok_count += 1
                findings_ok = (ok_count == len(mismatches))
            else:
                findings_ok = ("none" in f_text.lower()) or ("no mismatch" in f_text.lower())
    scores["meeting_notes_findings_section_mentions_mismatches"] = 1.0 if findings_ok else 0.0

    attendance_summary_ok = False
    if sections is not None and isinstance(artifacts.get("overall_stats"), dict) and isinstance(artifacts.get("attendance_stats_rows"), list):
        a_start, a_end = sections["Attendance Statistics Summary"]
        a_text = _section_text(notes_lines, a_start, a_end)
        o = artifacts["overall_stats"]
        att_rows = artifacts["attendance_stats_rows"]
        att_map = _rows_to_attendance_map(att_rows) if isinstance(att_rows, list) else None
        if isinstance(o, dict) and att_map is not None:
            total_sessions_str = str(o.get("total_sessions"))
            total_unique_str = str(o.get("total_unique_students"))
            overall_avg_val = o.get("overall_avg_arrival_delay_minutes")
            try:
                overall_avg_str = f"{float(overall_avg_val):.2f}"
            except Exception:
                overall_avg_str = None
            low_sessions = sorted([sid for sid, rec in att_map.items() if int(rec["attendees"]) < 3])
            lows_present = all(ls in a_text for ls in low_sessions) if low_sessions else True
            nums_present = (total_sessions_str in a_text) and (total_unique_str in a_text) and (overall_avg_str in a_text if overall_avg_str else False)
            attendance_summary_ok = nums_present and lows_present
    scores["meeting_notes_attendance_summary_matches_artifacts"] = 1.0 if attendance_summary_ok else 0.0

    actions_ok = False
    if sections is not None:
        ai_start, ai_end = sections["Action Items"]
        ai_text = _section_text(notes_lines, ai_start, ai_end)
        ai_bullets = [ln.strip()[1:].strip() for ln in ai_text.splitlines() if ln.strip().startswith(("-", "*"))]

        expected_actions: List[str] = []

        if isinstance(cc, dict) and isinstance(cc.get("mismatches"), list):
            for m in cc["mismatches"]:
                key = m.get("key", "")
                parts = key.split("↔")
                if len(parts) == 2:
                    const = parts[1]
                    code_val = m.get("code_value")
                    yaml_val = m.get("yaml_value")
                    expected_actions.append(f"Update scripts/room_monitor.py {const} from {code_val} to {yaml_val} to match config.")

        try:
            yaml_block = cc.get("yaml") if isinstance(cc, dict) else None
            if isinstance(yaml_block, dict):
                bpm = yaml_block.get("break_policy.break_minutes")
                if isinstance(bpm, (int, float)) and bpm < 5:
                    expected_actions.append("Update config/study_space.yaml break_policy.break_minutes to 5 to ensure sufficient breaks.")
        except Exception:
            pass

        try:
            if isinstance(yaml_block, dict):
                qh_enabled = yaml_block.get("quiet_hours.enabled")
                max_db = yaml_block.get("noise_monitor.max_noise_db")
                if bool(qh_enabled) and isinstance(max_db, (int, float)) and max_db > 45:
                    expected_actions.append("Reduce config/study_space.yaml noise_monitor.max_noise_db to 45 for quieter study hours.")
        except Exception:
            pass

        low_list: List[str] = []
        if isinstance(artifacts.get("attendance_stats_rows"), list):
            att_map2 = _rows_to_attendance_map(artifacts["attendance_stats_rows"])  # type: ignore
            if att_map2 is not None:
                low_list = sorted([sid for sid, rec in att_map2.items() if int(rec["attendees"]) < 3])
                if len(low_list) > 0:
                    expected_actions.append(f"Consider consolidating low-attendance sessions: {','.join(low_list)}.")

        if isinstance(artifacts.get("overall_stats"), dict):
            try:
                avg_val = float(artifacts["overall_stats"].get("overall_avg_arrival_delay_minutes"))  # type: ignore
                if avg_val > 5.00:
                    expected_actions.append("Send a reminder encouraging on-time arrivals (aim for ≤5 minutes average delay).")
            except Exception:
                pass

        def normalize(s: str) -> str:
            return " ".join(s.strip().split())

        ai_norm = [normalize(s) for s in ai_bullets]
        exp_norm = [normalize(s) for s in expected_actions]

        def bullet_matches_expected(bullet: str, expected_str: str) -> bool:
            if expected_str.startswith("Update scripts/room_monitor.py "):
                m = re.match(r"Update scripts/room_monitor.py ([A-Z0-9_]+) from (.+) to (.+) to match config\.", expected_str)
                if m:
                    const, code_v, yaml_v = m.groups()
                    return ("Update scripts/room_monitor.py" in bullet
                            and const in bullet
                            and "from" in bullet
                            and str(code_v).strip().strip('"').strip("'") in bullet.replace('"', '').replace("'", "")
                            and "to" in bullet
                            and str(yaml_v).strip().strip('"').strip("'") in bullet.replace('"', '').replace("'", "")
                            and "match config" in bullet)
            return normalize(bullet) == normalize(expected_str)

        if len(ai_norm) == len(exp_norm) and all(any(bullet_matches_expected(b, e) for b in ai_bullets) for e in expected_actions):
            unmatched_indices = set(range(len(ai_bullets)))
            for e in expected_actions:
                found_idx = None
                for idx in list(unmatched_indices):
                    if bullet_matches_expected(ai_bullets[idx], e):
                        found_idx = idx
                        break
                if found_idx is not None:
                    unmatched_indices.discard(found_idx)
            actions_ok = (len(unmatched_indices) == 0)
    scores["meeting_notes_action_items_follow_rules"] = 1.0 if actions_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()