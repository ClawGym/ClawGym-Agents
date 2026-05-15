import csv
import json
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta


def _read_csv_dicts(path: Path):
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames if reader.fieldnames is not None else []
        return header, rows
    except Exception:
        return None, None


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _discover_jsonl_files(dir_path: Path):
    if not dir_path.exists() or not dir_path.is_dir():
        return []
    return sorted([p for p in dir_path.iterdir() if p.is_file() and p.suffix.lower() == ".jsonl"])


def _load_jsonl_records(path: Path):
    records = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    records.append(obj)
                except Exception:
                    # Malformed JSON line; fail by returning None
                    return None
        return records
    except Exception:
        return None


def _parse_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None


def _is_october_2024(date_str: str) -> bool:
    d = _parse_date(date_str)
    if d is None:
        return False
    return d.year == 2024 and d.month == 10


def _round_str(value, digits):
    try:
        return f"{round(float(value), digits):.{digits}f}"
    except Exception:
        return ""


def _section_bounds(md_text: str, title: str):
    """
    Find the start and end indices of a section whose title is exactly `title`,
    possibly preceded by Markdown heading markers (#).
    Returns (start_index_inclusive, end_index_exclusive) of lines; or (None,None) if not found.
    """
    lines = md_text.splitlines()
    pattern = re.compile(r"^\s*#*\s*" + re.escape(title) + r"\s*$", re.IGNORECASE)
    indices = [i for i, ln in enumerate(lines) if pattern.match(ln)]
    if not indices:
        return None, None
    start = indices[0] + 1  # content starts after the title line
    # find next section title among the known titles
    other_titles = {"Summary", "Decisions", "Action Items"} - {title}
    end = len(lines)
    for j in range(start, len(lines)):
        stripped = lines[j].strip().lstrip("#").strip()
        if stripped in other_titles:
            end = j
            break
    return start, end


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "feedback_files_scanned_listing_correct": 0.0,
        "feedback_summary_file_structure": 0.0,
        "feedback_summary_values_correct": 0.0,
        "ranked_candidates_file_structure": 0.0,
        "ranked_candidates_rows_and_ranking_correct": 0.0,
        "schedule_proposal_file_structure": 0.0,
        "schedule_proposal_selection_correct": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_decisions_correct": 0.0,
        "meeting_notes_action_items_complete": 0.0,
    }

    # Load lecturers
    lecturers_csv = workspace / "input" / "lecturers.csv"
    cal_csv = workspace / "input" / "calendar.csv"
    feedback_dir = workspace / "input" / "feedback"

    header_lect, rows_lect = _read_csv_dicts(lecturers_csv)
    header_cal, rows_cal = _read_csv_dicts(cal_csv)
    jsonl_files = _discover_jsonl_files(feedback_dir)

    # Prepare expected aggregated feedback
    expected_feedback_counts = {}  # filename -> count
    agg = {}  # speaker -> {'rating_sum':..., 'att_sum':..., 'count':...}
    feedback_read_ok = True

    if jsonl_files:
        for jf in jsonl_files:
            recs = _load_jsonl_records(jf)
            if recs is None:
                feedback_read_ok = False
                break
            expected_feedback_counts[jf.name] = len(recs)
            for r in recs:
                sp = r.get("speaker")
                rating = r.get("rating")
                attend = r.get("attendance")
                if sp is None or rating is None or attend is None:
                    feedback_read_ok = False
                    break
                try:
                    rating_f = float(rating)
                    attend_f = float(attend)
                except Exception:
                    feedback_read_ok = False
                    break
                if sp not in agg:
                    agg[sp] = {"rating_sum": 0.0, "att_sum": 0.0, "count": 0}
                agg[sp]["rating_sum"] += rating_f
                agg[sp]["att_sum"] += attend_f
                agg[sp]["count"] += 1
            if not feedback_read_ok:
                break
    else:
        feedback_read_ok = False

    # If lecturers loaded, build list of all speaker names
    all_speakers = []
    if rows_lect is not None:
        for r in rows_lect:
            if "name" in r:
                all_speakers.append(r["name"])

    # Prepare expected feedback summary values for each speaker
    expected_feedback_summary = {}
    if rows_lect is not None and feedback_read_ok:
        for sp in all_speakers:
            data = agg.get(sp)
            if data and data["count"] > 0:
                avg_rating = round(data["rating_sum"] / data["count"], 2)
                avg_att = round(data["att_sum"] / data["count"], 1)
                expected_feedback_summary[sp] = {
                    "avg_rating": f"{avg_rating:.2f}",
                    "avg_attendance": f"{avg_att:.1f}",
                    "feedback_count": str(data["count"]),
                }
            else:
                expected_feedback_summary[sp] = {
                    "avg_rating": "",
                    "avg_attendance": "",
                    "feedback_count": "0",
                }

    # Prepare expected conflicts (AM Auditorium)
    conflicts = set()
    if rows_cal is not None:
        for r in rows_cal:
            date = r.get("date", "")
            timeslot = r.get("timeslot", "")
            location = r.get("location", "")
            if timeslot == "AM" and location == "Auditorium" and _is_october_2024(date):
                conflicts.add(date)

    # Filter candidates and compute rankings
    filtered_candidates = []  # list of dict with computed fields
    if rows_lect is not None and feedback_read_ok:
        for r in rows_lect:
            name = r.get("name", "")
            email = r.get("email", "")
            topic_tags = r.get("topic_tags", "") or ""
            avail_dates = r.get("available_dates", "") or ""
            pref = r.get("preferred_timeslot", "")
            tags_norm = topic_tags.lower()
            matches_topic = ("tibetan" in tags_norm) or ("folk stories" in tags_norm)
            if matches_topic and pref == "AM":
                # available dates in Oct 2024
                dates_list = [d.strip() for d in avail_dates.split(";") if d.strip()]
                dates_oct = [d for d in dates_list if _is_october_2024(d)]
                # Determine earliest non-conflicting date (chronologically)
                valid_oct_dates = []
                for d in dates_oct:
                    pd = _parse_date(d)
                    if pd is not None:
                        valid_oct_dates.append((pd, d))
                valid_oct_dates.sort(key=lambda x: x[0])
                first_non_conflicting = ""
                for pd, d in valid_oct_dates:
                    if d not in conflicts:
                        first_non_conflicting = d
                        break
                fb = expected_feedback_summary.get(name, {"avg_rating": "", "avg_attendance": "", "feedback_count": "0"})
                avg_rating = fb["avg_rating"] if fb else ""
                avg_attendance = fb["avg_attendance"] if fb else ""
                feedback_count = fb["feedback_count"] if fb else "0"
                # For sorting, treat missing averages as 0
                def to_float_or_zero(s):
                    try:
                        return float(s)
                    except Exception:
                        return 0.0
                sort_rating = to_float_or_zero(avg_rating)
                sort_att = to_float_or_zero(avg_attendance)
                filtered_candidates.append({
                    "name": name,
                    "email": email,
                    "topic_tags": topic_tags,
                    "available_dates_in_oct": ";".join(dates_oct),
                    "first_non_conflicting_date": first_non_conflicting,
                    "avg_rating": avg_rating,
                    "avg_attendance": avg_attendance,
                    "feedback_count": feedback_count,
                    "sort_rating": sort_rating,
                    "sort_att": sort_att,
                })
        # rank by desc avg_rating, then desc avg_attendance, then alpha name
        filtered_candidates.sort(key=lambda x: (-x["sort_rating"], -x["sort_att"], x["name"]))
        # expected top 2 with non-empty first_non_conflicting_date
        expected_top_two = []
        for cand in filtered_candidates:
            if cand["first_non_conflicting_date"]:
                expected_top_two.append(cand)
            if len(expected_top_two) == 2:
                break
    else:
        expected_top_two = []

    # Check feedback_files_scanned.txt
    ff_scanned = workspace / "output" / "feedback_files_scanned.txt"
    ff_ok = False
    if ff_scanned.exists() and expected_feedback_counts:
        txt = _read_text(ff_scanned)
        if txt is not None:
            lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
            found = {}
            pattern = re.compile(r"^(?P<fn>.+?):\s*(?P<count>\d+)\s*$")
            parse_ok = True
            for ln in lines:
                m = pattern.match(ln)
                if not m:
                    parse_ok = False
                    break
                fn = m.group("fn")
                cnt = int(m.group("count"))
                found[fn] = cnt
            if parse_ok and found == expected_feedback_counts:
                ff_ok = True
    scores["feedback_files_scanned_listing_correct"] = 1.0 if ff_ok else 0.0

    # Check feedback_summary.csv
    fs_path = workspace / "output" / "feedback_summary.csv"
    fs_structure_ok = False
    fs_values_ok = False
    required_fs_header = ["speaker", "avg_rating", "avg_attendance", "feedback_count"]
    if fs_path.exists() and rows_lect is not None and feedback_read_ok:
        header, rows = _read_csv_dicts(fs_path)
        if header == required_fs_header and rows is not None:
            fs_structure_ok = True
            # Map by speaker
            got_speakers = set()
            correct = True
            if rows is None:
                correct = False
            else:
                if len(rows) != len(all_speakers):
                    correct = False
                # build map
                row_map = {}
                for r in rows:
                    sp = r.get("speaker", "")
                    row_map[sp] = r
                    got_speakers.add(sp)
                expected_names = set(all_speakers)
                if got_speakers != expected_names:
                    correct = False
                else:
                    for sp in all_speakers:
                        exp = expected_feedback_summary.get(sp)
                        if exp is None:
                            correct = False
                            break
                        r = row_map.get(sp, {})
                        if r.get("avg_rating", "") != exp["avg_rating"]:
                            correct = False
                            break
                        if r.get("avg_attendance", "") != exp["avg_attendance"]:
                            correct = False
                            break
                        if str(r.get("feedback_count", "")).strip() != exp["feedback_count"]:
                            correct = False
                            break
            fs_values_ok = correct
    scores["feedback_summary_file_structure"] = 1.0 if fs_structure_ok else 0.0
    scores["feedback_summary_values_correct"] = 1.0 if fs_values_ok else 0.0

    # Check ranked_candidates.csv
    rc_path = workspace / "output" / "ranked_candidates.csv"
    rc_structure_ok = False
    rc_values_ok = False
    required_rc_header = ["rank", "name", "email", "topic_tags", "avg_rating", "feedback_count", "avg_attendance", "available_dates_in_oct", "first_non_conflicting_date"]
    if rc_path.exists() and rows_lect is not None and feedback_read_ok:
        header, rows = _read_csv_dicts(rc_path)
        if header == required_rc_header and rows is not None:
            rc_structure_ok = True
            # Build expected rows in order with ranks
            expected_rows = []
            for i, cand in enumerate(filtered_candidates, start=1):
                expected_rows.append({
                    "rank": str(i),
                    "name": cand["name"],
                    "email": cand["email"],
                    "topic_tags": cand["topic_tags"],
                    "avg_rating": cand["avg_rating"],
                    "feedback_count": cand["feedback_count"],
                    "avg_attendance": cand["avg_attendance"],
                    "available_dates_in_oct": cand["available_dates_in_oct"],
                    "first_non_conflicting_date": cand["first_non_conflicting_date"],
                })
            # Compare rows exactly in order
            correct = True
            if len(rows) != len(expected_rows):
                correct = False
            else:
                for got, exp in zip(rows, expected_rows):
                    for k in required_rc_header:
                        if (got.get(k, "") or "") != (exp.get(k, "") or ""):
                            correct = False
                            break
                    if not correct:
                        break
            rc_values_ok = correct
    scores["ranked_candidates_file_structure"] = 1.0 if rc_structure_ok else 0.0
    scores["ranked_candidates_rows_and_ranking_correct"] = 1.0 if rc_values_ok else 0.0

    # Check schedule_proposal.csv
    sp_path = workspace / "output" / "schedule_proposal.csv"
    sp_structure_ok = False
    sp_values_ok = False
    required_sp_header = ["event_date", "timeslot", "location", "speaker_name", "email", "topic_tags"]
    if sp_path.exists() and rows_lect is not None and feedback_read_ok:
        header, rows = _read_csv_dicts(sp_path)
        if header == required_sp_header and rows is not None:
            # Must have exactly 2 rows
            if len(rows) == 2:
                sp_structure_ok = True
                # Build expected top two set
                expected_set = set()
                speaker_info = {r["name"]: r for r in rows_lect}
                for cand in expected_top_two:
                    info = speaker_info.get(cand["name"], {})
                    expected_set.add((
                        cand["first_non_conflicting_date"],
                        "AM",
                        "Auditorium",
                        cand["name"],
                        info.get("email", ""),
                        info.get("topic_tags", ""),
                    ))
                got_set = set()
                correct = True
                for r in rows:
                    if r.get("timeslot", "") != "AM":
                        correct = False
                        break
                    if r.get("location", "") != "Auditorium":
                        correct = False
                        break
                    got_tuple = (
                        r.get("event_date", ""),
                        r.get("timeslot", ""),
                        r.get("location", ""),
                        r.get("speaker_name", ""),
                        r.get("email", ""),
                        r.get("topic_tags", ""),
                    )
                    got_set.add(got_tuple)
                if correct and got_set == expected_set:
                    sp_values_ok = True
    scores["schedule_proposal_file_structure"] = 1.0 if sp_structure_ok else 0.0
    scores["schedule_proposal_selection_correct"] = 1.0 if sp_values_ok else 0.0

    # Check meeting_notes.md
    mn_path = workspace / "output" / "meeting_notes.md"
    mn_sections_ok = False
    mn_decisions_ok = False
    mn_actions_ok = False
    if mn_path.exists() and sp_values_ok:
        txt = _read_text(mn_path)
        if txt is not None:
            # Sections present
            s_start, s_end = _section_bounds(txt, "Summary")
            d_start, d_end = _section_bounds(txt, "Decisions")
            a_start, a_end = _section_bounds(txt, "Action Items")
            if None not in (s_start, s_end, d_start, d_end, a_start, a_end):
                mn_sections_ok = True
                decisions_text = "\n".join(txt.splitlines()[d_start:d_end])
                # Verify decisions mention both speakers and dates
                decisions_ok = True
                expected_pairs = []
                if len(expected_top_two) == 2:
                    expected_pairs = [
                        (expected_top_two[0]["name"], expected_top_two[0]["first_non_conflicting_date"]),
                        (expected_top_two[1]["name"], expected_top_two[1]["first_non_conflicting_date"]),
                    ]
                else:
                    decisions_ok = False
                for name, date in expected_pairs:
                    if (name not in decisions_text) or (date not in decisions_text):
                        decisions_ok = False
                        break
                mn_decisions_ok = decisions_ok

                # Verify action items
                action_lines = txt.splitlines()[a_start:a_end]
                action_text = "\n".join(action_lines)

                def _has_task_for_date(lines, date_str, keywords):
                    # find a line that includes date_str, contains all keywords, and mentions owner
                    for ln in lines:
                        ln_lower = ln.lower()
                        if date_str in ln and all(kw.lower() in ln_lower for kw in keywords) and ("owner" in ln_lower):
                            return True
                    return False

                actions_ok = True
                # For each event, validate four tasks with due dates
                for cand in expected_top_two:
                    event_date_str = cand["first_non_conflicting_date"]
                    due_date = _parse_date(event_date_str)
                    if due_date is None:
                        actions_ok = False
                        break
                    due_date_str = (due_date - timedelta(days=7)).strftime("%Y-%m-%d")
                    # Required tasks:
                    # 1) contact the speaker by email to confirm
                    if not _has_task_for_date(action_lines, due_date_str, ["contact", "confirm"]):
                        actions_ok = False
                        break
                    # 2) reserve the Auditorium
                    if not _has_task_for_date(action_lines, due_date_str, ["reserve", "auditorium"]):
                        actions_ok = False
                        break
                    # 3) notify homeroom teachers
                    if not _has_task_for_date(action_lines, due_date_str, ["notify", "homeroom"]):
                        actions_ok = False
                        break
                    # 4) arrange an AV check
                    # Accept either "av check" as one phrase or "av" and "check" separately
                    if not (_has_task_for_date(action_lines, due_date_str, ["av", "check"])):
                        actions_ok = False
                        break
                mn_actions_ok = actions_ok

    scores["meeting_notes_sections_present"] = 1.0 if mn_sections_ok else 0.0
    scores["meeting_notes_decisions_correct"] = 1.0 if mn_decisions_ok else 0.0
    scores["meeting_notes_action_items_complete"] = 1.0 if mn_actions_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()