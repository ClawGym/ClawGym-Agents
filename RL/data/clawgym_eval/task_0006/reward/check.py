import json
import csv
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timedelta


WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None


def _parse_simple_yaml(path: Path):
    # Very simple YAML parser for key: "value" pairs on single lines
    text = _read_text_safe(path)
    if text is None:
        return None
    data = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Remove surrounding quotes if present
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        data[key] = val
    return data


def _parse_iso_z(dt_str: str):
    # Parses YYYY-MM-DDTHH:MM:SSZ into naive datetime in UTC
    try:
        s = dt_str.strip()
        if not s.endswith("Z"):
            return None
        s2 = s[:-1]
        # Allow seconds optional; but spec includes seconds
        # Try with seconds first
        try:
            return datetime.fromisoformat(s2)
        except ValueError:
            # Try adding seconds if missing
            try:
                return datetime.fromisoformat(s2 + ":00")
            except Exception:
                return None
    except Exception:
        return None


def _isoformat_z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _weekday_name(dt: datetime) -> str:
    return WEEKDAY_NAMES[dt.weekday()]


def _compute_slot_analysis(members: list, calls: list):
    # returns dict keyed by (weekday_idx, weekday_name, hour) -> dict with calls_count and avg_attendance
    member_emails = {m.get("email") for m in members if isinstance(m, dict) and m.get("email")}
    groups = {}
    for row in calls:
        start = row.get("start_utc")
        attendees_field = row.get("attendees_emails", "")
        dt = _parse_iso_z(start) if isinstance(start, str) else None
        if dt is None:
            return None  # malformed data; fail the whole check
        # filter attendees by members.json
        attendees_raw = [a.strip() for a in attendees_field.split(";")] if isinstance(attendees_field, str) else []
        attendees = [a for a in attendees_raw if a in member_emails]
        weekday_idx = dt.weekday()
        weekday = WEEKDAY_NAMES[weekday_idx]
        hour = dt.hour
        key = (weekday_idx, weekday, hour)
        if key not in groups:
            groups[key] = []
        groups[key].append(len(attendees))
    result = {}
    for key, counts in groups.items():
        calls_count = len(counts)
        avg_attendance = sum(counts) / calls_count if calls_count > 0 else 0.0
        result[key] = {"calls_count": calls_count, "avg_attendance": avg_attendance}
    return result


def _pick_best_slot(slot_analysis: dict):
    # slot_analysis keys: (weekday_idx, weekday_name, hour) -> {calls_count, avg_attendance}
    if not slot_analysis:
        return None
    # Sort by -avg_attendance, -calls_count, weekday_idx ascending, hour ascending
    items = []
    for key, stats in slot_analysis.items():
        weekday_idx, weekday_name, hour = key
        calls_count = stats["calls_count"]
        avg_attendance = stats["avg_attendance"]
        items.append((-(avg_attendance), -(calls_count), weekday_idx, hour, key))
    items.sort()
    best_key = items[0][4]
    return best_key  # (weekday_idx, weekday_name, hour)


def _next_occurrence_after(reference_dt: datetime, target_weekday_idx: int, target_hour: int) -> datetime:
    # Compute next datetime strictly after reference_dt with weekday=target and hour=target_hour, minute=0, second=0
    # Calculate days ahead to the target weekday
    ref_weekday = reference_dt.weekday()
    days_ahead = (target_weekday_idx - ref_weekday) % 7
    candidate_date = (reference_dt.date() + timedelta(days=days_ahead))
    candidate_dt = datetime(candidate_date.year, candidate_date.month, candidate_date.day, target_hour, 0, 0)
    if candidate_dt <= reference_dt:
        candidate_dt = candidate_dt + timedelta(days=7)
    return candidate_dt


def _format_utc_offset_signed(offset_hours: float) -> str:
    # Convert offset hours to +HH:MM or -HH:MM
    total_minutes = int(round(offset_hours * 60))
    sign = "+" if total_minutes >= 0 else "-"
    abs_minutes = abs(total_minutes)
    hh = abs_minutes // 60
    mm = abs_minutes % 60
    return f"{sign}{hh:02d}:{mm:02d}"


