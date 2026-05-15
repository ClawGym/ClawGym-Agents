import json
import re
import sys
import subprocess
from pathlib import Path
from typing import Optional, Dict, Tuple, List
import tempfile


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _word_count(text: str) -> int:
    # Count tokens with letters or digits, allowing internal ' and -.
    tokens = re.findall(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*", text)
    return len(tokens)


def _extract_metric_spans_from_notes(notes_text: str) -> List[str]:
    if not notes_text:
        return []
    spans = set()

    # Hyphenated numeric terms like 48-hour
    for m in re.finditer(r"\b[~+\-]?\d+(?:\.\d+)?-[A-Za-z]+\b", notes_text):
        spans.add(m.group(0))

    # Percentages with sign
    for m in re.finditer(r"\b[~+\-]?\d+(?:\.\d+)?%", notes_text):
        spans.add(m.group(0))

    # Number with no space unit suffix (k, B, ms, s)
    for m in re.finditer(r"\b[~+\-]?\d+(?:\.\d+)?(?:k|B|ms|s)\b", notes_text):
        spans.add(m.group(0))

    # Number + space + common units
    for m in re.finditer(r"\b[~+\-]?\d+(?:\.\d+)?\s+(?:ms|s|week|weeks|hour|hours)\b", notes_text):
        spans.add(m.group(0))

    # Plain decimals and integers (include leading ~ + -)
    for m in re.finditer(r"\b[~+\-]?\d+(?:\.\d+)?\b", notes_text):
        spans.add(m.group(0))

    # Sort by length descending to prefer longer matches when counting presence
    return sorted(spans, key=lambda x: (-len(x), x))


def _extract_number_like_spans(text: str) -> List[str]:
    if not text:
        return []
    spans = set()
    # Include various numeric forms present in free text.
    patterns = [
        r"\b[~+\-]?\d+(?:\.\d+)?-[A-Za-z]+\b",                   # 48-hour
        r"\b[~+\-]?\d+(?:\.\d+)?\s+(?:ms|s|week|weeks|hour|hours)\b",  # 42 ms, 4 weeks
        r"\b[~+\-]?\d+(?:\.\d+)?(?:k|B|ms|s)\b",                 # 10k, ~1.2B, 32ms
        r"\b[~+\-]?\d+(?:\.\d+)?%\b",                            # -23%
        r"\b[~+\-]?\d+(?:\.\d+)?\b",                             # 0.867, 17
    ]
    for pat in patterns:
        for m in re.finditer(pat, text):
            spans.add(m.group(0))
    return sorted(spans, key=lambda x: (-len(x), x))


def _get_role_keywords(role_text: str) -> List[str]:
    if not role_text:
        return []
    text = role_text.strip()
    # Preserve hyphenated tokens and uppercase acronyms; include words length >=4
    tokens = set()
    # Hyphenated
    for m in re.finditer(r"[A-Za-z]{2,}-[A-Za-z]{2,}", text):
        tokens.add(m.group(0).lower())
        tokens.add(m.group(0).lower().replace("-", " "))
    # Uppercase acronyms like SRE, ML, GNNs, MLOps
    for m in re.finditer(r"\b[A-Z]{2,}[A-Za-z]*s?\b", text):
        tokens.add(m.group(0).lower())
    # Regular words length >=4
    for m in re.finditer(r"\b[A-Za-z]{4,}\b", text):
        tokens.add(m.group(0).lower())
    # Focused subset that reflects domain
    return list(tokens)


def _find_bullet_block_at_end(text: str) -> Tuple[int, bool]:
    """
    Returns (bullet_count_at_end, ends_cleanly)
    bullet_count_at_end: number of lines starting with '- ' at end ignoring trailing blank lines
    ends_cleanly: True if exactly that bullet block is last non-empty content
    """
    if not text:
        return 0, False
    lines = text.splitlines()
    # Remove trailing empty lines
    while lines and lines[-1].strip() == "":
        lines.pop()
    if not lines:
        return 0, False
    # Count how many last lines start with "- "
    cnt = 0
    i = len(lines) - 1
    while i >= 0 and lines[i].startswith("- "):
        cnt += 1
        i -= 1
    # Ensure that the bullet block is contiguous and last content
    ends_cleanly = cnt > 0
    return cnt, ends_cleanly


def _parse_run_log(log_text: str, cmd_initial: str, cmd_final: str) -> Tuple[bool, bool, Optional[Dict[str, float]], Optional[Dict[str, float]], bool]:
    """
    Parses the run log to check presence/order of commands and extract metrics values.
    Returns:
      (initial_present_before_final, both_present, initial_metrics, final_metrics, contains_readability_lines_for_both)
    metrics dict includes 'flesch_reading_ease' and 'flesch_kincaid_grade' if found.
    """
    if not log_text:
        return False, False, None, None, False
    lines = log_text.splitlines()
    text = log_text
    try:
        idx_init = text.index(cmd_initial)
    except ValueError:
        idx_init = -1
    try:
        idx_final = text.index(cmd_final)
    except ValueError:
        idx_final = -1

    both_present = idx_init != -1 and idx_final != -1
    initial_before_final = both_present and idx_init < idx_final

    def extract_after_command(cmd: str, start_index: int, end_index: int) -> Optional[Dict[str, float]]:
        # Extract metrics from lines between indices
        segment = text[start_index:end_index] if (start_index >= 0 and end_index > start_index) else text[start_index:] if start_index >= 0 else ""
        fre_m = re.search(r"Flesch Reading Ease:\s*([\-0-9.]+)", segment)
        fk_m = re.search(r"Flesch-Kincaid Grade:\s*([\-0-9.]+)", segment)
        if fre_m and fk_m:
            try:
                return {
                    "flesch_reading_ease": float(fre_m.group(1)),
                    "flesch_kincaid_grade": float(fk_m.group(1)),
                }
            except Exception:
                return None
        return None

    init_metrics = None
    final_metrics = None
    contains_readability_lines_for_both = False

    if idx_init != -1:
        end_for_init = len(text) if idx_final == -1 else idx_final
        init_metrics = extract_after_command(cmd_initial, idx_init, end_for_init)
    if idx_final != -1:
        final_metrics = extract_after_command(cmd_final, idx_final, len(text))
    contains_readability_lines_for_both = (init_metrics is not None) and (final_metrics is not None)

    return initial_before_final, both_present, init_metrics, final_metrics, contains_readability_lines_for_both


def _floats_close(a: float, b: float, tol: float = 1e-3) -> bool:
    return abs(a - b) <= tol


def _compute_readability_via_script(workspace: Path, input_rel: str) -> Optional[Dict[str, float]]:
    # Run the provided readability script in a subprocess, writing JSON to a temp file outside workspace
    script_path = workspace / "tools" / "readability.py"
    input_path = workspace / input_rel
    if not script_path.exists() or not input_path.exists():
        return None
    try:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "tmp_metrics.json"
            cmd = [sys.executable, str(script_path), "--input", str(input_path), "--out", str(out_path)]
            sp = subprocess.run(cmd, cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            # Even if the script prints errors, attempt to read the output JSON
            if out_path.exists():
                data = _safe_load_json(out_path)
                if isinstance(data, dict) and "flesch_reading_ease" in data and "flesch_kincaid_grade" in data:
                    return {
                        "flesch_reading_ease": float(data.get("flesch_reading_ease")),
                        "flesch_kincaid_grade": float(data.get("flesch_kincaid_grade")),
                    }
            return None
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Paths
    en_path = workspace / "output" / "industry_summary_en.md"
    es_path = workspace / "output" / "industry_summary_es.md"
    notes_path = workspace / "input" / "thesis_notes.txt"
    role_path = workspace / "input" / "role_brief.txt"
    glossary_path = workspace / "input" / "glossary_es.json"
    init_json_path = workspace / "output" / "readability_initial.json"
    final_json_path = workspace / "output" / "readability_final.json"
    run_log_path = workspace / "output" / "run_log.txt"
    qreport_path = workspace / "output" / "quality_report.md"
    email_path = workspace / "output" / "email_to_recruiter.txt"

    # Load contents
    en_text = _safe_read_text(en_path) or ""
    es_text = _safe_read_text(es_path) or ""
    notes_text = _safe_read_text(notes_path) or ""
    role_text = _safe_read_text(role_path) or ""
    glossary = _safe_load_json(glossary_path) or {}
    init_json = _safe_load_json(init_json_path)
    final_json = _safe_load_json(final_json_path)
    run_log_text = _safe_read_text(run_log_path) or ""
    qreport_text = _safe_read_text(qreport_path) or ""
    email_text = _safe_read_text(email_path) or ""

    scores = {
        "en_summary_exists": 1.0 if en_text else 0.0,
        "en_word_count_250_350": 0.0,
        "en_includes_two_verbatim_metrics": 0.0,
        "en_tailored_to_role_keywords": 0.0,
        "en_ends_with_three_bullets": 0.0,
        "es_summary_exists": 1.0 if es_text else 0.0,
        "es_preserves_bullet_structure": 0.0,
        "es_uses_glossary_terms": 0.0,
        "es_preserves_numbers_from_en": 0.0,
        "readability_initial_json_valid": 0.0,
        "readability_final_json_valid": 0.0,
        "run_log_commands_ordered_and_present": 0.0,
        "run_log_metrics_match_json": 0.0,
        "final_json_matches_current_readability": 0.0,
        "readability_improved_if_below_threshold": 0.0,
        "quality_report_word_count_150_250": 0.0,
        "quality_report_includes_scores": 0.0,
        "quality_report_revision_example_if_needed": 0.0,
        "email_word_count_120_180": 0.0,
        "email_mentions_masters_industry_and_call": 0.0,
    }

    # English summary checks
    if en_text:
        wc = _word_count(en_text)
        if 250 <= wc <= 350:
            scores["en_word_count_250_350"] = 1.0

        # Metrics from notes verbatim: at least two
        metric_spans = _extract_metric_spans_from_notes(notes_text)
        found_metrics = set()
        for span in metric_spans:
            if span in en_text:
                found_metrics.add(span)
        if len(found_metrics) >= 2:
            scores["en_includes_two_verbatim_metrics"] = 1.0

        # Tailored to role: require at least 3 keywords present
        role_keywords = _get_role_keywords(role_text)
        present = set()
        en_lower = en_text.lower()
        for kw in role_keywords:
            if kw and kw in en_lower:
                present.add(kw)
        if len(present) >= 3:
            scores["en_tailored_to_role_keywords"] = 1.0

        # Ends with a 3-item bullet list of "- " lines
        bullet_count, ends_cleanly = _find_bullet_block_at_end(en_text)
        if ends_cleanly and bullet_count == 3:
            scores["en_ends_with_three_bullets"] = 1.0

    # Spanish summary checks
    if es_text:
        # Preserve bullet list: 3 items at end
        bullet_count_es, ends_cleanly_es = _find_bullet_block_at_end(es_text)
        if ends_cleanly_es and bullet_count_es == 3:
            scores["es_preserves_bullet_structure"] = 1.0

        # Glossary enforcement where applicable: if EN contains english term, ES must contain mapped term
        glossary_ok = True
        en_lower = en_text.lower()
        for en_term, es_term in glossary.items():
            if en_term.lower() in en_lower:
                if es_term not in es_text:
                    glossary_ok = False
                    break
        scores["es_uses_glossary_terms"] = 1.0 if glossary_ok and bool(glossary) else 0.0 if glossary else 0.0

        # Numbers preserved from EN to ES
        en_numbers = _extract_number_like_spans(en_text)
        nums_ok = True
        for num in en_numbers:
            if num and num not in es_text:
                nums_ok = False
                break
        # If there were no numbers at all in EN (unlikely), consider it not satisfying the requirement
        if en_numbers and nums_ok:
            scores["es_preserves_numbers_from_en"] = 1.0

    # Readability JSON validity
    def _valid_readability_json(d: Optional[dict]) -> bool:
        if not isinstance(d, dict):
            return False
        keys = {"words", "sentences", "syllables", "flesch_reading_ease", "flesch_kincaid_grade"}
        if not keys.issubset(d.keys()):
            return False
        try:
            int(d["words"])
            int(d["sentences"])
            int(d["syllables"])
            float(d["flesch_reading_ease"])
            float(d["flesch_kincaid_grade"])
        except Exception:
            return False
        return True

    if _valid_readability_json(init_json):
        scores["readability_initial_json_valid"] = 1.0
    if _valid_readability_json(final_json):
        scores["readability_final_json_valid"] = 1.0

    # Run log checks: presence/order and metrics matching JSON
    cmd_initial = "python tools/readability.py --input output/industry_summary_en.md --out output/readability_initial.json"
    cmd_final = "python tools/readability.py --input output/industry_summary_en.md --out output/readability_final.json"
    initial_before_final, both_present, init_metrics_log, final_metrics_log, has_readability_lines = _parse_run_log(
        run_log_text, cmd_initial, cmd_final
    )
    if both_present and initial_before_final:
        scores["run_log_commands_ordered_and_present"] = 1.0

    # Compare log metrics to JSON values (rounded to 3 decimals in JSON)
    log_matches = False
    if init_metrics_log and final_metrics_log and _valid_readability_json(init_json) and _valid_readability_json(final_json):
        try:
            log_matches = (
                _floats_close(init_metrics_log["flesch_reading_ease"], float(init_json["flesch_reading_ease"])) and
                _floats_close(init_metrics_log["flesch_kincaid_grade"], float(init_json["flesch_kincaid_grade"])) and
                _floats_close(final_metrics_log["flesch_reading_ease"], float(final_json["flesch_reading_ease"])) and
                _floats_close(final_metrics_log["flesch_kincaid_grade"], float(final_json["flesch_kincaid_grade"]))
            )
        except Exception:
            log_matches = False
    if log_matches and has_readability_lines:
        scores["run_log_metrics_match_json"] = 1.0

    # Final JSON should match current readability of current EN summary
    current_metrics = _compute_readability_via_script(workspace, "output/industry_summary_en.md")
    if current_metrics and _valid_readability_json(final_json):
        if _floats_close(float(final_json["flesch_reading_ease"]), current_metrics["flesch_reading_ease"]) and \
           _floats_close(float(final_json["flesch_kincaid_grade"]), current_metrics["flesch_kincaid_grade"]):
            scores["final_json_matches_current_readability"] = 1.0

    # Readability improvement logic
    if _valid_readability_json(init_json) and _valid_readability_json(final_json):
        try:
            init_fre = float(init_json["flesch_reading_ease"])
            init_fk = float(init_json["flesch_kincaid_grade"])
            final_fre = float(final_json["flesch_reading_ease"])
            final_fk = float(final_json["flesch_kincaid_grade"])
            init_below = (init_fre < 50.0) or (init_fk > 12.0)
            if init_below:
                improved = (final_fre >= init_fre + 0.1) or (final_fk <= init_fk - 0.1)
                meets_now = (final_fre >= 50.0) and (final_fk <= 12.0)
                if improved or meets_now:
                    scores["readability_improved_if_below_threshold"] = 1.0
            else:
                # If thresholds met initially, they must still produce final JSON; we consider this check satisfied.
                scores["readability_improved_if_below_threshold"] = 1.0
        except Exception:
            pass

    # Quality report checks
    if qreport_text:
        qw = _word_count(qreport_text)
        if 150 <= qw <= 250:
            scores["quality_report_word_count_150_250"] = 1.0

        includes_scores = False
        if _valid_readability_json(init_json) and _valid_readability_json(final_json):
            init_fre_str = f"{float(init_json['flesch_reading_ease']):.3f}"
            init_fk_str = f"{float(init_json['flesch_kincaid_grade']):.3f}"
            final_fre_str = f"{float(final_json['flesch_reading_ease']):.3f}"
            final_fk_str = f"{float(final_json['flesch_kincaid_grade']):.3f}"
            if (init_fre_str in qreport_text and init_fk_str in qreport_text and
                final_fre_str in qreport_text and final_fk_str in qreport_text):
                includes_scores = True
        scores["quality_report_includes_scores"] = 1.0 if includes_scores else 0.0

        # If they needed revision (initial below thresholds), report should cite a changed sentence
        revision_example_ok = False
        if _valid_readability_json(init_json):
            try:
                init_fre = float(init_json["flesch_reading_ease"])
                init_fk = float(init_json["flesch_kincaid_grade"])
                init_below = (init_fre < 50.0) or (init_fk > 12.0)
            except Exception:
                init_below = False
        else:
            init_below = False

        if init_below:
            # Look for a quoted sentence as concrete example and mention of change
            # Require at least five words inside quotes and presence of the word "change" or "revise"
            quoted = re.search(r"\"([^\"]{10,})\"", qreport_text)
            changed_mention = re.search(r"\b(changed|revised|simplified|shortened|clarified|rewrote)\b", qreport_text, re.IGNORECASE)
            if quoted and changed_mention:
                # Ensure at least 5 words inside the quotes
                inner = quoted.group(1)
                if len(re.findall(r"\b\w+\b", inner)) >= 5:
                    revision_example_ok = True
        else:
            # If no revision needed, we consider this satisfied as N/A -> pass
            revision_example_ok = True

        scores["quality_report_revision_example_if_needed"] = 1.0 if revision_example_ok else 0.0

    # Email checks
    if email_text:
        ew = _word_count(email_text)
        if 120 <= ew <= 180:
            scores["email_word_count_120_180"] = 1.0
        email_low = email_text.lower()
        mentions_summary = ("summary" in email_low or "attached" in email_low or "attachment" in email_low)
        mentions_master = ("master" in email_low or "master's" in email_low)
        mentions_industry = ("industry" in email_low)
        # 15-minute intro call
        mentions_call = False
        if re.search(r"\b15\s*[- ]?\s*min(?:ute)?s?\b", email_low):
            mentions_call = True
        if re.search(r"\bintro\b|\bintroduction\b|\bcall\b|\bchat\b|\bmeeting\b", email_low):
            # We still require the 15-min component; keep as is
            pass
        if mentions_summary and mentions_master and mentions_industry and mentions_call:
            scores["email_mentions_masters_industry_and_call"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()