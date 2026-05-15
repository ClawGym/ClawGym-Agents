import json
import csv
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


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


def _load_input_artworks(workspace: Path) -> Tuple[bool, List[dict], Dict[str, set], Dict[str, set], List[str]]:
    """
    Returns:
      ok: True iff all JSON files were parsed and contain required fields.
      items: list of {'id', 'author', 'work'} for each artwork
      works_by_author: author -> set of works
      files_by_author: author -> set of ids
      errors: list of error messages
    """
    input_dir = workspace / "input" / "artworks"
    errors: List[str] = []
    items: List[dict] = []
    works_by_author: Dict[str, set] = {}
    files_by_author: Dict[str, set] = {}

    if not input_dir.exists():
        errors.append("input/artworks directory missing")
        return False, items, works_by_author, files_by_author, errors

    json_paths = sorted(input_dir.glob("*.json"))
    if not json_paths:
        errors.append("no JSON files under input/artworks")
        return False, items, works_by_author, files_by_author, errors

    all_ok = True
    for p in json_paths:
        data = _safe_load_json(p)
        if data is None:
            errors.append(f"failed to parse JSON: {p}")
            all_ok = False
            continue
        for key in ("id", "inspiration_author", "inspiration_work"):
            if key not in data or not isinstance(data[key], str) or not data[key].strip():
                errors.append(f"missing or invalid required field '{key}' in {p}")
                all_ok = False
        if not all_ok:
            # continue to next file but do not add this one to items
            continue
        item = {
            "id": data["id"].strip(),
            "author": data["inspiration_author"].strip(),
            "work": data["inspiration_work"].strip(),
        }
        items.append(item)
        works_by_author.setdefault(item["author"], set()).add(item["work"])
        files_by_author.setdefault(item["author"], set()).add(item["id"])
    return all_ok, items, works_by_author, files_by_author, errors


def _parse_references_csv(workspace: Path) -> Tuple[bool, bool, List[dict], Dict[str, dict]]:
    """
    Returns:
      exists: file exists
      header_ok: header matches exactly
      rows: list of row dicts (raw strings, evidence_count kept as raw for further parsing)
      by_author: mapping author -> row dict
    """
    csv_path = workspace / "output" / "research" / "references.csv"
    if not csv_path.exists():
        return False, False, [], {}

    # Read raw first line to verify exact header
    try:
        raw_text = csv_path.read_text(encoding="utf-8")
    except Exception:
        return True, False, [], {}

    lines = raw_text.splitlines()
    if not lines:
        return True, False, [], {}

    expected_header = "author,work_titles,files,evidence_count,sources,notes"
    header_ok = lines[0].strip() == expected_header

    # Parse CSV using csv module
    rows: List[dict] = []
    by_author: Dict[str, dict] = {}
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            # If header differs, DictReader fieldnames may differ; still parse for diagnostics
            for row in reader:
                # Normalize None to empty string
                norm_row = {k: (v if v is not None else "") for k, v in row.items()}
                rows.append(norm_row)
                if "author" in norm_row:
                    author = norm_row.get("author", "")
                    if author and author not in by_author:
                        by_author[author] = norm_row
                    elif author:
                        # If duplicate authors, keep the first and ignore subsequent for mapping
                        pass
    except Exception:
        # Malformed CSV
        return True, header_ok, [], {}

    return True, header_ok, rows, by_author


def _count_url_tokens(s: str) -> int:
    if not s:
        return 0
    parts = [t.strip() for t in s.split(";")]
    return sum(1 for t in parts if "://" in t)


def _split_pipe_values(s: str) -> List[str]:
    if not s:
        return []
    return [t.strip() for t in s.split("|") if t.strip()]


def _parse_queries_txt(workspace: Path) -> Tuple[bool, Dict[str, str]]:
    """
    Returns:
      exists: queries file exists
      mapping: author -> query_terms
    """
    qpath = workspace / "output" / "research" / "queries.txt"
    if not qpath.exists():
        return False, {}
    text = _safe_read_text(qpath)
    if text is None:
        return True, {}
    mapping: Dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Expect "<author> - <query terms>"
        if " - " not in line:
            # invalid line
            return True, {}
        author, terms = line.split(" - ", 1)
        author = author.strip()
        terms = terms.strip()
        if not author or not terms:
            return True, {}
        if author in mapping:
            # duplicate author line
            return True, {}
        mapping[author] = terms
    return True, mapping


