import json
import sys
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            return rows
    except Exception:
        return None


def _parse_iso_date(s: str) -> Optional[datetime]:
    if s is None:
        return None
    s = s.strip()
    try:
        # Enforce exact ISO format YYYY-MM-DD
        dt = datetime.strptime(s, "%Y-%m-%d")
        # Ensure string matches zero-padded format strictly
        if s != dt.strftime("%Y-%m-%d"):
            return None
        return dt
    except Exception:
        return None


def _parse_positive_int(s: str) -> Optional[int]:
    if s is None:
        return None
    s = s.strip()
    if not s.isdigit():
        return None
    try:
        val = int(s)
        if val <= 0:
            return None
        return val
    except Exception:
        return None


def _round_two_decimals(x: float) -> float:
    # Standard rounding to two decimals; return float
    return round(x + 1e-12, 2)


def _round_nearest_int(x: float) -> int:
    return int(round(x))


def _compute_expected(workspace: Path) -> Optional[Dict[str, object]]:
    # Load inputs
    roster_path = workspace / "input" / "student_roster.csv"
    submissions_path = workspace / "input" / "submissions.csv"
    roster_rows = _read_csv_dicts(roster_path)
    submissions_rows = _read_csv_dicts(submissions_path)
    if roster_rows is None or submissions_rows is None:
        return None

    # Build roster mapping
    roster: Dict[str, str] = {}
    for r in roster_rows:
        sid = r.get("student_id", "").strip()
        grade = r.get("grade", "").strip()
        if sid:
            roster[sid] = grade

    # Expected issue counts
    issue_counts = {
        "invalid_deadline_date": 0,
        "invalid_submission_date": 0,
        "non_numeric_word_count": 0,
        "student_id_not_in_roster": 0,
    }

    # Structures for stats
    grades = set(roster.values())
    # We'll compute only for grades that have at least one roster-matched submission.
    grade_totals: Dict[str, int] = {}
    grade_valid_on_time_counts: Dict[str, int] = {}
    grade_on_time_submissions: Dict[str, int] = {}
    grade_word_counts: Dict[str, List[int]] = {}

    # Topic counts for roster-matched submissions
    topic_counts: Dict[str, int] = {}
    roster_matched_total = 0

    for s in submissions_rows:
        sid = (s.get("student_id") or "").strip()
        deadline_raw = (s.get("deadline_date") or "").strip()
        submission_raw = (s.get("submission_date") or "").strip()
        word_raw = (s.get("word_count") or "").strip()
        topic = (s.get("topic") or "").strip()

        in_roster = sid in roster
        if not in_roster:
            issue_counts["student_id_not_in_roster"] += 1
        else:
            roster_matched_total += 1
            # topic counts regardless of validity of dates/word_count
            if topic:
                topic_counts[topic] = topic_counts.get(topic, 0) + 1

            grade = roster[sid]
            grade_totals[grade] = grade_totals.get(grade, 0) + 1

            # Dates for on_time metrics
            deadline_dt = _parse_iso_date(deadline_raw)
            submission_dt = _parse_iso_date(submission_raw)
            if deadline_raw and deadline_dt is None:
                issue_counts["invalid_deadline_date"] += 1
            if submission_raw and submission_dt is None:
                issue_counts["invalid_submission_date"] += 1

            if deadline_dt is not None and submission_dt is not None:
                grade_valid_on_time_counts[grade] = grade_valid_on_time_counts.get(grade, 0) + 1
                if submission_dt <= deadline_dt:
                    grade_on_time_submissions[grade] = grade_on_time_submissions.get(grade, 0) + 1

            # Word count metrics
            wc = _parse_positive_int(word_raw)
            if word_raw and wc is None:
                issue_counts["non_numeric_word_count"] += 1
            if wc is not None:
                if grade not in grade_word_counts:
                    grade_word_counts[grade] = []
                grade_word_counts[grade].append(wc)
        # If not in roster, still check date/word to count issues? The task focuses on logging parsing issues including validation failures.
        # For expected counts, we follow the dataset to produce deterministic expected values as per provided inputs.

    # Build expected grade stats for grades that have at least one roster-matched submission
    expected_grade_stats: Dict[str, Dict[str, object]] = {}
    for grade, total_subs in grade_totals.items():
        valid_on_time = grade_valid_on_time_counts.get(grade, 0)
        on_time_subs = grade_on_time_submissions.get(grade, 0)
        on_time_rate = 0.0
        if valid_on_time > 0:
            on_time_rate = _round_two_decimals(on_time_subs / valid_on_time)
        # avg word count
        wc_list = grade_word_counts.get(grade, [])
        valid_for_avg = len(wc_list)
        avg_wc = 0
        if valid_for_avg > 0:
            avg_wc = _round_nearest_int(sum(wc_list) / valid_for_avg)
        expected_grade_stats[grade] = {
            "grade": grade,
            "total_submissions": total_subs,
            "valid_for_on_time": valid_on_time,
            "on_time_submissions": on_time_subs,
            "on_time_rate": on_time_rate,
            "valid_for_avg_word_count": valid_for_avg,
            "avg_word_count": avg_wc,
        }

    # Sort topic counts by submission_count descending for verification
    expected_topic_counts = dict(topic_counts)
    expected = {
        "grade_stats": expected_grade_stats,
        "topic_counts": expected_topic_counts,
        "topic_total": roster_matched_total,
        "issue_counts": issue_counts,
    }
    return expected


