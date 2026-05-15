import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta


def _safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_time_hhmm(s: str):
    if not isinstance(s, str):
        return None
    if not re.fullmatch(r"\d{2}:\d{2}", s):
        return None
    try:
        dt = datetime.strptime(s, "%H:%M")
        return dt.hour * 60 + dt.minute
    except Exception:
        return None


def _fmt_minutes(m: int) -> str:
    h = (m // 60) % 24
    mi = m % 60
    return f"{h:02d}:{mi:02d}"


def _read_schedule_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = list(reader)
        return header, rows
    except Exception:
        return None, None


def _duration_minutes(start_str: str, end_str: str):
    s = _parse_time_hhmm(start_str)
    e = _parse_time_hhmm(end_str)
    if s is None or e is None:
        return None
    d = e - s
    if d < 0:
        return None
    return d


def _index_by(rows, key):
    d = {}
    for r in rows:
        k = r.get(key)
        if k in d:
            d[k].append(r)
        else:
            d[k] = [r]
    return d


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "config_micro_break_section_present": 0.0,
        "config_micro_break_values_correct": 0.0,
        "schedule_csv_columns_correct": 0.0,
        "schedule_date_and_time_format_correct": 0.0,
        "task_ids_unique": 0.0,
        "non_break_task_ids_from_config": 0.0,
        "within_kitchen_hours_all": 0.0,
        "within_staff_availability_all": 0.0,
        "non_break_tasks_within_preferred_window": 0.0,
        "no_overlap_same_staff": 0.0,
        "break_rows_valid": 0.0,
        "break_policy_enforced_or_reported": 0.0,
        "validation_report_structure_and_totals": 0.0,
        "validation_report_violation_counts_match": 0.0,
        "scheduler_py_updated": 0.0,
        "messages_final_three_lines": 0.0,
        "messages_line2_preserves_details": 0.0,
        "messages_line3_preserves_policy_numbers": 0.0,
    }

    # Load config and staff
    cfg_path = workspace / "config" / "schedule.json"
    staff_path = workspace / "data" / "staff.json"
    cfg = _safe_load_json(cfg_path)
    staff = _safe_load_json(staff_path)
    staff_list = []
    if staff and isinstance(staff, dict) and isinstance(staff.get("staff"), list):
        staff_list = staff.get("staff") or []

    # Check config micro break policy
    if isinstance(cfg, dict):
        policies = cfg.get("policies")
        if isinstance(policies, dict) and isinstance(policies.get("micro_break"), dict):
            scores["config_micro_break_section_present"] = 1.0
            mb = policies.get("micro_break")
            hb = mb.get("heavy_block_minutes")
            bm = mb.get("break_minutes")
            if hb == 90 and bm == 10:
                scores["config_micro_break_values_correct"] = 1.0

    # Prepare reference maps
    cfg_tasks = {}
    kitchen_start = None
    kitchen_end = None
    cfg_date = None
    if isinstance(cfg, dict):
        cfg_date = cfg.get("date")
        kh = cfg.get("kitchen_hours", {})
        kitchen_start = _parse_time_hhmm(kh.get("start", "")) if isinstance(kh, dict) else None
        kitchen_end = _parse_time_hhmm(kh.get("end", "")) if isinstance(kh, dict) else None
        for t in cfg.get("tasks", []) if isinstance(cfg.get("tasks", []), list) else []:
            if isinstance(t, dict) and "id" in t:
                cfg_tasks[t["id"]] = t

    staff_by_name = {}
    for s in staff_list:
        if not isinstance(s, dict):
            continue
        name = s.get("name")
        role = s.get("role")
        av = s.get("availability", {})
        av_start = _parse_time_hhmm(av.get("start", "")) if isinstance(av, dict) else None
        av_end = _parse_time_hhmm(av.get("end", "")) if isinstance(av, dict) else None
        if name:
            staff_by_name[name] = {"role": role, "av_start": av_start, "av_end": av_end}

    # Check scheduler.py updated with stricter indicators of actual implementation
    sched_py_path = workspace / "scripts" / "scheduler.py"
    sched_py_text = _safe_read_text(sched_py_path) or ""
    # Require presence of explicit implementation markers not in baseline:
    # - writing validation_report.json
    # - handling "policies" and "micro_break"
    # - explicit "Break" literal or intensity "break" in code
    markers = [
        "validation_report.json",
        '"micro_break"',
        "'micro_break'",
        '"policies"',
        "'policies'",
        '"Break"',
        "'Break'",
        '"break"',
        "'break'",
    ]
    if all(m in sched_py_text for m in ["policies", "micro_break"]) or ("validation_report.json" in sched_py_text) or ('"Break"' in sched_py_text) or ("'Break'" in sched_py_text):
        # Ensure we don't accidentally pass on the baseline "breaks" comment; require at least one of the strong markers
        strong = any(x in sched_py_text for x in ["validation_report.json", '"Break"', "'Break'"])
        if strong or all(m in sched_py_text for m in ['"policies"', '"micro_break"']):
            scores["scheduler_py_updated"] = 1.0

    # Load schedule.csv
    schedule_path = workspace / "output" / "schedule.csv"
    header, rows = _read_schedule_csv(schedule_path)
    expected_columns = ["date", "task_id", "task_name", "staff_name", "role", "start", "end", "intensity"]
    if header == expected_columns and isinstance(rows, list):
        scores["schedule_csv_columns_correct"] = 1.0

    # If schedule present, perform checks
    non_break_rows = []
    break_rows = []
    all_rows_valid_time_format = True
    all_dates_match = True
    if rows is not None and header == expected_columns:
        # Date/time format check
        for r in rows:
            date_ok = (cfg_date is not None and r.get("date") == cfg_date)
            s_parsed = _parse_time_hhmm(r.get("start", ""))
            e_parsed = _parse_time_hhmm(r.get("end", ""))
            if not date_ok:
                all_dates_match = False
            if s_parsed is None or e_parsed is None or e_parsed <= s_parsed:
                all_rows_valid_time_format = False

            if r.get("intensity") == "break":
                break_rows.append(r)
            else:
                non_break_rows.append(r)
        if all_rows_valid_time_format and all_dates_match:
            scores["schedule_date_and_time_format_correct"] = 1.0

        # Unique task_id check
        ids = [r.get("task_id") for r in rows]
        if len(ids) == len(set(ids)) and all(i is not None and i != "" for i in ids):
            scores["task_ids_unique"] = 1.0

        # Non-break task IDs from config
        if non_break_rows:
            all_ids_valid = True
            for r in non_break_rows:
                tid = r.get("task_id")
                if tid not in cfg_tasks:
                    all_ids_valid = False
                    break
            if all_ids_valid:
                scores["non_break_task_ids_from_config"] = 1.0

        # Within kitchen hours
        within_kitchen = True
        if kitchen_start is None or kitchen_end is None:
            within_kitchen = False
        else:
            for r in rows:
                s = _parse_time_hhmm(r.get("start", ""))
                e = _parse_time_hhmm(r.get("end", ""))
                if s is None or e is None or s < kitchen_start or e > kitchen_end:
                    within_kitchen = False
                    break
        scores["within_kitchen_hours_all"] = 1.0 if within_kitchen else 0.0

        # Within staff availability
        within_avail = True
        for r in rows:
            name = r.get("staff_name", "")
            s = _parse_time_hhmm(r.get("start", ""))
            e = _parse_time_hhmm(r.get("end", ""))
            if name not in staff_by_name or s is None or e is None:
                within_avail = False
                break
            avs = staff_by_name[name]["av_start"]
            ave = staff_by_name[name]["av_end"]
            if avs is None or ave is None or s < avs or e > ave:
                within_avail = False
                break
        scores["within_staff_availability_all"] = 1.0 if within_avail else 0.0

        # Non-break tasks within preferred window and role matches
        within_window = True
        for r in non_break_rows:
            tid = r.get("task_id")
            task = cfg_tasks.get(tid)
            if not task:
                within_window = False
                break
            pw = task.get("preferred_window", {})
            pws = _parse_time_hhmm(pw.get("start", "")) if isinstance(pw, dict) else None
            pwe = _parse_time_hhmm(pw.get("end", "")) if isinstance(pw, dict) else None
            s = _parse_time_hhmm(r.get("start", ""))
            e = _parse_time_hhmm(r.get("end", ""))
            if pws is None or pwe is None or s is None or e is None:
                within_window = False
                break
            if s < pws or e > pwe:
                within_window = False
                break
            # role check against task required_role
            if r.get("role") != task.get("required_role"):
                within_window = False
                break
        scores["non_break_tasks_within_preferred_window"] = 1.0 if within_window and len(non_break_rows) > 0 else 0.0

        # No overlap same staff
        no_overlap = True
        rows_by_staff = _index_by(rows, "staff_name")
        for staff_name, srows in rows_by_staff.items():
            # Parse times and sort
            times = []
            for r in srows:
                st = _parse_time_hhmm(r.get("start", ""))
                en = _parse_time_hhmm(r.get("end", ""))
                if st is None or en is None:
                    continue
                times.append((st, en, r))
            times.sort(key=lambda x: x[0])
            for i in range(len(times)):
                for j in range(i + 1, len(times)):
                    a_s, a_e, _ = times[i]
                    b_s, b_e, _ = times[j]
                    if a_e > b_s and b_e > a_s:
                        no_overlap = False
                        break
                if not no_overlap:
                    break
            if not no_overlap:
                break
        scores["no_overlap_same_staff"] = 1.0 if no_overlap else 0.0

        # Break rows valid: name Break, intensity break, duration 10
        breaks_valid = True
        for br in break_rows:
            if br.get("task_name") != "Break" or br.get("intensity") != "break":
                breaks_valid = False
                break
            d = _duration_minutes(br.get("start", ""), br.get("end", ""))
            if d != 10:
                breaks_valid = False
                break
        if breaks_valid:
            scores["break_rows_valid"] = 1.0

        # Compute violations and break policy compliance expectations
        # Outside availability violations (includes kitchen hours, staff availability, and preferred_window for non-break)
        outside_avail_count = 0
        if kitchen_start is None or kitchen_end is None:
            outside_avail_count = len(rows)
        else:
            for r in rows:
                s = _parse_time_hhmm(r.get("start", ""))
                e = _parse_time_hhmm(r.get("end", ""))
                if s is None or e is None:
                    outside_avail_count += 1
                    continue
                if s < kitchen_start or e > kitchen_end:
                    outside_avail_count += 1
                    continue
                name = r.get("staff_name", "")
                staff_info = staff_by_name.get(name)
                if not staff_info:
                    outside_avail_count += 1
                    continue
                if staff_info["av_start"] is None or staff_info["av_end"] is None or s < staff_info["av_start"] or e > staff_info["av_end"]:
                    outside_avail_count += 1
                    continue
                # preferred_window applies only to non-break tasks
                if r.get("intensity") != "break":
                    tid = r.get("task_id")
                    task = cfg_tasks.get(tid)
                    if not task:
                        outside_avail_count += 1
                        continue
                    pw = task.get("preferred_window", {})
                    pws = _parse_time_hhmm(pw.get("start", "")) if isinstance(pw, dict) else None
                    pwe = _parse_time_hhmm(pw.get("end", "")) if isinstance(pw, dict) else None
                    if pws is None or pwe is None or s < pws or e > pwe:
                        outside_avail_count += 1
                        continue

        # Overlap violations: count pair overlaps per staff
        overlap_count = 0
        for staff_name, srows in rows_by_staff.items():
            times = []
            for r in srows:
                st = _parse_time_hhmm(r.get("start", ""))
                en = _parse_time_hhmm(r.get("end", ""))
                if st is None or en is None:
                    continue
                times.append((st, en, r))
            times.sort(key=lambda x: x[0])
            for i in range(len(times)):
                for j in range(i + 1, len(times)):
                    a_s, a_e, _ = times[i]
                    b_s, b_e, _ = times[j]
                    if a_e > b_s and b_e > a_s:
                        overlap_count += 1

        # Missing break after heavy block violations
        # Build a set of break markers for fast lookup: (staff_name, start_minute, end_minute)
        break_index = set()
        for br in break_rows:
            bn = br.get("staff_name", "")
            bs = _parse_time_hhmm(br.get("start", ""))
            be = _parse_time_hhmm(br.get("end", ""))
            if bn and bs is not None and be is not None:
                break_index.add((bn, bs, be))

        # Collect heavy tasks by staff sorted by start
        heavy_by_staff = {}
        for r in non_break_rows:
            if r.get("intensity") == "heavy":
                st = _parse_time_hhmm(r.get("start", ""))
                en = _parse_time_hhmm(r.get("end", ""))
                if st is None or en is None:
                    continue
                heavy_by_staff.setdefault(r.get("staff_name", ""), []).append((st, en, r))
        for sname in heavy_by_staff:
            heavy_by_staff[sname].sort(key=lambda x: x[0])

        missing_breaks = 0

        for sname, tasks_list in heavy_by_staff.items():
            # Rule 1: after any single heavy >= 90, require immediate break
            for (st, en, r) in tasks_list:
                dur = en - st
                if dur >= 90:
                    if (sname, en, en + 10) not in break_index:
                        missing_breaks += 1

            # Rule 2: after any back-to-back sequence of heavy tasks (each <90) totaling >=90
            i = 0
            n = len(tasks_list)
            while i < n:
                st, en, r = tasks_list[i]
                dur = en - st
                if dur >= 90:
                    i += 1
                    continue
                total = dur
                j = i + 1
                last_en = en
                while j < n:
                    st2, en2, r2 = tasks_list[j]
                    dur2 = en2 - st2
                    if dur2 >= 90:
                        break
                    if st2 != last_en:
                        break
                    total += dur2
                    last_en = en2
                    j += 1
                if total >= 90:
                    if (sname, last_en, last_en + 10) not in break_index:
                        missing_breaks += 1
                    i = j
                else:
                    i += 1

        # Determine if break policy is enforced or violations reported
        vr_path = workspace / "output" / "validation_report.json"
        vr = _safe_load_json(vr_path)

        # First, validate structure and totals
        structure_ok = False
        totals_ok = False
        byrule_ok = False
        if isinstance(vr, dict):
            try:
                checked_date = vr.get("checked_date")
                totals = vr.get("totals")
                violations = vr.get("violations")
                if (
                    isinstance(checked_date, str)
                    and checked_date == cfg_date
                    and isinstance(totals, dict)
                    and "tasks" in totals
                    and "breaks" in totals
                    and isinstance(violations, dict)
                    and "total" in violations
                    and "by_rule" in violations
                    and isinstance(violations["by_rule"], dict)
                ):
                    structure_ok = True
                    # Check totals against schedule
                    tasks_count = sum(1 for r in rows if r.get("intensity") != "break")
                    breaks_count = sum(1 for r in rows if r.get("intensity") == "break")
                    if totals.get("tasks") == tasks_count and totals.get("breaks") == breaks_count:
                        totals_ok = True
                    # Check violations total equals sum of by_rule
                    by = violations["by_rule"]
                    req_keys = {"outside_availability", "overlap_same_staff", "missing_break_after_heavy_block"}
                    if set(by.keys()) >= req_keys:
                        ssum = int(by.get("outside_availability", 0)) + int(by.get("overlap_same_staff", 0)) + int(by.get("missing_break_after_heavy_block", 0))
                        if violations.get("total") == ssum:
                            byrule_ok = True
            except Exception:
                pass
        if structure_ok and totals_ok and byrule_ok:
            scores["validation_report_structure_and_totals"] = 1.0

        # Compare violation counts
        if isinstance(vr, dict) and "violations" in vr and isinstance(vr["violations"], dict) and isinstance(vr["violations"].get("by_rule"), dict):
            by = vr["violations"]["by_rule"]
            vr_outside = by.get("outside_availability")
            vr_overlap = by.get("overlap_same_staff")
            vr_missing_breaks = by.get("missing_break_after_heavy_block")
            try:
                if (
                    int(vr_outside) == outside_avail_count
                    and int(vr_overlap) == overlap_count
                    and int(vr_missing_breaks) == missing_breaks
                ):
                    scores["validation_report_violation_counts_match"] = 1.0
            except Exception:
                pass

        # Now set break_policy_enforced_or_reported based on missing_breaks and validation report match
        if missing_breaks == 0:
            scores["break_policy_enforced_or_reported"] = 1.0
        else:
            if scores["validation_report_violation_counts_match"] == 1.0:
                scores["break_policy_enforced_or_reported"] = 1.0

    # Messages checks
    messages_final_path = workspace / "output" / "messages_final.txt"
    mf_text = _safe_read_text(messages_final_path)
    if mf_text is not None:
        lines = mf_text.splitlines()
        # Strictly require exactly 3 lines and non-empty content per line
        if len(lines) == 3 and all(ln.strip() != "" for ln in lines):
            scores["messages_final_three_lines"] = 1.0

        # Line 2 preserves details (index 1)
        if len(lines) >= 2:
            l2 = lines[1].strip()
            # Check names
            names_ok = all(n in l2 for n in ["Ben", "Ana", "Cara", "Dan"])
            # Check time details:
            # - stock 2 hours or 120 minutes or 2h
            time_2h_ok = any(
                pat in l2.lower()
                for pat in ["2 hours", "2-hour", "2 hr", "2hrs", "2h", "120 minutes", "120-minutes", "120 min"]
            )
            # - Ana at 8 (8, 8:00, 08:00)
            ana_time_ok = bool(re.search(r"\b8(:00)?\b", l2)) or "08:00" in l2
            # - Cara bread by 9:30 (accept 9:30 or 09:30)
            nine_thirty_ok = ("9:30" in l2) or ("09:30" in l2)
            # - Dan after 11 (11 or 11:00)
            eleven_ok = bool(re.search(r"\b11(:00)?\b", l2)) or "11:00" in l2
            if names_ok and time_2h_ok and ana_time_ok and nine_thirty_ok and eleven_ok:
                scores["messages_line2_preserves_details"] = 1.0

        # Line 3: policy numbers 90 minutes and 10-minute pause/break
        if len(lines) >= 3:
            l3 = lines[2].lower()
            has_90 = "90" in l3
            has_10 = "10" in l3
            has_break_or_pause = ("break" in l3) or ("pause" in l3)
            if has_90 and has_10 and has_break_or_pause:
                scores["messages_line3_preserves_policy_numbers"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()