def _safe_load_test_report(workspace: Path) -> Tuple[bool, Optional[dict]]:
    path = workspace / "output" / "test_report.json"
    if not path.exists():
        return False, None
    data = _safe_load_json(path)
    if data is None or not isinstance(data, dict):
        return True, None
    return True, data


def _validate_script_presence(workspace: Path) -> Tuple[bool, bool]:
    """
    Check that tests/validate_references.py exists and mentions expected paths/fields.
    Returns: (exists, content_ok)
    """
    script_path = workspace / "tests" / "validate_references.py"
    if not script_path.exists():
        return False, False
    text = _safe_read_text(script_path)
    if text is None:
        return True, False
    expected_snippets = [
        "input/artworks",
        "output/research/references.csv",
        "output/test_report.json",
        "evidence_count",
        "sources",
        "notes",
        "files_missing_reference",
        "authors_failing_notes",
    ]
    content_ok = all(snippet in text for snippet in expected_snippets)
    return True, content_ok


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "references_csv_exists_and_header": 0.0,
        "references_csv_authors_coverage": 0.0,
        "references_csv_works_and_files_match": 0.0,
        "references_sources_and_evidence_counts": 0.0,
        "references_notes_contains_czech": 0.0,
        "queries_txt_per_author_format": 0.0,
        "validate_script_exists_and_mentions": 0.0,
        "test_report_exists_and_fields": 0.0,
        "test_report_values_consistency": 0.0,
        "email_draft_headers": 0.0,
        "email_includes_counts_and_references": 0.0,
        "email_lists_issues_if_any": 0.0,
    }

    # Load input artworks
    input_ok, items, works_by_author, files_by_author, _errors = _load_input_artworks(workspace)
    input_authors = sorted(works_by_author.keys())
    total_files = len(items)
    unique_authors = len(input_authors)

    # Parse references CSV
    csv_exists, header_ok, csv_rows, csv_by_author = _parse_references_csv(workspace)

    if csv_exists and header_ok:
        scores["references_csv_exists_and_header"] = 1.0
    else:
        scores["references_csv_exists_and_header"] = 0.0

    # Authors coverage
    if input_ok and csv_exists:
        if all(author in csv_by_author for author in input_authors):
            scores["references_csv_authors_coverage"] = 1.0

    # Works and files match
    if input_ok and csv_exists and input_authors:
        works_files_match = True
        for author in input_authors:
            row = csv_by_author.get(author)
            if not row:
                works_files_match = False
                break
            # Parse row fields
            row_works = set(_split_pipe_values(row.get("work_titles", "")))
            row_files = set(_split_pipe_values(row.get("files", "")))
            expected_works = works_by_author.get(author, set())
            expected_files = files_by_author.get(author, set())
            if row_works != expected_works or row_files != expected_files:
                works_files_match = False
                break
        scores["references_csv_works_and_files_match"] = 1.0 if works_files_match else 0.0

    # Sources and evidence counts
    if csv_exists and csv_rows:
        all_ok_sources = True
        for row in csv_rows:
            try:
                ev_raw = row.get("evidence_count", "")
                ev = int(ev_raw.strip()) if isinstance(ev_raw, str) else int(ev_raw)
            except Exception:
                all_ok_sources = False
                break
            srcs = row.get("sources", "")
            url_count = _count_url_tokens(srcs)
            if ev < 2 or url_count < 2 or ev > url_count:
                all_ok_sources = False
                break
        scores["references_sources_and_evidence_counts"] = 1.0 if all_ok_sources else 0.0

    # Notes contain 'Czech' (case-insensitive)
    if csv_exists and csv_rows:
        notes_ok = True
        for row in csv_rows:
            notes = row.get("notes", "")
            if not isinstance(notes, str) or "czech" not in notes.lower():
                notes_ok = False
                break
        scores["references_notes_contains_czech"] = 1.0 if notes_ok else 0.0

    # Queries per author format
    q_exists, queries_map = _parse_queries_txt(workspace)
    if input_ok and q_exists:
        if len(queries_map) == unique_authors and all(a in queries_map and queries_map[a].strip() for a in input_authors):
            scores["queries_txt_per_author_format"] = 1.0

    # Validate script existence and content mentions
    v_exists, v_content_ok = _validate_script_presence(workspace)
    if v_exists and v_content_ok:
        scores["validate_script_exists_and_mentions"] = 1.0

    # Test report
    tr_exists, tr_data = _safe_load_test_report(workspace)
    if tr_exists and isinstance(tr_data, dict):
        # Field presence and types
        required_fields = {
            "total_files": int,
            "unique_authors": int,
            "authors_with_2plus_sources": int,
            "files_missing_reference": list,
            "authors_failing_notes": list,
            "passed": bool,
        }
        types_ok = True
        for k, typ in required_fields.items():
            if k not in tr_data:
                types_ok = False
                break
            if not isinstance(tr_data[k], typ):
                types_ok = False
                break
        if types_ok:
            scores["test_report_exists_and_fields"] = 1.0

        # Values consistency
        if input_ok and csv_exists and csv_rows and types_ok:
            # Recompute expected values
            # files_missing_reference: any input artwork whose author not in csv or work not in author's work_titles
            recomputed_missing: List[str] = []
            for item in items:
                author = item["author"]
                work = item["work"]
                row = csv_by_author.get(author)
                if not row:
                    recomputed_missing.append(item["id"])
                else:
                    row_works = set(_split_pipe_values(row.get("work_titles", "")))
                    if work not in row_works:
                        recomputed_missing.append(item["id"])
            recomputed_missing_sorted = sorted(recomputed_missing)

            # authors_failing_notes: any CSV row whose notes doesn't contain 'Czech'
            recomputed_authors_failing = sorted(
                [row.get("author", "") for row in csv_rows if "czech" not in (row.get("notes", "") or "").lower()]
            )

            # authors_with_2plus_sources
            recomputed_authors_with_2plus = 0
            for row in csv_rows:
                try:
                    ev_raw = row.get("evidence_count", "")
                    ev = int(ev_raw.strip()) if isinstance(ev_raw, str) else int(ev_raw)
                except Exception:
                    ev = -1
                url_count = _count_url_tokens(row.get("sources", ""))
                if ev >= 2 and url_count >= 2:
                    recomputed_authors_with_2plus += 1

            expected_total_files = total_files if input_ok else 0
            expected_unique_authors = unique_authors if input_ok else 0
            expected_passed = (len(recomputed_missing_sorted) == 0 and len(recomputed_authors_failing) == 0)

            # Compare with test_report.json
            values_ok = True
            if tr_data.get("total_files") != expected_total_files:
                values_ok = False
            if tr_data.get("unique_authors") != expected_unique_authors:
                values_ok = False
            if tr_data.get("authors_with_2plus_sources") != recomputed_authors_with_2plus:
                values_ok = False
            # Compare lists as sorted value equality
            reported_missing = tr_data.get("files_missing_reference", [])
            if sorted(reported_missing) != recomputed_missing_sorted:
                values_ok = False
            reported_authors_failing = tr_data.get("authors_failing_notes", [])
            if sorted(reported_authors_failing) != recomputed_authors_failing:
                values_ok = False
            if tr_data.get("passed") is not expected_passed:
                values_ok = False

            scores["test_report_values_consistency"] = 1.0 if values_ok else 0.0

    # Email draft checks
    email_path = workspace / "output" / "draft_email.txt"
    email_text = _safe_read_text(email_path)
    if email_text is not None:
        has_to = "To: curator@gallery.example" in email_text
        has_subject = "Subject: Provenance check: Czech literature references validated" in email_text
        if has_to and has_subject:
            scores["email_draft_headers"] = 1.0

        # include counts and references.csv path
        counts_ok = False
        mentions_csv = "output/research/references.csv" in email_text
        if tr_data and isinstance(tr_data, dict):
            tf = str(tr_data.get("total_files", ""))
            ua = str(tr_data.get("unique_authors", ""))
            a2 = str(tr_data.get("authors_with_2plus_sources", ""))
            if tf and ua and a2 and (tf in email_text) and (ua in email_text) and (a2 in email_text) and mentions_csv:
                counts_ok = True
        if counts_ok:
            scores["email_includes_counts_and_references"] = 1.0

        # list issues if any
        issues_ok = True
        if tr_data and isinstance(tr_data, dict):
            missing_ids = tr_data.get("files_missing_reference", [])
            failing_authors = tr_data.get("authors_failing_notes", [])
            if missing_ids:
                # every id should be present in the email
                for fid in missing_ids:
                    if str(fid) not in email_text:
                        issues_ok = False
                        break
            if issues_ok and failing_authors:
                for name in failing_authors:
                    if name not in email_text:
                        issues_ok = False
                        break
        # If no issues, it's okay regardless
        if issues_ok:
            scores["email_lists_issues_if_any"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()