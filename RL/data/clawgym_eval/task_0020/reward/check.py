import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Set


SEARCH_TERMS_ORDER = ["Formula E", "electric", "EV", "battery", "cost", "sustainability"]


def read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()  # fallback
        except Exception:
            return None


def read_lines(path: Path) -> Optional[List[str]]:
    text = read_text_file(path)
    if text is None:
        return None
    # Keep exact line content without trailing newline
    return text.splitlines()


def resolve_source_path(workspace: Path, source_str: str) -> Optional[Path]:
    # Try as absolute or relative to workspace
    p = Path(source_str)
    candidates = []
    if p.is_absolute():
        candidates.append(p)
    else:
        candidates.append((workspace / p))
        candidates.append((workspace / "input" / p))
    # Also try to find by basename under input recursively if not found
    for cand in candidates:
        try:
            if cand.exists() and cand.is_file():
                return cand.resolve()
        except Exception:
            continue
    # Search by basename
    base = p.name
    input_dir = workspace / "input"
    if input_dir.exists():
        for sub in input_dir.rglob("*"):
            try:
                if sub.is_file() and sub.name == base:
                    return sub.resolve()
            except Exception:
                continue
    return None


def compute_expected_matches(workspace: Path) -> List[Tuple[Path, int, str]]:
    input_dir = workspace / "input"
    expected: List[Tuple[Path, int, str]] = []
    if not input_dir.exists():
        return expected
    files = []
    for f in input_dir.rglob("*"):
        if f.is_file() and f.suffix.lower() in {".txt", ".md"}:
            files.append(f)
    pattern = re.compile(r"(Formula E|electric|EV|battery|cost|sustainability)", re.IGNORECASE)
    for f in sorted(files):
        lines = read_lines(f)
        if lines is None:
            continue
        for idx, line in enumerate(lines, start=1):
            if pattern.search(line) is not None:
                expected.append((f.resolve(), idx, line))
    return expected


def parse_grep_output(workspace: Path, grep_path: Path) -> Optional[List[Tuple[Path, int, str, str]]]:
    """
    Parse grep output lines of the form: <path>:<line_number>:<text>
    Returns list of tuples: (resolved_path, line_number, text, original_path_string)
    """
    text = read_text_file(grep_path)
    if text is None:
        return None
    lines = text.splitlines()
    results: List[Tuple[Path, int, str, str]] = []
    for raw in lines:
        if raw.strip() == "":
            continue
        parts = raw.split(":", 2)
        if len(parts) < 3:
            return None  # malformed line
        path_str, line_num_str, line_text = parts[0], parts[1], parts[2]
        try:
            ln = int(line_num_str)
        except Exception:
            return None
        resolved = resolve_source_path(workspace, path_str)
        if resolved is None:
            return None
        file_lines = read_lines(resolved)
        if file_lines is None:
            return None
        if not (1 <= ln <= len(file_lines)):
            return None
        actual_line = file_lines[ln - 1]
        if actual_line != line_text:
            return None
        # Verify that the line indeed contains at least one of the terms
        if determine_match_term(line_text) is None:
            return None
        results.append((resolved, ln, line_text, path_str))
    return results


def determine_match_term(text: str) -> Optional[str]:
    for term in SEARCH_TERMS_ORDER:
        # case-insensitive substring match
        if re.search(re.escape(term), text, flags=re.IGNORECASE):
            return term
    return None


