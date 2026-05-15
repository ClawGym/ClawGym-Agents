import json
import csv
import sys
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
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


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _parse_reading_list(path: Path) -> Tuple[Dict[str, Dict], Dict[str, set], List[str]]:
    rows = _load_csv_dicts(path)
    readings: Dict[str, Dict] = {}
    themes_map: Dict[str, set] = {}
    required_ids: List[str] = []
    if not rows:
        return readings, themes_map, required_ids
    for r in rows:
        tid = (r.get("text_id") or "").strip()
        if not tid:
            # Skip malformed rows without text_id
            continue
        readings[tid] = r
        targets = r.get("target_themes", "") or ""
        allowed = [t.strip() for t in targets.split(";") if t.strip() != ""]
        themes_map[tid] = set(allowed)
        if (r.get("required", "") or "").strip().lower() == "yes":
            required_ids.append(tid)
    return readings, themes_map, required_ids


def _parse_notes_quotes(path: Path) -> Dict[str, List[str]]:
    """
    Parse notes.md and extract quotes per text_id.
    Recognizes sections like '## ... (text_id: AW_Tidal_Library)' and '- Quote: ...'
    """
    content = _read_text(path)
    quotes: Dict[str, List[str]] = {}
    if content is None:
        return quotes
    current_text_id: Optional[str] = None
    section_re = re.compile(r"\(text_id:\s*([^)]+)\)")
    for line in content.splitlines():
        line = line.strip()
        m = section_re.search(line) if line.startswith("##") else None
        if m:
            current_text_id = m.group(1).strip()
            quotes.setdefault(current_text_id, [])
            continue
        if current_text_id and line.startswith("- Quote:"):
            q = line[len("- Quote:"):].strip()
            if q:
                quotes.setdefault(current_text_id, []).append(q)
    return quotes


def _safe_word_count(s: str) -> int:
    if not isinstance(s, str):
        return 0
    return len([w for w in s.strip().split() if w])


def _compute_question_metrics(
    questions: List[Dict],
    texts: Dict[str, str],
    allowed_themes: Dict[str, set],
) -> Dict[str, Dict]:
    """
    Compute per-question metrics:
    - option_count
    - excerpt_found (bool)
    - excerpt_count (int)
    - invalid_theme_tags (list[str])
    """
    metrics: Dict[str, Dict] = {}
    for q in questions:
        qid = q.get("id")
        text_id = q.get("text_id")
        options = q.get("options")
        excerpt = q.get("source_excerpt")
        theme_tags = q.get("theme_tags")
        text_content = texts.get(text_id, "")
        if not isinstance(excerpt, str) or excerpt == "":
            excerpt_count = 0
        else:
            excerpt_count = text_content.count(excerpt)
        excerpt_found = excerpt_count > 0
        opt_count = len(options) if isinstance(options, list) else 0
        invalid_tags = []
        if isinstance(theme_tags, list):
            for t in theme_tags:
                if not isinstance(t, str) or t not in allowed_themes.get(text_id, set()):
                    invalid_tags.append(t if isinstance(t, str) else "")
        else:
            invalid_tags = ["<invalid>"]
        metrics[qid] = {
            "id": qid,
            "text_id": text_id,
            "option_count": opt_count,
            "excerpt_found": excerpt_found,
            "excerpt_count": excerpt_count,
            "invalid_theme_tags": invalid_tags,
        }
    return metrics


def _recompute_summary(
    questions: List[Dict],
    required_ids: List[str],
    metrics: Dict[str, Dict]
) -> Dict:
    total = len(questions)
    by_text: Dict[str, int] = {}
    total_words = 0
    total_options = 0
    theme_counts: Dict[str, int] = {}
    for q in questions:
        text_id = q.get("text_id")
        by_text[text_id] = by_text.get(text_id, 0) + 1
        total_words += _safe_word_count(q.get("question"))
        opts = q.get("options")
        total_options += len(opts) if isinstance(opts, list) else 0
        tags = q.get("theme_tags")
        if isinstance(tags, list):
            for t in tags:
                if isinstance(t, str):
                    theme_counts[t] = theme_counts.get(t, 0) + 1
    avg_q_len = (total_words / total) if total > 0 else 0.0
    avg_opt = (total_options / total) if total > 0 else 0.0
    req_wo_questions = [tid for tid in required_ids if by_text.get(tid, 0) == 0]
    all_excerpts_found = all((m.get("excerpt_found", False) is True) for m in metrics.values()) if metrics else False
    return {
        "total_questions": total,
        "questions_by_text": by_text,
        "avg_question_length_words": avg_q_len,
        "avg_option_count": avg_opt,
        "theme_tag_counts": theme_counts,
        "required_readings_without_questions": req_wo_questions,
        "all_excerpts_found": all_excerpts_found,
    }


