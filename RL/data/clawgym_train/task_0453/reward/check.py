import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, []
            rows = list(reader)
            return headers, rows
    except Exception:
        return None, []


def _compute_expected_summary(bookings_path: Path):
    headers, rows = _safe_read_csv_dicts(bookings_path)
    if headers is None:
        return None
    # If there are zero rows, expected is an empty mapping
    if not rows:
        return {}

    # Drop exact duplicate rows considering all columns in order
    seen = set()
    deduped_rows = []
    for r in rows:
        key = tuple((k, r.get(k, "")) for k in headers)
        if key not in seen:
            seen.add(key)
            deduped_rows.append(r)

    # Exclude statuses "cancelled" or "hold" (case-insensitive, tolerant of leading/trailing spaces)
    def is_excluded(status_val: str) -> bool:
        s = "" if status_val is None else str(status_val).strip().lower()
        return ("cancel" in s) or ("hold" in s)

    included = [r for r in deduped_rows if not is_excluded(r.get("status", ""))]

    # Group by year-month derived from event_date (YYYY-MM)
    summary = {}
    for r in included:
        ed = r.get("event_date", "")
        try:
            dt = datetime.strptime(str(ed).strip(), "%Y-%m-%d")
        except Exception:
            # Align with pandas to_datetime(errors='coerce'): invalid dates become NaT -> year_month NaN -> excluded from groupby
            continue
        ym = dt.strftime("%Y-%m")
        try:
            guests_val = float(str(r.get("guests", "")).strip())
            revenue_val = float(str(r.get("total_amount", "")).strip())
        except Exception:
            return None
        if ym not in summary:
            summary[ym] = {"count": 0, "revenue": 0.0, "guests_sum": 0.0}
        summary[ym]["count"] += 1
        summary[ym]["revenue"] += revenue_val
        summary[ym]["guests_sum"] += guests_val

    expected = {}
    for ym, vals in summary.items():
        count = vals["count"]
        revenue = vals["revenue"]
        avg_guests = (vals["guests_sum"] / count) if count > 0 else 0.0
        expected[ym] = {
            "total_confirmed_events": float(count),
            "total_revenue_confirmed": float(revenue),
            "avg_guests_per_event_confirmed": float(avg_guests),
        }
    return expected


def _parse_summary_csv(path: Path):
    headers, rows = _safe_read_csv_dicts(path)
    if headers is None:
        return None, []
    return headers, rows


def _is_sorted_year_month(rows):
    ym_list = [r.get("year_month", "") for r in rows]
    try:
        return ym_list == sorted(ym_list)
    except Exception:
        return False


