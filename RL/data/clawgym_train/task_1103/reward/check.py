import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
import numbers


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def run_readability_checker(workspace: Path, text_path: Path, lexicon_path: Path) -> Optional[Tuple[str, str, int]]:
    try:
        proc = subprocess.run(
            [sys.executable, str(workspace / "tools" / "readability_check.py"), str(text_path), str(lexicon_path)],
            cwd=str(workspace),
            text=True,
            capture_output=True
        )
        return proc.stdout, proc.stderr, proc.returncode
    except Exception:
        return None


def parse_stdout_metrics(stdout: str) -> Optional[Dict[str, float]]:
    """
    Expected STDOUT format:
    READABILITY_METRICS
    chars: {int}
    words: {int}
    sentences: {int}
    avg_sentence_length: {float}
    flesch_kincaid_grade: {float}
    """
    lines = [ln.strip() for ln in stdout.strip().splitlines() if ln.strip()]
    try:
        idx = lines.index("READABILITY_METRICS")
    except ValueError:
        return None
    metrics_lines = lines[idx + 1:]
    kv = {}
    for ln in metrics_lines:
        if ":" not in ln:
            continue
        k, v = ln.split(":", 1)
        kv[k.strip()] = v.strip()
    required = ["chars", "words", "sentences", "avg_sentence_length", "flesch_kincaid_grade"]
    if not all(k in kv for k in required):
        return None
    try:
        parsed = {
            "chars": int(kv["chars"]),
            "words": int(kv["words"]),
            "sentences": int(kv["sentences"]),
            "avg_sentence_length": float(kv["avg_sentence_length"]),
            "flesch_kincaid_grade": float(kv["flesch_kincaid_grade"]),
        }
        return parsed
    except Exception:
        return None


def parse_stderr_warnings(stderr: str) -> List[Dict[str, Any]]:
    warnings: List[Dict[str, Any]] = []
    lines = [ln.rstrip("\n") for ln in stderr.splitlines()]
    for ln in lines:
        ln_stripped = ln.strip()
        # BANNED_WORD_FOUND
        m1 = re.match(r'^WARNING:\s+BANNED_WORD_FOUND\s+"(.+?)"\s+at\s+line\s+(\d+)\s*$', ln_stripped)
        if m1:
            warnings.append({
                "type": "BANNED_WORD_FOUND",
                "detail": m1.group(1),
                "line": int(m1.group(2))
            })
            continue
        # SENTENCE_TOO_LONG
        m2 = re.match(r'^WARNING:\s+SENTENCE_TOO_LONG\s+(.+?)\s+at\s+line\s+(\d+)\s*$', ln_stripped)
        if m2:
            warnings.append({
                "type": "SENTENCE_TOO_LONG",
                "detail": m2.group(1),
                "line": int(m2.group(2))
            })
            continue
    return warnings


def tokenize_words(text: str) -> List[str]:
    return re.findall(r"\b[\w']+\b", text)


def split_sentences(text: str) -> List[Tuple[str, int]]:
    pattern = re.compile(r"[^.!?]+[.!?]")
    sentences: List[Tuple[str, int]] = []
    for m in pattern.finditer(text):
        sentences.append((m.group(), m.start()))
    if sentences:
        last_end = sentences[-1][1] + len(sentences[-1][0])
        if last_end < len(text):
            tail = text[last_end:]
            if tail.strip():
                sentences.append((tail, last_end))
    else:
        if text.strip():
            sentences.append((text, 0))
    return sentences


