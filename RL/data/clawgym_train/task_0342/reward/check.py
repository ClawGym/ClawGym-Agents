import json
import csv
import re
import sys
from pathlib import Path
from statistics import median


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None


def list_meeting_dates(input_meetings_dir: Path):
    dates = []
    if not input_meetings_dir.exists():
        return []
    for p in input_meetings_dir.iterdir():
        if p.is_dir():
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name):
                dates.append(p.name)
    # Sort descending by date string
    dates.sort(reverse=True)
    # Select top 3 most recent
    return dates[:3]


def count_unique_rows(rows):
    seen = set()
    count = 0
    for r in rows:
        # Use tuple of fields to define uniqueness; preserve columns as per attendance.csv
        key = (r.get("name", ""), r.get("role", ""), r.get("department", ""))
        if key not in seen:
            seen.add(key)
            count += 1
    return count


def compute_meeting_stats(workspace: Path, dates):
    stats = {}
    total_attendance = []
    total_vacancy_mentions = 0
    vacancy_mentions_by_meeting = {}
    action_items_by_meeting = {}

    for d in dates:
        meeting_dir = workspace / "input" / "meetings" / d
        attendance_csv = meeting_dir / "attendance.csv"
        minutes_md = meeting_dir / "minutes.md"

        # Attendance
        header, rows = read_csv_dicts(attendance_csv)
        if header is None or rows is None:
            attendees_total = None
            grad_count = None
            undergrad_count = None
            staff_count = None
            community_count = None
        else:
            attendees_total = count_unique_rows(rows)
            # Count roles literally as provided
            role_counts = {"grad": 0, "undergrad": 0, "staff": 0, "community": 0}
            # If roles have other values, we ignore them for the four categories
            for r in rows:
                role = r.get("role", "")
                if role in role_counts:
                    role_counts[role] += 1
            grad_count = role_counts["grad"]
            undergrad_count = role_counts["undergrad"]
            staff_count = role_counts["staff"]
            community_count = role_counts["community"]
            total_attendance.append(attendees_total)

        # Minutes
        minutes_text = read_text(minutes_md) or ""
        # Count occurrences of substring "vacan" (case-insensitive)
        vacancy_mentions = len(re.findall(r"vacan", minutes_text, flags=re.IGNORECASE))
        vacancy_mentions_by_meeting[d] = vacancy_mentions
        total_vacancy_mentions += vacancy_mentions

        # Count action items: lines starting with "- [ ]" or "- [x]" (case-insensitive for x)
        action_items = 0
        for line in minutes_text.splitlines():
            if re.match(r"^\s*-\s*\[\s\]", line):
                action_items += 1
            elif re.match(r"^\s*-\s*\[(x|X)\]", line):
                action_items += 1
        action_items_by_meeting[d] = action_items

        stats[d] = {
            "attendees_total": attendees_total,
            "grad_count": grad_count,
            "undergrad_count": undergrad_count,
            "staff_count": staff_count,
            "community_count": community_count,
            "vacancy_mentions": vacancy_mentions,
            "action_items": action_items,
        }

    avg_attendance = None
    med_attendance = None
    if total_attendance and all(isinstance(x, int) for x in total_attendance):
        avg_attendance = sum(total_attendance) / len(total_attendance)
        med_attendance = median(total_attendance)

    aggregates = {
        "meetings_analyzed": dates,
        "average_attendance": avg_attendance,
        "median_attendance": med_attendance,
        "total_vacancy_mentions": total_vacancy_mentions,
        "vacancy_mentions_by_meeting": vacancy_mentions_by_meeting,
        "action_items_by_meeting": action_items_by_meeting,
    }
    return stats, aggregates


def approx_equal_num(a, b, tol=1e-6):
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def contains_path_or_line_match(text: str, date: str, filename: str) -> bool:
    if text is None:
        return False
    # Accept if full path or date/filename segment appears anywhere
    patterns = [
        f"input/meetings/{date}/{filename}",
        f"{date}/{filename}",
    ]
    for pat in patterns:
        if pat in text:
            return True
    # Otherwise, accept if there is a line that contains both the date and the filename
    for line in text.splitlines():
        if date in line and filename in line:
            return True
    return False


