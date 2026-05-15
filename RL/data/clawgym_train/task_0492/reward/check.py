import json
import re
import sys
import csv
from pathlib import Path
from typing import Optional, Tuple, List


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_lines(path: Path) -> Optional[List[str]]:
    txt = _safe_read_text(path)
    if txt is None:
        return None
    # Preserve exact lines without stripping spaces; drop trailing final newline impact
    return txt.splitlines()


def _parse_feedback_counts(feedback_path: Path) -> Optional[Tuple[int, int, int]]:
    # Returns (total_records, count_pro_science, skipped) based on the provided script logic
    try:
        with feedback_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            total = 0
            pro = 0
            skipped = 0
            for row in reader:
                stance = (row.get("stance") or "").strip()
                if not stance:
                    skipped += 1
                    continue
                total += 1
                if stance == "pro_science":
                    pro += 1
            return (total, pro, skipped)
    except Exception:
        return None


def _expected_diag_lines_from_feedback(workspace: Path) -> Optional[Tuple[List[str], List[str]]]:
    fb = workspace / "input" / "feedback.tsv"
    counts = _parse_feedback_counts(fb)
    if counts is None:
        return None
    total, pro, skipped = counts
    stdout_lines = [
        f"Total_records: {total}",
        f"Count_pro_science: {pro}",
        f"Count_non_pro_science: {total - pro}",
    ]
    stderr_lines = []
    if skipped:
        stderr_lines.append(f"WARNING: {skipped} row(s) had missing stance and were ignored.")
    return stdout_lines, stderr_lines


def _extract_bullets(path: Path) -> Optional[List[str]]:
    lines = _safe_read_lines(path)
    if lines is None:
        return None
    bullets = []
    for line in lines:
        if line.strip().startswith("- "):
            # Keep verbatim line (no stripping of trailing spaces)
            bullets.append(line)
    return bullets


def _word_count(text: str) -> int:
    # Count words as sequences of letters/digits/underscore-apostrophe joined.
    tokens = re.findall(r"[A-Za-z0-9']+", text)
    return len(tokens)


def _contains_expected_numbers_format(email_text: str, expected_pro: int, expected_total: int) -> bool:
    # Required exact form: (Count_pro_science=X of Total_records=Y)
    pattern = r"\(Count_pro_science=(\d+)\s+of\s+Total_records=(\d+)\)"
    m = re.search(pattern, email_text)
    if not m:
        return False
    x = int(m.group(1))
    y = int(m.group(2))
    return x == expected_pro and y == expected_total


def _normalize_for_match(s: str) -> str:
    # Lowercase, collapse whitespace, strip common quotes
    s = s.lower()
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    s = s.replace("—", "-").replace("–", "-")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_translated_excerpt(email_text: str) -> Optional[str]:
    marker = "Translated from Spanish:"
    idx = email_text.find(marker)
    if idx == -1:
        return None
    # Excerpt is the text after the marker within the same paragraph (until double newline or EOF)
    after = email_text[idx + len(marker):]
    # Find paragraph end: two consecutive newlines or end
    m = re.search(r"\n\s*\n", after)
    if m:
        para = after[: m.start()]
    else:
        para = after
    # Clean leading whitespace/newlines
    para = para.lstrip()
    return para


def _excerpt_sentence_count(excerpt: str) -> int:
    # Count sentence-ending punctuation . ! ?
    return len(re.findall(r"[\.!?]", excerpt))


