import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text_lines(path: Path) -> Optional[List[str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
        # Normalize newlines and split without keeping newline characters
        lines = text.splitlines()
        return lines
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return [], []
            header = rows[0]
            data = rows[1:]
            return header, data
    except Exception:
        return None, None


def _posix_relpath(path: Path, base: Path) -> str:
    try:
        rel = path.relative_to(base)
    except ValueError:
        rel = path
    return rel.as_posix()


def _extract_quotes_from_line(line: str, is_blockquote: bool) -> List[str]:
    # For both cases, prioritize extracting content inside straight double quotes "..."
    # If none found in blockquote, use the entire content after "> " as a single quote candidate.
    candidates: List[str] = []
    content = line
    if is_blockquote and line.lstrip().startswith("> "):
        # Use the first occurrence of '> ' at the start after optional leading spaces
        # but spec says begins with "> ", so assume it's at the start
        idx = line.find("> ")
        content = line[idx + 2:] if idx != -1 else line

    # Find all quoted segments
    matches = list(re.finditer(r'"([^"]+)"', content))
    if matches:
        for m in matches:
            candidates.append(m.group(1))
    else:
        if is_blockquote:
            # Take the content after "> " as the quote text when no quotes present
            candidates.append(content.strip())
    return candidates


def _find_year_in_line(line: str) -> str:
    m = re.search(r'(?<!\d)(\d{4})(?!\d)', line)
    if m:
        return m.group(1)
    return "unknown"


def _extract_attribution_from_line(line: str) -> str:
    if "—" in line:
        after = line.split("—", 1)[1].strip()
        # Remove trailing year in parentheses if present
        after = re.sub(r'\s*\(\d{4}\)\s*$', '', after).strip()
        if after:
            return after
    return "unknown"


def _scan_research_expected(workspace: Path) -> Tuple[List[Dict[str, str]], Dict[str, int], int]:
    research_root = workspace / "input" / "research"
    expected_rows: List[Dict[str, str]] = []
    per_file_counts: Dict[str, int] = {}
    total_files_scanned = 0

    if not research_root.exists():
        return [], {}, 0

    # Collect candidate files: .txt, .md, .markdown
    files: List[Path] = []
    for p in research_root.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".txt", ".md", ".markdown"}:
            files.append(p)

    # Deterministic order
    files_sorted = sorted(files, key=lambda x: _posix_relpath(x, workspace))

    # Pre-dedup list
    pre_dedup: List[Dict[str, str]] = []

    for file_path in files_sorted:
        lines = _read_text_lines(file_path)
        total_files_scanned += 1
        rel = _posix_relpath(file_path, workspace)
        count_for_file = 0
        if lines is None:
            per_file_counts[rel] = 0
            continue
        for idx, line in enumerate(lines, start=1):
            line_stripped = line.rstrip("\n")
            is_blockquote = line_stripped.startswith("> ")
            # Determine if this line contains quote candidates
            candidates = _extract_quotes_from_line(line_stripped, is_blockquote)
            if not candidates:
                continue
            # Check each candidate for keyword presence
            for qt in candidates:
                if re.search(r'\btrial\b', qt, flags=re.IGNORECASE) or re.search(r'samizdat', qt, flags=re.IGNORECASE):
                    # Matched
                    count_for_file += 1
                    entry = {
                        "source_file": rel,
                        "line_start": str(idx),
                        "line_end": str(idx),
                        "speaker_or_attribution": _extract_attribution_from_line(line_stripped),
                        "year": _find_year_in_line(line_stripped),
                        "quote_text": qt,
                    }
                    pre_dedup.append(entry)
        per_file_counts[rel] = count_for_file

    # Deduplicate by quote_text, keeping first occurrence
    seen_texts = set()
    for row in pre_dedup:
        qt = row["quote_text"]
        if qt not in seen_texts:
            expected_rows.append(row)
            seen_texts.add(qt)

    return expected_rows, per_file_counts, total_files_scanned


def _parse_csv_quotes(csv_path: Path) -> Optional[List[Dict[str, str]]]:
    header, rows = _load_csv(csv_path)
    if header is None or rows is None:
        return None
    expected_header = ["source_file", "line_start", "line_end", "speaker_or_attribution", "year", "quote_text"]
    if header != expected_header:
        # Still try to parse rows into dicts using this header if length matches
        if len(header) != len(expected_header):
            return []
        # Otherwise, map with given header to allow downstream checks
    result: List[Dict[str, str]] = []
    for r in rows:
        if len(r) != 6:
            return None
        result.append({
            "source_file": r[0],
            "line_start": r[1],
            "line_end": r[2],
            "speaker_or_attribution": r[3],
            "year": r[4],
            "quote_text": r[5],
        })
    return result


def _collapse_whitespace(s: str) -> str:
    return " ".join(s.split())


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "part_a_csv_exists_and_header": 0.0,
        "part_a_csv_rows_count": 0.0,
        "part_a_csv_content_match": 0.0,
        "part_a_no_duplicate_quote_text_in_csv": 0.0,
        "part_a_report_exists_and_schema": 0.0,
        "part_a_report_totals_correct": 0.0,
        "part_a_report_per_file_counts_correct": 0.0,
        "part_a_cross_consistency_csv_json": 0.0,
        "part_b_output_exists": 0.0,
        "part_b_subject_preserved_exactly": 0.0,
        "part_b_body_includes_required_elements": 0.0,
        "part_b_body_single_paragraph_and_length": 0.0,
        "part_b_body_rewritten_changed": 0.0,
    }

    # Compute expected data from inputs
    expected_rows, expected_per_file_counts, expected_total_files = _scan_research_expected(workspace)
    expected_total_quotes = len(expected_rows)

    # Part A: CSV checks
    csv_path = workspace / "output" / "extracted_quotes.csv"
    csv_header_ok = False
    csv_rows: Optional[List[Dict[str, str]]] = None
    if csv_path.exists():
        header, _ = _load_csv(csv_path)
        if header is not None:
            if header == ["source_file", "line_start", "line_end", "speaker_or_attribution", "year", "quote_text"]:
                csv_header_ok = True
                scores["part_a_csv_exists_and_header"] = 1.0
        csv_rows = _parse_csv_quotes(csv_path)
    else:
        csv_rows = None

    # Rows count check
    if csv_rows is not None:
        if len(csv_rows) == expected_total_quotes:
            scores["part_a_csv_rows_count"] = 1.0

    # Content match check (set equality on full tuple)
    if csv_rows is not None:
        def row_to_tuple(r: Dict[str, str]) -> Tuple[str, int, int, str, str, str]:
            try:
                ls = int(str(r["line_start"]).strip())
                le = int(str(r["line_end"]).strip())
            except Exception:
                # If conversion fails, use -1 to ensure mismatch
                ls = -1
                le = -1
            return (
                r["source_file"],
                ls,
                le,
                r["speaker_or_attribution"],
                r["year"],
                r["quote_text"],
            )

        actual_set = set(row_to_tuple(r) for r in csv_rows)
        expected_set = set(
            (er["source_file"], int(er["line_start"]), int(er["line_end"]), er["speaker_or_attribution"], er["year"], er["quote_text"])
            for er in expected_rows
        )
        if actual_set == expected_set and len(csv_rows) == len(expected_rows):
            scores["part_a_csv_content_match"] = 1.0

        # Duplicates by quote_text
        quote_texts = [r.get("quote_text", "") for r in csv_rows]
        if len(set(quote_texts)) == len(quote_texts):
            scores["part_a_no_duplicate_quote_text_in_csv"] = 1.0

    # Part A: JSON report checks
    report_path = workspace / "output" / "extraction_report.json"
    report = None
    if report_path.exists():
        report = _load_json(report_path)
        if isinstance(report, dict) and \
           "total_files_scanned" in report and \
           "total_quotes_extracted" in report and \
           "per_file_counts" in report and \
           isinstance(report.get("per_file_counts"), dict):
            # Validate type of values in per_file_counts
            per_counts_types_ok = all(isinstance(k, str) and isinstance(v, int) for k, v in report["per_file_counts"].items())
            if isinstance(report.get("total_files_scanned"), int) and isinstance(report.get("total_quotes_extracted"), int) and per_counts_types_ok:
                scores["part_a_report_exists_and_schema"] = 1.0

    if isinstance(report, dict):
        # Totals correct
        if report.get("total_files_scanned") == expected_total_files and report.get("total_quotes_extracted") == expected_total_quotes:
            scores["part_a_report_totals_correct"] = 1.0
        # per_file_counts correct (exact mapping)
        if report.get("per_file_counts") == expected_per_file_counts:
            scores["part_a_report_per_file_counts_correct"] = 1.0

        # Cross consistency between CSV and JSON
        consistent = False
        if csv_rows is not None:
            unique_quotes_csv = len({r.get("quote_text", "") for r in csv_rows})
            if isinstance(report.get("total_quotes_extracted"), int):
                consistent = (unique_quotes_csv == report.get("total_quotes_extracted"))
        if consistent:
            scores["part_a_cross_consistency_csv_json"] = 1.0

    # Part B: Outreach email rewrite checks
    out_email_path = workspace / "output" / "outreach_email_rewrite.txt"
    if out_email_path.exists():
        scores["part_b_output_exists"] = 1.0
        out_lines = _read_text_lines(out_email_path) or []
        # Load original subject and body
        in_draft_path = workspace / "input" / "outreach_draft.txt"
        orig_subject = None
        orig_body_lines: List[str] = []
        in_lines = _read_text_lines(in_draft_path) or []
        if in_lines:
            orig_subject = in_lines[0]
            orig_body_lines = in_lines[1:] if len(in_lines) > 1 else []

        # Subject preserved exactly
        if out_lines and orig_subject is not None and out_lines[0] == orig_subject:
            scores["part_b_subject_preserved_exactly"] = 1.0

        # Body checks
        body_lines = out_lines[1:] if len(out_lines) > 1 else []
        body_text = "\n".join(body_lines).strip()
        # Required elements
        req_ok = True
        # project title 'Dissident Voices'
        if "Dissident Voices" not in body_text:
            req_ok = False
        # materials 'trial transcript excerpts' and 'samizdat passages (Chronicle of Current Events)'
        if re.search(r'trial transcript excerpts', body_text, flags=re.IGNORECASE) is None:
            req_ok = False
        if re.search(r'samizdat passages\s*\(Chronicle of Current Events\)', body_text, flags=re.IGNORECASE) is None:
            req_ok = False
        # non-commercial educational
        has_noncommercial = re.search(r'non-?commercial', body_text, flags=re.IGNORECASE) is not None
        has_educational = re.search(r'educational', body_text, flags=re.IGNORECASE) is not None
        if not (has_noncommercial and has_educational):
            req_ok = False
        # request for reply by 'May 30'
        if "May 30" not in body_text:
            req_ok = False
        # contact email
        if "filmmaker@example.org" not in body_text:
            req_ok = False
        if req_ok and body_text:
            scores["part_b_body_includes_required_elements"] = 1.0

        # Single paragraph and <= 120 words
        # Single paragraph: no blank lines in body
        no_blank_lines = True
        for bl in body_lines:
            if bl.strip() == "":
                no_blank_lines = False
                break
        word_count = len(body_text.split())
        if no_blank_lines and word_count <= 120 and word_count > 0:
            scores["part_b_body_single_paragraph_and_length"] = 1.0

        # Body rewritten changed from original
        if orig_body_lines:
            orig_body = "\n".join(orig_body_lines).strip()
            if _collapse_whitespace(body_text) and _collapse_whitespace(body_text) != _collapse_whitespace(orig_body):
                scores["part_b_body_rewritten_changed"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()