def _validate_questions_validation_csv(
    path: Path,
    questions: List[Dict],
    computed_metrics: Dict[str, Dict]
) -> bool:
    rows = _load_csv_dicts(path)
    if rows is None:
        return False
    # Expect exact header
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, [])
    except Exception:
        return False
    expected_header = ["id", "text_id", "option_count", "excerpt_found", "excerpt_count", "invalid_theme_tags"]
    if header != expected_header:
        return False
    # Check rows cover exactly the question ids
    qids = [q.get("id") for q in questions if isinstance(q.get("id"), str)]
    row_ids = [r.get("id") for r in rows if r.get("id") is not None]
    if set(qids) != set(row_ids):
        return False
    # Compare each row with computed metrics
    metrics_map = computed_metrics
    q_by_id = {q.get("id"): q for q in questions if isinstance(q.get("id"), str)}
    for r in rows:
        rid = r.get("id")
        if rid not in metrics_map or rid not in q_by_id:
            return False
        cm = metrics_map[rid]
        # text_id
        if (r.get("text_id") or "") != (q_by_id[rid].get("text_id") or ""):
            return False
        # option_count
        try:
            oc = int(r.get("option_count"))
        except Exception:
            return False
        if oc != cm["option_count"]:
            return False
        # excerpt_found: accept true/false case-insensitive
        rf = (r.get("excerpt_found") or "").strip().lower()
        if rf not in {"true", "false"}:
            return False
        if (rf == "true") != cm["excerpt_found"]:
            return False
        # excerpt_count
        try:
            ec = int(r.get("excerpt_count"))
        except Exception:
            return False
        if ec != cm["excerpt_count"]:
            return False
        # invalid_theme_tags: compare as sets, order-insensitive; blank means none
        row_invalid_str = (r.get("invalid_theme_tags") or "").strip()
        row_tags = [t for t in row_invalid_str.split(";") if t != ""]
        cm_tags = [t for t in cm.get("invalid_theme_tags", []) if isinstance(t, str) and t != ""]
        if set(row_tags) != set(cm_tags):
            return False
    return True


def _approx_equal(a: float, b: float, tol: float = 1e-2) -> bool:
    return abs(a - b) <= tol


def _validate_summary_stats_json(
    path: Path,
    recomputed: Dict
) -> bool:
    data = _load_json(path)
    if not isinstance(data, dict):
        return False
    # Required keys
    required_keys = [
        "total_questions",
        "questions_by_text",
        "avg_question_length_words",
        "avg_option_count",
        "theme_tag_counts",
        "required_readings_without_questions",
        "all_excerpts_found",
    ]
    for k in required_keys:
        if k not in data:
            return False
    try:
        if int(data["total_questions"]) != int(recomputed["total_questions"]):
            return False
        # questions_by_text must match exactly (including text_ids and counts)
        qbt_file = data["questions_by_text"]
        if not isinstance(qbt_file, dict):
            return False
        qbt_file_norm = {k: int(v) for k, v in qbt_file.items()}
        if qbt_file_norm != recomputed["questions_by_text"]:
            return False
        # Averages with tolerance
        if not _approx_equal(float(data["avg_question_length_words"]), float(recomputed["avg_question_length_words"])):
            return False
        if not _approx_equal(float(data["avg_option_count"]), float(recomputed["avg_option_count"])):
            return False
        # theme_tag_counts exact
        ttc_file = data["theme_tag_counts"]
        if not isinstance(ttc_file, dict):
            return False
        ttc_file_norm = {str(k): int(v) for k, v in ttc_file.items()}
        if ttc_file_norm != recomputed["theme_tag_counts"]:
            return False
        # required_readings_without_questions as list (order-insensitive)
        rrwq_file = data["required_readings_without_questions"]
        if not isinstance(rrwq_file, list):
            return False
        if sorted([str(x) for x in rrwq_file]) != sorted(recomputed["required_readings_without_questions"]):
            return False
        # all_excerpts_found boolean
        aef = data["all_excerpts_found"]
        if bool(aef) != bool(recomputed["all_excerpts_found"]):
            return False
    except Exception:
        return False
    return True