def word_count(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\b\w+\b", text))


def line_has_word_and_number(line: str, word_substr: str, expected_number: float) -> bool:
    if word_substr.lower() not in line.lower():
        return False
    # Find numbers in the line (integers or floats)
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?", line)
    for n in nums:
        try:
            val = float(n)
            if abs(val - expected_number) <= 1e-6:
                return True
        except Exception:
            continue
    return False


def contains_any_vacancy_related_phrase(text: str) -> bool:
    if not text:
        return False
    phrases = [
        "call for nominations",
        "nomination",
        "vacant seats",
        "email departments",
        "faq for prospective nominees",
        "update website with role descriptions",
        "highlight the nomination form",
        "departmental newsletters",
        "tabling at graduate commons",
    ]
    t = text.lower()
    return any(p in t for p in phrases)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "discovery_inventory_exists": 0.0,
        "discovery_includes_three_most_recent_dates": 0.0,
        "discovery_lists_files_2024_10_01": 0.0,
        "discovery_lists_files_2024_10_08": 0.0,
        "discovery_lists_files_2024_10_15": 0.0,
        "attendance_summary_exists": 0.0,
        "attendance_summary_header_correct": 0.0,
        "attendance_summary_rows_three_meetings": 0.0,
        "attendance_summary_counts_correct": 0.0,
        "aggregates_json_exists": 0.0,
        "aggregates_fields_present": 0.0,
        "aggregates_values_correct": 0.0,
        "summary_file_exists": 0.0,
        "summary_word_count_leq_250": 0.0,
        "summary_includes_three_dates": 0.0,
        "summary_mentions_average_and_median": 0.0,
        "summary_mentions_total_vacancy_mentions": 0.0,
        "summary_includes_vacancy_related_action_items": 0.0,
        "rewritten_email_exists": 0.0,
        "rewritten_email_has_note_header_with_date": 0.0,
        "rewritten_email_kept_subject_line": 0.0,
        "rewritten_email_no_placeholders_remaining": 0.0,
        "rewritten_email_includes_three_dates": 0.0,
        "rewritten_email_mentions_average_attendance": 0.0,
        "rewritten_email_mentions_total_vacancy_mentions": 0.0,
    }

    # Determine expected three most recent meetings from input
    input_meetings_dir = workspace / "input" / "meetings"
    expected_dates = list_meeting_dates(input_meetings_dir)
    # For deterministic grading with provided materials, expect exactly these:
    expected_dates_set = set(expected_dates)

    # Compute expected stats from inputs
    stats, aggregates_expected = compute_meeting_stats(workspace, expected_dates)

    # Discovery inventory checks
    inventory_path = workspace / "output" / "discovery" / "file_inventory.txt"
    if inventory_path.exists():
        scores["discovery_inventory_exists"] = 1.0
        inv_text = read_text(inventory_path) or ""
        # includes three most recent dates
        if expected_dates and all(d in inv_text for d in expected_dates):
            scores["discovery_includes_three_most_recent_dates"] = 1.0
        else:
            # If no expected dates (e.g., missing inputs), leave as 0.0
            pass
        # Per-date files presence
        # For robustness, directly reference known dates from the provided inputs if present
        for d, key in [
            ("2024-10-01", "discovery_lists_files_2024_10_01"),
            ("2024-10-08", "discovery_lists_files_2024_10_08"),
            ("2024-10-15", "discovery_lists_files_2024_10_15"),
        ]:
            if d in expected_dates_set:
                has_att = contains_path_or_line_match(inv_text, d, "attendance.csv")
                has_min = contains_path_or_line_match(inv_text, d, "minutes.md")
                if has_att and has_min:
                    scores[key] = 1.0
            else:
                # If this date isn't among the three most recent, it's not required
                scores[key] = 0.0
    else:
        # Missing inventory file leaves checks at 0.0
        pass

    # Attendance summary CSV checks
    summary_csv = workspace / "output" / "stats" / "attendance_summary.csv"
    if summary_csv.exists():
        scores["attendance_summary_exists"] = 1.0
        header, rows = read_csv_dicts(summary_csv)
        expected_header = [
            "meeting_date",
            "attendees_total",
            "grad_count",
            "undergrad_count",
            "staff_count",
            "community_count",
        ]
        if header == expected_header:
            scores["attendance_summary_header_correct"] = 1.0

        if rows is not None:
            # Check exactly three meetings
            dates_in_csv = [r.get("meeting_date") for r in rows if "meeting_date" in r]
            if expected_dates and set(dates_in_csv) == set(expected_dates) and len(rows) == 3:
                scores["attendance_summary_rows_three_meetings"] = 1.0

            # Validate counts for each meeting
            counts_ok = True
            if expected_dates:
                for r in rows:
                    d = r.get("meeting_date")
                    if d not in stats or stats[d]["attendees_total"] is None:
                        counts_ok = False
                        break
                    try:
                        a = int(r.get("attendees_total", ""))
                        g = int(r.get("grad_count", ""))
                        u = int(r.get("undergrad_count", ""))
                        s = int(r.get("staff_count", ""))
                        c = int(r.get("community_count", ""))
                    except Exception:
                        counts_ok = False
                        break
                    if not (
                        a == stats[d]["attendees_total"]
                        and g == stats[d]["grad_count"]
                        and u == stats[d]["undergrad_count"]
                        and s == stats[d]["staff_count"]
                        and c == stats[d]["community_count"]
                    ):
                        counts_ok = False
                        break
            else:
                # No expected dates; cannot validate counts
                counts_ok = False

            if counts_ok:
                scores["attendance_summary_counts_correct"] = 1.0
    else:
        # Missing CSV; scores remain 0.0
        pass

    # Aggregates JSON checks
    aggregates_path = workspace / "output" / "stats" / "aggregates.json"
    if aggregates_path.exists():
        scores["aggregates_json_exists"] = 1.0
        data = load_json(aggregates_path)
        if isinstance(data, dict):
            required_fields = [
                "meetings_analyzed",
                "average_attendance",
                "median_attendance",
                "total_vacancy_mentions",
                "vacancy_mentions_by_meeting",
                "action_items_by_meeting",
            ]
            if all(k in data for k in required_fields):
                scores["aggregates_fields_present"] = 1.0

            values_ok = True
            if expected_dates:
                # meetings_analyzed set equality (order independent)
                try:
                    if set(data.get("meetings_analyzed", [])) != set(expected_dates):
                        values_ok = False
                except Exception:
                    values_ok = False

                # average and median attendance
                if aggregates_expected["average_attendance"] is None:
                    values_ok = False
                else:
                    if not approx_equal_num(
                        data.get("average_attendance"),
                        aggregates_expected["average_attendance"],
                    ):
                        values_ok = False
                    if not approx_equal_num(
                        data.get("median_attendance"),
                        aggregates_expected["median_attendance"],
                    ):
                        values_ok = False

                # vacancy mentions by meeting
                vm = data.get("vacancy_mentions_by_meeting")
                if not isinstance(vm, dict):
                    values_ok = False
                else:
                    # exact mapping for dates
                    for d in expected_dates:
                        if d not in vm or vm[d] != aggregates_expected["vacancy_mentions_by_meeting"][d]:
                            values_ok = False
                            break

                # action items by meeting
                ai = data.get("action_items_by_meeting")
                if not isinstance(ai, dict):
                    values_ok = False
                else:
                    for d in expected_dates:
                        if d not in ai or ai[d] != aggregates_expected["action_items_by_meeting"][d]:
                            values_ok = False
                            break

                # total vacancy mentions
                if data.get("total_vacancy_mentions") != aggregates_expected["total_vacancy_mentions"]:
                    values_ok = False
            else:
                values_ok = False

            if values_ok:
                scores["aggregates_values_correct"] = 1.0

    # Summary file checks
    summary_md = workspace / "output" / "gsc_meeting_summary.md"
    if summary_md.exists():
        scores["summary_file_exists"] = 1.0
        text = read_text(summary_md) or ""
        # word count <= 250
        if word_count(text) <= 250:
            scores["summary_word_count_leq_250"] = 1.0
        # includes three dates
        if expected_dates and all(d in text for d in expected_dates):
            scores["summary_includes_three_dates"] = 1.0
        # mentions average and median
        text_lower = text.lower()
        if "average" in text_lower and "median" in text_lower:
            scores["summary_mentions_average_and_median"] = 1.0
        # mentions total vacancy mentions (7) near "vacan"
        if expected_dates:
            expected_total_vac = aggregates_expected["total_vacancy_mentions"]
            found = False
            for line in text.splitlines():
                if "vacan" in line.lower():
                    if re.search(rf"\b{expected_total_vac}\b", line):
                        found = True
                        break
            if found:
                scores["summary_mentions_total_vacancy_mentions"] = 1.0
        # includes 1–3 salient action items related to the vacancies
        if contains_any_vacancy_related_phrase(text):
            scores["summary_includes_vacancy_related_action_items"] = 1.0
    # else missing summary; scores remain 0.0

    # Rewritten email checks
    rewritten_email = workspace / "output" / "rewritten_email_to_gsc.md"
    if rewritten_email.exists():
        scores["rewritten_email_exists"] = 1.0
        email_text = read_text(rewritten_email) or ""
        email_lines = email_text.splitlines()
        # Note header line at the very top with ISO date
        if email_lines:
            m = re.match(r"^Note: Generated from input/draft_email_to_gsc\.md on (\d{4}-\d{2}-\d{2})$", email_lines[0])
            if m:
                scores["rewritten_email_has_note_header_with_date"] = 1.0
        # Subject line kept
        if any(line.strip() == "Subject: Interested in GSC seat?" for line in email_lines):
            scores["rewritten_email_kept_subject_line"] = 1.0
        # No placeholders remaining
        placeholders = [
            "[DEPARTMENT]",
            "[insert 2-3 relevant points from recent meetings here]",
            "[YOUR NAME]",
            "[PROGRAM]",
        ]
        if not any(ph in email_text for ph in placeholders):
            scores["rewritten_email_no_placeholders_remaining"] = 1.0
        # Includes three meeting dates
        if expected_dates and all(d in email_text for d in expected_dates):
            scores["rewritten_email_includes_three_dates"] = 1.0
        # Mentions average attendance value (10) near "average"
        avg_ok = False
        if expected_dates:
            expected_avg = aggregates_expected["average_attendance"]
            if expected_avg is not None:
                for line in email_lines:
                    if line_has_word_and_number(line, "averag", expected_avg):
                        avg_ok = True
                        break
        if avg_ok:
            scores["rewritten_email_mentions_average_attendance"] = 1.0
        # Mentions total vacancy mentions near "vacan"
        vac_ok = False
        if expected_dates:
            expected_total_vac = aggregates_expected["total_vacancy_mentions"]
            for line in email_lines:
                if "vacan" in line.lower():
                    if re.search(rf"\b{expected_total_vac}\b", line):
                        vac_ok = True
                        break
        if vac_ok:
            scores["rewritten_email_mentions_total_vacancy_mentions"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()