def metrics_json_valid(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    required_fields = ["chars", "words", "sentences", "avg_sentence_length", "flesch_kincaid_grade", "warnings", "exit_code"]
    for k in required_fields:
        if k not in obj:
            return False
    if not isinstance(obj["chars"], numbers.Integral):
        return False
    if not isinstance(obj["words"], numbers.Integral):
        return False
    if not isinstance(obj["sentences"], numbers.Integral):
        return False
    if not isinstance(obj["avg_sentence_length"], numbers.Real):
        return False
    if not isinstance(obj["flesch_kincaid_grade"], numbers.Real):
        return False
    if not isinstance(obj["exit_code"], numbers.Integral):
        return False
    if not isinstance(obj["warnings"], list):
        return False
    for w in obj["warnings"]:
        if not isinstance(w, dict):
            return False
        if set(w.keys()) != {"type", "detail", "line"}:
            return False
        if w["type"] not in {"BANNED_WORD_FOUND", "SENTENCE_TOO_LONG"}:
            return False
        if not isinstance(w["detail"], str):
            return False
        if not isinstance(w["line"], numbers.Integral):
            return False
    return True


def compare_metrics(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    # Compare numeric fields with tolerance for floats
    if a.get("chars") != b.get("chars"):
        return False
    if a.get("words") != b.get("words"):
        return False
    if a.get("sentences") != b.get("sentences"):
        return False
    try:
        if abs(float(a.get("avg_sentence_length")) - float(b.get("avg_sentence_length"))) > 0.01:
            return False
        if abs(float(a.get("flesch_kincaid_grade")) - float(b.get("flesch_kincaid_grade"))) > 0.01:
            return False
    except Exception:
        return False
    if a.get("exit_code") != b.get("exit_code"):
        return False
    # Compare warnings list exactly (order and content)
    wa = a.get("warnings", [])
    wb = b.get("warnings", [])
    if not isinstance(wa, list) or not isinstance(wb, list):
        return False
    if len(wa) != len(wb):
        return False
    for i in range(len(wa)):
        ai = wa[i]
        bi = wb[i]
        if ai.get("type") != bi.get("type"):
            return False
        if ai.get("detail") != bi.get("detail"):
            return False
        if ai.get("line") != bi.get("line"):
            return False
    return True


def load_lexicon_avoid(workspace: Path) -> Optional[List[str]]:
    lex_path = workspace / "input" / "lexicon.json"
    obj = safe_load_json(lex_path)
    if not isinstance(obj, dict):
        return None
    avoid = obj.get("avoid", [])
    if not isinstance(avoid, list):
        return None
    words = []
    for w in avoid:
        if isinstance(w, str):
            w2 = w.strip()
            if w2:
                words.append(w2)
    return words


def contains_banned_words(text: str, banned: List[str]) -> bool:
    for w in banned:
        pattern = re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE)
        if pattern.search(text):
            return True
    return False


def check_no_sentence_over_limit(text: str, limit: int) -> bool:
    for sent, _ in split_sentences(text):
        count = len(tokenize_words(sent))
        if count > limit:
            return False
    return True


def count_bullets(text: str) -> int:
    count = 0
    for ln in text.splitlines():
        if re.match(r'^\s*[-*]\s+', ln):
            count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "metrics_before_json_valid": 0.0,
        "metrics_before_matches_tool_output": 0.0,
        "revised_letter_file_exists": 0.0,
        "revised_within_20pct_word_count": 0.0,
        "revised_contains_no_banned_words": 0.0,
        "revised_no_sentence_over_25_words": 0.0,
        "metrics_after_json_valid": 0.0,
        "metrics_after_matches_tool_output": 0.0,
        "after_checker_exit_code_zero": 0.0,
        "after_flesch_kincaid_le_8": 0.0,
        "summary_bullet_count_between_3_and_5": 0.0,
        "summary_mentions_replacements_and_shortening": 0.0,
    }

    # Paths
    before_metrics_path = workspace / "analysis" / "metrics_before.json"
    after_metrics_path = workspace / "analysis" / "metrics_after.json"
    summary_path = workspace / "analysis" / "summary.md"
    revised_path = workspace / "output" / "revised_letter.md"
    draft_path = workspace / "input" / "draft_letter.md"
    lexicon_path = workspace / "input" / "lexicon.json"

    # Load lexicon avoid list
    avoid_list = load_lexicon_avoid(workspace)

    # Validate metrics_before.json
    before_json = safe_load_json(before_metrics_path)
    if metrics_json_valid(before_json):
        scores["metrics_before_json_valid"] = 1.0

    # Compare metrics_before.json against tool output
    if draft_path.exists() and lexicon_path.exists():
        run1 = run_readability_checker(workspace, draft_path, lexicon_path)
        if run1 is not None and metrics_json_valid(before_json):
            stdout1, stderr1, code1 = run1
            parsed_metrics1 = parse_stdout_metrics(stdout1)
            parsed_warnings1 = parse_stderr_warnings(stderr1)
            if parsed_metrics1 is not None:
                expected_before = {
                    "chars": parsed_metrics1["chars"],
                    "words": parsed_metrics1["words"],
                    "sentences": parsed_metrics1["sentences"],
                    "avg_sentence_length": parsed_metrics1["avg_sentence_length"],
                    "flesch_kincaid_grade": parsed_metrics1["flesch_kincaid_grade"],
                    "warnings": parsed_warnings1,
                    "exit_code": code1,
                }
                if compare_metrics(before_json, expected_before):
                    scores["metrics_before_matches_tool_output"] = 1.0

    # Revised letter exists
    if revised_path.exists() and revised_path.is_file():
        scores["revised_letter_file_exists"] = 1.0

    # Word count within ±20%
    draft_text = safe_read_text(draft_path) or ""
    revised_text = safe_read_text(revised_path) or ""
    if draft_text and revised_text:
        orig_words = len(tokenize_words(draft_text))
        new_words = len(tokenize_words(revised_text))
        if orig_words > 0:
            lower = int(orig_words * 0.8)
            upper = int(orig_words * 1.2)
            if lower <= new_words <= upper:
                scores["revised_within_20pct_word_count"] = 1.0

    # No banned words in revised letter
    if revised_text and isinstance(avoid_list, list):
        if not contains_banned_words(revised_text, avoid_list):
            scores["revised_contains_no_banned_words"] = 1.0

    # No sentence over 25 words in revised letter
    if revised_text:
        if check_no_sentence_over_limit(revised_text, 25):
            scores["revised_no_sentence_over_25_words"] = 1.0

    # Validate metrics_after.json
    after_json = safe_load_json(after_metrics_path)
    if metrics_json_valid(after_json):
        scores["metrics_after_json_valid"] = 1.0

    # Compare metrics_after.json against tool output and additional checks
    after_run_ok = False
    after_grade_le_8_both = False
    after_exit_zero_both = False
    if revised_path.exists() and lexicon_path.exists():
        run2 = run_readability_checker(workspace, revised_path, lexicon_path)
        if run2 is not None and metrics_json_valid(after_json):
            stdout2, stderr2, code2 = run2
            parsed_metrics2 = parse_stdout_metrics(stdout2)
            parsed_warnings2 = parse_stderr_warnings(stderr2)
            if parsed_metrics2 is not None:
                expected_after = {
                    "chars": parsed_metrics2["chars"],
                    "words": parsed_metrics2["words"],
                    "sentences": parsed_metrics2["sentences"],
                    "avg_sentence_length": parsed_metrics2["avg_sentence_length"],
                    "flesch_kincaid_grade": parsed_metrics2["flesch_kincaid_grade"],
                    "warnings": parsed_warnings2,
                    "exit_code": code2,
                }
                if compare_metrics(after_json, expected_after):
                    scores["metrics_after_matches_tool_output"] = 1.0
                    after_run_ok = True
                # exit code zero check
                if code2 == 0 and after_json.get("exit_code") == 0:
                    after_exit_zero_both = True
                # grade <= 8 check
                try:
                    if float(parsed_metrics2["flesch_kincaid_grade"]) <= 8.0 and float(after_json.get("flesch_kincaid_grade")) <= 8.0:
                        after_grade_le_8_both = True
                except Exception:
                    after_grade_le_8_both = False

    if after_exit_zero_both:
        scores["after_checker_exit_code_zero"] = 1.0
    if after_grade_le_8_both:
        scores["after_flesch_kincaid_le_8"] = 1.0

    # Summary checks
    summary_text = safe_read_text(summary_path) or ""
    if summary_text:
        bullets = count_bullets(summary_text)
        if 3 <= bullets <= 5:
            scores["summary_bullet_count_between_3_and_5"] = 1.0

        # Check mentions of replacements and sentence shortening
        has_replacement_ref = bool(re.search(r'\b(replace|replaced|rephrase|rephrased|reword|reworded|substitut)\w*\b', summary_text, flags=re.IGNORECASE))
        has_shorten_ref = bool(re.search(r'\b(shorten|shortened|shorter|split|trim|trimmed|reduce|reduced|cut)\w*\b', summary_text, flags=re.IGNORECASE) and re.search(r'\bsentence\w*\b', summary_text, flags=re.IGNORECASE))
        # Count mentions of banned words that were present in original draft
        mentioned_banned = 0
        if isinstance(avoid_list, list) and draft_text:
            original_banned_present = []
            for w in avoid_list:
                if re.search(r"\b" + re.escape(w) + r"\b", draft_text, flags=re.IGNORECASE):
                    original_banned_present.append(w)
            for w in original_banned_present:
                if re.search(r"\b" + re.escape(w) + r"\b", summary_text, flags=re.IGNORECASE):
                    mentioned_banned += 1
        if has_replacement_ref and has_shorten_ref and mentioned_banned >= 2:
            scores["summary_mentions_replacements_and_shortening"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()