def _apply_template(template: str, replacements: dict) -> str:
    # Simple placeholder replacement
    out = template
    for k, v in replacements.items():
        out = out.replace("{" + k + "}", v)
    return out


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_runs": 0.0,
        "slot_analysis_header_correct": 0.0,
        "slot_analysis_rows_correct": 0.0,
        "avg_attendance_decimal_precision": 0.0,
        "next_call_utc_correct": 0.0,
        "invites_files_present": 0.0,
        "invites_content_correct": 0.0,
    }

    # Attempt to run the user's script
    cmd = [
        sys.executable,
        "plan_next_call.py",
        "--members", "input/members.json",
        "--calls", "input/past_calls.csv",
        "--config", "input/config.yaml",
        "--template", "input/invite_template.txt",
        "--outdir", "output",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )
        if proc.returncode == 0:
            scores["script_runs"] = 1.0
    except Exception:
        # If execution fails, leave script_runs at 0.0
        pass

    # Load inputs for expected computations
    members_path = workspace / "input" / "members.json"
    calls_path = workspace / "input" / "past_calls.csv"
    config_path = workspace / "input" / "config.yaml"
    template_path = workspace / "input" / "invite_template.txt"

    members = _load_json_safe(members_path)
    calls = _load_csv_safe(calls_path)
    config = _parse_simple_yaml(config_path)
    template_text = _read_text_safe(template_path)

    expected_slot_analysis = None
    expected_best_slot = None
    expected_next_iso = None
    expected_next_dt = None

    if members is not None and calls is not None and config is not None and template_text is not None:
        expected_slot_analysis = _compute_slot_analysis(members, calls)
        if expected_slot_analysis is not None and expected_slot_analysis:
            expected_best_slot = _pick_best_slot(expected_slot_analysis)
            # Compute next occurrence strictly after reference timestamp
            ref_str = config.get("reference_date_utc")
            ref_dt = _parse_iso_z(ref_str) if isinstance(ref_str, str) else None
            if ref_dt is not None and expected_best_slot is not None:
                weekday_idx, weekday_name, hour = expected_best_slot
                next_dt = _next_occurrence_after(ref_dt, weekday_idx, hour)
                expected_next_dt = next_dt
                expected_next_iso = _isoformat_z(next_dt)

    # Validate slot_analysis.csv
    slot_analysis_path = workspace / "output" / "slot_analysis.csv"
    if slot_analysis_path.exists() and expected_slot_analysis is not None:
        try:
            with slot_analysis_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                if header == ["weekday", "hour_utc", "calls_count", "avg_attendance"]:
                    scores["slot_analysis_header_correct"] = 1.0
                # Parse rows into mapping
                actual_map = {}
                avg_field_strings = []
                for r in rows[1:]:
                    if len(r) != 4:
                        actual_map = None
                        break
                    weekday, hour_s, calls_count_s, avg_att_s = r
                    try:
                        hour = int(hour_s)
                        calls_count = int(calls_count_s)
                        avg_val = float(avg_att_s)
                        avg_field_strings.append(avg_att_s)
                    except Exception:
                        actual_map = None
                        break
                    if weekday not in WEEKDAY_NAMES:
                        actual_map = None
                        break
                    key = (WEEKDAY_NAMES.index(weekday), weekday, hour)
                    actual_map[key] = (calls_count, avg_val, avg_att_s)
                if actual_map is not None:
                    # Build expected map for comparison
                    expected_map = {}
                    for key, stats in expected_slot_analysis.items():
                        expected_map[key] = (stats["calls_count"], float(stats["avg_attendance"]))
                    # Compare keys
                    if set(actual_map.keys()) == set(expected_map.keys()):
                        # Compare numeric values for each key
                        ok = True
                        for key in expected_map:
                            exp_calls, exp_avg = expected_map[key]
                            act_calls, act_avg, act_avg_str = actual_map[key]
                            if act_calls != exp_calls:
                                ok = False
                                break
                            # Compare float exactly; since we built exp_avg from same arithmetic, it should match parse
                            # Allow a tiny tolerance to avoid float quirks
                            if abs(act_avg - exp_avg) > 1e-9:
                                ok = False
                                break
                        if ok:
                            scores["slot_analysis_rows_correct"] = 1.0
                    # Check decimal precision: ensure every avg_attendance string has a decimal point
                    if actual_map is not None:
                        has_decimal_all = True
                        for key in actual_map:
                            avg_str = actual_map[key][2]
                            if "." not in avg_str:
                                has_decimal_all = False
                                break
                        scores["avg_attendance_decimal_precision"] = 1.0 if has_decimal_all else 0.0
        except Exception:
            pass

    # Validate next_call_utc.txt
    next_call_path = workspace / "output" / "next_call_utc.txt"
    if expected_next_iso is not None and next_call_path.exists():
        content = _read_text_safe(next_call_path)
        if content is not None:
            line = content.strip()
            if line == expected_next_iso:
                scores["next_call_utc_correct"] = 1.0

    # Validate invites files presence and content
    invites_dir = workspace / "output" / "invites"
    expected_invite_filenames = set()
    if members is not None:
        for m in members:
            if isinstance(m, dict) and m.get("email"):
                expected_invite_filenames.add(f"{m['email']}.txt")

    if invites_dir.exists() and invites_dir.is_dir() and expected_invite_filenames:
        actual_files = {p.name for p in invites_dir.glob("*.txt")}
        if actual_files == expected_invite_filenames:
            scores["invites_files_present"] = 1.0

    # Validate invites content
    if expected_next_dt is not None and template_text is not None and invites_dir.exists() and expected_invite_filenames:
        correct_count = 0
        total = len(expected_invite_filenames)
        for m in members:
            name = m.get("name")
            email = m.get("email")
            offset = m.get("utc_offset_hours")
            if not isinstance(name, str) or not isinstance(email, str):
                continue
            try:
                offset_hours = float(offset)
            except Exception:
                continue
            total_minutes = int(round(offset_hours * 60))
            local_dt = expected_next_dt + timedelta(minutes=total_minutes)
            local_str = local_dt.strftime("%Y-%m-%d %H:%M")
            offset_signed = _format_utc_offset_signed(offset_hours)
            meeting_title = config.get("meeting_title", "")
            video_link = config.get("video_link", "")
            replacements = {
                "name": name,
                "meeting_title": meeting_title,
                "video_link": video_link,
                "local_datetime": local_str,
                "utc_offset_signed": offset_signed,
            }
            expected_invite = _apply_template(template_text, replacements)
            invite_path = invites_dir / f"{email}.txt"
            actual_invite = _read_text_safe(invite_path)
            if actual_invite is None:
                continue
            # Normalize newlines for comparison
            exp_norm = expected_invite.replace("\r\n", "\n").replace("\r", "\n")
            act_norm = actual_invite.replace("\r\n", "\n").replace("\r", "\n")
            if exp_norm == act_norm:
                correct_count += 1
        if total > 0:
            scores["invites_content_correct"] = float(correct_count) / float(total)

    return scores


def main() -> None:
    import json as _json
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(_json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()