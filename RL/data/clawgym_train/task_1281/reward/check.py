import json
import csv
import re
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional, Dict


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return None, f"missing_file:{path}"
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, f"read_error:{e}"


def _safe_parse_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return None, f"missing_file:{path}"
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # Validate required columns minimally
        if reader.fieldnames is None:
            return None, "csv_no_header"
        needed = {"required", "document", "deadline"}
        if not needed.issubset(set([h.strip() for h in reader.fieldnames])):
            return None, "csv_missing_columns"
        return rows, None
    except Exception as e:
        return None, f"csv_parse_error:{e}"


def _count_required_rows(rows: List[Dict[str, str]]) -> int:
    cnt = 0
    for row in rows:
        val = str(row.get("required", "")).strip().lower()
        if val in ("yes", "y", "true", "1"):
            cnt += 1
    return cnt


def _get_required_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    req = []
    for row in rows:
        val = str(row.get("required", "")).strip().lower()
        if val in ("yes", "y", "true", "1"):
            req.append(row)
    return req


def _parse_markdown_output(md_text: str) -> Tuple[Optional[str], List[str]]:
    # Return header line (first non-empty) and bullet lines starting with "- "
    lines = [ln.rstrip("\n") for ln in md_text.splitlines()]
    header = None
    for ln in lines:
        if ln.strip() == "":
            continue
        header = ln.strip()
        break
    bullets = []
    for ln in lines:
        if ln.lstrip().startswith("- "):
            bullets.append(ln.strip())
    return header, bullets


def _script_uses_utf8_for_csv(script_text: str) -> bool:
    # Look for an open(args.csv ... encoding='utf-8' or 'utf8')
    # Be forgiving with quotes and whitespace and case.
    # Regex to find: open( args.csv , ... encoding= 'utf-8' )
    pattern = re.compile(r"open\s*\(\s*args\.csv\s*,[^)]*encoding\s*=\s*['\"]utf-?8['\"]", re.IGNORECASE | re.DOTALL)
    if pattern.search(script_text):
        return True
    # Also accept using Path with read_text(encoding=...)
    pattern2 = re.compile(r"read_text\s*\(\s*encoding\s*=\s*['\"]utf-?8['\"]\s*\)", re.IGNORECASE)
    return bool(pattern2.search(script_text))


def _script_creates_parent_dir(script_text: str) -> bool:
    # Accept either os.makedirs(parent, exist_ok=True) or Path(...).parent.mkdir(parents=True, exist_ok=True)
    if re.search(r"os\.makedirs\s*\([^)]*exist_ok\s*=\s*True[^)]*\)", script_text):
        return True
    if re.search(r"\.parent\.mkdir\s*\([^)]*parents\s*=\s*True[^)]*exist_ok\s*=\s*True[^)]*\)", script_text):
        return True
    return False


def _header_matches_expected(header: str, expected_count: int) -> bool:
    return header == f"Required documents ({expected_count} items)"


def _bullets_match_required(bullets: List[str], required_rows: List[Dict[str, str]]) -> bool:
    # Each required document must appear once with its exact document and deadline fields.
    # Accept any dash/punctuation between doc and 'deadline:'; require line starts with '- '.
    matched = set()
    for row in required_rows:
        doc = (row.get("document", "") or "").strip()
        deadline = (row.get("deadline", "") or "").strip()
        # Find any bullet that starts with "- " and contains the exact doc and "deadline: <deadline>"
        found = False
        for b in bullets:
            if not b.startswith("- "):
                continue
            if doc in b and re.search(r"deadline:\s*" + re.escape(deadline) + r"\b", b, re.IGNORECASE):
                if b not in matched:
                    found = True
                    matched.add(b)
                    break
        if not found:
            return False
    # Ensure there are no extra bullets beyond required count that include "deadline:"
    # i.e., bullet count should equal required count
    deadline_bullets = [b for b in bullets if "deadline:" in b.lower()]
    return len(deadline_bullets) == len(required_rows)


def _email_has_explanation_and_count(email_text: str, expected_count: int) -> bool:
    text = email_text.lower()
    # Must mention error/issue/problem and fix/resolved/update in non-technical terms
    has_problem = any(w in text for w in ["error", "issue", "problem"])
    has_fix = any(w in text for w in ["fix", "fixed", "resolve", "resolved", "update", "updated"])
    # Must mention the count number
    has_count = str(expected_count) in email_text
    # Mention visa/documents context
    has_context = any(w in text for w in ["visa", "document", "documents"])
    return has_problem and has_fix and has_count and has_context


