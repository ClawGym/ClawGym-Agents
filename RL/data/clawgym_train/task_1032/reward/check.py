import csv
import json
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        if not rows:
            # Empty CSV (no data rows)
            return [], None
        return rows, None
    except Exception as e:
        return None, str(e)


class VolunteerHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_cells: List[str] = []
        self.current_cell_data: List[str] = []
        self.rows: List[List[str]] = []

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "tbody":
            self.in_tbody = True
        elif self.in_tbody and t == "tr":
            self.in_tr = True
            self.current_cells = []
        elif self.in_tr and t == "td":
            self.in_td = True
            self.current_cell_data = []

    def handle_endtag(self, tag):
        t = tag.lower()
        if t == "tbody":
            self.in_tbody = False
        elif self.in_tbody and t == "tr":
            if self.in_tr and len(self.current_cells) >= 3:
                self.rows.append(self.current_cells[:3])
            self.in_tr = False
            self.current_cells = []
        elif self.in_tr and t == "td":
            if self.in_td:
                cell = "".join(self.current_cell_data).strip()
                self.current_cells.append(cell)
            self.in_td = False
            self.current_cell_data = []

    def handle_data(self, data):
        if self.in_td:
            self.current_cell_data.append(data)


def _parse_volunteers_html(path: Path) -> Tuple[Optional[Dict[str, Dict]], Optional[str]]:
    text = _safe_read_text(path)
    if text is None:
        return None, "volunteers.html not readable"
    try:
        parser = VolunteerHTMLParser()
        parser.feed(text)
        volunteers: Dict[str, Dict] = {}
        for row in parser.rows:
            # Expect Name, MaxShifts, AvailableShifts
            if len(row) < 3:
                continue
            name = row[0].strip()
            try:
                max_shifts = int(row[1].strip())
            except Exception:
                return None, f"Invalid MaxShifts for volunteer {name}"
            av_raw = row[2].strip()
            if av_raw == "":
                av_list = []
            else:
                av_list = [s.strip() for s in av_raw.split(",")]
            volunteers[name] = {"MaxShifts": max_shifts, "AvailableShifts": set(av_list)}
        if not volunteers:
            return None, "No volunteer rows found"
        return volunteers, None
    except Exception as e:
        return None, str(e)


def _parse_shifts_csv(path: Path) -> Tuple[Optional[Dict[str, Dict]], Optional[str]]:
    rows, err = _safe_read_csv_dicts(path)
    if rows is None:
        return None, err or "Failed to read shifts.csv"
    if len(rows) == 0:
        return None, "No shift rows found"
    required_cols = ["ShiftID", "Date", "StartTime", "EndTime", "DurationHours", "RequiredCount"]
    for col in required_cols:
        if col not in rows[0].keys():
            return None, f"Missing column {col}"
    shifts: Dict[str, Dict] = {}
    try:
        for r in rows:
            sid = r["ShiftID"].strip()
            date = r["Date"].strip()
            start = r["StartTime"].strip()
            end = r["EndTime"].strip()
            dur = float(str(r["DurationHours"]).strip())
            req = int(str(r["RequiredCount"]).strip())
            shifts[sid] = {
                "ShiftID": sid,
                "Date": date,
                "StartTime": start,
                "EndTime": end,
                "DurationHours": dur,
                "RequiredCount": req,
            }
        if not shifts:
            return None, "No shift rows found"
        return shifts, None
    except Exception as e:
        return None, f"Error parsing shifts.csv: {e}"


def _compute_duration_hours(start_time: str, end_time: str) -> Optional[float]:
    try:
        fmt = "%H:%M"
        start_dt = datetime.strptime(start_time, fmt)
        end_dt = datetime.strptime(end_time, fmt)
        delta = end_dt - start_dt
        hours = delta.total_seconds() / 3600.0
        return hours
    except Exception:
        return None


def _read_assignments_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    rows, err = _safe_read_csv_dicts(path)
    if rows is None:
        return None, err or "Failed to read assignments.csv"
    # Validate header exact match
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            expected = ["ShiftID", "Date", "StartTime", "EndTime", "VolunteerName"]
            if header != expected:
                return None, f"Invalid header: expected {expected}, got {header}"
    except Exception as e:
        return None, f"Failed header read: {e}"
    # Ensure required columns exist in dict rows
    for col in ["ShiftID", "Date", "StartTime", "EndTime", "VolunteerName"]:
        if len(rows) == 0 or col not in rows[0].keys():
            return None, f"Missing column {col}"
    return rows, None


