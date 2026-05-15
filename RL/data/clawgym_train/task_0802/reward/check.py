import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta


# -----------------------------
# Helper functions
# -----------------------------

def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _safe_load_csv_dict_by_key(path: Path, key_field: str):
    rows = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = row.get(key_field)
                if key is None:
                    return None
                rows[key] = row
        return rows
    except Exception:
        return None

def _parse_focus_areas(raw: str):
    # Split by |, strip whitespace and surrounding quotes
    items = []
    for part in raw.split("|"):
        part = part.strip()
        if part.startswith('"') and part.endswith('"') and len(part) >= 2:
            part = part[1:-1]
        if part.startswith("'") and part.endswith("'") and len(part) >= 2:
            part = part[1:-1]
        items.append(part)
    # Remove empties
    return [x for x in items if x]

def _parse_yaml_availability(path: Path):
    """
    Minimal YAML parser tailored to the provided availability.yaml structure.
    Supports:
      - top-level keys: week_start, self, partner
      - under self/partner: day keys Mon..Sun mapping to list of "HH:MM-HH:MM" strings
      - partner also has 'name'
      - lists in square brackets with quoted strings or bare strings
      - empty lists as []
    Returns dict or None on failure.
    """
    text = _safe_read_text(path)
    if not text:
        return None
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip() != "" and not ln.strip().startswith("#")]
    data = {"self": {}, "partner": {}}
    current_section = None
    try:
        for ln in lines:
            indent = len(ln) - len(ln.lstrip(" "))
            stripped = ln.strip()
            if indent == 0:
                if ":" in stripped:
                    key, val = [x.strip() for x in stripped.split(":", 1)]
                    if key == "week_start":
                        data["week_start"] = val
                    elif key == "self":
                        current_section = "self"
                    elif key == "partner":
                        current_section = "partner"
                    else:
                        # unexpected top-level key is ignored
                        current_section = None
                else:
                    current_section = None
            elif indent == 2 and current_section in ("self", "partner"):
                if ":" not in stripped:
                    continue
                key, val = [x.strip() for x in stripped.split(":", 1)]
                if key == "name":
                    data[current_section]["name"] = val.strip('"').strip("'")
                else:
                    # Expect list like ["17:00-19:00", "20:00-21:00"] or []
                    vals = []
                    if val.startswith("[") and val.endswith("]"):
                        inner = val[1:-1].strip()
                        if inner:
                            parts = []
                            curr = ""
                            in_quotes = False
                            quote_char = ""
                            for ch in inner:
                                if in_quotes:
                                    if ch == quote_char:
                                        in_quotes = False
                                        curr += ch
                                    else:
                                        curr += ch
                                else:
                                    if ch in ("'", '"'):
                                        in_quotes = True
                                        quote_char = ch
                                        curr += ch
                                    elif ch == ",":
                                        parts.append(curr.strip())
                                        curr = ""
                                    else:
                                        curr += ch
                            if curr.strip():
                                parts.append(curr.strip())
                            for p in parts:
                                p = p.strip()
                                if p.startswith('"') and p.endswith('"') and len(p) >= 2:
                                    p = p[1:-1]
                                if p.startswith("'") and p.endswith("'") and len(p) >= 2:
                                    p = p[1:-1]
                                vals.append(p)
                        else:
                            vals = []
                    else:
                        vals = []
                    data[current_section][key] = vals
            else:
                # deeper indentation not expected; ignore
                continue
        # basic validation
        if "week_start" not in data:
            return None
        return data
    except Exception:
        return None

def _parse_hhmm(s: str):
    try:
        m = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", s)
        if not m:
            return None
        h = int(m.group(1))
        mi = int(m.group(2))
        return h * 60 + mi
    except Exception:
        return None

def _minutes_to_hhmm(m: int) -> str:
    h = m // 60
    mi = m % 60
    return f"{h:02d}:{mi:02d}"

def _interval_within_any(start: int, end: int, blocks: list[tuple[int, int]]) -> bool:
    for bstart, bend in blocks:
        if start >= bstart and end <= bend:
            return True
    return False

def _compute_overlaps(blocks_a: list[tuple[int, int]], blocks_b: list[tuple[int, int]]) -> list[tuple[int, int]]:
    overlaps = []
    for a0, a1 in blocks_a:
        for b0, b1 in blocks_b:
            s = max(a0, b0)
            e = min(a1, b1)
            if e > s:
                overlaps.append((s, e))
    return overlaps

