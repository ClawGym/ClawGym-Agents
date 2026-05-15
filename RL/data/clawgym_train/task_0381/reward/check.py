import json
import csv
import sys
import re
from pathlib import Path
from statistics import median


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _compute_summary_from_csv(rows):
    try:
        total = len(rows)
        if total == 0:
            return {
                "total_associates": 0,
                "avg_pto_used_hours": 0.0,
                "median_pto_used_hours": 0.0,
                "percent_with_future_days_booked": 0,
            }
        pto_used = [float(r["pto_used_hours_ytd"]) for r in rows]
        future = [int(r["future_days_booked"]) for r in rows]
        avg_pto = round(sum(pto_used) / total, 1)
        med_pto = round(median(pto_used), 1)
        with_future = sum(1 for d in future if d > 0)
        # Match Python round behavior used in the provided script
        percent_future = int(round((with_future / total) * 100))
        return {
            "total_associates": total,
            "avg_pto_used_hours": avg_pto,
            "median_pto_used_hours": med_pto,
            "percent_with_future_days_booked": percent_future,
        }
    except Exception:
        return None


def _find_by_the_numbers_header(lines):
    for idx, line in enumerate(lines):
        s = line.strip().lower()
        if s == "by the numbers" or s == "by the numbers:":
            return idx
    return None


def _is_bullet_line(s: str) -> bool:
    stripped = s.lstrip()
    return stripped.startswith("- ") or stripped.startswith("• ")


def _group_consecutive_bullets(lines):
    groups = []
    current = []
    for line in lines:
        if _is_bullet_line(line):
            current.append(line.strip())
        else:
            if current:
                groups.append(current)
                current = []
    if current:
        groups.append(current)
    return groups


def _extract_numeric_after_colon(line: str, expect_percent: bool = False):
    # Expect format: Label: <value>
    if ":" not in line:
        return None
    label_part, value_part = line.split(":", 1)
    value_part = value_part.strip()
    if expect_percent:
        if not value_part.endswith("%"):
            return None
        num_str = value_part[:-1].strip()
        try:
            return int(num_str)
        except Exception:
            return None
    else:
        # parse float or int
        try:
            if re.fullmatch(r"[+-]?\d+", value_part):
                return float(int(value_part))
            else:
                return float(value_part)
        except Exception:
            return None


def _labels_match_in_order(lines_after_header, json_data):
    expected = [
        ("Associates", "total_associates", False),
        ("Avg PTO used (hours)", "avg_pto_used_hours", False),
        ("Median PTO used (hours)", "median_pto_used_hours", False),
        ("Associates with future days booked (%)", "percent_with_future_days_booked", True),
    ]
    non_empty = [ln for ln in lines_after_header if ln.strip() != ""]
    if len(non_empty) < 4:
        return False
    # Check exactly next four lines match the expected labels and values
    for i, (label, key, is_percent) in enumerate(expected):
        line = non_empty[i]
        if not line.startswith(f"{label}:"):
            return False
        val = _extract_numeric_after_colon(line, expect_percent=is_percent)
        if val is None:
            return False
        # Compare to JSON data
        if key not in json_data:
            return False
        json_val = json_data[key]
        if is_percent:
            try:
                if int(json_val) != int(val):
                    return False
            except Exception:
                return False
        else:
            try:
                # Compare numerically with exact float equality to the JSON value
                if float(json_val) != float(val):
                    return False
            except Exception:
                return False
        # Also ensure no trailing content beyond the value (allowing trailing spaces)
        # For percent, ensure exactly one trailing %.
        # Already validated by parsing and start with label
    # Ensure no additional recognized label line immediately follows (to keep it exactly four lines)
    if len(non_empty) > 4:
        next_line = non_empty[4]
        next_starts = any(next_line.startswith(f"{lbl}:") for (lbl, _, _) in expected)
        if next_starts:
            return False
    return True


def _check_policy_bullet_group(group_lines: list) -> bool:
    # group_lines are bullet lines like "- ..." or "• ...", stripped
    # We need exactly one group with exactly three lines matching three facts.
    if len(group_lines) != 3:
        return False
    # Normalize content
    bullets = [ln[1:].strip() if ln.startswith("-") or ln.startswith("•") else ln for ln in group_lines]
    bullets_lower = [b.lower() for b in bullets]

    # Fact 1: Annual PTO allotment 200 hours
    def fact1(s):
        s = s.lower()
        return ("pto" in s) and ("200" in s) and ("hour" in s)

    # Fact 2: Up to 3 consecutive business days off without partner pre-approval when scheduled at least 3 business days in advance and coverage arranged.
    def fact2(s):
        s = s.lower()
        # Look for two occurrences of "3"
        count_3 = s.count("3")
        has_consecutive = "consecutive" in s
        has_business = "business" in s
        has_advance = "advance" in s
        has_coverage = "coverage" in s
        has_preapproval = ("pre-approval" in s) or ("preapproval" in s)
        has_partner = "partner" in s
        return (count_3 >= 2) and has_consecutive and has_business and has_advance and has_coverage and has_preapproval and has_partner

    # Fact 3: At least one uninterrupted 5-day period off per year
    def fact3(s):
        s = s.lower()
        has_five = ("5-day" in s) or ("5 day" in s) or (re.search(r"\b5\b", s) is not None)
        has_uninterrupted = "uninterrupted" in s
        return has_five and has_uninterrupted

    matched = [False, False, False]
    for s in bullets:
        if not matched[0] and fact1(s):
            matched[0] = True
            continue
        if not matched[1] and fact2(s):
            matched[1] = True
            continue
        if not matched[2] and fact3(s):
            matched[2] = True
            continue
    return all(matched)