def _english_translation_quality_check(text: str) -> bool:
    # Heuristics: should not be the original Spanish, and should contain multiple expected English concepts.
    # Negative Spanish tokens:
    spanish_tokens = ["como padre", "laboratorios", "ciencias", "curiosidad", "clases", "experimentos", "reducir", "tiempo de laboratorio", "hija", "rigorosa", "rigoroso", "rigurosa", "rigurosamente"]
    low = text.lower()
    for tok in spanish_tokens:
        if tok in low:
            return False

    # Positive English concept tokens; require matches from at least 4 distinct categories
    categories = [
        ["parent", "father", "mother"],
        ["curiosity"],
        ["experiment", "experiments"],
        ["lab", "laboratory", "laboratories"],
        ["mistake", "error"],
        ["logical", "logically"],
        ["rigorous", "rigorously"],
    ]
    hits = 0
    for group in categories:
        if any(g in low for g in group):
            hits += 1
    return hits >= 4


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "translated_comment_present": 0.0,
        "translated_comment_english_content": 0.0,
        "diagnostics_contains_expected_stdout_stderr": 0.0,
        "diagnostics_includes_interpretation_and_numbers_used": 0.0,
        "extracted_points_verbatim_two_distinct": 0.0,
        "email_has_subject_first_line": 0.0,
        "email_word_count_150_220": 0.0,
        "email_includes_extracted_points_verbatim": 0.0,
        "email_includes_translated_excerpt_prefaced": 0.0,
        "email_includes_numbers_with_required_format": 0.0,
        "numbers_consistency_between_email_and_diagnostics": 0.0,
    }

    # Paths
    translated_path = workspace / "output" / "translated_comment_en.txt"
    diagnostics_path = workspace / "output" / "diagnostics.txt"
    extracted_points_path = workspace / "output" / "extracted_points.txt"
    email_path = workspace / "output" / "email_to_board.txt"
    talking_points_path = workspace / "input" / "talking_points.md"
    feedback_path = workspace / "input" / "feedback.tsv"

    # Load texts
    translated_text = _safe_read_text(translated_path)
    diagnostics_text = _safe_read_text(diagnostics_path)
    email_text = _safe_read_text(email_path)
    extracted_lines = _safe_read_lines(extracted_points_path)
    talking_bullets = _extract_bullets(talking_points_path)
    counts = _parse_feedback_counts(feedback_path)
    expected_outputs = _expected_diag_lines_from_feedback(workspace)

    # 1) translated_comment_present
    if translated_text is not None and len(translated_text.strip()) > 0:
        scores["translated_comment_present"] = 1.0

    # 1b) translated_comment_english_content
    if translated_text is not None and len(translated_text.strip()) > 0:
        if _english_translation_quality_check(translated_text):
            scores["translated_comment_english_content"] = 1.0

    # 2) diagnostics_contains_expected_stdout_stderr
    if diagnostics_text is not None and expected_outputs is not None:
        stdout_lines, stderr_lines = expected_outputs
        has_all_stdout = all(line in diagnostics_text for line in stdout_lines)
        has_all_stderr = all(line in diagnostics_text for line in stderr_lines)
        # If there is no expected stderr (no warnings), we still require stdout lines.
        if has_all_stdout and (has_all_stderr or len(stderr_lines) == 0):
            scores["diagnostics_contains_expected_stdout_stderr"] = 1.0

    # 2b) diagnostics_includes_interpretation_and_numbers_used
    if diagnostics_text is not None and expected_outputs is not None and counts is not None:
        total, pro, skipped = counts
        # Ensure presence of an interpretive paragraph that mentions warning (if any) and explicitly states which numbers used
        # Check for explicit numeric mentions
        mentions_numbers = (f"Count_pro_science={pro}" in diagnostics_text) and (f"Total_records={total}" in diagnostics_text)
        # Check mention of warning if a warning exists
        mentions_warning = True
        if skipped > 0:
            mentions_warning = ("WARNING" in diagnostics_text) or ("warning" in diagnostics_text) or ("missing stance" in diagnostics_text.lower())
        # Check that beyond raw stdout/stderr lines, there is additional commentary
        stdout_lines, stderr_lines = expected_outputs
        reduced = diagnostics_text
        for line in stdout_lines + stderr_lines:
            reduced = reduced.replace(line, "")
        # Look for at least some alphabetic content remaining as interpretation
        has_extra_text = len(re.findall(r"[A-Za-z]{3,}", reduced)) >= 1
        if mentions_numbers and mentions_warning and has_extra_text:
            scores["diagnostics_includes_interpretation_and_numbers_used"] = 1.0

    # 3) extracted_points_verbatim_two_distinct
    if extracted_lines is not None and talking_bullets is not None:
        # Must be exactly two lines, each exactly one of the bullet lines, distinct
        if len(extracted_lines) == 2:
            l1, l2 = extracted_lines[0], extracted_lines[1]
            if l1 != l2 and (l1 in talking_bullets) and (l2 in talking_bullets):
                scores["extracted_points_verbatim_two_distinct"] = 1.0

    # 4) Email checks
    if email_text is not None and len(email_text.strip()) > 0:
        # Subject on the first line (strictly require "Subject:" prefix)
        first_line = email_text.splitlines()[0] if email_text.splitlines() else ""
        if first_line.strip().lower().startswith("subject:") and len(first_line.strip()) > len("subject:"):
            scores["email_has_subject_first_line"] = 1.0

        # Word count between 150 and 220 inclusive
        wc = _word_count(email_text)
        if 150 <= wc <= 220:
            scores["email_word_count_150_220"] = 1.0

        # Incorporate the two selected talking points verbatim
        if extracted_lines is not None and len(extracted_lines) == 2:
            if all(line in email_text for line in extracted_lines):
                scores["email_includes_extracted_points_verbatim"] = 1.0

        # Include a quoted excerpt of at most two sentences from the translated comment, prefaced with "Translated from Spanish:"
        excerpt_ok = False
        if translated_text is not None and len(translated_text.strip()) > 0:
            excerpt = _extract_translated_excerpt(email_text)
            if excerpt is not None:
                # Count sentences in the excerpt paragraph
                sentence_count = _excerpt_sentence_count(excerpt)
                if sentence_count <= 2:
                    # Check excerpt is from the translated text (normalized substring)
                    ex_norm = _normalize_for_match(excerpt.replace('"', '').replace("'", ""))
                    tr_norm = _normalize_for_match(translated_text.replace('"', '').replace("'", ""))
                    if len(ex_norm) > 0 and ex_norm in tr_norm:
                        excerpt_ok = True
        if excerpt_ok:
            scores["email_includes_translated_excerpt_prefaced"] = 1.0

        # Include numbers with required exact format and correct values
        if counts is not None:
            total, pro, _ = counts
            if _contains_expected_numbers_format(email_text, pro, total):
                scores["email_includes_numbers_with_required_format"] = 1.0

    # 5) numbers_consistency_between_email_and_diagnostics
    if diagnostics_text is not None and email_text is not None and counts is not None:
        total, pro, _ = counts
        email_has = _contains_expected_numbers_format(email_text, pro, total)
        diag_mentions = (f"Count_pro_science={pro}" in diagnostics_text) and (f"Total_records={total}" in diagnostics_text)
        if email_has and diag_mentions:
            scores["numbers_consistency_between_email_and_diagnostics"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()