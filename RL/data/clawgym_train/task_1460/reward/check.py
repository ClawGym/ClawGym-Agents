import json
import csv
import math
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(row)
            # Ensure expected columns exist
            expected = {
                "date",
                "pages_drawn",
                "hours_drawing",
                "breaks",
                "neck_pain",
                "wrist_pain",
                "eye_strain",
                "sleep_hours",
            }
            if not rows:
                return None
            if set(rows[0].keys()) != expected:
                return None
            return rows
    except Exception:
        return None


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _compute_weekly_stats(rows: List[Dict[str, str]]) -> Optional[Dict[str, Dict[str, float]]]:
    # Weeks: Week 1 = 2026-03-01..2026-03-07, Week 2 = 2026-03-08..2026-03-14
    try:
        w1_start = datetime(2026, 3, 1)
        w1_end = datetime(2026, 3, 7)
        w2_start = datetime(2026, 3, 8)
        w2_end = datetime(2026, 3, 14)

        metrics = ["hours_drawing", "breaks", "neck_pain", "wrist_pain", "eye_strain", "sleep_hours"]
        sums_w1 = {m: 0.0 for m in metrics}
        counts_w1 = 0
        sums_w2 = {m: 0.0 for m in metrics}
        counts_w2 = 0

        for r in rows:
            d = _parse_date(r["date"])
            if d is None:
                return None
            # Convert numeric fields
            try:
                for m in metrics:
                    _ = float(r[m])
            except Exception:
                return None

            if w1_start <= d <= w1_end:
                for m in metrics:
                    sums_w1[m] += float(r[m])
                counts_w1 += 1
            elif w2_start <= d <= w2_end:
                for m in metrics:
                    sums_w2[m] += float(r[m])
                counts_w2 += 1
            else:
                # Out of expected range; include but not counted to weeks
                pass

        if counts_w1 == 0 or counts_w2 == 0:
            return None

        avgs_w1 = {m: sums_w1[m] / counts_w1 for m in metrics}
        avgs_w2 = {m: sums_w2[m] / counts_w2 for m in metrics}

        return {"week1": avgs_w1, "week2": avgs_w2}
    except Exception:
        return None


def _round1_str(x: float) -> str:
    return f"{x:.1f}"


def _floor_to_half(x: float) -> float:
    return math.floor(x * 2.0) / 2.0


def _get_planned_changes_section(text: str) -> Tuple[List[str], int, int]:
    lines = text.splitlines()
    start = -1
    end = len(lines)
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## planned changes"):
            start = i
            break
    if start == -1:
        # Try the exact heading from the initial doc
        for i, line in enumerate(lines):
            if line.strip().lower().startswith("## planned changes (draft)"):
                start = i
                break
    if start == -1:
        return ([], -1, -1)
    for j in range(start + 1, len(lines)):
        if lines[j].strip().startswith("## "):
            end = j
            break
    section = lines[start:end]
    return (section, start, end)


def _get_pain_points_section(text: str) -> Tuple[List[str], int, int]:
    lines = text.splitlines()
    start = -1
    end = len(lines)
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## pain points"):
            start = i
            break
    if start == -1:
        return ([], -1, -1)
    for j in range(start + 1, len(lines)):
        if lines[j].strip().startswith("## "):
            end = j
            break
    section = lines[start:end]
    return (section, start, end)


def _find_lines_with_bullets(lines: List[str]) -> List[str]:
    items = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            items.append(line)
        elif stripped.startswith("-[") or stripped.startswith("- ["):
            items.append(line)
    return items


def _contains_number_on_line(line: str, number_str: str) -> bool:
    return number_str in line


def _find_line_with_keywords_and_numbers(lines: List[str], keywords: List[str], numbers: List[str]) -> bool:
    for line in lines:
        lower = line.lower()
        if all(k.lower() in lower for k in keywords) and all(n in line for n in numbers):
            return True
    return False


