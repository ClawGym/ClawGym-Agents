import json
import sys
import csv
import re
from pathlib import Path
from statistics import mean
from typing import List, Dict, Tuple, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None


def _load_json_safe(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv_dicts_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: v for k, v in row.items()})
            return rows
    except Exception:
        return None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(str(s).strip())
    except Exception:
        return None


def _compute_expected_high_impact(student_rows: List[Dict[str, str]]) -> List[Dict[str, object]]:
    by_cat: Dict[str, List[float]] = {}
    for row in student_rows:
        try:
            rating = float(row.get("rating", "").strip())
        except Exception:
            continue
        if rating >= 3:
            cat = row.get("category", "").strip()
            if cat == "":
                continue
            by_cat.setdefault(cat, []).append(rating)
    summary = []
    for cat, ratings in by_cat.items():
        cnt = len(ratings)
        avg = round(sum(ratings) / cnt, 1) if cnt > 0 else 0.0
        summary.append({"category": cat, "count": cnt, "avg_rating": avg})
    summary.sort(key=lambda d: (-d["count"], -d["avg_rating"], d["category"]))
    for idx, item in enumerate(summary, start=1):
        item["rank"] = idx
    ordered = [{"rank": it["rank"], "category": it["category"], "count": it["count"], "avg_rating": it["avg_rating"]} for it in summary]
    return ordered


def _load_output_high_impact_csv(path: Path) -> Optional[List[Dict[str, object]]]:
    rows = _load_csv_dicts_safe(path)
    if rows is None:
        return None
    header = []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, [])
    except Exception:
        return None
    required_header = ["rank", "category", "count", "avg_rating"]
    if header != required_header:
        return None
    parsed = []
    for i, row in enumerate(rows):
        if any(k not in row for k in required_header):
            return None
        rnk = _parse_int(row["rank"])
        cnt = _parse_int(row["count"])
        avg = _parse_float(row["avg_rating"])
        cat = row["category"]
        if rnk is None or cnt is None or avg is None or cat is None:
            return None
        parsed.append({"rank": rnk, "category": cat, "count": cnt, "avg_rating": avg})
    return parsed


def _parse_errors_from_log(text: str) -> Tuple[int, Dict[str, Dict[str, object]]]:
    total = 0
    msg_counts: Dict[str, int] = {}
    msg_groups: Dict[str, set] = {}
    for line in text.splitlines():
        m = re.search(r"\[ERROR\]\s(.*)$", line)
        if m:
            total += 1
            message = m.group(1).strip()
            msg_counts[message] = msg_counts.get(message, 0) + 1
            groups = re.findall(r"group\s+'([^']+)'", message)
            if message not in msg_groups:
                msg_groups[message] = set()
            for g in groups:
                msg_groups[message].add(g)
    expected = {}
    for msg, cnt in msg_counts.items():
        groups_sorted = sorted(msg_groups.get(msg, set()))
        expected[msg] = {"count": cnt, "groups": groups_sorted}
    return total, expected


def _load_errors_json(path: Path) -> Optional[dict]:
    data = _load_json_safe(path)
    if not isinstance(data, dict):
        return None
    if "total_error_lines" not in data or "errors" not in data:
        return None
    if not isinstance(data["total_error_lines"], int):
        return None
    if not isinstance(data["errors"], list):
        return None
    for item in data["errors"]:
        if not isinstance(item, dict):
            return None
        if "message" not in item or "count" not in item or "groups" not in item:
            return None
        if not isinstance(item["message"], str):
            return None
        if not isinstance(item["count"], int):
            return None
        if not isinstance(item["groups"], list):
            return None
        for g in item["groups"]:
            if not isinstance(g, str):
                return None
    return data


def _word_count(text: str) -> int:
    lines = text.splitlines()
    body_lines = [ln for ln in lines if not ln.strip().lower().startswith("subject:")]
    body = "\n".join(body_lines)
    words = re.findall(r"\b[\w'-]+\b", body, flags=re.UNICODE)
    return len(words)


def _has_subject_line(text: str) -> bool:
    for ln in text.splitlines():
        if ln.strip().lower().startswith("subject:"):
            return True
    return False


def _has_closing_phrase(text: str) -> bool:
    closings = ["sincerely", "regards", "best regards", "thank you", "thanks", "warm regards", "best"]
    tail = "\n".join(text.splitlines()[-10:])
    t_low = tail.lower()
    return any(c in t_low for c in closings)


def _contains_spanish(text: str) -> bool:
    if re.search(r"[áéíóúñ¡¿]", text):
        return True
    spanish_words = [
        "estimados", "estimadas", "familias", "padres", "madres", "tutores", "semana", "clase",
        "estudiantes", "medidas", "hábitos", "apoyo", "gracias", "asunto", "atentamente", "saludos",
        "próxima", "próximo", "implementaremos", "pilotaremos", "en casa", "escuela", "en clase",
        "comunidad", "participación"
    ]
    t_low = text.lower()
    hits = sum(1 for w in spanish_words if w in t_low)
    return hits >= 2