def _email_has_path_and_question(email_text: str) -> bool:
    # Must include the path and at least one clear question relevant to submission
    includes_path = "output/visa_checklist.md" in email_text
    has_question = "?" in email_text
    # Relevance: include any of these keywords
    text = email_text.lower()
    relevance = any(w in text for w in ["english", "khmer", "translation", "color", "scan", "scans", "submit", "submission", "original", "notarized"])
    return includes_path and has_question and relevance


def _debug_summary_exception_and_cause(debug_text: str) -> bool:
    # Must include exception type and point of failure, and root cause in plain language
    text = debug_text
    low = text.lower()
    has_exception = "UnicodeDecodeError" in text or "unicodedecodeerror" in low
    mentions_reading_csv = any(w in low for w in ["csv", "read", "reading", "open"])
    mentions_encoding = "encoding" in low
    mentions_ascii_or_utf = any(w in low for w in ["ascii", "utf-8", "utf8"])
    return has_exception and mentions_reading_csv and mentions_encoding and mentions_ascii_or_utf


def _debug_summary_changes_and_command(debug_text: str) -> bool:
    low = debug_text.lower()
    # Must include code changes (encoding and directory creation) and the exact command
    mentions_utf8 = "utf-8" in low or "utf8" in low
    mentions_parent_dir = any(p in low for p in ["create parent", "created parent", "parent directory", "mkdir", "os.makedirs"])
    mentions_command = "python scripts/process_checklist.py input/checklist.csv --out output/visa_checklist.md" in debug_text
    return mentions_utf8 and mentions_parent_dir and mentions_command


def _debug_summary_mentions_logfile(debug_text: str) -> bool:
    low = debug_text.lower()
    return "logs/last_run.txt" in low or "last_run.txt" in low or "last run" in low


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_handles_utf8_csv": 0.0,
        "script_creates_parent_dir_for_out": 0.0,
        "output_file_exists": 0.0,
        "header_line_correct": 0.0,
        "bullet_items_match_required_rows": 0.0,
        "excludes_non_required_item": 0.0,
        "debug_summary_includes_exception_and_cause": 0.0,
        "debug_summary_includes_code_changes_and_command": 0.0,
        "debug_summary_mentions_logfile": 0.0,
        "email_includes_explanation_and_count": 0.0,
        "email_includes_path_and_question": 0.0,
    }

    # Load input CSV
    csv_path = workspace / "input" / "checklist.csv"
    rows, csv_err = _safe_parse_csv(csv_path)
    required_rows: List[Dict[str, str]] = []
    required_count = 0
    if rows is not None:
        required_rows = _get_required_rows(rows)
        required_count = len(required_rows)

    # Check script content
    script_path = workspace / "scripts" / "process_checklist.py"
    script_text, script_err = _safe_read_text(script_path)
    if script_text is not None:
        if _script_uses_utf8_for_csv(script_text):
            scores["script_handles_utf8_csv"] = 1.0
        if _script_creates_parent_dir(script_text):
            scores["script_creates_parent_dir_for_out"] = 1.0

    # Check output markdown
    md_path = workspace / "output" / "visa_checklist.md"
    md_text, md_err = _safe_read_text(md_path)
    if md_text is not None:
        scores["output_file_exists"] = 1.0
        header, bullets = _parse_markdown_output(md_text)
        if header is not None and rows is not None:
            if _header_matches_expected(header, required_count):
                scores["header_line_correct"] = 1.0
        if rows is not None:
            if _bullets_match_required(bullets, required_rows):
                scores["bullet_items_match_required_rows"] = 1.0
            # Ensure non-required item (Transcript (optional)) is not included
            if all("Transcript (optional)" not in b for b in bullets):
                scores["excludes_non_required_item"] = 1.0

    # Check debug summary
    debug_path = workspace / "output" / "DEBUG_SUMMARY.md"
    debug_text, debug_err = _safe_read_text(debug_path)
    if debug_text is not None:
        if _debug_summary_exception_and_cause(debug_text):
            scores["debug_summary_includes_exception_and_cause"] = 1.0
        if _debug_summary_changes_and_command(debug_text):
            scores["debug_summary_includes_code_changes_and_command"] = 1.0
        if _debug_summary_mentions_logfile(debug_text):
            scores["debug_summary_mentions_logfile"] = 1.0

    # Check email
    email_path = workspace / "output" / "email_to_international_office.txt"
    email_text, email_err = _safe_read_text(email_path)
    if email_text is not None and rows is not None:
        if _email_has_explanation_and_count(email_text, required_count):
            scores["email_includes_explanation_and_count"] = 1.0
        if _email_has_path_and_question(email_text):
            scores["email_includes_path_and_question"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()