def _day_name_from_date(d: datetime.date) -> str:
    # Monday is 0
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return names[d.weekday()]

def _date_from_str(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _load_inputs(workspace: Path):
    pieces_path = workspace / "input" / "pieces.csv"
    log_path = workspace / "input" / "last_week_log.csv"
    avail_path = workspace / "input" / "availability.yaml"

    pieces_rows = _safe_load_csv_dict_by_key(pieces_path, "piece_id")
    log_rows = _safe_load_csv_dict_by_key(log_path, "piece_id")
    avail = _parse_yaml_availability(avail_path)

    return pieces_rows, log_rows, avail

def _prepare_pieces(pieces_rows: dict):
    if pieces_rows is None:
        return None
    pieces = {}
    for pid, row in pieces_rows.items():
        try:
            pieces[pid] = {
                "piece_id": pid,
                "title": row.get("title", ""),
                "composer": row.get("composer", ""),
                "type": row.get("type", ""),
                "difficulty": int(row.get("difficulty", "0") or 0),
                "target_tempo_bpm": int(row.get("target_tempo_bpm", "0") or 0),
                "focus_areas": _parse_focus_areas(row.get("focus_areas", "") or ""),
            }
        except Exception:
            return None
    return pieces

def _prepare_log(log_rows: dict):
    if log_rows is None:
        return None
    logs = {}
    for pid, row in log_rows.items():
        try:
            logs[pid] = {
                "piece_id": pid,
                "total_minutes": int(row.get("total_minutes", "0") or 0),
                "avg_tempo_bpm": int(row.get("avg_tempo_bpm", "0") or 0),
            }
        except Exception:
            return None
    return logs

def _availability_to_blocks(avail: dict):
    if avail is None:
        return None
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    self_blocks = {}
    partner_blocks = {}
    for d in days:
        s_list = []
        for s in avail.get("self", {}).get(d, []) or []:
            try:
                s_start, s_end = s.split("-", 1)
                s0 = _parse_hhmm(s_start.strip())
                s1 = _parse_hhmm(s_end.strip())
                if s0 is None or s1 is None or s1 <= s0:
                    return None
                s_list.append((s0, s1))
            except Exception:
                return None
        self_blocks[d] = s_list
        p_list = []
        for p in avail.get("partner", {}).get(d, []) or []:
            try:
                p_start, p_end = p.split("-", 1)
                p0 = _parse_hhmm(p_start.strip())
                p1 = _parse_hhmm(p_end.strip())
                if p0 is None or p1 is None or p1 <= p0:
                    return None
                p_list.append((p0, p1))
            except Exception:
                return None
        partner_blocks[d] = p_list
    partner_name = avail.get("partner", {}).get("name", "")
    return {"self": self_blocks, "partner": partner_blocks, "partner_name": partner_name, "week_start": avail.get("week_start")}

def _daily_targets():
    return {"Mon": 90, "Tue": 90, "Wed": 90, "Thu": 90, "Fri": 90, "Sat": 120, "Sun": 120}

def _collect_plan_sessions(plan):
    # Validate basic schema and return normalized sessions with computed minutes
    req_fields = {"date", "day", "start", "end", "piece_id", "type", "focus_areas"}
    normalized = []
    for idx, s in enumerate(plan):
        if not isinstance(s, dict):
            return None, f"session_{idx}_not_dict"
        if not req_fields.issubset(s.keys()):
            return None, f"session_{idx}_missing_fields"
        date = s.get("date")
        day = s.get("day")
        start = s.get("start")
        end = s.get("end")
        pid = s.get("piece_id")
        stype = s.get("type")
        foc = s.get("focus_areas")
        # Validate types
        if not isinstance(date, str) or not isinstance(day, str) or not isinstance(start, str) or not isinstance(end, str) or not isinstance(pid, str) or not isinstance(stype, str) or not isinstance(foc, list):
            return None, f"session_{idx}_field_types_invalid"
        d = _date_from_str(date)
        if d is None:
            return None, f"session_{idx}_bad_date"
        if day not in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            return None, f"session_{idx}_bad_day"
        t0 = _parse_hhmm(start)
        t1 = _parse_hhmm(end)
        if t0 is None or t1 is None or t1 <= t0:
            return None, f"session_{idx}_bad_time_interval"
        duration = t1 - t0
        normalized.append({
            "date": date,
            "date_obj": d,
            "day": day,
            "start": start,
            "end": end,
            "start_min": t0,
            "end_min": t1,
            "duration": duration,
            "piece_id": pid,
            "type": stype,
            "focus_areas": foc,
            "index": idx
        })
    return normalized, None

def _sum_minutes_by_day(sessions: list):
    per_day = {}
    for s in sessions:
        per_day.setdefault(s["day"], 0)
        per_day[s["day"]] += s["duration"]
    return per_day

def _sum_minutes_by_piece(sessions: list):
    per_piece = {}
    for s in sessions:
        pid = s["piece_id"]
        per_piece.setdefault(pid, 0)
        per_piece[pid] += s["duration"]
    return per_piece

def _find_lines(text: str):
    return text.splitlines()

def _line_contains_all(line: str, parts: list[str]) -> bool:
    line_low = line.lower()
    return all(p.lower() in line_low for p in parts)

# -----------------------------
# Grader
# -----------------------------

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "generator_script_present": 0.0,
        "plan_file_valid_json_and_schema": 0.0,
        "plan_dates_and_days_valid": 0.0,
        "sessions_within_availability": 0.0,
        "daily_targets_and_session_length_valid": 0.0,
        "technique_time_requirements_met": 0.0,
        "session_type_consistency": 0.0,
        "focus_areas_valid": 0.0,
        "per_piece_minimums_met": 0.0,
        "duet_piece_session_requirements_met": 0.0,
        "status_summary_exists": 0.0,
        "report_daily_minutes_summary_present": 0.0,
        "report_per_piece_progress_included": 0.0,
        "report_lists_duet_sessions": 0.0,
        "report_technique_percentage_statement": 0.0,
        "report_prioritization_explanation_present": 0.0,
    }

    # Check generator script exists
    gen_script = workspace / "scripts" / "generate_practice.py"
    if gen_script.exists() and gen_script.is_file():
        scores["generator_script_present"] = 1.0

    # Load inputs
    pieces_rows, log_rows, avail_yaml = _load_inputs(workspace)
    pieces = _prepare_pieces(pieces_rows) if pieces_rows is not None else None
    logs = _prepare_log(log_rows) if log_rows is not None else None
    avail_blocks = _availability_to_blocks(avail_yaml) if avail_yaml is not None else None

    # Load plan
    plan_path = workspace / "output" / "weekly_plan.json"
    plan = _safe_load_json(plan_path)

    if isinstance(plan, list):
        sessions, err = _collect_plan_sessions(plan)
        if sessions is not None:
            # Basic schema ok
            scores["plan_file_valid_json_and_schema"] = 1.0

            # Validate date range and days: 7 consecutive days starting from week_start
            if avail_blocks is not None and "week_start" in avail_blocks and avail_blocks["week_start"]:
                ws_date = _date_from_str(avail_blocks["week_start"])
                if ws_date is not None:
                    expected_dates = [ws_date + timedelta(days=i) for i in range(7)]
                    expected_dates_str = set(d.strftime("%Y-%m-%d") for d in expected_dates)
                    expected_day_names = [_day_name_from_date(d) for d in expected_dates]
                    # All sessions must be within expected dates and day aligned
                    dates_ok = True
                    for s in sessions:
                        if s["date"] not in expected_dates_str:
                            dates_ok = False
                            break
                        if _day_name_from_date(s["date_obj"]) != s["day"]:
                            dates_ok = False
                            break
                    # Ensure all days are present (at least zero? must meet targets, so there should be sessions)
                    present_dates = set(s["date"] for s in sessions)
                    if present_dates == expected_dates_str and dates_ok:
                        scores["plan_dates_and_days_valid"] = 1.0

            # Validate within availability and duet overlaps
            within_ok = False
            if avail_blocks is not None:
                within_ok = True
                for s in sessions:
                    day = s["day"]
                    st = s["start_min"]
                    en = s["end_min"]
                    self_blocks = avail_blocks["self"].get(day, [])
                    if s["type"] == "duet":
                        partner_blocks = avail_blocks["partner"].get(day, [])
                        overlaps = _compute_overlaps(self_blocks, partner_blocks)
                        if not _interval_within_any(st, en, overlaps):
                            within_ok = False
                            break
                    else:
                        if not _interval_within_any(st, en, self_blocks):
                            within_ok = False
                            break
            if within_ok:
                scores["sessions_within_availability"] = 1.0

            # Daily targets and session duration <= 60
            daily_ok = True
            # Check each session duration <= 60
            for s in sessions:
                if s["duration"] > 60:
                    daily_ok = False
                    break
            if daily_ok:
                per_day = _sum_minutes_by_day(sessions)
                targets = _daily_targets()
                # Must have exactly those 7 keys
                # We'll assert each day sum equals target exactly
                for day, target in targets.items():
                    if per_day.get(day, 0) != target:
                        daily_ok = False
                        break
                # Also ensure no extra days included
                if daily_ok:
                    for day_key in per_day.keys():
                        if day_key not in targets:
                            daily_ok = False
                            break
            if daily_ok:
                scores["daily_targets_and_session_length_valid"] = 1.0

            # Technique time >= 20% and present on >= 5 days
            total_minutes = sum(s["duration"] for s in sessions)
            tech_minutes = sum(s["duration"] for s in sessions if s["type"] == "technique")
            tech_days = set(s["day"] for s in sessions if s["type"] == "technique")
            tech_ok = False
            if total_minutes > 0:
                tech_pct = tech_minutes / total_minutes
                if tech_pct >= 0.20 and len(tech_days) >= 5:
                    tech_ok = True
            if tech_ok:
                scores["technique_time_requirements_met"] = 1.0

            # Session type consistency with pieces.csv, focus areas valid
            stype_ok = False
            focus_ok = False
            if pieces is not None:
                stype_ok = True
                focus_ok = True
                for s in sessions:
                    pid = s["piece_id"]
                    piece = pieces.get(pid)
                    if piece is None:
                        stype_ok = False
                        focus_ok = False
                        break
                    # Session 'type' must match piece 'type'
                    if s["type"] != piece["type"]:
                        stype_ok = False
                    # focus_areas must be a non-empty list and subset of piece's focus areas
                    if not isinstance(s["focus_areas"], list) or len(s["focus_areas"]) == 0:
                        focus_ok = False
                    else:
                        for fa in s["focus_areas"]:
                            if not isinstance(fa, str) or fa not in piece["focus_areas"]:
                                focus_ok = False
                                break
                    if not stype_ok or not focus_ok:
                        break
            if stype_ok:
                scores["session_type_consistency"] = 1.0
            if focus_ok:
                scores["focus_areas_valid"] = 1.0

            # Per-piece minimums based on last week
            ppm_ok = False
            if pieces is not None and logs is not None:
                per_piece_minutes = _sum_minutes_by_piece(sessions)
                ppm_ok = True
                for pid, piece in pieces.items():
                    log = logs.get(pid)
                    if log is None:
                        ppm_ok = False
                        break
                    avg = log["avg_tempo_bpm"]
                    target = piece["target_tempo_bpm"]
                    threshold = 60 if avg < target else 30
                    if per_piece_minutes.get(pid, 0) < threshold:
                        ppm_ok = False
                        break
            if ppm_ok:
                scores["per_piece_minimums_met"] = 1.0

            # Each duet piece has at least two separate sessions of at least 30 minutes
            duet_ok = False
            if pieces is not None:
                duet_ok = True
                duet_piece_ids = [pid for pid, p in pieces.items() if p["type"] == "duet"]
                for dp in duet_piece_ids:
                    qualifying = [s for s in sessions if s["piece_id"] == dp and s["duration"] >= 30]
                    if len(qualifying) < 2:
                        duet_ok = False
                        break
            if duet_ok:
                scores["duet_piece_session_requirements_met"] = 1.0

        else:
            # malformed plan list
            pass

    # Status summary checks
    report_path = workspace / "output" / "status_summary.md"
    report_text = _safe_read_text(report_path)
    if report_text:
        scores["status_summary_exists"] = 1.0

    # Further report checks only if we have plan and report
    if scores["plan_file_valid_json_and_schema"] == 1.0 and scores["status_summary_exists"] == 1.0:
        # Daily minutes summary present: for each day, a line containing day token and the total minutes number
        report_lines = _find_lines(report_text)
        report_daily_ok = True
        targets = _daily_targets()
        # Compute per-day scheduled minutes
        per_day_minutes = {}
        if isinstance(plan, list):
            sessions, _ = _collect_plan_sessions(plan)
            if sessions is not None:
                per_day_minutes = _sum_minutes_by_day(sessions)
        # For each day, find a line containing the day token and its total minutes number
        for day, mins in targets.items():
            # default to computed minutes if available
            day_total = per_day_minutes.get(day, None)
            if day_total is None:
                report_daily_ok = False
                break
            found_for_day = False
            for line in report_lines:
                if re.search(rf"\b{day}\b", line):
                    if re.search(rf"\b{day_total}\b", line):
                        found_for_day = True
                        break
            if not found_for_day:
                report_daily_ok = False
                break
        if report_daily_ok:
            scores["report_daily_minutes_summary_present"] = 1.0

        # Per-piece progress included: For each piece, find a segment near piece_id that mentions last_week total_minutes, avg_tempo_bpm, this week's allocated minutes, and target_tempo_bpm
        per_piece_ok = False
        if pieces is not None and logs is not None and isinstance(plan, list):
            sessions, _ = _collect_plan_sessions(plan)
            if sessions is not None:
                per_piece_minutes = _sum_minutes_by_piece(sessions)
                text = report_text
                all_ok = True
                for pid, piece in pieces.items():
                    # Skip if piece not scheduled? The constraints imply minimums, so it should be scheduled.
                    allocated = per_piece_minutes.get(pid, 0)
                    last = logs.get(pid, {"total_minutes": 0, "avg_tempo_bpm": 0})
                    last_minutes = last["total_minutes"]
                    last_avg = last["avg_tempo_bpm"]
                    target_bpm = piece["target_tempo_bpm"]
                    # Find occurrence window around pid
                    idx = text.find(pid)
                    if idx == -1:
                        all_ok = False
                        break
                    start = max(0, idx - 200)
                    end = min(len(text), idx + 200)
                    window = text[start:end]
                    # Check that numbers appear in window
                    # Allow numeric presence even without labels
                    needed = [str(last_minutes), str(last_avg), str(allocated), str(target_bpm)]
                    if not all(n in window for n in needed):
                        all_ok = False
                        break
                if all_ok:
                    per_piece_ok = True
        if per_piece_ok:
            scores["report_per_piece_progress_included"] = 1.0

        # Report lists duet sessions with Alex (date and time windows)
        duet_list_ok = False
        if isinstance(plan, list):
            sessions, _ = _collect_plan_sessions(plan)
            if sessions is not None:
                duet_sessions = [s for s in sessions if s["type"] == "duet"]
                text = report_text
                # Require 'Alex' mention
                if "alex" in text.lower():
                    all_listed = True
                    for s in duet_sessions:
                        date = s["date"]
                        window = f"{s['start']}-{s['end']}"
                        # Look for both date and time window on the same or adjacent lines
                        found = False
                        for i, line in enumerate(report_lines):
                            if date in line and window in line:
                                found = True
                                break
                            if date in line:
                                # check next line if present
                                if i + 1 < len(report_lines) and window in report_lines[i + 1]:
                                    found = True
                                    break
                        if not found:
                            all_listed = False
                            break
                    if all_listed:
                        duet_list_ok = True
        if duet_list_ok:
            scores["report_lists_duet_sessions"] = 1.0

        # Report states technique percent and verifies requirement
        tech_pct_ok = False
        if isinstance(plan, list):
            sessions, _ = _collect_plan_sessions(plan)
            if sessions is not None:
                total = sum(s["duration"] for s in sessions)
                tech = sum(s["duration"] for s in sessions if s["type"] == "technique")
                if total > 0:
                    pct = 100.0 * tech / total
                    # Find a line containing 'technique' and a percentage close to pct, and some indication of meeting requirement
                    for line in report_lines:
                        if "technique" in line.lower():
                            # Find percentages in the line
                            matches = re.findall(r"(\d+(?:\.\d+)?)\s*%", line)
                            ok_num = False
                            for m in matches:
                                try:
                                    val = float(m)
                                    if abs(val - pct) <= 0.5 or abs(val - round(pct)) <= 0.5:
                                        ok_num = True
                                        break
                                except Exception:
                                    pass
                            if ok_num:
                                # Check mention of requirement
                                if any(k in line.lower() for k in ["meet", "meets", "satisf", ">= 20", "at least 20"]):
                                    tech_pct_ok = True
                                    break
        if tech_pct_ok:
            scores["report_technique_percentage_statement"] = 1.0

        # Report explains prioritization: mentions pieces below target tempo and balancing technique vs repertoire
        # Require presence of "tempo" and ("below target" or "under target") and "technique" and "repertoire"
        text_low = report_text.lower()
        if ("tempo" in text_low) and (("below target" in text_low) or ("under target" in text_low) or ("below the target" in text_low)) and ("technique" in text_low) and ("repertoire" in text_low):
            scores["report_prioritization_explanation_present"] = 1.0

    return scores


# -----------------------------
# CLI entrypoint
# -----------------------------

def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()