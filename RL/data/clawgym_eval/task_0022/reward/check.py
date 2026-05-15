import json
import csv
import sys
from pathlib import Path
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def _safe_load_json(path: Path):
    try:
        return json.loads(_safe_read_text(path))
    except Exception:
        return None

def _safe_read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return reader.fieldnames, rows
    except Exception:
        return None, None

def _safe_parse_xml(path: Path):
    try:
        text = _safe_read_text(path)
        if not text.strip():
            return None
        root = ET.fromstring(text)
        return root
    except Exception:
        return None

def _parse_date(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _to_int_safe(val):
    try:
        return int(val)
    except Exception:
        return None

def _bool_str(val: bool) -> str:
    return "true" if val else "false"

def _normalize_bool_cell(cell: str):
    if cell is None:
        return None
    c = str(cell).strip().lower()
    if c in ("true", "false"):
        return c
    return None

def _bp_category(systolic: int, diastolic: int) -> str:
    if systolic is None or diastolic is None:
        return ""
    # Rules:
    # Normal: systolic < 120 AND diastolic < 80
    # Elevated: 120 ≤ systolic ≤ 129 AND diastolic < 80
    # Hypertension Stage 1: 130 ≤ systolic ≤ 139 OR 80 ≤ diastolic ≤ 89
    # Hypertension Stage 2: systolic ≥ 140 OR diastolic ≥ 90
    if systolic < 120 and diastolic < 80:
        return "Normal"
    if 120 <= systolic <= 129 and diastolic < 80:
        return "Elevated"
    if systolic >= 140 or diastolic >= 90:
        return "Hypertension Stage 2"
    if (130 <= systolic <= 139) or (80 <= diastolic <= 89):
        return "Hypertension Stage 1"
    # Fallback (shouldn't occur)
    return "Normal"

def _compute_expected_summary(workspace: Path):
    steps_path = workspace / "input" / "steps.csv"
    sleep_path = workspace / "input" / "sleep.json"
    bp_path = workspace / "input" / "bp_readings.xml"
    header, rows = _safe_read_csv_dicts(steps_path)
    if header is None or rows is None:
        return None

    # Map sleep by date
    sleep_json = _safe_load_json(sleep_path)
    sleep_map = {}
    if isinstance(sleep_json, list):
        for item in sleep_json:
            try:
                d = item.get("date")
                if isinstance(d, str):
                    sleep_map[d] = {
                        "duration_minutes": item.get("duration_minutes"),
                        "sleep_score": item.get("sleep_score"),
                    }
            except Exception:
                continue

    # Map BP by date
    bp_root = _safe_parse_xml(bp_path)
    bp_map = {}
    if bp_root is not None:
        for r in bp_root.findall(".//reading"):
            d = r.findtext("date") or ""
            sys_val = r.findtext("systolic")
            dia_val = r.findtext("diastolic")
            try:
                systolic = int(sys_val)
            except Exception:
                systolic = None
            try:
                diastolic = int(dia_val)
            except Exception:
                diastolic = None
            bp_map[d] = {
                "systolic": systolic,
                "diastolic": diastolic,
                "bp_category": _bp_category(systolic, diastolic) if (systolic is not None and diastolic is not None) else "",
            }

    expected = []
    for r in rows:
        date = (r.get("date") or "").strip()
        steps = _to_int_safe(r.get("steps"))
        min_light = _to_int_safe(r.get("minutes_light"))
        min_mod = _to_int_safe(r.get("minutes_moderate"))
        min_vig = _to_int_safe(r.get("minutes_vigorous"))
        if None in (steps, min_light, min_mod, min_vig):
            # skip malformed row
            continue
        minutes_moderate_vigorous = min_mod + min_vig
        active_minutes_total = min_light + min_mod + min_vig
        met_steps_target = steps >= 8000

        sleep_rec = sleep_map.get(date)
        if sleep_rec is not None:
            sleep_minutes = sleep_rec.get("duration_minutes")
            sleep_score = sleep_rec.get("sleep_score")
            if isinstance(sleep_minutes, int):
                in_range = 420 <= sleep_minutes <= 540
                sleep_in_range = _bool_str(in_range)
            else:
                sleep_minutes = None
                sleep_score = None
                sleep_in_range = ""
        else:
            sleep_minutes = None
            sleep_score = None
            sleep_in_range = ""

        # Normalize sleep to blanks when missing
        sleep_minutes_cell = "" if sleep_minutes is None else str(int(sleep_minutes))
        sleep_score_cell = "" if sleep_score is None else str(int(sleep_score))

        bp_rec = bp_map.get(date, {})
        systolic = bp_rec.get("systolic")
        diastolic = bp_rec.get("diastolic")
        bp_category = bp_rec.get("bp_category") or ""
        systolic_cell = "" if systolic is None else str(int(systolic))
        diastolic_cell = "" if diastolic is None else str(int(diastolic))

        expected.append({
            "date": date,
            "steps": str(steps),
            "met_steps_target": _bool_str(met_steps_target),
            "minutes_moderate_vigorous": str(minutes_moderate_vigorous),
            "active_minutes_total": str(active_minutes_total),
            "sleep_minutes": sleep_minutes_cell,
            "sleep_in_range": sleep_in_range,
            "sleep_score": sleep_score_cell,
            "systolic": systolic_cell,
            "diastolic": diastolic_cell,
            "bp_category": bp_category,
        })
    return expected

def _load_markdown_sections(md_text: str, section_titles: list) -> dict:
    # Case-insensitive section match by title substring in a line
    lines = md_text.splitlines()
    title_indices = []
    for i, line in enumerate(lines):
        for title in section_titles:
            if title.lower() in line.lower():
                title_indices.append((i, title))
                break
    sections = {t: "" for t in section_titles}
    title_indices_sorted = sorted(title_indices, key=lambda x: x[0])
    for idx, (start_i, title) in enumerate(title_indices_sorted):
        end_i = len(lines)
        if idx + 1 < len(title_indices_sorted):
            end_i = title_indices_sorted[idx + 1][0]
        content = "\n".join(lines[start_i + 1:end_i]).strip()
        sections[title] = content
    return sections

def _count_words(text: str) -> int:
    tokens = [t for t in text.strip().split() if t.strip()]
    return len(tokens)

def _find_ints_in_text(text: str) -> list:
    ints = []
    num = ""
    for ch in text:
        if ch.isdigit():
            num += ch
        else:
            if num != "":
                try:
                    ints.append(int(num))
                except Exception:
                    pass
                num = ""
    if num != "":
        try:
            ints.append(int(num))
        except Exception:
            pass
    return ints

def _weekday_weekend(date_str: str) -> str:
    d = _parse_date(date_str)
    if d is None:
        return "weekday"
    return "weekend" if d.weekday() >= 5 else "weekday"

def _extract_bullets(section_text: str) -> list:
    bullets = []
    for line in section_text.splitlines():
        s = line.strip()
        if s.startswith("- ") or s.startswith("* "):
            bullets.append(s)
    return bullets

def _read_output_csv(path: Path):
    header, rows = _safe_read_csv_dicts(path)
    return header, rows

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_csv_exists_and_header": 0.0,
        "summary_csv_row_count": 0.0,
        "summary_csv_values_correct": 0.0,
        "report_status_update_word_count": 0.0,
        "report_data_coverage_correct": 0.0,
        "report_targets_summary_correct": 0.0,
        "report_bp_distribution_correct": 0.0,
        "report_weekday_weekend_section_present": 0.0,
        "report_key_findings_bullets": 0.0,
        "report_recommendations_bullets_and_conditional": 0.0,
        "report_data_quality_notes_missing_sleep_listed": 0.0,
        "notes_attendees_and_date_range": 0.0,
        "notes_agenda_present": 0.0,
        "notes_discussion_notes_quality": 0.0,
        "notes_action_items_count_owner_due": 0.0,
        "notes_habit_stacking_item_correct": 0.0,
        "notes_action_items_category_coverage": 0.0,
    }

    # Compute expected summary from inputs
    expected_summary = _compute_expected_summary(workspace)
    # Establish expected dates, min/max, counts
    steps_path = workspace / "input" / "steps.csv"
    sleep_path = workspace / "input" / "sleep.json"
    bp_path = workspace / "input" / "bp_readings.xml"
    watchlist_path = workspace / "input" / "watchlist.json"

    expected_dates = []
    min_date_str = None
    max_date_str = None
    sleep_json = _safe_load_json(sleep_path) or []
    sleep_dates = set()
    if isinstance(sleep_json, list):
        for item in sleep_json:
            if isinstance(item, dict) and isinstance(item.get("date"), str):
                sleep_dates.add(item.get("date"))

    bp_root = _safe_parse_xml(bp_path)
    bp_dates = set()
    if bp_root is not None:
        for r in bp_root.findall(".//reading"):
            d = r.findtext("date") or ""
            if d:
                bp_dates.add(d)

    if expected_summary is not None and len(expected_summary) > 0:
        expected_dates = [row["date"] for row in expected_summary]
        min_date_str = min(expected_dates)
        max_date_str = max(expected_dates)
    # For later checks:
    missing_sleep_dates = []
    if expected_dates:
        for d in expected_dates:
            if d not in sleep_dates:
                missing_sleep_dates.append(d)

    # Expected booleans for data-driven checks
    steps_met_count = 0
    sleep_in_range_count = 0
    bp_cat_counts = {"Normal": 0, "Elevated": 0, "Hypertension Stage 1": 0, "Hypertension Stage 2": 0}
    if expected_summary:
        for row in expected_summary:
            if row["met_steps_target"] == "true":
                steps_met_count += 1
            if row["sleep_in_range"] == "true":
                sleep_in_range_count += 1
            cat = row["bp_category"]
            if cat in bp_cat_counts:
                bp_cat_counts[cat] += 1
    steps_days_total = len(expected_dates) if expected_dates else 0
    steps_met_fraction = (steps_met_count / steps_days_total) if steps_days_total > 0 else 0.0

    # Check daily_health_summary.csv
    output_csv_path = workspace / "output" / "daily_health_summary.csv"
    exp_header = [
        "date",
        "steps",
        "met_steps_target",
        "minutes_moderate_vigorous",
        "active_minutes_total",
        "sleep_minutes",
        "sleep_in_range",
        "sleep_score",
        "systolic",
        "diastolic",
        "bp_category",
    ]
    out_header, out_rows = _read_output_csv(output_csv_path)
    if out_header is not None and out_rows is not None:
        # header and existence
        if out_header == exp_header:
            scores["summary_csv_exists_and_header"] = 1.0
        else:
            scores["summary_csv_exists_and_header"] = 0.0
        # row count
        if expected_summary is not None:
            if len(out_rows) == len(expected_summary):
                scores["summary_csv_row_count"] = 1.0
            else:
                scores["summary_csv_row_count"] = 0.0
        # values correctness
        if expected_summary is not None:
            # Map by date
            exp_map = {r["date"]: r for r in expected_summary}
            all_ok = True
            for r in out_rows:
                d = (r.get("date") or "").strip()
                if d not in exp_map:
                    all_ok = False
                    break
                exp = exp_map[d]
                # Compare each field
                for k in exp_header:
                    if k == "date":
                        continue
                    exp_val = exp[k]
                    act_val = r.get(k, "")
                    if act_val is None:
                        act_val = ""
                    act_val = str(act_val).strip()
                    # For booleans (met_steps_target, sleep_in_range) accept case-insensitive true/false and blank for missing sleep_in_range
                    if k in ("met_steps_target", "sleep_in_range"):
                        if exp_val == "":
                            # expect blank
                            if act_val != "":
                                all_ok = False
                                break
                        else:
                            norm = _normalize_bool_cell(act_val)
                            if norm is None or norm != exp_val:
                                all_ok = False
                                break
                    elif k in ("steps", "minutes_moderate_vigorous", "active_minutes_total", "sleep_minutes", "sleep_score", "systolic", "diastolic"):
                        # numeric or blank
                        if exp_val == "":
                            if act_val != "":
                                all_ok = False
                                break
                        else:
                            # Must match integer content
                            try:
                                if int(act_val) != int(exp_val):
                                    all_ok = False
                                    break
                            except Exception:
                                all_ok = False
                                break
                    elif k == "bp_category":
                        if act_val != exp_val:
                            all_ok = False
                            break
                    else:
                        if act_val != exp_val:
                            all_ok = False
                            break
                if not all_ok:
                    break
            scores["summary_csv_values_correct"] = 1.0 if all_ok else 0.0

    # Health_Status_Report.md checks
    report_path = workspace / "output" / "Health_Status_Report.md"
    report_text = _safe_read_text(report_path)
    if report_text:
        section_titles = [
            "Status Update",
            "Data Coverage",
            "Targets Summary",
            "Weekday vs Weekend",
            "Key Findings",
            "Recommendations",
            "Data Quality Notes",
        ]
        sections = _load_markdown_sections(report_text, section_titles)

        # Status Update: 100–150 words
        status_text = sections.get("Status Update", "")
        wc = _count_words(status_text)
        if 100 <= wc <= 150:
            scores["report_status_update_word_count"] = 1.0

        # Data Coverage: date range and counts
        data_cov = sections.get("Data Coverage", "")
        cov_ok = True
        # Check date range
        if min_date_str and max_date_str:
            if (min_date_str in data_cov) and (max_date_str in data_cov):
                pass
            else:
                cov_ok = False
        else:
            cov_ok = False
        # Count of days with sleep and BP
        sleep_days_count = 0
        bp_days_count = 0
        if expected_dates:
            sleep_days_count = sum(1 for d in expected_dates if d in sleep_dates)
            bp_days_count = sum(1 for d in expected_dates if d in bp_dates)
        sleep_line_ok = False
        bp_line_ok = False
        for line in data_cov.splitlines():
            l = line.lower()
            ints = _find_ints_in_text(line)
            if "sleep" in l and ints:
                if sleep_days_count in ints:
                    sleep_line_ok = True
            if ("bp" in l or "blood pressure" in l) and ints:
                if bp_days_count in ints:
                    bp_line_ok = True
        if not (sleep_line_ok and bp_line_ok):
            cov_ok = False
        scores["report_data_coverage_correct"] = 1.0 if cov_ok else 0.0

        # Targets Summary: steps met, sleep in range, bp distribution
        targets_text = sections.get("Targets Summary", "")
        targ_ok = True
        # Steps met
        steps_ok = False
        sleep_range_ok = False
        for line in targets_text.splitlines():
            l = line.lower()
            ints = _find_ints_in_text(line)
            if ("step" in l or "met" in l) and ints:
                if steps_met_count in ints:
                    steps_ok = True
            if ("sleep" in l and "range" in l) and ints:
                if sleep_in_range_count in ints:
                    sleep_range_ok = True
        if not (steps_ok and sleep_range_ok):
            targ_ok = False
        # BP category distribution
        cat_ok = True
        for cat, cnt in bp_cat_counts.items():
            found = False
            for line in targets_text.splitlines():
                if cat.lower() in line.lower():
                    ints = _find_ints_in_text(line)
                    if cnt in ints:
                        found = True
                        break
            if not found:
                cat_ok = False
                break
        scores["report_targets_summary_correct"] = 1.0 if targ_ok else 0.0
        scores["report_bp_distribution_correct"] = 1.0 if cat_ok else 0.0

        # Weekday vs Weekend section presence with mentions
        wv_text = sections.get("Weekday vs Weekend", "")
        wv_ok = False
        if wv_text:
            if ("weekday" in wv_text.lower() and "weekend" in wv_text.lower() and
                "step" in wv_text.lower() and "sleep" in wv_text.lower()):
                wv_ok = True
        scores["report_weekday_weekend_section_present"] = 1.0 if wv_ok else 0.0

        # Key Findings: at least 3 bullets, at least two with digits
        kf_text = sections.get("Key Findings", "")
        bullets = _extract_bullets(kf_text)
        if len(bullets) >= 3:
            digits_bullets = sum(1 for b in bullets if any(ch.isdigit() for ch in b))
            if digits_bullets >= 2:
                scores["report_key_findings_bullets"] = 1.0

        # Recommendations: at least 3 bullets, at least 2 with digits; include "short walks" only if <50% met
        rec_text = sections.get("Recommendations", "")
        rec_bullets = _extract_bullets(rec_text)
        rec_ok = False
        if len(rec_bullets) >= 3:
            digits_bullets = sum(1 for b in rec_bullets if any(ch.isdigit() for ch in b))
            cond_ok = True
            if steps_met_fraction < 0.5:
                cond_ok = any(
                    ("short walk" in b.lower() or "short walks" in b.lower())
                    and ("3" in "".join(ch if ch.isdigit() else " " for ch in b))
                    and ("week" in b.lower())
                    for b in rec_bullets
                )
            if digits_bullets >= 2 and cond_ok:
                rec_ok = True
        scores["report_recommendations_bullets_and_conditional"] = 1.0 if rec_ok else 0.0

        # Data Quality Notes: list any dates with missing sleep
        dqn_text = sections.get("Data Quality Notes", "")
        dqn_ok = False
        if missing_sleep_dates:
            all_listed = all(d in dqn_text for d in missing_sleep_dates)
            dqn_ok = all_listed
        else:
            # If no missing sleep, accept empty or statement noting none
            dqn_ok = True
        scores["report_data_quality_notes_missing_sleep_listed"] = 1.0 if dqn_ok else 0.0

    # Wellness_Checkin_Notes.md checks
    notes_path = workspace / "output" / "Wellness_Checkin_Notes.md"
    notes_text = _safe_read_text(notes_path)
    if notes_text:
        n_sections = _load_markdown_sections(notes_text, [
            "Attendees",
            "Date Range Covered",
            "Agenda",
            "Discussion Notes",
            "Action Items",
        ])

        # Attendees and Date Range Covered
        att_text = n_sections.get("Attendees", "")
        att_ok = ("Me (client)" in att_text) and ("PCP (telehealth)" in att_text)
        dr_text = n_sections.get("Date Range Covered", "")
        if min_date_str and max_date_str:
            dr_ok = (min_date_str in dr_text and max_date_str in dr_text)
        else:
            dr_ok = False
        scores["notes_attendees_and_date_range"] = 1.0 if (att_ok and dr_ok) else 0.0

        # Agenda: must include Activity, Sleep, Blood Pressure, Habit Stacking
        ag_text = n_sections.get("Agenda", "")
        agenda_ok = all(term in ag_text for term in ["Activity", "Sleep", "Blood Pressure", "Habit Stacking"])
        scores["notes_agenda_present"] = 1.0 if agenda_ok else 0.0

        # Discussion Notes: at least 3 bullets; include mention of steps and sleep with numbers, and BP mention
        dn_text = n_sections.get("Discussion Notes", "")
        dn_bullets = _extract_bullets(dn_text)
        dn_ok = False
        if len(dn_bullets) >= 3:
            has_steps_num = any(("step" in b.lower()) and any(ch.isdigit() for ch in b) for b in dn_bullets)
            has_sleep_num = any(("sleep" in b.lower()) and any(ch.isdigit() for ch in b) for b in dn_bullets)
            has_bp = any(("bp" in b.lower()) or ("blood pressure" in b.lower()) for b in dn_bullets)
            dn_ok = has_steps_num and has_sleep_num and has_bp
        scores["notes_discussion_notes_quality"] = 1.0 if dn_ok else 0.0

        # Action Items: at least 4 items with Owner: Me and Due: YYYY-MM-DD
        ai_text = n_sections.get("Action Items", "")
        ai_bullets = _extract_bullets(ai_text)
        ai_count = 0
        for b in ai_bullets:
            if "owner:" in b.lower() and "me" in b:
                has_due = "due:" in b.lower()
                has_date = False
                for token in b.split():
                    if len(token) == 10 and token[4] == "-" and token[7] == "-":
                        if _parse_date(token) is not None:
                            has_date = True
                            break
                if has_due and has_date:
                    ai_count += 1
        scores["notes_action_items_count_owner_due"] = 1.0 if ai_count >= 4 else 0.0

        # Habit stacking item: 30-minute light walk with unwatched comedy, due 7 days after latest date
        watchlist = _safe_load_json(watchlist_path)
        expected_movie = None
        if isinstance(watchlist, list):
            candidates = [w for w in watchlist if isinstance(w, dict) and not w.get("watched", False)]
            zoolander = None
            for w in candidates:
                if w.get("title") == "Zoolander (2001)":
                    zoolander = w
                    break
            if zoolander is not None:
                expected_movie = zoolander.get("title")
            elif candidates:
                expected_movie = candidates[0].get("title")
        hs_ok = False
        expected_due = ""
        if max_date_str:
            max_d = _parse_date(max_date_str)
            if max_d:
                expected_due = (max_d + timedelta(days=7)).isoformat()
        if ai_bullets and expected_movie and expected_due:
            for b in ai_bullets:
                bl = b.lower()
                if expected_movie in b and ("30-minute" in bl or "30 minute" in bl) and "walk" in bl and "owner: me" in bl:
                    if expected_due in b:
                        hs_ok = True
                        break
        scores["notes_habit_stacking_item_correct"] = 1.0 if hs_ok else 0.0

        # Category coverage in action items: steps/walk, sleep, BP
        cover_steps = any(("walk" in b.lower() or "step" in b.lower()) for b in ai_bullets)
        cover_sleep = any(("sleep" in b.lower()) for b in ai_bullets)
        cover_bp = any(("bp" in b.lower()) or ("blood pressure" in b.lower()) for b in ai_bullets)
        scores["notes_action_items_category_coverage"] = 1.0 if (cover_steps and cover_sleep and cover_bp) else 0.0

    return scores

def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))

if __name__ == "__main__":
    main()