def load_csv_rows(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        try:
            with path.open("r", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception:
            return None
    if not rows:
        return None
    header = rows[0]
    data_rows = rows[1:]
    dict_rows: List[Dict[str, str]] = []
    for r in data_rows:
        # allow shorter rows that might have empty text fields containing commas? Use csv handles quotes; ensure length matches header
        if len(r) != len(header):
            return None
        dict_rows.append({h: v for h, v in zip(header, r)})
    return header, dict_rows


def count_words(text: str) -> int:
    # Count words as sequences of alphanumerics/apostrophes
    tokens = re.findall(r"\b[\w'-]+\b", text)
    return len(tokens)


def extract_quotes_with_citations(email_text: str, workspace: Path) -> List[Dict]:
    """
    Find patterns like "quoted text" [filename:line] or ‘/’ variations.
    Returns list of dicts with keys: quote, file_path, line_number, line_text.
    """
    results: List[Dict] = []
    # Patterns for double quotes and single quotes with citation
    patterns = [
        r'["“]([^"\n]+)["”]\s*\[([^\]:\n]+):(\d+)\]',
        r"[']([^'\n]+)[']\s*\[([^\]:\n]+):(\d+)\]",
    ]
    for pat in patterns:
        for m in re.finditer(pat, email_text):
            quoted = m.group(1).strip()
            fname = m.group(2).strip()
            lnum_str = m.group(3).strip()
            try:
                lnum = int(lnum_str)
            except Exception:
                continue
            fpath = resolve_source_path(workspace, fname)
            if fpath is None:
                # Try resolve by stripping leading ./ or input/
                alt = fname
                if alt.startswith("./"):
                    alt = alt[2:]
                if alt.startswith("input/"):
                    alt = alt[len("input/"):]
                fpath = resolve_source_path(workspace, alt)
            if fpath is None:
                continue
            file_lines = read_lines(fpath)
            if file_lines is None or not (1 <= lnum <= len(file_lines)):
                continue
            line_text = file_lines[lnum - 1]
            # Check verbatim substring
            if quoted and quoted in line_text:
                results.append({
                    "quote": quoted,
                    "file_path": fpath.resolve(),
                    "line_number": lnum,
                    "line_text": line_text,
                    "label": fname,
                })
    return results


def normalize_path(p: Path) -> Path:
    try:
        return p.resolve()
    except Exception:
        return p


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "grep_output_parses_and_matches_files": 0.0,
        "grep_output_completeness": 0.0,
        "extracted_csv_format_and_verification": 0.0,
        "extracted_csv_row_count": 0.0,
        "extracted_csv_multiple_files": 0.0,
        "extracted_csv_rows_from_grep_output": 0.0,
        "email_word_count": 0.0,
        "email_quotes_with_citations": 0.0,
        "email_quotes_from_extracted_lines": 0.0,
        "email_content_requirements": 0.0,
    }

    # Prepare expected matches from input files
    expected_matches = compute_expected_matches(workspace)
    expected_set: Set[Tuple[Path, int, str]] = set((normalize_path(p), ln, txt) for (p, ln, txt) in expected_matches)

    # Validate grep_output.txt
    grep_output_path = workspace / "output" / "grep_output.txt"
    parsed_grep = None
    if grep_output_path.exists():
        parsed_grep = parse_grep_output(workspace, grep_output_path)
        if parsed_grep is not None:
            # basic parsing and validation passed
            scores["grep_output_parses_and_matches_files"] = 1.0
            parsed_set: Set[Tuple[Path, int, str]] = set((normalize_path(p), ln, txt) for (p, ln, txt, _) in parsed_grep)
            if parsed_set == expected_set:
                scores["grep_output_completeness"] = 1.0
            else:
                scores["grep_output_completeness"] = 0.0
        else:
            scores["grep_output_parses_and_matches_files"] = 0.0
            scores["grep_output_completeness"] = 0.0
    else:
        # Missing grep output
        scores["grep_output_parses_and_matches_files"] = 0.0
        scores["grep_output_completeness"] = 0.0

    # Validate extracted_lines.csv
    csv_path = workspace / "output" / "extracted_lines.csv"
    header_and_rows = load_csv_rows(csv_path) if csv_path.exists() else None
    extracted_rows_verified: List[Tuple[Path, int, str]] = []
    if header_and_rows is not None:
        header, rows = header_and_rows
        # Strict header check
        expected_header = ["source_file", "line_number", "match_term", "text"]
        if header == expected_header and len(rows) >= 0:
            all_ok = True
            distinct_files: Set[Path] = set()
            for row in rows:
                src = row.get("source_file", "")
                lnum_str = row.get("line_number", "")
                mterm = row.get("match_term", "")
                text = row.get("text", "")
                # Resolve source file
                fpath = resolve_source_path(workspace, src)
                if fpath is None:
                    all_ok = False
                    break
                file_lines = read_lines(fpath)
                if file_lines is None:
                    all_ok = False
                    break
                try:
                    lnum = int(lnum_str)
                except Exception:
                    all_ok = False
                    break
                if not (1 <= lnum <= len(file_lines)):
                    all_ok = False
                    break
                actual_line = file_lines[lnum - 1]
                if actual_line != text:
                    all_ok = False
                    break
                # Determine expected match term by order
                expected_term = determine_match_term(actual_line)
                if expected_term is None or mterm != expected_term:
                    all_ok = False
                    break
                extracted_rows_verified.append((fpath.resolve(), lnum, actual_line))
                distinct_files.add(fpath.resolve())
            if all_ok:
                scores["extracted_csv_format_and_verification"] = 1.0
            else:
                scores["extracted_csv_format_and_verification"] = 0.0

            # Row count
            if len(rows) >= 8:
                scores["extracted_csv_row_count"] = 1.0

            # Multiple files
            if len(distinct_files) >= 2:
                scores["extracted_csv_multiple_files"] = 1.0

            # Rows should correspond to grep output subset
            if parsed_grep is not None:
                grep_triplets = set((normalize_path(p), ln, txt) for (p, ln, txt, _) in parsed_grep)
                ok_subset = True
                for trip in extracted_rows_verified:
                    if trip not in grep_triplets:
                        ok_subset = False
                        break
                if ok_subset and len(extracted_rows_verified) > 0:
                    scores["extracted_csv_rows_from_grep_output"] = 1.0
        else:
            # header wrong or malformed
            scores["extracted_csv_format_and_verification"] = 0.0
    else:
        # missing or unparseable
        scores["extracted_csv_format_and_verification"] = 0.0

    # Validate email_draft.txt
    email_path = workspace / "output" / "email_draft.txt"
    if email_path.exists():
        email_text = read_text_file(email_path) or ""
        # word count
        wc = count_words(email_text)
        if 150 <= wc <= 200:
            scores["email_word_count"] = 1.0

        # Extract quotes with citations
        quotes = extract_quotes_with_citations(email_text, workspace)
        if len(quotes) >= 3:
            scores["email_quotes_with_citations"] = 1.0

        # Quotes should be from extracted lines (use CSV verification results if available)
        csv_triplets_set = set(extracted_rows_verified)
        from_extracted_count = 0
        for q in quotes:
            trip = (normalize_path(q["file_path"]), q["line_number"], q["line_text"])
            if trip in csv_triplets_set:
                from_extracted_count += 1
        if from_extracted_count >= 3:
            scores["email_quotes_from_extracted_lines"] = 1.0

        # Content requirements: mention ICE, at least two of cost/battery/sustainability, and closing next step
        lower = email_text.lower()
        concerns = 0
        for key in ["cost", "battery", "sustainab"]:
            if key in lower:
                concerns += 1
        has_ice = "ice" in lower
        # Determine last sentence
        sentences = re.split(r"[.!?]\s*", email_text.strip())
        last_sentence = ""
        for s in reversed(sentences):
            if s.strip():
                last_sentence = s.strip()
                break
        closing_ok = False
        if last_sentence:
            ls = last_sentence.lower()
            if any(w in ls for w in ["review", "request", "propose", "recommend"]):
                closing_ok = True
        if has_ice and concerns >= 2 and closing_ok:
            scores["email_content_requirements"] = 1.0
    else:
        # Missing email file
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()