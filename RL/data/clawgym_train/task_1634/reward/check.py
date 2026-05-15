import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_read_csv_rows(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None
            rows = [dict({k: (v if v is not None else "") for k, v in row.items()}) for row in reader]
            return headers, rows
    except Exception:
        return None


def _float_equal(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _compute_session_metrics(headers: List[str], rows: List[Dict[str, str]]) -> Dict[str, Any]:
    allowed_genders = {"M", "F", "Other"}
    allowed_conditions = {"control", "treatment"}
    age_min, age_max = 18, 99
    likert_min, likert_max = 1, 5

    cols = headers
    missing_counts = {col: 0 for col in cols}
    invalid_counts = {col: 0 for col in cols}
    condition_counts = {cond: 0 for cond in allowed_conditions}

    seen = set()
    dup_count = 0
    for row in rows:
        key = tuple(row.get(col, "") for col in cols)
        if key in seen:
            dup_count += 1
        else:
            seen.add(key)

    ages_valid: List[int] = []
    likert_valid: Dict[str, List[int]] = {q: [] for q in ["q1", "q2", "q3"]}

    for row in rows:
        for col in cols:
            val = row.get(col, "")
            if val == "":
                missing_counts[col] += 1

        age_val = row.get("age", "")
        if age_val != "":
            try:
                age_int = int(age_val)
                if age_int < age_min or age_int > age_max:
                    invalid_counts["age"] += 1
                else:
                    ages_valid.append(age_int)
            except Exception:
                invalid_counts["age"] += 1

        gender_val = row.get("gender", "")
        if gender_val != "":
            if gender_val not in allowed_genders:
                invalid_counts["gender"] += 1

        condition_val = row.get("condition", "")
        if condition_val != "":
            if condition_val not in allowed_conditions:
                invalid_counts["condition"] += 1
            else:
                condition_counts[condition_val] += 1

        for q in ["q1", "q2", "q3"]:
            q_val = row.get(q, "")
            if q_val != "":
                try:
                    q_int = int(q_val)
                    if q_int < likert_min or q_int > likert_max:
                        invalid_counts[q] += 1
                    else:
                        likert_valid[q].append(q_int)
                except Exception:
                    invalid_counts[q] += 1

    def mean_or_none(values: List[int]) -> Optional[float]:
        if not values:
            return None
        return float(sum(values)) / float(len(values))

    metrics = {
        "n_rows": len(rows),
        "n_unique_participants": len({row.get("participant_id", "") for row in rows if row.get("participant_id", "") != ""}),
        "duplicate_rows_count": dup_count,
        "missing_counts": missing_counts,
        "invalid_value_counts": invalid_counts,
        "condition_counts": condition_counts,
        "mean_age": mean_or_none(ages_valid),
        "likert_means": {q: mean_or_none(vals) for q, vals in likert_valid.items()},
    }
    return metrics


def _discover_sessions(workspace: Path) -> List[Path]:
    sessions_dir = workspace / "study_data" / "sessions"
    if not sessions_dir.exists():
        return []
    files = [p for p in sessions_dir.rglob("*.csv") if p.is_file()]
    return files


def _load_consent_log(workspace: Path) -> Dict[str, str]:
    consent_path = workspace / "study_data" / "docs" / "consent_log.csv"
    mapping: Dict[str, str] = {}
    data = _safe_read_csv_rows(consent_path)
    if data is None:
        return mapping
    _, rows = data
    id_col = "participant_id"
    consent_col = "consented"
    for row in rows:
        pid = row.get(id_col, "")
        cons = row.get(consent_col, "")
        if pid != "":
            mapping[pid] = cons.strip().lower()
    return mapping


def _compute_expected_summary(workspace: Path) -> Dict[str, Any]:
    sessions_dir = workspace / "study_data" / "sessions"
    sessions_files = _discover_sessions(workspace)
    discovered_files_rel = []
    for p in sessions_files:
        try:
            rel = str(p.relative_to(sessions_dir)).replace("\\", "/")
        except Exception:
            rel = p.name
        discovered_files_rel.append(rel)
    sessions_metrics: Dict[str, Any] = {}
    all_participants: set = set()

    for p in sessions_files:
        data = _safe_read_csv_rows(p)
        if data is None:
            continue
        headers, rows = data
        metrics = _compute_session_metrics(headers, rows)
        sessions_metrics[p.name] = metrics
        for row in rows:
            pid = row.get("participant_id", "")
            if pid != "":
                all_participants.add(pid)

    consent_map = _load_consent_log(workspace)
    consent_violations: List[str] = []
    for pid in sorted(all_participants):
        if consent_map.get(pid, "").lower() != "yes":
            consent_violations.append(pid)

    overall = {
        "n_unique_participants_overall": len(all_participants),
        "consent_violations": consent_violations,
    }

    expected = {
        "discovered_files": sorted(discovered_files_rel),
        "sessions": sessions_metrics,
        "overall": overall,
    }
    return expected


def _compare_missing_counts(expected: Dict[str, int], actual: Any) -> bool:
    if not isinstance(actual, dict):
        return False
    if set(expected.keys()) != set(actual.keys()):
        return False
    for k, v in expected.items():
        if not isinstance(actual.get(k), int):
            return False
        if actual.get(k) != v:
            return False
    return True


def _compare_invalid_counts(expected: Dict[str, int], actual: Any) -> bool:
    return _compare_missing_counts(expected, actual)


def _compare_condition_counts(expected: Dict[str, int], actual: Any) -> bool:
    if not isinstance(actual, dict):
        return False
    if set(expected.keys()) != set(actual.keys()):
        return False
    for k, v in expected.items():
        if not isinstance(actual.get(k), int):
            return False
        if actual.get(k) != v:
            return False
    return True


def _compare_likert_means(expected: Dict[str, Optional[float]], actual: Any) -> bool:
    if not isinstance(actual, dict):
        return False
    if set(expected.keys()) != set(actual.keys()):
        return False
    for k, v in expected.items():
        av = actual.get(k, None)
        if v is None and av is None:
            continue
        if (v is None) != (av is None):
            return False
        if not isinstance(av, (int, float)):
            return False
        if not _float_equal(float(v), float(av)):
            return False
    return True


def _evaluate_report_quality(text: str) -> bool:
    t = text.lower()
    keywords = [
        "invalid",
        "missing",
        "duplicate",
        "condition",
        "mean",
        "consent",
    ]
    hits = sum(1 for kw in keywords if kw in t)
    followup = any(s in t for s in ["recommend", "follow-up", "follow up", "next steps", "action", "resolve", "proposed", "proposal"])
    return hits >= 5 and followup


def _evaluate_email_quality(text: str) -> bool:
    lines = text.splitlines()
    lower = text.lower()
    has_subject = any(re.match(r"^\s*subject\s*:", ln, re.IGNORECASE) for ln in lines)
    references_files = ("outputs/validation_summary.json" in text) and ("outputs/data_checks_report.md" in text)
    bullet_lines = [ln.strip() for ln in lines if ln.strip().startswith(("-", "*"))]
    has_bullets = len(bullet_lines) >= 2
    issues_keywords = ["invalid", "likert", "consent", "duplicate", "missing"]
    bullet_has_issues = any(any(kw in bl.lower() for kw in issues_keywords) for bl in bullet_lines)
    has_next_steps = any(s in lower for s in ["next steps", "propose", "proposed", "recommend"])
    return has_subject and references_files and has_bullets and bullet_has_issues and has_next_steps


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "json_present_parseable": 0.0,
        "json_discovered_files": 0.0,
        "json_sessions_keyset_correct": 0.0,
        "json_overall_unique_participants": 0.0,
        "json_overall_consent_violations": 0.0,
        "report_exists": 0.0,
        "report_content_quality": 0.0,
        "email_exists": 0.0,
        "email_content_quality": 0.0,
    }

    expected = _compute_expected_summary(workspace)
    expected_discovered = expected.get("discovered_files", [])
    expected_sessions = expected.get("sessions", {})
    expected_overall = expected.get("overall", {"n_unique_participants_overall": 0, "consent_violations": []})

    out_json_path = workspace / "outputs" / "validation_summary.json"
    out_report_path = workspace / "outputs" / "data_checks_report.md"
    out_email_path = workspace / "outputs" / "email_to_ra.txt"

    out_json = _safe_load_json(out_json_path)
    if isinstance(out_json, dict):
        scores["json_present_parseable"] = 1.0

        json_discovered = out_json.get("discovered_files")
        if isinstance(json_discovered, list) and all(isinstance(x, str) for x in json_discovered):
            if sorted(json_discovered) == sorted(expected_discovered):
                scores["json_discovered_files"] = 1.0

        json_sessions = out_json.get("sessions")
        if isinstance(json_sessions, dict):
            if set(json_sessions.keys()) == set(expected_sessions.keys()):
                scores["json_sessions_keyset_correct"] = 1.0

        json_overall = out_json.get("overall", {})
        if isinstance(json_overall, dict):
            j_n = json_overall.get("n_unique_participants_overall", None)
            if isinstance(j_n, int) and j_n == expected_overall.get("n_unique_participants_overall", None):
                scores["json_overall_unique_participants"] = 1.0
            j_cv = json_overall.get("consent_violations", None)
            exp_cv = expected_overall.get("consent_violations", [])
            if isinstance(j_cv, list) and sorted(j_cv) == sorted(exp_cv):
                scores["json_overall_consent_violations"] = 1.0

        for s_name, exp_metrics in expected_sessions.items():
            base = s_name.replace(".", "_").replace("-", "_").replace(" ", "_")
            key_map = {
                "n_rows": f"json_{base}_n_rows",
                "n_unique_participants": f"json_{base}_unique_participants",
                "duplicate_rows_count": f"json_{base}_duplicates",
                "missing_counts": f"json_{base}_missing_counts",
                "invalid_value_counts": f"json_{base}_invalid_counts",
                "condition_counts": f"json_{base}_condition_counts",
                "mean_age": f"json_{base}_mean_age",
                "likert_means": f"json_{base}_likert_means",
            }
            for k in key_map.values():
                if k not in scores:
                    scores[k] = 0.0

            act_session = json_sessions.get(s_name) if isinstance(json_sessions, dict) else None
            if isinstance(act_session, dict):
                if isinstance(act_session.get("n_rows"), int) and act_session.get("n_rows") == exp_metrics.get("n_rows"):
                    scores[key_map["n_rows"]] = 1.0
                if isinstance(act_session.get("n_unique_participants"), int) and act_session.get("n_unique_participants") == exp_metrics.get("n_unique_participants"):
                    scores[key_map["n_unique_participants"]] = 1.0
                if isinstance(act_session.get("duplicate_rows_count"), int) and act_session.get("duplicate_rows_count") == exp_metrics.get("duplicate_rows_count"):
                    scores[key_map["duplicate_rows_count"]] = 1.0
                if _compare_missing_counts(exp_metrics.get("missing_counts", {}), act_session.get("missing_counts")):
                    scores[key_map["missing_counts"]] = 1.0
                if _compare_invalid_counts(exp_metrics.get("invalid_value_counts", {}), act_session.get("invalid_value_counts")):
                    scores[key_map["invalid_value_counts"]] = 1.0
                if _compare_condition_counts(exp_metrics.get("condition_counts", {}), act_session.get("condition_counts")):
                    scores[key_map["condition_counts"]] = 1.0
                act_mean_age = act_session.get("mean_age")
                exp_mean_age = exp_metrics.get("mean_age")
                if (exp_mean_age is None and act_mean_age is None) or (
                    isinstance(act_mean_age, (int, float)) and _float_equal(exp_mean_age, float(act_mean_age))
                ):
                    scores[key_map["mean_age"]] = 1.0
                if _compare_likert_means(exp_metrics.get("likert_means", {}), act_session.get("likert_means")):
                    scores[key_map["likert_means"]] = 1.0

    report_text = _safe_read_text(out_report_path)
    if report_text is not None:
        scores["report_exists"] = 1.0
        if _evaluate_report_quality(report_text):
            scores["report_content_quality"] = 1.0

    email_text = _safe_read_text(out_email_path)
    if email_text is not None:
        scores["email_exists"] = 1.0
        if _evaluate_email_quality(email_text):
            scores["email_content_quality"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()