def _find_policy_bullets(lines: list) -> bool:
    groups = _group_consecutive_bullets(lines)
    for g in groups:
        if _check_policy_bullet_group(g):
            return True
    return False


def _contains_first_person_plural(text: str) -> bool:
    # Check for whole words 'we' or 'our'
    return re.search(r"\bwe\b", text, flags=re.IGNORECASE) is present or re.search(r"\bour\b", text, flags=re.IGNORECASE) is not None


def _first_person_plural(text: str) -> bool:
    return (re.search(r"\bwe\b", text, flags=re.IGNORECASE) is not None) or (re.search(r"\bour\b", text, flags=re.IGNORECASE) is not None)


def _encouragement_present(text: str) -> bool:
    # Look for 'schedule' or 'calendar' or the explicit preferred phrase
    t = text.lower()
    return ("schedule" in t) or ("calendar" in t) or ("time off" in t)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "pto_summary_exists_and_valid": 0.0,
        "pto_summary_values_match_input": 0.0,
        "email_file_exists": 0.0,
        "subject_preserved": 0.0,
        "signature_preserved": 0.0,
        "by_the_numbers_section_correct": 0.0,
        "policy_bullets_present_and_correct": 0.0,
        "preferred_phrases_included": 0.0,
        "avoid_phrases_absent": 0.0,
        "first_person_plural_used": 0.0,
        "encouragement_included": 0.0,
    }

    # Paths
    json_path = workspace / "output" / "pto_summary.json"
    email_path = workspace / "output" / "wellness_email.txt"
    csv_path = workspace / "input" / "pto_snapshot.csv"

    # Load JSON
    json_data = _load_json(json_path)
    if isinstance(json_data, dict):
        # Validate keys and types (numeric)
        required_keys = [
            "total_associates",
            "avg_pto_used_hours",
            "median_pto_used_hours",
            "percent_with_future_days_booked",
        ]
        has_all = all(k in json_data for k in required_keys)
        types_ok = True
        if has_all:
            try:
                _ = int(json_data["total_associates"])
                _ = float(json_data["avg_pto_used_hours"])
                _ = float(json_data["median_pto_used_hours"])
                _ = int(json_data["percent_with_future_days_booked"])
            except Exception:
                types_ok = False
        if has_all and types_ok:
            scores["pto_summary_exists_and_valid"] = 1.0

    # Compare JSON with recomputed from CSV
    rows = _load_csv_rows(csv_path)
    if rows is not None and isinstance(json_data, dict):
        expected_summary = _compute_summary_from_csv(rows)
        if expected_summary is not None:
            try:
                match = (
                    int(json_data.get("total_associates", -1)) == int(expected_summary["total_associates"])
                    and float(json_data.get("avg_pto_used_hours", -9999)) == float(expected_summary["avg_pto_used_hours"])
                    and float(json_data.get("median_pto_used_hours", -9999)) == float(expected_summary["median_pto_used_hours"])
                    and int(json_data.get("percent_with_future_days_booked", -1)) == int(expected_summary["percent_with_future_days_booked"])
                )
                if match:
                    scores["pto_summary_values_match_input"] = 1.0
            except Exception:
                pass

    # Email existence
    email_text = _read_text(email_path)
    if email_text is not None:
        scores["email_file_exists"] = 1.0

    # If email exists, run further checks
    if email_text is not None:
        lines = email_text.splitlines()

        # Subject preserved: check first non-empty line equals exact subject
        subject_expected = "Subject: Wellness Week and Vacation Reminders"
        first_nonempty = None
        for ln in lines:
            if ln.strip() != "":
                first_nonempty = ln
                break
        if first_nonempty == subject_expected:
            scores["subject_preserved"] = 1.0

        # Signature preserved: last non-empty line equals exact signature
        signature_expected = "— Jordan Avery, Partner"
        last_nonempty = None
        for ln in reversed(lines):
            if ln.strip() != "":
                last_nonempty = ln
                break
        if last_nonempty == signature_expected:
            scores["signature_preserved"] = 1.0

        # By the numbers section correctness
        if isinstance(json_data, dict):
            idx = _find_by_the_numbers_header(lines)
            if idx is not None:
                after = lines[idx + 1 :]
                if _labels_match_in_order(after, json_data):
                    scores["by_the_numbers_section_correct"] = 1.0

        # Policy bullets present and correct
        if _find_policy_bullets(lines):
            scores["policy_bullets_present_and_correct"] = 1.0

        # Preferred phrases and avoid phrases
        preferred_phrases = [
            "We support you in taking uninterrupted time away.",
            "Your well-being comes first.",
            "Please put your time off on the calendar.",
            "We will plan coverage together.",
        ]
        avoid_phrases = [
            "as workload permits",
            "subject to client demands",
            "only if necessary",
            "if you really need it",
        ]

        preferred_count = 0
        for p in preferred_phrases:
            if p in email_text:
                preferred_count += 1
        if preferred_count >= 2:
            scores["preferred_phrases_included"] = 1.0

        avoid_found = False
        lower_email = email_text.lower()
        for a in avoid_phrases:
            if a in lower_email:
                avoid_found = True
                break
        if not avoid_found:
            scores["avoid_phrases_absent"] = 1.0

        # First-person plural usage
        if _first_person_plural(email_text):
            scores["first_person_plural_used"] = 1.0

        # Encouragement present
        if _encouragement_present(email_text):
            scores["encouragement_included"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()