def _find_order_indices(text: str, terms: List[str]) -> Optional[List[int]]:
    positions = []
    t_low = text.lower()
    start = 0
    for term in terms:
        term_low = term.lower()
        idx = t_low.find(term_low, start)
        if idx == -1:
            return None
        positions.append(idx)
        start = idx + len(term_low)
    return positions


def _count_near_category(text: str, category: str, count: int, window: int = 80) -> bool:
    t_low = text.lower()
    cat_low = category.lower()
    idx = t_low.find(cat_low)
    if idx == -1:
        return False
    start = max(0, idx - 20)
    end = min(len(text), idx + len(category) + window)
    segment = text[start:end]
    return str(count) in segment


def _avg_near_category(text: str, category: str, avg: float, window: int = 100) -> bool:
    t_low = text.lower()
    cat_low = category.lower()
    idx = t_low.find(cat_low)
    if idx == -1:
        return False
    start = max(0, idx - 20)
    end = min(len(text), idx + len(category) + window)
    segment = text[start:end]
    avg_1d = f"{avg:.1f}"
    patterns = {avg_1d}
    if abs(avg - round(avg)) < 1e-9:
        patterns.add(f"{int(round(avg))}")
        patterns.add(f"{avg:.2f}")
    else:
        patterns.add(f"{avg:.2f}")
    for p in patterns:
        if p in segment:
            return True
    return False


