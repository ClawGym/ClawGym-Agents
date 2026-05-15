import json
import sys
import re
import csv
from pathlib import Path
from typing import Optional, List, Dict, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # Validate required columns
                if not {"id", "language", "herb", "sentiment", "quote"}.issubset(row.keys()):
                    return None
                rows.append(row)
            return rows
    except Exception:
        return None


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _compute_expected_from_csv(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    # Initialize
    total = 0
    by_lang = {"en": 0, "es": 0}
    sentiment_overall = {"positive": 0, "neutral": 0, "negative": 0}
    herbs_set = set()
    positive_by_herb: Dict[str, int] = {}
    quote_lengths: Dict[str, List[int]] = {"en": [], "es": []}

    for r in rows:
        total += 1
        lang = r.get("language", "")
        herb = r.get("herb", "")
        sent = r.get("sentiment", "")
        quote = r.get("quote", "")
        herbs_set.add(herb)
        if lang in by_lang:
            by_lang[lang] += 1
            quote_lengths.setdefault(lang, []).append(len(quote))
        # Sentiment counts
        if sent in sentiment_overall:
            sentiment_overall[sent] += 1
        # Positive by herb
        if herb not in positive_by_herb:
            positive_by_herb[herb] = 0
        if sent == "positive":
            positive_by_herb[herb] += 1

    # Ensure all herbs included (even if zero positive)
    for h in herbs_set:
        positive_by_herb.setdefault(h, 0)

    # Top 3 positive herbs sorted by count desc, then name asc
    sorted_items = sorted(positive_by_herb.items(), key=lambda kv: (-kv[1], kv[0]))
    top3 = [{"herb": name, "positive_count": count} for name, count in sorted_items[:3]]

    # Avg quote length by language
    avg_quote_len = {}
    for lang in ("en", "es"):
        arr = quote_lengths.get(lang, [])
        if arr:
            avg_quote_len[lang] = sum(arr) / len(arr)
        else:
            avg_quote_len[lang] = 0.0

    return {
        "total_testimonials": total,
        "by_language": by_lang,
        "sentiment_overall": sentiment_overall,
        "positive_by_herb": positive_by_herb,
        "top3_positive_herbs": top3,
        "avg_quote_length_by_language": avg_quote_len,
    }


def _contains_timestamp(s: str) -> bool:
    # Accept ISO date or time patterns
    patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",           # YYYY-MM-DD
        r"\b\d{2}/\d{2}/\d{4}\b",           # MM/DD/YYYY
        r"\b\d{2}:\d{2}(:\d{2})?\b",        # HH:MM or HH:MM:SS
    ]
    for p in patterns:
        if re.search(p, s):
            return True
    return False


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _find_section_lines(text: str, heading: str) -> List[str]:
    # Return lines after a heading (case-insensitive) until next blank line or next heading-like line
    lines = text.splitlines()
    section: List[str] = []
    found = False
    for i, line in enumerate(lines):
        if not found and heading.lower() in line.strip().lower():
            found = True
            # Continue to next line for content
            continue
        if found:
            if line.strip() == "":
                break
            section.append(line)
    return section


def _line_has_name_and_number(line: str, name: str, number: int) -> bool:
    return (name.lower() in line.lower()) and (str(number) in line)


