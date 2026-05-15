import json
import sys
import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            # Ensure headers are present and not empty
            if reader.fieldnames is None or any(h is None or h == "" for h in reader.fieldnames):
                return None
            return rows
    except Exception:
        return None


def _load_json(path: Path) -> Optional[object]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_lecture_topics(md_path: Path) -> Optional[List[str]]:
    text = _read_text(md_path)
    if text is None:
        return None
    topics: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            topic = stripped[2:].strip()
            if topic:
                topics.append(topic)
    return topics if topics else None


def _parse_question_bank(csv_path: Path) -> Optional[Dict[str, Dict[str, object]]]:
    rows = _read_csv_dicts(csv_path)
    if rows is None:
        return None
    bank: Dict[str, Dict[str, object]] = {}
    required_cols = {"id", "prompt", "topic", "nominal_difficulty", "type"}
    # Validate columns
    header = set(rows[0].keys()) if rows else set()
    if not required_cols.issubset(header):
        return None
    try:
        for r in rows:
            qid = r["id"].strip()
            prom = r["prompt"].strip()
            topic = r["topic"].strip()
            ndiff = int(r["nominal_difficulty"])
            qtype = r["type"].strip()
            if qid in bank:
                return None
            bank[qid] = {
                "prompt": prom,
                "topic": topic,
                "nominal_difficulty": ndiff,
                "type": qtype,
            }
    except Exception:
        return None
    return bank


def _compute_empirical_difficulty(past_csv_path: Path) -> Optional[Dict[str, float]]:
    rows = _read_csv_dicts(past_csv_path)
    if rows is None:
        return None
    required_cols = {"student_id", "question_id", "correct"}
    header = set(rows[0].keys()) if rows else set()
    if not required_cols.issubset(header):
        return None
    sums: Dict[str, int] = {}
    counts: Dict[str, int] = {}
    try:
        for r in rows:
            qid = r["question_id"].strip()
            correct_val = r["correct"].strip()
            if correct_val not in {"0", "1"}:
                # malformed
                return None
            c = int(correct_val)
            counts[qid] = counts.get(qid, 0) + 1
            sums[qid] = sums.get(qid, 0) + c
        diffs: Dict[str, float] = {}
        for qid, cnt in counts.items():
            mean = sums[qid] / cnt if cnt > 0 else 0.0
            diffs[qid] = 1.0 - mean
        return diffs
    except Exception:
        return None