def _diagnostics_next_step_present(report_text: str, message: str) -> bool:
    idx = report_text.find(message)
    if idx == -1:
        return False
    window_text = report_text[idx: idx + 300]
    keywords = [
        "fix", "resolve", "retry", "supply", "correct", "address",
        "investigate", "re-run", "rerun", "escalate", "update", "remove", "add"
    ]
    wlow = window_text.lower()
    return any(k in wlow for k in keywords)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "high_impact_csv_exists_and_structure": 0.0,
        "high_impact_csv_values_and_order": 0.0,
        "diagnostics_json_exists_and_structure": 0.0,
        "diagnostics_json_content_correct": 0.0,
        "report_exec_summary_top3_alignment": 0.0,
        "report_diagnostics_error_counts_and_next_steps": 0.0,
        "email_parents_en_length_and_structure": 0.0,
        "email_parents_en_top3_alignment": 0.0,
        "email_parents_es_subject_and_top3": 0.0,
        "email_parents_es_spanish_language_check": 0.0,
        "message_students_length_and_top_category": 0.0,
        "cross_top3_consistency_csv_report_emails": 0.0,
    }

    input_survey = workspace / "input" / "student_survey.csv"
    input_log = workspace / "input" / "command_output.log"
    out_csv = workspace / "output" / "data" / "high_impact_ranked.csv"
    out_json = workspace / "output" / "diagnostics" / "errors_summary.json"
    out_report = workspace / "output" / "reports" / "tech_distraction_plan.md"
    out_email_en = workspace / "output" / "communications" / "email_parents_en.txt"
    out_email_es = workspace / "output" / "communications" / "email_parents_es.txt"
    out_msg_students = workspace / "output" / "communications" / "message_students.txt"

    survey_rows = _load_csv_dicts_safe(input_survey) if input_survey.exists() else None
    log_text = _read_text_safe(input_log) if input_log.exists() else None

    output_csv_parsed = _load_output_high_impact_csv(out_csv) if out_csv.exists() else None
    if output_csv_parsed is not None:
        scores["high_impact_csv_exists_and_structure"] = 1.0
    if survey_rows is not None and output_csv_parsed is not None:
        expected_summary = _compute_expected_high_impact(survey_rows)
        ok = True
        if len(expected_summary) != len(output_csv_parsed):
            ok = False
        else:
            for exp_row, act_row in zip(expected_summary, output_csv_parsed):
                if exp_row["category"] != act_row["category"]:
                    ok = False
                    break
                if exp_row["count"] != act_row["count"]:
                    ok = False
                    break
                exp_avg = float(exp_row["avg_rating"])
                act_avg = float(act_row["avg_rating"])
                if round(exp_avg, 1) != round(act_avg, 1):
                    ok = False
                    break
                if exp_row["rank"] != act_row["rank"]:
                    ok = False
                    break
            ranks = [r["rank"] for r in output_csv_parsed]
            if ranks != list(range(1, len(ranks) + 1)):
                ok = False
        if ok:
            scores["high_impact_csv_values_and_order"] = 1.0

    json_data = _load_errors_json(out_json) if out_json.exists() else None
    if json_data is not None:
        scores["diagnostics_json_exists_and_structure"] = 1.0
    if log_text is not None and json_data is not None:
        expected_total, expected_map = _parse_errors_from_log(log_text)
        actual_total = json_data.get("total_error_lines")
        actual_errors = json_data.get("errors", [])
        actual_map: Dict[str, Dict[str, object]] = {}
        for e in actual_errors:
            msg = e.get("message")
            cnt = e.get("count")
            groups = e.get("groups", [])
            if isinstance(msg, str) and isinstance(cnt, int) and isinstance(groups, list):
                try:
                    groups_sorted = sorted(groups)
                except Exception:
                    groups_sorted = list(groups)
                actual_map[msg] = {"count": cnt, "groups": groups_sorted}
        ok = True
        if actual_total != sum(e.get("count", 0) for e in actual_errors if isinstance(e, dict)):
            ok = False
        if actual_total != expected_total:
            ok = False
        if set(actual_map.keys()) != set(expected_map.keys()):
            ok = False
        else:
            for msg, exp in expected_map.items():
                act = actual_map.get(msg)
                if act is None:
                    ok = False
                    break
                if act["count"] != exp["count"]:
                    ok = False
                    break
                if set(act["groups"]) != set(exp["groups"]):
                    ok = False
                    break
        if ok:
            scores["diagnostics_json_content_correct"] = 1.0

    report_text = _read_text_safe(out_report) if out_report.exists() else None
    top3 = []
    expected_summary = None
    if survey_rows is not None:
        expected_summary = _compute_expected_high_impact(survey_rows)
        top3 = [row["category"] for row in expected_summary[:3]]
        top3_counts = [row["count"] for row in expected_summary[:3]]
        top3_avgs = [row["avg_rating"] for row in expected_summary[:3]]
    else:
        top3_counts = []
        top3_avgs = []

    if report_text is not None and expected_summary is not None and len(top3) == 3:
        order_ok = _find_order_indices(report_text, top3) is not None
        counts_ok = all(_count_near_category(report_text, c, cnt) for c, cnt in zip(top3, top3_counts))
        avgs_ok = all(_avg_near_category(report_text, c, float(avg)) for c, avg in zip(top3, top3_avgs))
        if order_ok and counts_ok and avgs_ok:
            scores["report_exec_summary_top3_alignment"] = 1.0

    if report_text is not None and log_text is not None:
        exp_total, exp_map = _parse_errors_from_log(log_text)
        diag_ok = True
        for msg, exp in exp_map.items():
            if report_text.find(msg) == -1:
                diag_ok = False
                break
            if not _diagnostics_next_step_present(report_text, msg):
                diag_ok = False
                break
            idx = report_text.find(msg)
            seg = report_text[max(0, idx - 50): idx + len(msg) + 150]
            if str(exp["count"]) not in seg:
                if str(exp["count"]) not in report_text:
                    diag_ok = False
                    break
        if diag_ok:
            if str(exp_total) not in report_text:
                diag_ok = False
        if diag_ok:
            scores["report_diagnostics_error_counts_and_next_steps"] = 1.0

    email_en_text = _read_text_safe(out_email_en) if out_email_en.exists() else None
    if email_en_text is not None:
        wc = _word_count(email_en_text)
        has_subject = _has_subject_line(email_en_text)
        has_closing = _has_closing_phrase(email_en_text)
        if has_subject and has_closing and 150 <= wc <= 250:
            scores["email_parents_en_length_and_structure"] = 1.0
    if email_en_text is not None and expected_summary is not None and len(top3) == 3:
        order_ok = _find_order_indices(email_en_text, top3) is not None
        counts_ok = all(_count_near_category(email_en_text, c, cnt) for c, cnt in zip(top3, top3_counts))
        if order_ok and counts_ok:
            scores["email_parents_en_top3_alignment"] = 1.0

    email_es_text = _read_text_safe(out_email_es) if out_email_es.exists() else None
    if email_es_text is not None and expected_summary is not None and len(top3) == 3:
        has_subject_es = _has_subject_line(email_es_text)
        order_ok_es = _find_order_indices(email_es_text, top3) is not None
        counts_ok_es = all(_count_near_category(email_es_text, c, cnt) for c, cnt in zip(top3, top3_counts))
        if has_subject_es and order_ok_es and counts_ok_es:
            scores["email_parents_es_subject_and_top3"] = 1.0
        if _contains_spanish(email_es_text):
            scores["email_parents_es_spanish_language_check"] = 1.0

    msg_students_text = _read_text_safe(out_msg_students) if out_msg_students.exists() else None
    if msg_students_text is not None and expected_summary is not None and len(top3) >= 1:
        wc = _word_count(msg_students_text)
        mentions_top = top3[0].lower() in msg_students_text.lower()
        if 80 <= wc <= 120 and mentions_top:
            scores["message_students_length_and_top_category"] = 1.0

    cross_ok = True
    if expected_summary is None or report_text is None or email_en_text is None or email_es_text is None:
        cross_ok = False
    else:
        csv_top3 = [row["category"] for row in expected_summary[:3]]
        rep_ok = _find_order_indices(report_text, csv_top3) is not None
        en_ok = _find_order_indices(email_en_text, csv_top3) is not None
        es_ok = _find_order_indices(email_es_text, csv_top3) is not None
        cross_ok = rep_ok and en_ok and es_ok
    if cross_ok:
        scores["cross_top3_consistency_csv_report_emails"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()