def _text_has_name_and_number_same_line(text: str, name: str, number: int) -> bool:
    for line in text.splitlines():
        if _line_has_name_and_number(line, name, number):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_file_exists": 0.0,
        "run_log_has_command": 0.0,
        "run_log_has_timestamp": 0.0,
        "stats_exists_and_parseable": 0.0,
        "stats_total_testimonials_correct": 0.0,
        "stats_by_language_correct": 0.0,
        "stats_sentiment_correct": 0.0,
        "stats_positive_by_herb_complete_and_correct": 0.0,
        "stats_top3_positive_herbs_correct": 0.0,
        "stats_avg_quote_length_by_language_correct": 0.0,
        "brief_update_exists": 0.0,
        "brief_under_180_words": 0.0,
        "brief_mentions_total_and_languages": 0.0,
        "brief_key_metrics_section_has_top3_from_stats": 0.0,
        "brief_has_caveat_not_clinical_evidence": 0.0,
        "brief_next_steps_2_to_3_bullets": 0.0,
        "rewritten_email_exists": 0.0,
        "rewritten_email_under_140_words": 0.0,
        "rewritten_email_contains_by_may_15": 0.0,
        "rewritten_email_mentions_anecdotal": 0.0,
        "rewritten_email_includes_total_and_top3_from_stats": 0.0,
    }

    # Check script existence
    script_path = workspace / "output" / "analyze_feedback.py"
    if script_path.is_file():
        scores["script_file_exists"] = 1.0

    # Check run log
    run_log_path = workspace / "output" / "run_log.txt"
    run_log_text = _safe_read_text(run_log_path)
    if run_log_text is not None:
        # Command presence
        command_found = False
        timestamp_found = False
        for line in run_log_text.splitlines():
            if "analyze_feedback.py" in line and ("python" in line or "python3" in line):
                command_found = True
                if _contains_timestamp(line):
                    timestamp_found = True
        scores["run_log_has_command"] = 1.0 if command_found else 0.0
        scores["run_log_has_timestamp"] = 1.0 if timestamp_found else 0.0
    else:
        scores["run_log_has_command"] = 0.0
        scores["run_log_has_timestamp"] = 0.0

    # Load stats.json
    stats_path = workspace / "output" / "stats.json"
    stats = _safe_load_json(stats_path)
    if isinstance(stats, dict):
        required_keys = {
            "total_testimonials",
            "by_language",
            "sentiment_overall",
            "positive_by_herb",
            "top3_positive_herbs",
            "avg_quote_length_by_language",
        }
        if required_keys.issubset(stats.keys()):
            scores["stats_exists_and_parseable"] = 1.0
        else:
            scores["stats_exists_and_parseable"] = 0.0
    else:
        stats = None
        scores["stats_exists_and_parseable"] = 0.0

    # Compute expected metrics from CSV if available
    input_csv_path = workspace / "input" / "herbal_testimonials.csv"
    rows = _safe_read_csv_dicts(input_csv_path)
    expected = None
    if rows is not None:
        expected = _compute_expected_from_csv(rows)

    # Validate stats against expected if both present
    if stats is not None and expected is not None:
        # total_testimonials
        if isinstance(stats.get("total_testimonials"), int) and stats["total_testimonials"] == expected["total_testimonials"]:
            scores["stats_total_testimonials_correct"] = 1.0

        # by_language
        by_lang = stats.get("by_language")
        if isinstance(by_lang, dict) and set(by_lang.keys()) == {"en", "es"}:
            if isinstance(by_lang.get("en"), int) and isinstance(by_lang.get("es"), int):
                if by_lang["en"] == expected["by_language"]["en"] and by_lang["es"] == expected["by_language"]["es"]:
                    scores["stats_by_language_correct"] = 1.0

        # sentiment_overall
        sent_overall = stats.get("sentiment_overall")
        if isinstance(sent_overall, dict) and set(sent_overall.keys()) == {"positive", "neutral", "negative"}:
            if all(isinstance(sent_overall.get(k), int) for k in ["positive", "neutral", "negative"]):
                if all(sent_overall[k] == expected["sentiment_overall"][k] for k in ["positive", "neutral", "negative"]):
                    scores["stats_sentiment_correct"] = 1.0

        # positive_by_herb complete and correct (include all herbs present in CSV)
        pbh = stats.get("positive_by_herb")
        if isinstance(pbh, dict):
            all_herbs = set(expected["positive_by_herb"].keys())
            if all(h in pbh for h in all_herbs) and all(isinstance(pbh.get(h), int) for h in pbh.keys()):
                if all(pbh[h] == expected["positive_by_herb"][h] for h in all_herbs):
                    scores["stats_positive_by_herb_complete_and_correct"] = 1.0

        # top3_positive_herbs
        top3 = stats.get("top3_positive_herbs")
        if isinstance(top3, list) and len(top3) == 3:
            top3_ok = True
            for item in top3:
                if not (isinstance(item, dict) and "herb" in item and "positive_count" in item and isinstance(item["positive_count"], int)):
                    top3_ok = False
                    break
            if top3_ok:
                if top3 == expected["top3_positive_herbs"]:
                    scores["stats_top3_positive_herbs_correct"] = 1.0

        # avg_quote_length_by_language
        avg_len = stats.get("avg_quote_length_by_language")
        if isinstance(avg_len, dict) and set(avg_len.keys()) == {"en", "es"}:
            en_val = avg_len.get("en")
            es_val = avg_len.get("es")
            if isinstance(en_val, (int, float)) and isinstance(es_val, (int, float)):
                if _float_equal(en_val, expected["avg_quote_length_by_language"]["en"]) and _float_equal(es_val, expected["avg_quote_length_by_language"]["es"]):
                    scores["stats_avg_quote_length_by_language_correct"] = 1.0

    # Brief update checks
    brief_path = workspace / "output" / "brief_update.md"
    brief_text = _safe_read_text(brief_path)
    if brief_text is not None:
        scores["brief_update_exists"] = 1.0
        # word count <= 180
        scores["brief_under_180_words"] = 1.0 if _word_count(brief_text) <= 180 else 0.0

        # mentions total testimonials and English/Spanish
        mentions_total = False
        mentions_langs = False
        if stats is not None and isinstance(stats.get("total_testimonials"), int):
            total_str = str(stats["total_testimonials"])
            if total_str in brief_text:
                mentions_total = True
        if re.search(r"\benglish\b", brief_text, flags=re.IGNORECASE) and re.search(r"\bspanish\b", brief_text, flags=re.IGNORECASE):
            mentions_langs = True
        scores["brief_mentions_total_and_languages"] = 1.0 if (mentions_total and mentions_langs) else 0.0

        # Key Metrics section has top3 with counts
        key_metrics_lines = _find_section_lines(brief_text, "Key Metrics")
        key_metrics_ok = False
        if key_metrics_lines and stats is not None and isinstance(stats.get("top3_positive_herbs"), list) and len(stats["top3_positive_herbs"]) == 3:
            # Ensure each top herb and count appears together in some line
            found_all = True
            for item in stats["top3_positive_herbs"]:
                herb = str(item.get("herb", ""))
                count = item.get("positive_count")
                if not herb or not isinstance(count, int):
                    found_all = False
                    break
                # Search within key_metrics_lines only
                line_found = any(_line_has_name_and_number(line, herb, count) for line in key_metrics_lines)
                if not line_found:
                    found_all = False
                    break
            key_metrics_ok = found_all
        scores["brief_key_metrics_section_has_top3_from_stats"] = 1.0 if key_metrics_ok else 0.0

        # Caveat noting anecdotes are not clinical evidence
        caveat_ok = bool(re.search(r"not\s+clinical\s+evidence", brief_text, flags=re.IGNORECASE))
        scores["brief_has_caveat_not_clinical_evidence"] = 1.0 if caveat_ok else 0.0

        # Next Steps bullets 2–3
        next_steps_lines = _find_section_lines(brief_text, "Next Steps")
        bullet_count = sum(1 for line in next_steps_lines if re.match(r"^\s*[-*]\s+", line))
        scores["brief_next_steps_2_to_3_bullets"] = 1.0 if bullet_count in (2, 3) else 0.0

    # Rewritten email checks
    email_path = workspace / "output" / "rewritten_email.txt"
    email_text = _safe_read_text(email_path)
    if email_text is not None:
        scores["rewritten_email_exists"] = 1.0
        scores["rewritten_email_under_140_words"] = 1.0 if _word_count(email_text) <= 140 else 0.0
        scores["rewritten_email_contains_by_may_15"] = 1.0 if re.search(r"\bby\s+may\s+15\b", email_text, flags=re.IGNORECASE) else 0.0
        scores["rewritten_email_mentions_anecdotal"] = 1.0 if re.search(r"\banecdotal\b|\banecdotes\b", email_text, flags=re.IGNORECASE) else 0.0

        # Includes total number and top3 herbs with counts from stats.json
        includes_all = False
        if stats is not None and isinstance(stats.get("total_testimonials"), int) and isinstance(stats.get("top3_positive_herbs"), list) and len(stats["top3_positive_herbs"]) == 3:
            total_ok = str(stats["total_testimonials"]) in email_text
            top_ok = True
            for item in stats["top3_positive_herbs"]:
                herb = str(item.get("herb", ""))
                count = item.get("positive_count")
                if not herb or not isinstance(count, int):
                    top_ok = False
                    break
                if not _text_has_name_and_number_same_line(email_text, herb, count):
                    top_ok = False
                    break
            includes_all = total_ok and top_ok
        scores["rewritten_email_includes_total_and_top3_from_stats"] = 1.0 if includes_all else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()