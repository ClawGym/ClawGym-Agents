import json
import csv
import sys
import re
import subprocess
from pathlib import Path
from typing import Tuple, List, Dict, Optional


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[dict]:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def safe_read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    try:
        with path.open(newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None, None


def approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def run_validator(workspace: Path) -> Tuple[bool, str, str]:
    validator = workspace / "input" / "validate_critiques.py"
    csv_path = workspace / "input" / "fall2025_critiques.csv"
    if not validator.exists() or not csv_path.exists():
        return False, "", ""
    try:
        result = subprocess.run(
            [sys.executable, str(validator), str(csv_path)],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=10
        )
        return True, result.stdout, result.stderr
    except Exception:
        return False, "", ""


def parse_validator_errors(text: str) -> Dict[int, List[str]]:
    errors: Dict[int, List[str]] = {}
    if not text:
        return errors
    for line in text.splitlines():
        m = re.match(r"ROW\s+(\d+):\s*(.+)", line.strip())
        if m:
            rownum = int(m.group(1))
            reason = m.group(2).strip()
            errors.setdefault(rownum, []).append(reason)
    return errors


def get_invalid_ids_from_rows(header: List[str], rows: List[List[str]], invalid_rows: List[int]) -> List[str]:
    student_id_idx = header.index("student_id") if "student_id" in header else 0
    ids = []
    for rn in invalid_rows:
        data_idx = rn - 2
        if 0 <= data_idx < len(rows):
            ids.append(rows[data_idx][student_id_idx])
    return ids


def compute_expected_from_raw(workspace: Path) -> Optional[dict]:
    csv_path = workspace / "input" / "fall2025_critiques.csv"
    header, rows = safe_read_csv(csv_path)
    if header is None or rows is None:
        return None
    ok, out, err = run_validator(workspace)
    if not ok:
        return None
    invalid_map = parse_validator_errors(err)
    invalid_rows = sorted(invalid_map.keys())
    invalid_ids = set(get_invalid_ids_from_rows(header, rows, invalid_rows))
    student_id_idx = header.index("student_id")
    assignment_idx = header.index("assignment")
    medium_idx = header.index("medium")
    fi_idx = header.index("faith_integration_score")
    ae_idx = header.index("aesthetic_score")
    cleaned_rows = []
    for r in rows:
        sid = r[student_id_idx]
        if sid in invalid_ids:
            continue
        cleaned_rows.append(r)
    assn_stats: Dict[str, Dict[str, float]] = {}
    for r in cleaned_rows:
        assn = r[assignment_idx]
        try:
            fi = float(r[fi_idx])
            ae = float(r[ae_idx])
        except Exception:
            return None
        s = assn_stats.setdefault(assn, {"n": 0, "sum_fi": 0.0, "sum_ae": 0.0})
        s["n"] += 1
        s["sum_fi"] += fi
        s["sum_ae"] += ae
    summary_by_assignment = {}
    for assn, s in assn_stats.items():
        n = int(s["n"])
        avg_fi = s["sum_fi"] / n if n > 0 else 0.0
        avg_ae = s["sum_ae"] / n if n > 0 else 0.0
        summary_by_assignment[assn] = {"n_submissions": n, "avg_fi": avg_fi, "avg_ae": avg_ae}
    medium_counts: Dict[str, int] = {}
    for r in cleaned_rows:
        m = r[medium_idx]
        medium_counts[m] = medium_counts.get(m, 0) + 1
    total_valid = len(cleaned_rows)
    total_invalid = len(invalid_rows)
    high_fi = 0
    sum_fi = 0.0
    sum_ae = 0.0
    for r in cleaned_rows:
        try:
            fi = float(r[fi_idx])
            ae = float(r[ae_idx])
        except Exception:
            return None
        if fi >= 4:
            high_fi += 1
        sum_fi += fi
        sum_ae += ae
    share_high = (high_fi / total_valid) if total_valid > 0 else 0.0
    overall_mean_fi = (sum_fi / total_valid) if total_valid > 0 else 0.0
    overall_mean_ae = (sum_ae / total_valid) if total_valid > 0 else 0.0
    return {
        "header": header,
        "rows": rows,
        "invalid_rows": invalid_rows,
        "invalid_ids": invalid_ids,
        "cleaned_rows": cleaned_rows,
        "summary_by_assignment": summary_by_assignment,
        "medium_counts": medium_counts,
        "overall": {
            "total_valid": total_valid,
            "total_invalid": total_invalid,
            "share_high": share_high,
            "mean_fi": overall_mean_fi,
            "mean_ae": overall_mean_ae,
        }
    }


def parse_numeric(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def load_summary_by_assignment(path: Path) -> Optional[Dict[str, Dict[str, float]]]:
    header, rows = safe_read_csv(path)
    if header is None or rows is None:
        return None
    expected_header = ["assignment", "n_submissions", "avg_faith_integration_score", "avg_aesthetic_score"]
    if [h.strip() for h in header] != expected_header:
        return None
    mapping: Dict[str, Dict[str, float]] = {}
    for r in rows:
        if len(r) != 4:
            return None
        assn = r[0].strip()
        n = parse_numeric(r[1])
        avg_fi = parse_numeric(r[2])
        avg_ae = parse_numeric(r[3])
        if assn == "" or n is None or avg_fi is None or avg_ae is None:
            return None
        mapping[assn] = {"n": int(round(n)), "avg_fi": float(avg_fi), "avg_ae": float(avg_ae)}
    return mapping


def load_medium_counts(path: Path) -> Optional[Dict[str, int]]:
    header, rows = safe_read_csv(path)
    if header is None or rows is None:
        return None
    expected_header = ["medium", "count"]
    if [h.strip() for h in header] != expected_header:
        return None
    mapping: Dict[str, int] = {}
    for r in rows:
        if len(r) != 2:
            return None
        m = r[0].strip()
        c = parse_numeric(r[1])
        if m == "" or c is None:
            return None
        mapping[m] = int(round(float(c)))
    return mapping


def load_cleaned_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    return safe_read_csv(path)


def extract_first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "validation_log_present_and_contains_expected": 0.0,
        "cleaned_csv_structure_correct": 0.0,
        "cleaned_csv_exclusion_correct": 0.0,
        "summary_by_assignment_correct": 0.0,
        "medium_counts_correct": 0.0,
        "overall_stats_json_correct": 0.0,
        "report_exclusions_and_reasons": 0.0,
        "report_highest_assignment": 0.0,
        "report_top_two_media_mentioned": 0.0,
        "email_structure_and_greeting": 0.0,
        "email_bulleted_list_includes_key_numbers": 0.0,
        "email_mentions_outputs_folder": 0.0,
    }

    expected = compute_expected_from_raw(workspace)
    if expected is None:
        return scores

    validation_log_path = workspace / "output" / "logs" / "validation.log"
    log_text = safe_read_text(validation_log_path)
    if log_text is not None:
        contains_row7 = "ROW 7: non-numeric faith_integration_score 'NA'" in log_text
        contains_row8 = "ROW 8: aesthetic_score out of range (1-5): 6.0" in log_text
        contains_summary = "Found 2 invalid row(s)." in log_text
        if contains_row7 and contains_row8 and contains_summary:
            scores["validation_log_present_and_contains_expected"] = 1.0

    cleaned_csv_path = workspace / "output" / "clean" / "fall2025_critiques_clean.csv"
    in_header, in_rows = expected["header"], expected["rows"]
    cleaned_header, cleaned_rows = load_cleaned_csv(cleaned_csv_path)
    structure_ok = False
    exclusion_ok = False
    if cleaned_header is not None and cleaned_rows is not None:
        if cleaned_header == in_header:
            try:
                fi_idx = cleaned_header.index("faith_integration_score")
                ae_idx = cleaned_header.index("aesthetic_score")
                all_valid = True
                for r in cleaned_rows:
                    fi = float(r[fi_idx])
                    ae = float(r[ae_idx])
                    if not (1.0 <= fi <= 5.0) or not (1.0 <= ae <= 5.0):
                        all_valid = False
                        break
                structure_ok = all_valid
            except Exception:
                structure_ok = False
        invalid_ids_set = set(expected["invalid_ids"])
        student_id_idx = in_header.index("student_id")
        all_input_ids = [row[student_id_idx] for row in in_rows]
        expected_valid_ids = set(i for i in all_input_ids if i not in invalid_ids_set)
        if cleaned_header is not None:
            cleaned_id_idx = cleaned_header.index("student_id") if "student_id" in cleaned_header else 0
            cleaned_ids = [row[cleaned_id_idx] for row in cleaned_rows]
            cleaned_ids_set = set(cleaned_ids)
            excludes_invalid = len(invalid_ids_set & cleaned_ids_set) == 0
            includes_all_valid = expected_valid_ids == cleaned_ids_set
            exclusion_ok = excludes_invalid and includes_all_valid
    if structure_ok:
        scores["cleaned_csv_structure_correct"] = 1.0
    if exclusion_ok:
        scores["cleaned_csv_exclusion_correct"] = 1.0

    summary_path = workspace / "output" / "analysis" / "summary_by_assignment.csv"
    student_summary = load_summary_by_assignment(summary_path)
    if student_summary is not None:
        expected_summary = expected["summary_by_assignment"]
        ok = True
        if set(student_summary.keys()) != set(expected_summary.keys()):
            ok = False
        else:
            for assn, vals in expected_summary.items():
                sv = student_summary.get(assn)
                if sv is None:
                    ok = False
                    break
                if sv["n"] != vals["n_submissions"]:
                    ok = False
                    break
                if not approx_equal(sv["avg_fi"], vals["avg_fi"], tol=1e-6):
                    ok = False
                    break
                if not approx_equal(sv["avg_ae"], vals["avg_ae"], tol=1e-6):
                    ok = False
                    break
        if ok:
            scores["summary_by_assignment_correct"] = 1.0

    medium_counts_path = workspace / "output" / "analysis" / "medium_counts.csv"
    student_medium_counts = load_medium_counts(medium_counts_path)
    if student_medium_counts is not None:
        expected_medium_counts = expected["medium_counts"]
        if student_medium_counts == expected_medium_counts:
            scores["medium_counts_correct"] = 1.0

    overall_json_path = workspace / "output" / "analysis" / "overall_stats.json"
    overall = safe_load_json(overall_json_path)
    if overall is not None and isinstance(overall, dict):
        keys_ok = all(k in overall for k in [
            "total_valid_submissions",
            "total_invalid_rows",
            "share_high_faith_4plus",
            "overall_mean_faith_integration",
            "overall_mean_aesthetic"
        ])
        if keys_ok:
            try:
                tv = int(overall["total_valid_submissions"])
                ti = int(overall["total_invalid_rows"])
                sh = float(overall["share_high_faith_4plus"])
                mfi = float(overall["overall_mean_faith_integration"])
                mae = float(overall["overall_mean_aesthetic"])
                exp = expected["overall"]
                ok = (
                    tv == exp["total_valid"] and
                    ti == exp["total_invalid"] and
                    approx_equal(sh, exp["share_high"], tol=1e-6) and
                    approx_equal(mfi, exp["mean_fi"], tol=1e-6) and
                    approx_equal(mae, exp["mean_ae"], tol=1e-6)
                )
                if ok:
                    scores["overall_stats_json_correct"] = 1.0
            except Exception:
                pass

    report_path = workspace / "output" / "report" / "summary.md"
    report_text = safe_read_text(report_path)
    if report_text is not None:
        lower = report_text.lower()
        reasons_ok = ("2" in report_text) and ("non-numeric" in lower) and ("out of range" in lower)
        if reasons_ok:
            scores["report_exclusions_and_reasons"] = 1.0
        if "sacred space sketch" in lower:
            scores["report_highest_assignment"] = 1.0
        exp_medium_counts = expected["medium_counts"]
        if exp_medium_counts:
            max_count = max(exp_medium_counts.values())
            top_mediums = sorted([m for m, c in exp_medium_counts.items() if c == max_count])
            found = 0
            for m in top_mediums:
                if m.lower() in lower:
                    found += 1
            if found >= 2:
                scores["report_top_two_media_mentioned"] = 1.0

    email_path = workspace / "output" / "email" / "draft_to_chair.txt"
    email_text = safe_read_text(email_path)
    if email_text is not None:
        first_line = extract_first_nonempty_line(email_text).lower()
        if first_line.startswith("hi ") or first_line.startswith("hello ") or first_line.startswith("dear"):
            scores["email_structure_and_greeting"] = 1.0
        lines = [ln.strip() for ln in email_text.splitlines()]
        bullet_lines = [ln for ln in lines if ln.startswith("- ") or ln.startswith("* ") or ln.startswith("• ")]
        has_valid_submissions = any("10" in ln for ln in bullet_lines)
        has_share_high = any(("0.5" in ln) or ("50%" in ln) for ln in bullet_lines)
        has_top_assignment = any("sacred space sketch" in ln.lower() for ln in bullet_lines)
        if bullet_lines and has_valid_submissions and has_share_high and has_top_assignment:
            scores["email_bulleted_list_includes_key_numbers"] = 1.0
        lower_email = email_text.lower()
        if ("output" in lower_email) and ("folder" in lower_email) and ("review" in lower_email or "available" in lower_email):
            scores["email_mentions_outputs_folder"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()