def _parse_validation_report(path: Path) -> Optional[List[Dict[str, object]]]:
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    # Validate exact columns
    expected_cols = ["question_id", "topic", "type", "empirical_difficulty", "nominal_difficulty"]
    if not rows:
        return None
    header_cols = list(rows[0].keys())
    if header_cols != expected_cols:
        return None
    parsed: List[Dict[str, object]] = []
    try:
        for r in rows:
            qid = r["question_id"].strip()
            topic = r["topic"].strip()
            qtype = r["type"].strip()
            emp = float(r["empirical_difficulty"])
            ndiff = int(r["nominal_difficulty"])
            parsed.append({
                "question_id": qid,
                "topic": topic,
                "type": qtype,
                "empirical_difficulty": emp,
                "nominal_difficulty": ndiff,
            })
    except Exception:
        return None
    return parsed


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "validation_report_structure": 0.0,
        "validation_report_data_correctness": 0.0,
        "selected_count_and_uniqueness": 0.0,
        "topics_coverage_constraints": 0.0,
        "types_constraints": 0.0,
        "difficulty_band_constraint": 0.0,
        "midterm_exam_contains_questions": 0.0,
        "midterm_exam_fields_per_question": 0.0,
        "summary_stats_alignment": 0.0,
        "email_includes_required_info": 0.0,
    }

    # Paths
    lecture_md = workspace / "input" / "lecture_outline.md"
    qbank_csv = workspace / "input" / "question_bank.csv"
    past_csv = workspace / "input" / "past_results.csv"

    out_midterm = workspace / "output" / "midterm_exam.md"
    out_report = workspace / "output" / "validation_report.csv"
    out_summary = workspace / "output" / "summary_stats.json"
    out_email = workspace / "output" / "email_to_ta.txt"

    topics_list = _parse_lecture_topics(lecture_md)
    qbank = _parse_question_bank(qbank_csv)
    ediffs = _compute_empirical_difficulty(past_csv)
    report_rows = _parse_validation_report(out_report)

    # Early checks for report structure
    if report_rows is not None:
        scores["validation_report_structure"] = 1.0

    # Prepare selected set if available
    selected_ids: List[str] = []
    if report_rows is not None:
        selected_ids = [row["question_id"] for row in report_rows]

    # Verify selected count and uniqueness (exactly 10 rows and 10 unique ids)
    if report_rows is not None:
        all_ids_unique = len(selected_ids) == len(set(selected_ids))
        if len(report_rows) == 10 and all_ids_unique:
            scores["selected_count_and_uniqueness"] = 1.0

    # Validate report data correctness vs inputs
    report_data_ok = False
    if report_rows is not None and qbank is not None and ediffs is not None:
        data_ok = True
        for row in report_rows:
            qid = row["question_id"]
            # Must exist in bank and ediffs
            if qid not in qbank or qid not in ediffs:
                data_ok = False
                break
            # Topic, type, nominal_difficulty should match bank
            bi = qbank[qid]
            if row["topic"] != bi["topic"]:
                data_ok = False
                break
            if row["type"] != bi["type"]:
                data_ok = False
                break
            if row["nominal_difficulty"] != bi["nominal_difficulty"]:
                data_ok = False
                break
            # empirical_difficulty should match recomputed
            if not _float_equal(row["empirical_difficulty"], ediffs[qid]):
                data_ok = False
                break
        if data_ok:
            scores["validation_report_data_correctness"] = 1.0
            report_data_ok = True

    # Constraints: topics coverage, types, difficulty band
    if report_data_ok and topics_list is not None:
        allowed_topics = set(topics_list)
        # Topic inclusion constraints
        # Only allowed topics
        selected_topics = [row["topic"] for row in report_rows]
        only_allowed = all(t in allowed_topics for t in selected_topics)
        # At least one per topic
        counts_per_topic: Dict[str, int] = {}
        for t in selected_topics:
            counts_per_topic[t] = counts_per_topic.get(t, 0) + 1
        atleast_one_each = all(counts_per_topic.get(t, 0) >= 1 for t in topics_list)
        # No more than 3 per topic
        at_most_three = all(counts_per_topic.get(t, 0) <= 3 for t in counts_per_topic)
        if only_allowed and atleast_one_each and at_most_three:
            scores["topics_coverage_constraints"] = 1.0

        # Types constraint
        counts_by_type: Dict[str, int] = {}
        for row in report_rows:
            typ = row["type"]
            counts_by_type[typ] = counts_by_type.get(typ, 0) + 1
        at_least_4_mcq = counts_by_type.get("MCQ", 0) >= 4
        at_least_4_sa = counts_by_type.get("Short Answer", 0) >= 4
        if at_least_4_mcq and at_least_4_sa:
            scores["types_constraints"] = 1.0

        # Difficulty band average
        if len(report_rows) == 10:
            avg_emp = sum(r["empirical_difficulty"] for r in report_rows) / 10.0
            if 0.40 - 1e-9 <= avg_emp <= 0.60 + 1e-9:
                scores["difficulty_band_constraint"] = 1.0

    # Midterm exam content checks
    md_text = _read_text(out_midterm)
    if md_text is not None and report_rows is not None and qbank is not None:
        # Check that md includes exactly the selected question ids (no extras, no missing)
        found_ids = set(re.findall(r"\bqb\d{3}\b", md_text))
        expected_ids = set(selected_ids)
        if found_ids == expected_ids and len(expected_ids) == 10:
            scores["midterm_exam_contains_questions"] = 1.0

        # For each selected question, ensure id, prompt, type, and topic appear in the file
        all_present = True
        for row in report_rows:
            qid = row["question_id"]
            info = qbank.get(qid)
            if info is None:
                all_present = False
                break
            required_strings = [qid, info["prompt"], info["type"], info["topic"]]
            for s in required_strings:
                if s not in md_text:
                    all_present = False
                    break
            if not all_present:
                break
        if all_present:
            scores["midterm_exam_fields_per_question"] = 1.0

    # Summary stats consistency
    summary = _load_json(out_summary)
    if summary is not None and report_rows is not None and topics_list is not None:
        try:
            # Extract values from summary
            total_questions = summary.get("total_questions", None)
            avg_emp_val = summary.get("average_empirical_difficulty", None)
            per_topic_counts = summary.get("per_topic_counts", None)
            counts_by_type_json = summary.get("counts_by_type", None)
            missing_topics = summary.get("missing_topics", None)

            # Validate existence and types
            def _to_float(x):
                if isinstance(x, (int, float)):
                    return float(x)
                if isinstance(x, str):
                    return float(x.strip())
                raise ValueError()

            if (
                isinstance(total_questions, int)
                and per_topic_counts is not None and isinstance(per_topic_counts, dict)
                and counts_by_type_json is not None and isinstance(counts_by_type_json, dict)
                and isinstance(missing_topics, list)
            ):
                # Compute expected from report_rows
                expected_total = len(report_rows)
                avg_emp = sum(r["empirical_difficulty"] for r in report_rows) / float(expected_total) if expected_total > 0 else 0.0
                expected_avg_rounded = round(avg_emp, 3)
                # Allow avg_emp_val numeric or numeric string
                avg_ok = False
                try:
                    avg_val_float = _to_float(avg_emp_val)
                    avg_ok = _float_equal(avg_val_float, expected_avg_rounded, tol=1e-9)
                except Exception:
                    avg_ok = False

                # Per-topic counts expected for represented topics only (non-zero)
                counts_per_topic_calc: Dict[str, int] = {}
                for r in report_rows:
                    t = r["topic"]
                    counts_per_topic_calc[t] = counts_per_topic_calc.get(t, 0) + 1
                # Validate no extraneous topics beyond allowed
                allowed_topics_set = set(topics_list)
                per_topic_keys = set(per_topic_counts.keys())
                if not per_topic_keys.issubset(allowed_topics_set):
                    per_topic_ok = False
                else:
                    # Validate counts for provided keys
                    per_topic_ok = True
                    for k, v in per_topic_counts.items():
                        if not isinstance(v, int):
                            per_topic_ok = False
                            break
                        if counts_per_topic_calc.get(k, 0) != v:
                            per_topic_ok = False
                            break

                # counts_by_type must include only MCQ and Short Answer keys (if present) and counts match
                counts_by_type_calc: Dict[str, int] = {}
                for r in report_rows:
                    typ = r["type"]
                    counts_by_type_calc[typ] = counts_by_type_calc.get(typ, 0) + 1
                allowed_types = {"MCQ", "Short Answer"}
                types_keys = set(counts_by_type_json.keys())
                if not types_keys.issubset(allowed_types):
                    types_ok = False
                else:
                    types_ok = True
                    for k, v in counts_by_type_json.items():
                        if not isinstance(v, int):
                            types_ok = False
                            break
                        if counts_by_type_calc.get(k, 0) != v:
                            types_ok = False
                            break

                # missing_topics should equal topics with zero representation among allowed topics
                missing_expected = sorted([t for t in topics_list if counts_per_topic_calc.get(t, 0) == 0])
                missing_ok = sorted([str(x) for x in missing_topics]) == missing_expected

                if (
                    total_questions == expected_total
                    and avg_ok
                    and per_topic_ok
                    and types_ok
                    and missing_ok
                ):
                    scores["summary_stats_alignment"] = 1.0
        except Exception:
            pass

    # Email content checks
    email_text = _read_text(out_email)
    if email_text is not None and report_rows is not None and topics_list is not None:
        email_ok = True
        # Must include TA name "Maris"
        if "Maris" not in email_text:
            email_ok = False
        # Must include file paths of generated artifacts
        for p in ["output/midterm_exam.md", "output/validation_report.csv", "output/summary_stats.json"]:
            if p not in email_text:
                email_ok = False
                break
        # Include total questions (10) and notion of total
        if "total" not in email_text.lower():
            email_ok = False
        # Check presence of number 10
        if not re.search(r"\b10\b", email_text):
            email_ok = False
        # Include per-topic counts (at least topic names)
        for t in topics_list:
            if t not in email_text:
                email_ok = False
                break
        # Include counts by type names
        if ("MCQ" not in email_text) or ("Short Answer" not in email_text):
            email_ok = False
        # Include average empirical difficulty rounded to 3 decimals
        try:
            avg_emp = sum(r["empirical_difficulty"] for r in report_rows) / float(len(report_rows)) if report_rows else 0.0
            avg_str = f"{round(avg_emp, 3):.3f}"
            if avg_str not in email_text:
                email_ok = False
        except Exception:
            email_ok = False

        if email_ok:
            scores["email_includes_required_info"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()