def _extract_body_lines_after_first(text: str) -> List[str]:
    lines = text.splitlines()
    if not lines:
        return []
    return lines[1:]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "report_date_range_and_count": 0.0,
        "report_weekly_averages": 0.0,
        "report_flare_days": 0.0,
        "report_wrist_trend": 0.0,
        "ergonomics_planned_changes": 0.0,
        "ergonomics_data_snapshot": 0.0,
        "email_requirements": 0.0,
        "cross_consistency_trend_and_targets": 0.0,
    }

    # Load input data
    csv_path = workspace / "input" / "work_log.csv"
    rows = _safe_read_csv(csv_path)

    # Compute expected statistics if possible
    stats = None
    b_target = None
    h_target = None
    wrist_diff_1d_str = None
    wrist_trend_phrase = None
    flare_days_expected: List[Tuple[str, str]] = []
    date_min = None
    date_max = None

    if rows is not None:
        # Determine date range and count
        dates = []
        all_in_range = True
        for r in rows:
            d = _parse_date(r["date"])
            if d is None:
                all_in_range = False
                break
            dates.append(d)
        if dates:
            dates_sorted = sorted(dates)
            date_min = dates_sorted[0].strftime("%Y-%m-%d")
            date_max = dates_sorted[-1].strftime("%Y-%m-%d")

        stats = _compute_weekly_stats(rows)
        if stats is not None:
            # Compute targets
            w2_breaks = stats["week2"]["breaks"]
            b_target = math.ceil(w2_breaks) + 1
            w2_hours = stats["week2"]["hours_drawing"]
            h_target = _floor_to_half(w2_hours - 0.5)
            # Wrist diff and trend
            w1_wp = stats["week1"]["wrist_pain"]
            w2_wp = stats["week2"]["wrist_pain"]
            wrist_diff_val = w2_wp - w1_wp
            wrist_diff_1d_str = _round1_str(wrist_diff_val)
            if wrist_diff_val >= 0.5 - 1e-9:
                wrist_trend_phrase = "Wrist pain trend: WORSENED"
            else:
                wrist_trend_phrase = "Wrist pain trend: STABLE/IMPROVED"
            # Flare days
            flare_days_expected = []
            for r in rows:
                try:
                    if float(r["wrist_pain"]) >= 7.0:
                        # list date and pages_drawn
                        flare_days_expected.append((r["date"], str(int(float(r["pages_drawn"])))))
                except Exception:
                    pass

    # Load deliverables
    report_path = workspace / "reports" / "health_summary.md"
    report_text = _safe_read_text(report_path)

    erg_path = workspace / "docs" / "ErgonomicsRoutine.md"
    erg_text = _safe_read_text(erg_path)

    email_path = workspace / "outbox" / "email_to_editor.txt"
    email_text = _safe_read_text(email_path)

    # Check: report_date_range_and_count
    if report_text is not None and date_min is not None and date_max is not None:
        has_dates = (date_min in report_text) and (date_max in report_text)
        # find a line that mentions "day" and "14"
        count_ok = False
        for line in report_text.splitlines():
            if "day" in line.lower() and "14" in line:
                count_ok = True
                break
        if has_dates and count_ok:
            scores["report_date_range_and_count"] = 1.0

    # Check: report_weekly_averages
    if report_text is not None and stats is not None:
        metrics = ["hours_drawing", "breaks", "neck_pain", "wrist_pain", "eye_strain", "sleep_hours"]
        total = 0
        correct = 0
        has_week1_label = "week 1" in report_text.lower()
        has_week2_label = "week 2" in report_text.lower()
        for m in metrics:
            total += 1
            w1_val = _round1_str(stats["week1"][m])
            w2_val = _round1_str(stats["week2"][m])
            # Require metric name present and both values present
            m_present = m in report_text
            w1_present = w1_val in report_text
            w2_present = w2_val in report_text
            if m_present and w1_present and w2_present and has_week1_label and has_week2_label:
                correct += 1
        if total > 0:
            scores["report_weekly_averages"] = correct / total

    # Check: report_flare_days
    if report_text is not None and flare_days_expected is not None:
        # Require each expected flare day to be present with date and pages_drawn on same line
        lines = report_text.splitlines()
        found = 0
        for date_str, pages_str in flare_days_expected:
            line_found = False
            for line in lines:
                if date_str in line and pages_str in line:
                    line_found = True
                    break
            if line_found:
                found += 1
        if flare_days_expected:
            scores["report_flare_days"] = found / len(flare_days_expected)

    # Check: report_wrist_trend
    if report_text is not None and wrist_diff_1d_str is not None and wrist_trend_phrase is not None:
        diff_present = wrist_diff_1d_str in report_text
        trend_present = wrist_trend_phrase in report_text
        if diff_present and trend_present:
            scores["report_wrist_trend"] = 1.0

    # Check: ergonomics_planned_changes
    if erg_text is not None and b_target is not None and h_target is not None:
        section, s_idx, e_idx = _get_planned_changes_section(erg_text)
        if section and s_idx != -1:
            # Extract only lines within section excluding the heading line
            sect_lines = section[1:]
            bullet_lines = _find_lines_with_bullets(sect_lines)
            # exactly three items
            three_items = len(bullet_lines) == 3
            # no placeholder
            no_placeholder = not any("placeholder" in ln.lower() for ln in sect_lines)
            # min breaks/day item
            b_ok = False
            for ln in bullet_lines:
                if "min breaks/day" in ln.lower() and str(b_target) in ln:
                    b_ok = True
                    break
            # max drawing hours/day item
            h_ok = False
            h_str = f"{h_target:.1f}".rstrip('0').rstrip('.') if abs(h_target - round(h_target)) > 1e-9 else str(int(h_target))
            # Ensure we accept 7.5 as "7.5" and also potentially as "7.5h" if someone added h
            for ln in bullet_lines:
                if "max drawing hours/day" in ln.lower() and ("7.5" in ln or h_str in ln):
                    # also ensure number matches expected
                    if f"{h_target:.1f}" in ln or h_str in ln:
                        h_ok = True
                        break
            # stop-work rule exact phrase
            stop_phrase = 'If wrist pain >= 7, stop drawing for the day and schedule recovery.'
            stop_ok = any(stop_phrase in ln for ln in bullet_lines)

            if three_items and no_placeholder and b_ok and h_ok and stop_ok:
                scores["ergonomics_planned_changes"] = 1.0

    # Check: ergonomics_data_snapshot
    if erg_text is not None and stats is not None:
        pain_section, ps_idx, pe_idx = _get_pain_points_section(erg_text)
        if pain_section and ps_idx != -1:
            pain_lines = pain_section
            snapshot_idx = -1
            for i, ln in enumerate(pain_lines):
                if "Data Snapshot (Mar 1–14)" in ln or "Data Snapshot (Mar 1-14)" in ln:
                    snapshot_idx = i
                    break
            if snapshot_idx != -1:
                # Compute top two symptoms by Week 2 avg
                w2 = stats["week2"]
                symptom_avgs = {
                    "neck_pain": w2["neck_pain"],
                    "wrist_pain": w2["wrist_pain"],
                    "eye_strain": w2["eye_strain"],
                }
                top_two = sorted(symptom_avgs.items(), key=lambda kv: kv[1], reverse=True)[:2]
                needed = [(name, _round1_str(val)) for name, val in top_two]
                # Ensure both appear after the snapshot line within the pain points section
                sub_lines = pain_lines[snapshot_idx + 1 :]
                all_ok = True
                for name, val in needed:
                    # find a line that contains name and val
                    if not _find_line_with_keywords_and_numbers(sub_lines, [name], [val]):
                        all_ok = False
                        break
                if all_ok:
                    scores["ergonomics_data_snapshot"] = 1.0

    # Check: email_requirements
    if email_text is not None and b_target is not None and h_target is not None and wrist_trend_phrase is not None:
        lines = email_text.splitlines()
        if lines:
            subject_ok = lines[0].strip() == "Subject: Ergonomic plan update and schedule request (Mar 1–14)"
            body_lines = _extract_body_lines_after_first(email_text)
            body_text = "\n".join(body_lines)
            # Trend wording (WORSENED or STABLE/IMPROVED)
            trend_word = "WORSENED" if "WORSENED" in wrist_trend_phrase else "STABLE/IMPROVED"
            trend_ok = trend_word in body_text

            # Targets statement presence
            # Min breaks/day = b_target
            min_breaks_ok = _find_line_with_keywords_and_numbers(
                body_lines, ["Min breaks/day"], [str(b_target)]
            )
            # Max drawing hours/day = h_target
            max_hours_ok = _find_line_with_keywords_and_numbers(
                body_lines, ["Max drawing hours/day"], [f"{h_target:.1f}"]
            ) or _find_line_with_keywords_and_numbers(
                body_lines, ["Max drawing hours/day"], [str(h_target)]
            )

            # Proposal: reduce daily pages by 1 on flare days
            proposal_ok = "reduce daily pages by 1 on flare days" in body_text
            # Reference flare-day definition
            flare_def_ok = "wrist_pain >= 7" in body_text

            # Mention both artifact paths
            paths_ok = ("reports/health_summary.md" in body_text) and ("docs/ErgonomicsRoutine.md" in body_text)

            if all([subject_ok, trend_ok, min_breaks_ok, max_hours_ok, proposal_ok, flare_def_ok, paths_ok]):
                scores["email_requirements"] = 1.0

    # Cross-consistency: trend and targets across report and email
    if report_text is not None and email_text is not None and wrist_trend_phrase is not None and b_target is not None and h_target is not None:
        trend_ok_report = wrist_trend_phrase in report_text
        trend_word_expected = "WORSENED" if "WORSENED" in wrist_trend_phrase else "STABLE/IMPROVED"
        trend_ok_email = trend_word_expected in email_text

        # targets present and consistent in both docs and email
        targets_in_email = ("Min breaks/day" in email_text and str(b_target) in email_text and "Max drawing hours/day" in email_text and f"{h_target:.1f}" in email_text)
        # targets in ergonomics doc planned changes
        if erg_text is not None:
            erg_section, e_sidx, e_eidx = _get_planned_changes_section(erg_text)
            if erg_section:
                bullets = _find_lines_with_bullets(erg_section[1:])
                b_doc_ok = any(("min breaks/day" in ln.lower() and str(b_target) in ln) for ln in bullets)
                h_doc_ok = any(("max drawing hours/day" in ln.lower() and f"{h_target:.1f}" in ln) for ln in bullets)
                targets_in_doc = b_doc_ok and h_doc_ok
            else:
                targets_in_doc = False
        else:
            targets_in_doc = False

        if trend_ok_report and trend_ok_email and targets_in_email and targets_in_doc:
            scores["cross_consistency_trend_and_targets"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()