def _parse_grade_stats_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    rows = _read_csv_dicts(path)
    return rows


def _parse_topic_counts_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    rows = _read_csv_dicts(path)
    return rows


def _float_equal(a: float, b: float, tol: float = 0.005) -> bool:
    return abs(a - b) <= tol


def _extract_int_near_keywords(text: str, keywords_sets: List[List[str]]) -> Optional[int]:
    # Try to find a line containing all keywords from any set in keywords_sets and return first integer found in that line.
    for line in text.splitlines():
        l = line.lower()
        for keywords in keywords_sets:
            if all(k in l for k in keywords):
                m = re.search(r"(\d+)", line)
                if m:
                    try:
                        return int(m.group(1))
                    except Exception:
                        pass
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "outputs_created": 0.0,
        "grade_stats_structure": 0.0,
        "grade_stats_values": 0.0,
        "topic_counts_structure": 0.0,
        "topic_counts_values": 0.0,
        "topic_counts_sorted_desc": 0.0,
        "parse_log_issues_present": 0.0,
        "data_quality_report_counts": 0.0,
        "data_quality_report_quotes": 0.0,
        "data_quality_report_explanations": 0.0,
        "email_structure": 0.0,
        "email_content_on_time": 0.0,
        "email_content_avg_word": 0.0,
        "email_content_top_topic": 0.0,
        "email_content_caveat_next_step": 0.0,
    }

    # Paths for outputs
    out_dir = workspace / "outputs"
    grade_stats_path = out_dir / "grade_stats.csv"
    topic_counts_path = out_dir / "topic_counts.csv"
    parse_log_path = out_dir / "parse_log.txt"
    dq_report_path = out_dir / "data_quality_report.txt"
    email_path = out_dir / "email_to_principal.txt"

    # Check outputs existence
    required_files = [grade_stats_path, topic_counts_path, parse_log_path, dq_report_path, email_path]
    if all(p.exists() for p in required_files):
        scores["outputs_created"] = 1.0
    else:
        scores["outputs_created"] = 0.0

    # Compute expected from inputs
    expected = _compute_expected(workspace)
    if expected is None:
        # Without inputs, we cannot verify content; leave other scores at 0.0
        return scores

    # Validate grade_stats.csv structure and values
    grade_rows = _parse_grade_stats_csv(grade_stats_path) if grade_stats_path.exists() else None
    if grade_rows is not None and len(grade_rows) > 0:
        # Check header structure
        try:
            with grade_stats_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
        except Exception:
            header = []
        expected_header = ["grade", "total_submissions", "valid_for_on_time", "on_time_submissions", "on_time_rate", "valid_for_avg_word_count", "avg_word_count"]
        header_clean = [h.strip() for h in header]
        if header_clean == expected_header:
            scores["grade_stats_structure"] = 1.0

        # Build map by grade
        grade_map = {row.get("grade", "").strip(): row for row in grade_rows}
        # Expect exactly the grades found in expected grade stats
        expected_grades = set(expected["grade_stats"].keys())
        # Verify row count matches expected
        if set(grade_map.keys()) >= expected_grades and len(grade_map) == len(expected_grades):
            all_ok = True
            for g, exp in expected["grade_stats"].items():
                if g not in grade_map:
                    all_ok = False
                    break
                row = grade_map[g]
                # Compare integers
                def parse_int_field(name: str) -> Optional[int]:
                    v = row.get(name, "")
                    try:
                        return int(str(v).strip())
                    except Exception:
                        return None

                def parse_float_field(name: str) -> Optional[float]:
                    v = row.get(name, "")
                    try:
                        return float(str(v).strip())
                    except Exception:
                        return None

                ts = parse_int_field("total_submissions")
                v_on_time = parse_int_field("valid_for_on_time")
                ots = parse_int_field("on_time_submissions")
                rate = parse_float_field("on_time_rate")
                v_for_avg = parse_int_field("valid_for_avg_word_count")
                avg_wc = parse_int_field("avg_word_count")

                if ts is None or v_on_time is None or ots is None or rate is None or v_for_avg is None or avg_wc is None:
                    all_ok = False
                    break

                if ts != exp["total_submissions"]:
                    all_ok = False
                    break
                if v_on_time != exp["valid_for_on_time"]:
                    all_ok = False
                    break
                if ots != exp["on_time_submissions"]:
                    all_ok = False
                    break
                if not _float_equal(rate, float(exp["on_time_rate"]), tol=0.005):
                    all_ok = False
                    break
                if v_for_avg != exp["valid_for_avg_word_count"]:
                    all_ok = False
                    break
                if avg_wc != exp["avg_word_count"]:
                    all_ok = False
                    break

            if all_ok:
                scores["grade_stats_values"] = 1.0

    # Validate topic_counts.csv structure, values, and sorting
    topic_rows = _parse_topic_counts_csv(topic_counts_path) if topic_counts_path.exists() else None
    if topic_rows is not None and len(topic_rows) > 0:
        # Structure
        try:
            with topic_counts_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
        except Exception:
            header = []
        expected_header = ["topic", "submission_count", "share_of_total"]
        header_clean = [h.strip() for h in header]
        if header_clean == expected_header:
            scores["topic_counts_structure"] = 1.0

        # Values
        expected_topics = expected["topic_counts"]
        topic_map = {row.get("topic", "").strip(): row for row in topic_rows}
        # require exact same set of topics and same number of rows
        if set(topic_map.keys()) == set(expected_topics.keys()) and len(topic_rows) == len(expected_topics):
            values_ok = True
            for t, exp_count in expected_topics.items():
                row = topic_map.get(t)
                if not row:
                    values_ok = False
                    break
                # submission_count
                try:
                    scount = int(str(row.get("submission_count", "")).strip())
                except Exception:
                    values_ok = False
                    break
                if scount != exp_count:
                    values_ok = False
                    break
                # share_of_total rounded to 2 decimals
                try:
                    share_val = float(str(row.get("share_of_total", "")).strip())
                except Exception:
                    values_ok = False
                    break
                total = expected["topic_total"]
                exp_share = _round_two_decimals(exp_count / total if total else 0.0)
                if not _float_equal(share_val, exp_share, tol=0.005):
                    values_ok = False
                    break
            if values_ok:
                scores["topic_counts_values"] = 1.0

        # Sorted descending by submission_count
        try:
            counts = []
            for row in topic_rows:
                counts.append(int(str(row.get("submission_count", "")).strip()))
            non_increasing = all(counts[i] >= counts[i + 1] for i in range(len(counts) - 1))
            if non_increasing:
                scores["topic_counts_sorted_desc"] = 1.0
        except Exception:
            pass

    # Validate parse_log.txt issues presence
    parse_log_text = _read_text(parse_log_path) if parse_log_path.exists() else None
    if parse_log_text:
        log_lines = parse_log_text.lower().splitlines()
        def find_in_lines(must_have: List[str]) -> bool:
            for ln in log_lines:
                if all(token in ln for token in must_have):
                    return True
            return False

        has_invalid_deadline = find_in_lines(["invalid", "deadline"])
        has_invalid_submission = find_in_lines(["invalid", "submission"])
        # word_count non-numeric patterns
        has_word_issue = (find_in_lines(["word", "non"]) and find_in_lines(["word", "numeric"])) or find_in_lines(["word", "invalid"]) or find_in_lines(["word", "integer"])
        has_sid_issue = find_in_lines(["student", "not", "roster"]) or find_in_lines(["student_id", "not", "roster"]) or find_in_lines(["unknown", "student"])
        if has_invalid_deadline and has_invalid_submission and has_word_issue and has_sid_issue:
            scores["parse_log_issues_present"] = 1.0

    # Validate data_quality_report.txt
    dq_text = _read_text(dq_report_path) if dq_report_path.exists() else None
    if dq_text:
        # Counts
        expected_issue_counts = expected["issue_counts"]
        # Find numbers near keywords
        deadline_count = _extract_int_near_keywords(
            dq_text,
            keywords_sets=[["deadline", "invalid"], ["invalid", "deadline_date"]]
        )
        submission_count = _extract_int_near_keywords(
            dq_text,
            keywords_sets=[["submission", "invalid"], ["invalid", "submission_date"]]
        )
        # Try to find word_count non-numeric
        word_count_count = _extract_int_near_keywords(
            dq_text,
            keywords_sets=[["word", "non", "numeric"], ["word", "invalid"], ["word", "not", "integer"]]
        )
        student_roster_count = _extract_int_near_keywords(
            dq_text,
            keywords_sets=[["student", "not", "roster"], ["student_id", "not", "roster"], ["unknown", "student"]]
        )
        counts_ok = (
            deadline_count == expected_issue_counts["invalid_deadline_date"] and
            submission_count == expected_issue_counts["invalid_submission_date"] and
            word_count_count == expected_issue_counts["non_numeric_word_count"] and
            student_roster_count == expected_issue_counts["student_id_not_in_roster"]
        )
        if counts_ok:
            scores["data_quality_report_counts"] = 1.0

        # Quotes from parse_log.txt
        quotes_ok = False
        if parse_log_text:
            # find at least two distinct lines from parse_log present in dq report
            log_lines_full = [ln.strip() for ln in parse_log_text.splitlines() if ln.strip()]
            found = set()
            for ln in log_lines_full:
                if len(ln) >= 8 and ln in dq_text:
                    found.add(ln)
                if len(found) >= 2:
                    break
            if len(found) >= 2:
                quotes_ok = True
        if quotes_ok:
            scores["data_quality_report_quotes"] = 1.0

        # Explanations: look for impact on metrics
        lt = dq_text.lower()
        has_excluded = ("exclude" in lt) or ("excluded" in lt)
        has_on_time = ("on_time" in lt) or ("on-time" in lt) or ("on time" in lt)
        has_avg = ("average" in lt) or ("avg" in lt)
        if has_excluded and has_on_time and has_avg:
            scores["data_quality_report_explanations"] = 1.0

    # Validate email_to_principal.txt
    email_text = _read_text(email_path) if email_path.exists() else None
    if email_text:
        # Structure: under 180 words, intro line, 4 bullets
        words = re.findall(r"\b\w+\b", email_text)
        under_limit = len(words) <= 180
        lines = [ln.rstrip("\n\r") for ln in email_text.splitlines()]
        non_empty_lines = [ln for ln in lines if ln.strip()]
        intro_ok = False
        if non_empty_lines:
            first_line = non_empty_lines[0].lower()
            if "preliminary" in first_line and ("submission" in first_line or "submission patterns" in first_line):
                intro_ok = True
        bullet_lines = [ln.strip() for ln in lines if ln.strip().startswith("- ") or ln.strip().startswith("* ")]
        bullets_ok = len(bullet_lines) >= 4
        if under_limit and intro_ok and bullets_ok:
            scores["email_structure"] = 1.0

        # Content: on_time_rate bullet with a grade and numeric
        on_time_ok = False
        avg_word_ok = False
        top_topic_ok = False
        caveat_ok = False

        # Prepare expected on_time patterns
        expected_rates = {
            "9": 0.0,
            "10": 1.0,
            "11": 0.5,
            "12": 1.0,
        }
        rate_strings = {
            "9": ["0", "0.0", "0.00", "0%"],
            "10": ["1", "1.0", "1.00", "100%"],
            "11": ["0.5", "0.50", "50%"],
            "12": ["1", "1.0", "1.00", "100%"],
        }
        for bl in bullet_lines:
            bl_l = bl.lower()
            # on_time bullet: contains grade and on-time mention and a numeric value consistent with expected
            if (("on_time" in bl_l) or ("on-time" in bl_l) or ("on time" in bl_l)) and "grade" in bl_l:
                for g, strs in rate_strings.items():
                    if g in bl:
                        for rs in strs:
                            if rs in bl:
                                on_time_ok = True
                                break
                    if on_time_ok:
                        break
            # avg word count bullet
            if (("avg" in bl_l) or ("average" in bl_l)) and ("word" in bl_l):
                # look for a number
                if re.search(r"\d", bl):
                    avg_word_ok = True
            # top topic bullet
            if ("top" in bl_l or "most" in bl_l or "popular" in bl_l):
                if any(t in bl for t in ["Sports", "Academics", "Community", "Arts"]):
                    top_topic_ok = True
            # caveat + next step
            if ("caveat" in bl_l or "data quality" in bl_l or "invalid" in bl_l or "date" in bl_l or "non-numeric" in bl_l or "student" in bl_l):
                if ("recommend" in bl_l or "next" in bl_l or "plan" in bl_l or "fix" in bl_l or "clean" in bl_l):
                    caveat_ok = True

        if on_time_ok:
            scores["email_content_on_time"] = 1.0
        if avg_word_ok:
            scores["email_content_avg_word"] = 1.0
        if top_topic_ok:
            scores["email_content_top_topic"] = 1.0
        if caveat_ok:
            scores["email_content_caveat_next_step"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()