def _compute_coverage(shifts: Dict[str, Dict], assignments: List[Dict[str, str]]) -> Tuple[Dict[str, int], int, int, List[str]]:
    per_shift_counts: Dict[str, int] = {sid: 0 for sid in shifts.keys()}
    for row in assignments:
        sid = row.get("ShiftID", "").strip()
        if sid in per_shift_counts:
            per_shift_counts[sid] += 1
    total_required = sum(shifts[sid]["RequiredCount"] for sid in shifts.keys())
    filled_clipped = sum(min(per_shift_counts[sid], shifts[sid]["RequiredCount"]) for sid in shifts.keys())
    uncovered_shifts = [sid for sid in shifts.keys() if per_shift_counts[sid] < shifts[sid]["RequiredCount"]]
    return per_shift_counts, total_required, filled_clipped, uncovered_shifts


def _extract_section(text: str, title: str, titles: List[str]) -> Optional[str]:
    # Find a section by its title and return text until the next title or end
    idx = text.find(title)
    if idx == -1:
        return None
    start = idx + len(title)
    end = len(text)
    for t in titles:
        if t == title:
            continue
        j = text.find(t, start)
        if j != -1 and j < end:
            end = j
    return text[start:end]


def _compute_fairness_optimum(shifts: Dict[str, Dict], volunteers: Dict[str, Dict]) -> Tuple[bool, int, Optional[int]]:
    # Build slots list
    slots: List[str] = []
    for sid, info in shifts.items():
        slots.extend([sid] * int(info["RequiredCount"]))
    # Compute eligibles per shiftID
    eligibles: Dict[str, List[str]] = {}
    for sid in shifts.keys():
        names = []
        for name, v in volunteers.items():
            if sid in v["AvailableShifts"] and v["MaxShifts"] > 0:
                names.append(name)
        eligibles[sid] = names
    # Order slots by smallest eligible set size
    slots_ordered = sorted(slots, key=lambda s: len(eligibles.get(s, [])))
    counts = {name: 0 for name in volunteers.keys()}
    best = {"found": False, "min_diff": None}  # type: ignore

    def backtrack(i: int):
        if i == len(slots_ordered):
            maxc = max(counts.values()) if counts else 0
            minc = min(counts.values()) if counts else 0
            diff = maxc - minc
            if best["min_diff"] is None or diff < best["min_diff"]:
                best["min_diff"] = diff
                best["found"] = True
            return
        sid = slots_ordered[i]
        for name in eligibles.get(sid, []):
            if counts[name] < volunteers[name]["MaxShifts"]:
                counts[name] += 1
                backtrack(i + 1)
                counts[name] -= 1
        # If no eligible assignments, cannot fill this slot in this branch

    backtrack(0)
    if best["found"]:
        return True, len(slots_ordered), int(best["min_diff"]) if best["min_diff"] is not None else 0

    # If full coverage not possible, compute partial best coverage and best diff among those
    best_partial = {"max_filled": 0, "min_diff": None}  # type: ignore

    def backtrack_partial(i: int, filled: int):
        if i == len(slots_ordered):
            if filled > best_partial["max_filled"]:
                best_partial["max_filled"] = filled
                maxc = max(counts.values()) if counts else 0
                minc = min(counts.values()) if counts else 0
                best_partial["min_diff"] = maxc - minc
            elif filled == best_partial["max_filled"]:
                maxc = max(counts.values()) if counts else 0
                minc = min(counts.values()) if counts else 0
                diff = maxc - minc
                if best_partial["min_diff"] is None or diff < best_partial["min_diff"]:
                    best_partial["min_diff"] = diff
            return
        sid = slots_ordered[i]
        # Option: skip this slot
        backtrack_partial(i + 1, filled)
        # Try assignment options
        for name in eligibles.get(sid, []):
            if counts[name] < volunteers[name]["MaxShifts"]:
                counts[name] += 1
                backtrack_partial(i + 1, filled + 1)
                counts[name] -= 1

    backtrack_partial(0, 0)
    return False, best_partial["max_filled"], int(best_partial["min_diff"]) if best_partial["min_diff"] is not None else 0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "assignments_csv_exists_and_schema": 0.0,
        "assignment_exact_required_counts_met": 0.0,
        "assignment_respects_availability": 0.0,
        "assignment_respects_max_shifts": 0.0,
        "assignment_times_match_inputs": 0.0,
        "assignment_unique_volunteer_per_shift": 0.0,
        "coverage_report_sections_present": 0.0,
        "coverage_report_summary_consistent_with_assignments": 0.0,
        "coverage_report_per_volunteer_sorted_and_counts": 0.0,
        "coverage_report_data_validation_section_accuracy": 0.0,
        "email_to_brandon_references_and_length": 0.0,
        "email_to_brandon_mentions_coverage_and_issues": 0.0,
        "fairness_balance_score": 0.0,
    }

    # Load inputs
    shifts_path = workspace / "input" / "shifts.csv"
    volunteers_path = workspace / "input" / "volunteers.html"

    shifts, _ = _parse_shifts_csv(shifts_path) if shifts_path.exists() else (None, "missing shifts.csv")
    volunteers, _ = _parse_volunteers_html(volunteers_path) if volunteers_path.exists() else (None, "missing volunteers.html")

    # Outputs: assignments.csv
    assignments_path = workspace / "outputs" / "assignments.csv"
    assignments_rows, _ = _read_assignments_csv(assignments_path) if assignments_path.exists() else (None, "assignments.csv missing")
    if assignments_rows is not None:
        scores["assignments_csv_exists_and_schema"] = 1.0

    # Evaluate assignments if all inputs and assignments present
    exact_coverage_ok = False
    availability_ok = False
    maxshifts_ok = False
    times_match_ok = False
    unique_per_shift_ok = False
    per_shift_counts: Dict[str, int] = {}
    uncovered_shifts: List[str] = []
    total_required = 0
    filled_clipped = 0
    if shifts is not None and volunteers is not None and assignments_rows is not None:
        # Times and IDs match inputs for each row
        times_match_ok = True
        for row in assignments_rows:
            sid = row.get("ShiftID", "").strip()
            date = row.get("Date", "").strip()
            start = row.get("StartTime", "").strip()
            end = row.get("EndTime", "").strip()
            if sid not in shifts:
                times_match_ok = False
                break
            sinfo = shifts[sid]
            if not (sinfo["Date"] == date and sinfo["StartTime"] == start and sinfo["EndTime"] == end):
                times_match_ok = False
                break
        scores["assignment_times_match_inputs"] = 1.0 if times_match_ok else 0.0

        # Availability and volunteer existence
        availability_ok = True
        for row in assignments_rows:
            name = row.get("VolunteerName", "").strip()
            sid = row.get("ShiftID", "").strip()
            if name not in volunteers:
                availability_ok = False
                break
            if sid not in volunteers[name]["AvailableShifts"]:
                availability_ok = False
                break
        scores["assignment_respects_availability"] = 1.0 if availability_ok else 0.0

        # MaxShifts
        assigned_counts_by_volunteer = {name: 0 for name in volunteers.keys()}
        for row in assignments_rows:
            name = row.get("VolunteerName", "").strip()
            if name in assigned_counts_by_volunteer:
                assigned_counts_by_volunteer[name] += 1
        maxshifts_ok = True
        for name, v in volunteers.items():
            if assigned_counts_by_volunteer.get(name, 0) > v["MaxShifts"]:
                maxshifts_ok = False
                break
        scores["assignment_respects_max_shifts"] = 1.0 if maxshifts_ok else 0.0

        # Unique volunteer per shift
        unique_per_shift_ok = True
        seen_pairs: Dict[str, set] = {}
        for row in assignments_rows:
            sid = row.get("ShiftID", "").strip()
            name = row.get("VolunteerName", "").strip()
            if sid not in seen_pairs:
                seen_pairs[sid] = set()
            if name in seen_pairs[sid]:
                unique_per_shift_ok = False
                break
            seen_pairs[sid].add(name)
        scores["assignment_unique_volunteer_per_shift"] = 1.0 if unique_per_shift_ok else 0.0

        # Coverage
        per_shift_counts, total_required, filled_clipped, uncovered_shifts = _compute_coverage(shifts, assignments_rows)
        exact_coverage_ok = True
        for sid, info in shifts.items():
            if per_shift_counts.get(sid, 0) != info["RequiredCount"]:
                exact_coverage_ok = False
                break
        scores["assignment_exact_required_counts_met"] = 1.0 if exact_coverage_ok else 0.0

    # coverage_report.md checks
    coverage_report_path = workspace / "outputs" / "coverage_report.md"
    cov_text = _safe_read_text(coverage_report_path) if coverage_report_path.exists() else None
    if cov_text is not None:
        # Sections presence
        required_sections = ["Coverage Summary", "Per-Volunteer Assignments", "Fairness Metrics", "Data Validation"]
        sections_ok = all(s in cov_text for s in required_sections)
        scores["coverage_report_sections_present"] = 1.0 if sections_ok else 0.0

        # Summary consistency
        consistency_ok = False
        if shifts is not None and assignments_rows is not None:
            total_shifts = len(shifts)
            _, total_required_num, filled_clipped_num, uncovered = _compute_coverage(shifts, assignments_rows)
            # String check
            # Require exact numbers to appear and coverage status mention
            found_numbers = str(total_shifts) in cov_text and str(total_required_num) in cov_text and str(filled_clipped_num) in cov_text
            if exact_coverage_ok:
                status_ok = ("All covered" in cov_text)
                consistency_ok = found_numbers and status_ok
            else:
                status_ok = True
                for sid in uncovered:
                    if sid not in cov_text:
                        status_ok = False
                        break
                consistency_ok = found_numbers and status_ok
        scores["coverage_report_summary_consistent_with_assignments"] = 1.0 if consistency_ok else 0.0

        # Per-Volunteer section sorted and counts/hours included
        per_vol_ok = False
        if volunteers is not None and assignments_rows is not None:
            section = _extract_section(cov_text, "Per-Volunteer Assignments", required_sections)
            if section is not None:
                lines = [ln.strip() for ln in section.splitlines() if ln.strip()]
                # Build assigned counts and hours
                dur_map = {sid: shifts[sid]["DurationHours"] for sid in shifts} if shifts is not None else {}
                by_vol_assigns: Dict[str, int] = {name: 0 for name in volunteers.keys()}
                by_vol_hours: Dict[str, float] = {name: 0.0 for name in volunteers.keys()}
                for row in assignments_rows:
                    nm = row.get("VolunteerName", "").strip()
                    sid = row.get("ShiftID", "").strip()
                    if nm in by_vol_assigns:
                        by_vol_assigns[nm] += 1
                        if shifts is not None and sid in dur_map:
                            by_vol_hours[nm] += float(dur_map[sid])
                # Check names in sorted order
                names_sorted = sorted(volunteers.keys())
                name_positions: Dict[str, int] = {}
                for n in names_sorted:
                    # Find first occurrence of name in section
                    idx = -1
                    for i, ln in enumerate(lines):
                        if n in ln:
                            idx = i
                            break
                    if idx == -1:
                        name_positions = {}
                        break
                    name_positions[n] = idx
                if name_positions and all(name_positions[names_sorted[i]] <= name_positions[names_sorted[i+1]] for i in range(len(names_sorted)-1)):
                    # Check that each line with a volunteer contains their count and hours
                    per_vol_ok = True
                    for n in names_sorted:
                        count = by_vol_assigns.get(n, 0)
                        hours = by_vol_hours.get(n, 0.0)
                        # Accept hours as either integer or with one decimal if .0
                        hours_int = int(round(hours))
                        hour_strs = {str(hours_int), f"{hours_int}.0", f"{hours:.1f}", f"{hours:.2f}"}
                        # find a line with the name and containing count and one of hours representations
                        found_line = False
                        for ln in lines:
                            if n in ln and str(count) in ln and any(hs in ln for hs in hour_strs):
                                found_line = True
                                break
                        if not found_line:
                            per_vol_ok = False
                            break
        scores["coverage_report_per_volunteer_sorted_and_counts"] = 1.0 if per_vol_ok else 0.0

        # Data Validation section accuracy
        data_val_ok = False
        if shifts is not None and volunteers is not None:
            # Compute actual validations
            durations_ok = True
            for sid, info in shifts.items():
                comp = _compute_duration_hours(info["StartTime"], info["EndTime"])
                if comp is None or abs(comp - float(info["DurationHours"])) > 1e-6:
                    durations_ok = False
                    break
            refs_ok = True
            invalid_refs: List[str] = []
            for name, v in volunteers.items():
                for sid in v["AvailableShifts"]:
                    if sid not in shifts:
                        refs_ok = False
                        invalid_refs.append(sid)
            section = _extract_section(cov_text, "Data Validation", required_sections)
            if section is not None:
                section_lower = section.lower()
                # Ensure the section mentions duration and shift references
                mentions_duration = ("durationhours" in section_lower) or ("duration" in section_lower)
                mentions_refs = ("shiftid" in section_lower) or ("reference" in section_lower)
                if durations_ok and refs_ok:
                    mentions_none = ("none" in section_lower)
                    data_val_ok = mentions_duration and mentions_refs and mentions_none
                else:
                    # Expect mention of issues
                    has_issue_terms = any(term in section_lower for term in ["mismatch", "invalid", "error", "anomal"])
                    has_ids = any(sid in section for sid in invalid_refs)
                    data_val_ok = mentions_duration and mentions_refs and (has_issue_terms or has_ids)
        scores["coverage_report_data_validation_section_accuracy"] = 1.0 if data_val_ok else 0.0

    # email_to_brandon checks
    email_path = workspace / "outputs" / "email_to_brandon.txt"
    email_text = _safe_read_text(email_path) if email_path.exists() else None
    if email_text is not None:
        # References and length
        words = re.findall(r"\b\w+\b", email_text)
        word_count = len(words)
        mentions_assignments = "assignments.csv" in email_text
        mentions_report = "coverage_report.md" in email_text
        # To Brandon Bryant (presence)
        name_ok = ("Brandon Bryant" in email_text) or (("Brandon" in email_text) and ("Bryant" in email_text))
        length_ok = word_count <= 200
        scores["email_to_brandon_references_and_length"] = 1.0 if all([mentions_assignments, mentions_report, name_ok, length_ok]) else 0.0

        # Coverage and issues mention
        cov_ok = False
        if shifts is not None and assignments_rows is not None:
            if exact_coverage_ok:
                cov_ok = ("All covered" in email_text) or ("covered" in email_text.lower())
            else:
                # expect mention of uncovered/gaps
                cov_ok = ("uncovered" in email_text.lower()) or ("gap" in email_text.lower()) or ("not filled" in email_text.lower())
        # Fairness high-level mention
        fairness_mention = ("fair" in email_text.lower()) or ("balance" in email_text.lower()) or ("distribution" in email_text.lower())
        scores["email_to_brandon_mentions_coverage_and_issues"] = 1.0 if (cov_ok and fairness_mention) else 0.0

    # Fairness balance score (only if assignments valid enough)
    if shifts is not None and volunteers is not None and assignments_rows is not None and availability_ok and maxshifts_ok and times_match_ok:
        # Compute current assigned diff among known volunteers
        counts = {name: 0 for name in volunteers.keys()}
        for row in assignments_rows:
            name = row.get("VolunteerName", "").strip()
            if name in counts:
                counts[name] += 1
        assigned_diff = (max(counts.values()) - min(counts.values())) if counts else 0
        opt_full_possible, opt_covered_slots, opt_min_diff = _compute_fairness_optimum(shifts, volunteers)
        filled_slots = filled_clipped
        fairness_score = 0.0
        if exact_coverage_ok and opt_full_possible and opt_min_diff is not None:
            if assigned_diff == opt_min_diff:
                fairness_score = 1.0
            elif assigned_diff == opt_min_diff + 1:
                fairness_score = 0.5
            else:
                fairness_score = 0.0
        elif not opt_full_possible:
            if filled_slots == opt_covered_slots:
                if opt_min_diff is not None and assigned_diff == opt_min_diff:
                    fairness_score = 1.0
                else:
                    fairness_score = 0.5
            else:
                fairness_score = 0.0
        else:
            fairness_score = 0.0
        scores["fairness_balance_score"] = float(fairness_score)
    else:
        scores["fairness_balance_score"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()