def _float_equals(a: float, b: float, tol: float = 1e-9) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _extract_section(text: str, section_name: str) -> str:
    lines = text.splitlines()
    sec_start = -1
    pattern = re.compile(rf"^\s*#*\s*{re.escape(section_name)}\s*:?\s*$", re.IGNORECASE)
    for i, line in enumerate(lines):
        if pattern.search(line):
            sec_start = i + 1
            break
    if sec_start == -1:
        for i, line in enumerate(lines):
            if section_name.lower() in line.lower():
                sec_start = i + 1
                break
    if sec_start == -1:
        return ""
    collected = []
    for j in range(sec_start, len(lines)):
        l = lines[j]
        if j != sec_start and (re.match(r"^\s*#*\s*.+:\s*$", l) or re.match(r"^\s*#{1,6}\s+\S+", l)):
            break
        collected.append(l)
    return "\n".join(collected)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "fixed_script_exists": 0.0,
        "fixed_script_filters_status_trim_case": 0.0,
        "fixed_script_deduplicates": 0.0,
        "fixed_script_writes_correct_output_path": 0.0,
        "original_script_not_overwritten": 0.0,
        "summary_exists_and_header": 0.0,
        "summary_sorted_ascending": 0.0,
        "summary_values_correct": 0.0,
        "meeting_notes_exists_and_sections": 0.0,
        "meeting_notes_root_cause_cites_bug_line": 0.0,
        "meeting_notes_fix_summary_covers_points": 0.0,
        "meeting_notes_verification_lists_totals": 0.0,
        "meeting_notes_sanity_statement_excludes_cancel_hold": 0.0,
        "meeting_notes_action_items_count": 0.0,
    }

    bookings_csv = workspace / "data" / "bookings.csv"
    original_script = workspace / "scripts" / "monthly_report.py"
    fixed_script = workspace / "output" / "fixed_monthly_report.py"
    summary_csv = workspace / "output" / "monthly_summary.csv"
    meeting_notes = workspace / "output" / "meeting_notes.md"

    # Fixed script presence
    fixed_text = _safe_read_text(fixed_script)
    if fixed_text:
        scores["fixed_script_exists"] = 1.0
        # Check filtering with trimming and case-insensitive logic
        filt_ok = False
        # Presence of drop of cancelled/hold with case-insensitive and trimming
        # Accept patterns using .str.strip() and .str.lower() or case=False in contains
        has_strip = ".str.strip" in fixed_text or "strip(" in fixed_text
        has_case_insensitive = ("case=False" in fixed_text) or (".str.lower" in fixed_text) or ("lower()" in fixed_text)
        # Check that 'cancel' or 'hold' are referenced in filtering logic
        mentions_status = ("cancel" in fixed_text.lower() or "hold" in fixed_text.lower())
        if has_case_insensitive and mentions_status and has_strip:
            filt_ok = True
        scores["fixed_script_filters_status_trim_case"] = 1.0 if filt_ok else 0.0

        # Check drop duplicates
        dedup_ok = "drop_duplicates" in fixed_text
        scores["fixed_script_deduplicates"] = 1.0 if dedup_ok else 0.0

        # Check it writes to output/monthly_summary.csv
        out_path_ok = "output/monthly_summary.csv" in fixed_text.replace("\\", "/")
        scores["fixed_script_writes_correct_output_path"] = 1.0 if out_path_ok else 0.0

    # Ensure original script not overwritten only when fixed script exists (avoid awarding for pre-existing input)
    orig_text = _safe_read_text(original_script)
    if fixed_text and orig_text and "df = df[cancel_mask]" in orig_text:
        scores["original_script_not_overwritten"] = 1.0

    # Summary CSV checks
    headers, rows = _parse_summary_csv(summary_csv)
    expected_headers = [
        "year_month",
        "total_confirmed_events",
        "total_revenue_confirmed",
        "avg_guests_per_event_confirmed",
    ]
    if headers is not None and rows is not None and len(rows) > 0:
        if headers == expected_headers:
            scores["summary_exists_and_header"] = 1.0
        if _is_sorted_year_month(rows):
            scores["summary_sorted_ascending"] = 1.0

        # Verify values by recomputation
        expected = _compute_expected_summary(bookings_csv)
        if expected is not None:
            # Parse actual
            actual = {}
            try:
                for r in rows:
                    ym = str(r.get("year_month", "")).strip()
                    if not ym:
                        actual = None
                        break
                    def parse_float(v):
                        try:
                            s = str(v).strip()
                            return float(s)
                        except Exception:
                            return None
                    cnt = parse_float(r.get("total_confirmed_events", ""))
                    rev = parse_float(r.get("total_revenue_confirmed", ""))
                    avg = parse_float(r.get("avg_guests_per_event_confirmed", ""))
                    if None in (cnt, rev, avg):
                        actual = None
                        break
                    actual[ym] = {
                        "total_confirmed_events": cnt,
                        "total_revenue_confirmed": rev,
                        "avg_guests_per_event_confirmed": avg,
                    }
            except Exception:
                actual = None

            if actual is not None and set(actual.keys()) == set(expected.keys()):
                all_match = True
                for ym, exp_vals in expected.items():
                    act_vals = actual.get(ym)
                    if act_vals is None:
                        all_match = False
                        break
                    if not (_float_equals(exp_vals["total_confirmed_events"], act_vals["total_confirmed_events"])
                            and _float_equals(exp_vals["total_revenue_confirmed"], act_vals["total_revenue_confirmed"])
                            and _float_equals(exp_vals["avg_guests_per_event_confirmed"], act_vals["avg_guests_per_event_confirmed"])):
                        all_match = False
                        break
                if all_match:
                    scores["summary_values_correct"] = 1.0

    # Meeting notes checks
    notes_text = _safe_read_text(meeting_notes)
    if notes_text:
        required_sections = ["Issue summary", "Root cause", "Fix summary", "Verification", "Action items"]
        if all(sec.lower() in notes_text.lower() for sec in required_sections):
            scores["meeting_notes_exists_and_sections"] = 1.0

        if ("df = df[cancel_mask]" in notes_text) and ("scripts/monthly_report.py" in notes_text):
            scores["meeting_notes_root_cause_cites_bug_line"] = 1.0

        fix_section = _extract_section(notes_text, "Fix summary")
        if fix_section:
            has_path = "output/fixed_monthly_report.py" in fix_section
            has_filtering = ("filter" in fix_section.lower()) or ("exclude" in fix_section.lower())
            has_trim = ("trim" in fix_section.lower()) or ("strip" in fix_section.lower())
            has_case = ("case" in fix_section.lower()) or ("lower" in fix_section.lower()) or ("normalize" in fix_section.lower())
            has_dup = ("duplicate" in fix_section.lower()) or ("drop_duplicates" in fix_section.lower()) or ("de-dup" in fix_section.lower())
            if has_path and has_filtering and has_trim and has_case and has_dup:
                scores["meeting_notes_fix_summary_covers_points"] = 1.0

        ver_section = _extract_section(notes_text, "Verification")
        verify_totals_ok = False
        if ver_section and headers is not None and rows:
            per_month_checks = []
            for r in rows:
                ym = str(r.get("year_month", "")).strip()
                cnt_s = str(r.get("total_confirmed_events", "")).strip()
                rev_s = str(r.get("total_revenue_confirmed", "")).strip()
                avg_s = str(r.get("avg_guests_per_event_confirmed", "")).strip()
                if not ym:
                    per_month_checks.append(False)
                    continue
                present_all_numbers = (cnt_s in ver_section and rev_s in ver_section and avg_s in ver_section)
                ym_present = ym in ver_section
                per_month_checks.append(ym_present and present_all_numbers)
            verify_totals_ok = all(per_month_checks)
        if verify_totals_ok:
            scores["meeting_notes_verification_lists_totals"] = 1.0

        sanity_ok = False
        if re.search(r"cancel", notes_text, re.IGNORECASE) and re.search(r"hold", notes_text, re.IGNORECASE):
            if (re.search(r"no longer counted", notes_text, re.IGNORECASE)
                or re.search(r"\bnot counted\b", notes_text, re.IGNORECASE)
                or re.search(r"\bexcluded\b", notes_text, re.IGNORECASE)
                or re.search(r"removed from (the )?counts", notes_text, re.IGNORECASE)):
                sanity_ok = True
        if sanity_ok:
            scores["meeting_notes_sanity_statement_excludes_cancel_hold"] = 1.0

        ai_section = _extract_section(notes_text, "Action items")
        if ai_section:
            bullet_lines = [ln for ln in ai_section.splitlines() if re.match(r"^\s*[-*]\s+\S+", ln)]
            if 3 <= len(bullet_lines) <= 5:
                scores["meeting_notes_action_items_count"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()