def _email_contains_num(text: str, value: float) -> bool:
    """
    Check if any reasonable string representation of value appears in text.
    Accepts integer, one or two decimals.
    """
    candidates = set()
    try:
        iv = int(round(value))
        if abs(value - iv) < 1e-6:
            candidates.add(str(iv))
    except Exception:
        pass
    candidates.add(f"{value:.0f}")
    candidates.add(f"{value:.1f}".rstrip("0").rstrip("."))
    candidates.add(f"{value:.2f}".rstrip("0").rstrip("."))
    candidates.add(str(value))
    text_low = text.lower()
    for c in candidates:
        if c and c.lower() in text_low:
            return True
    return False


def _validate_email(
    path: Path,
    recomputed: Dict
) -> Dict[str, float]:
    """
    Returns dict of:
    - email_subject_and_references
    - email_reports_totals_and_coverage
    - email_reports_excerpts_and_required_readings
    - email_mentions_key_stats_and_top_tags
    """
    scores = {
        "email_subject_and_references": 0.0,
        "email_reports_totals_and_coverage": 0.0,
        "email_reports_excerpts_and_required_readings": 0.0,
        "email_mentions_key_stats_and_top_tags": 0.0,
    }
    content = _read_text(path)
    if content is None:
        return scores
    text = content.strip()
    lines = [l.strip() for l in text.splitlines() if l.strip() != ""]
    # Subject line
    has_subject = any(l.lower().startswith("subject:") for l in lines)
    # References to output files
    refs_ok = ("outputs/quiz/questions.json" in text and
               "outputs/validation/questions_validation.csv" in text and
               "outputs/validation/summary_stats.json" in text and
               "outputs/message/email_draft.txt" in text)
    if has_subject and refs_ok:
        scores["email_subject_and_references"] = 1.0
    # Totals and coverage
    total_ok = _email_contains_num(text, float(recomputed["total_questions"]))
    coverage_ok = True
    for tid, count in recomputed["questions_by_text"].items():
        if tid not in text:
            coverage_ok = False
            break
        if not _email_contains_num(text, float(count)):
            coverage_ok = False
            break
    if total_ok and coverage_ok:
        scores["email_reports_totals_and_coverage"] = 1.0
    # Excerpts found and required readings without questions
    aef_bool = recomputed["all_excerpts_found"]
    aef_ok_phrase = ("all_excerpts_found" in text.lower() or "all excerpts found" in text.lower())
    aef_ok_value = ("true" in text.lower() if aef_bool else "false" in text.lower())
    rrwq = recomputed["required_readings_without_questions"]
    rr_phrase = ("required_readings_without_questions" in text.lower() or "required readings without questions" in text.lower())
    if len(rrwq) == 0:
        rr_ok = rr_phrase and ("none" in text.lower())
    else:
        rr_ok = rr_phrase and all(tid in text for tid in rrwq)
    if aef_ok_phrase and aef_ok_value and rr_ok:
        scores["email_reports_excerpts_and_required_readings"] = 1.0
    # Key stats and top 2 theme tags
    avg_q_len_ok = _email_contains_num(text, float(recomputed["avg_question_length_words"]))
    avg_opt_ok = _email_contains_num(text, float(recomputed["avg_option_count"]))
    ttc = recomputed["theme_tag_counts"]
    top_tags = sorted(ttc.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
    tags_ok = True
    if top_tags:
        for tag, _cnt in top_tags:
            if tag not in text:
                tags_ok = False
                break
    if avg_q_len_ok and avg_opt_ok and tags_ok:
        scores["email_mentions_key_stats_and_top_tags"] = 1.0
    return scores


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "questions_json_valid_structure": 0.0,
        "total_question_count_correct": 0.0,
        "per_text_required_distribution": 0.0,
        "question_ids_unique": 0.0,
        "options_and_answer_index_valid": 0.0,
        "theme_tags_nonempty": 0.0,
        "source_excerpts_present_in_texts": 0.0,
        "theme_tags_allowed_per_question": 0.0,
        "notes_quote_used_per_text": 0.0,
        "validation_csv_consistent": 0.0,
        "summary_stats_consistent": 0.0,
        "email_subject_and_references": 0.0,
        "email_reports_totals_and_coverage": 0.0,
        "email_reports_excerpts_and_required_readings": 0.0,
        "email_mentions_key_stats_and_top_tags": 0.0,
    }

    # Load inputs
    reading_list_path = workspace / "input" / "reading_list.csv"
    texts_dir = workspace / "input" / "texts"
    notes_path = workspace / "input" / "notes.md"
    readings, allowed_themes, required_ids = _parse_reading_list(reading_list_path)

    # Load texts content
    texts: Dict[str, str] = {}
    for tid in readings.keys():
        tpath = texts_dir / f"{tid}.txt"
        tcontent = _read_text(tpath) or ""
        texts[tid] = tcontent

    # Parse notes quotes
    quotes_by_text = _parse_notes_quotes(notes_path)

    # Load questions
    questions_path = workspace / "outputs" / "quiz" / "questions.json"
    questions = _load_json(questions_path)
    if isinstance(questions, list) and len(questions) > 0:
        scores["questions_json_valid_structure"] = 1.0
    else:
        questions = [] if isinstance(questions, list) else []

    # Basic checks on questions
    # total count exactly 6
    if len(questions) == 6:
        scores["total_question_count_correct"] = 1.0

    # per text required distribution: exactly 3 per required text_id
    per_text_counts: Dict[str, int] = {}
    for q in questions:
        tid = q.get("text_id")
        per_text_counts[tid] = per_text_counts.get(tid, 0) + 1
    required_dist_ok = True
    if required_ids:
        for tid in required_ids:
            if per_text_counts.get(tid, 0) != 3:
                required_dist_ok = False
                break
    else:
        required_dist_ok = False
    if required_dist_ok and len(questions) == 6:
        scores["per_text_required_distribution"] = 1.0

    # ids unique (only evaluate if there is at least one question)
    if len(questions) > 0:
        ids = [q.get("id") for q in questions if isinstance(q.get("id"), str)]
        if len(ids) == len(questions) and len(set(ids)) == len(questions):
            scores["question_ids_unique"] = 1.0

    # validate each question fields (only evaluate if questions exist)
    if len(questions) > 0:
        options_and_answer_ok = True
        theme_tags_nonempty_ok = True
        for q in questions:
            # options exactly 4 strings
            opts = q.get("options")
            if not (isinstance(opts, list) and len(opts) == 4 and all(isinstance(o, str) for o in opts)):
                options_and_answer_ok = False
            # answer_index int in 0..3
            ai = q.get("answer_index")
            if not (isinstance(ai, int) and 0 <= ai <= 3):
                options_and_answer_ok = False
            # theme_tags non-empty list
            tags = q.get("theme_tags")
            if not (isinstance(tags, list) and len(tags) >= 1 and all(isinstance(t, str) for t in tags)):
                theme_tags_nonempty_ok = False
        if options_and_answer_ok:
            scores["options_and_answer_index_valid"] = 1.0
        if theme_tags_nonempty_ok:
            scores["theme_tags_nonempty"] = 1.0

    # Compute metrics for excerpts and themes validity
    computed_metrics = _compute_question_metrics(questions, texts, allowed_themes)

    # source excerpts present
    if len(questions) > 0:
        all_excerpts_ok = all(m.get("excerpt_found", False) for m in computed_metrics.values())
        scores["source_excerpts_present_in_texts"] = 1.0 if all_excerpts_ok else 0.0

    # theme tags allowed per question
    if len(questions) > 0:
        allowed_ok = True
        for m in computed_metrics.values():
            if len(m.get("invalid_theme_tags", [])) != 0:
                allowed_ok = False
                break
        scores["theme_tags_allowed_per_question"] = 1.0 if allowed_ok else 0.0

    # At least one question per required text uses a Quote from notes.md verbatim as source_excerpt
    if len(questions) > 0 and len(required_ids) > 0:
        quote_use_ok = True
        for tid in required_ids:
            quotes = quotes_by_text.get(tid, [])
            if not quotes:
                quote_use_ok = False
                break
            any_match = False
            for q in questions:
                if q.get("text_id") == tid and isinstance(q.get("source_excerpt"), str):
                    if q["source_excerpt"] in quotes:
                        any_match = True
                        break
            if not any_match:
                quote_use_ok = False
                break
        scores["notes_quote_used_per_text"] = 1.0 if quote_use_ok else 0.0

    # Validate questions_validation.csv consistency
    validation_csv_path = workspace / "outputs" / "validation" / "questions_validation.csv"
    val_csv_ok = _validate_questions_validation_csv(validation_csv_path, questions, computed_metrics)
    scores["validation_csv_consistent"] = 1.0 if val_csv_ok else 0.0

    # Validate summary_stats.json consistency
    recomputed_summary = _recompute_summary(questions, required_ids, computed_metrics)
    summary_json_path = workspace / "outputs" / "validation" / "summary_stats.json"
    summary_ok = _validate_summary_stats_json(summary_json_path, recomputed_summary)
    scores["summary_stats_consistent"] = 1.0 if summary_ok else 0.0

    # Validate email
    email_path = workspace / "outputs" / "message" / "email_draft.txt"
    email_scores = _validate_email(email_path, recomputed_summary)
    scores.update(email_scores)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()