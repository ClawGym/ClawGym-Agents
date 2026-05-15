import json
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames or [], rows
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_keywords_yaml(path: Path) -> Optional[List[str]]:
    # Minimal YAML parser for the expected structure:
    # keywords:
    #   - incident
    #   - response
    try:
        raw = _read_text(path)
        if raw is None:
            return None
        lines = [l.rstrip("\n") for l in raw.splitlines()]
        keywords: List[str] = []
        in_keywords = False
        indent_level = None
        for line in lines:
            if not in_keywords:
                if line.strip().startswith("keywords:"):
                    in_keywords = True
                    # Determine indentation for list items
                    indent_level = None
                continue
            else:
                if line.strip() == "" or line.strip().startswith("#"):
                    continue
                # Determine if list continues
                stripped = line.lstrip()
                if indent_level is None:
                    indent_level = len(line) - len(stripped)
                # If indentation less than expected, we've left the block
                current_indent = len(line) - len(stripped)
                if current_indent < indent_level:
                    break
                if stripped.startswith("- "):
                    term = stripped[2:].strip()
                    # Strip optional quotes
                    if len(term) >= 2 and ((term[0] == term[-1]) and term[0] in ("'", '"')):
                        term = term[1:-1]
                    if term:
                        keywords.append(term)
                else:
                    # Non-list line within block ends parsing
                    break
        return keywords if keywords else None
    except Exception:
        return None


def _compute_word_and_keyword_counts(text: str, keywords: List[str]) -> Tuple[int, Dict[str, int]]:
    # total_words: simple whitespace-separated word count
    total_words = len([w for w in text.split() if w.strip() != ""])
    counts: Dict[str, int] = {}
    for term in keywords:
        # case-insensitive whole word
        try:
            pattern = re.compile(rf"\b{re.escape(term)}\b", flags=re.IGNORECASE)
            counts[term] = len(pattern.findall(text))
        except re.error:
            counts[term] = 0
    return total_words, counts


def _expected_paths(workspace: Path) -> Dict[str, Path]:
    return {
        "raw_nist_html": workspace / "downloads" / "raw" / "html" / "nist_sp800-61r2.html",
        "raw_enisa_html": workspace / "downloads" / "raw" / "html" / "enisa_good_practice_incident_mgmt.html",
        "raw_nist_pdf": workspace / "downloads" / "raw" / "pdfs" / "nist_sp800-61r2.pdf",
        "raw_enisa_pdf": workspace / "downloads" / "raw" / "pdfs" / "enisa_good_practice_incident_mgmt.pdf",
        "ext_nist_html": workspace / "outputs" / "extracted" / "nist_sp800-61r2.html.txt",
        "ext_enisa_html": workspace / "outputs" / "extracted" / "enisa_good_practice_incident_mgmt.html.txt",
        "ext_nist_pdf": workspace / "outputs" / "extracted" / "nist_sp800-61r2.pdf.txt",
        "ext_enisa_pdf": workspace / "outputs" / "extracted" / "enisa_good_practice_incident_mgmt.pdf.txt",
        "per_document_csv": workspace / "outputs" / "metrics" / "per_document.csv",
        "aggregate_json": workspace / "outputs" / "metrics" / "aggregate.json",
        "report_md": workspace / "outputs" / "report.md",
        "keywords_yaml": workspace / "input" / "keywords.yaml",
    }


def _get_section(text: str, section_header: str, all_headers: List[str]) -> Optional[str]:
    # Extract content between section_header and the next header in all_headers
    lines = text.splitlines()
    header_indices = {}
    for idx, line in enumerate(lines):
        if line.strip() in all_headers:
            header_indices[line.strip()] = idx
    if section_header not in header_indices:
        return None
    start = header_indices[section_header] + 1
    # Find next header index after start
    following_indices = [i for (h, i) in header_indices.items() if i > header_indices[section_header]]
    end = min(following_indices) if following_indices else len(lines)
    section_lines = lines[start:end]
    return "\n".join(section_lines).strip()


def _recompute_counts_for_all(extracted_paths: Dict[Tuple[str, str], Path], keywords: List[str]) -> Dict[Tuple[str, str], Dict[str, int]]:
    # Returns mapping (doc_id, source_type) -> dict with total_words and keyword counts (keys include 'total_words' and keyword_<term>)
    result: Dict[Tuple[str, str], Dict[str, int]] = {}
    for (doc_id, source_type), path in extracted_paths.items():
        text = _read_text(path)
        if text is None:
            return {}
        total_words, kw_counts = _compute_word_and_keyword_counts(text, keywords)
        row: Dict[str, int] = {"total_words": total_words}
        for term, cnt in kw_counts.items():
            row[f"keyword_{term}"] = cnt
        result[(doc_id, source_type)] = row
    return result


def _build_extracted_paths_map(workspace: Path) -> Dict[Tuple[str, str], Path]:
    # Build expected mapping of (doc_id, source_type) to extracted text path
    return {
        ("nist_sp800-61r2", "html"): workspace / "outputs" / "extracted" / "nist_sp800-61r2.html.txt",
        ("nist_sp800-61r2", "pdf"): workspace / "outputs" / "extracted" / "nist_sp800-61r2.pdf.txt",
        ("enisa_good_practice_incident_mgmt", "html"): workspace / "outputs" / "extracted" / "enisa_good_practice_incident_mgmt.html.txt",
        ("enisa_good_practice_incident_mgmt", "pdf"): workspace / "outputs" / "extracted" / "enisa_good_practice_incident_mgmt.pdf.txt",
    }


def _parse_int(s: str) -> Optional[int]:
    try:
        s = s.strip()
        if s == "":
            return None
        return int(s)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    paths = _expected_paths(workspace)
    scores = {
        "raw_nist_html_official_domain": 0.0,
        "raw_enisa_html_official_domain": 0.0,
        "raw_nist_pdf_signature": 0.0,
        "raw_enisa_pdf_signature": 0.0,
        "extracted_texts_present": 0.0,
        "per_document_csv_structure": 0.0,
        "per_document_csv_rows_complete": 0.0,
        "per_document_total_words_match": 0.0,
        "per_document_keyword_counts_match": 0.0,
        "per_document_pages_fields_valid": 0.0,
        "aggregate_totals_correct": 0.0,
        "aggregate_top_keywords_valid": 0.0,
        "report_overview_valid": 0.0,
        "report_keyword_totals_listed": 0.0,
        "report_per_document_summary_listed": 0.0,
        "report_top_terms_listed": 0.0,
    }

    # Load keywords
    keywords = _parse_keywords_yaml(paths["keywords_yaml"])
    if keywords is None:
        # Without keywords, many checks cannot proceed; leave zeros for those
        keywords = []

    # Check raw HTML NIST domain
    nist_html = _read_text(paths["raw_nist_html"])
    if nist_html is not None:
        if "nist.gov" in nist_html.lower():
            scores["raw_nist_html_official_domain"] = 1.0

    # Check raw HTML ENISA domain
    enisa_html = _read_text(paths["raw_enisa_html"])
    if enisa_html is not None:
        if "enisa.europa.eu" in enisa_html.lower():
            scores["raw_enisa_html_official_domain"] = 1.0

    # Check raw PDFs signatures
    nist_pdf_bytes = _read_bytes(paths["raw_nist_pdf"])
    if nist_pdf_bytes is not None and nist_pdf_bytes[:4] == b"%PDF":
        scores["raw_nist_pdf_signature"] = 1.0

    enisa_pdf_bytes = _read_bytes(paths["raw_enisa_pdf"])
    if enisa_pdf_bytes is not None and enisa_pdf_bytes[:4] == b"%PDF":
        scores["raw_enisa_pdf_signature"] = 1.0

    # Extracted text existence
    extracted_ok = True
    for key in ["ext_nist_html", "ext_enisa_html", "ext_nist_pdf", "ext_enisa_pdf"]:
        txt = _read_text(paths[key])
        if txt is None or len(txt.strip()) == 0:
            extracted_ok = False
            break
    if extracted_ok:
        scores["extracted_texts_present"] = 1.0

    # Per-document CSV structure and content checks
    per_doc = _load_csv_dicts(paths["per_document_csv"])
    extracted_paths_map = _build_extracted_paths_map(workspace)
    recomputed_counts: Dict[Tuple[str, str], Dict[str, int]] = {}
    if per_doc is not None and keywords:
        header, rows = per_doc
        expected_columns = {"doc_id", "source_type", "total_words", "pages"}
        expected_keyword_columns = {f"keyword_{k}" for k in keywords}
        if header is not None:
            header_set = set(header)
        else:
            header_set = set()
        if expected_columns.issubset(header_set) and expected_keyword_columns.issubset(header_set):
            scores["per_document_csv_structure"] = 1.0

        # Rows complete: expect exactly 4 rows for the 4 extracted files
        expected_entries = {
            ("nist_sp800-61r2", "html"),
            ("nist_sp800-61r2", "pdf"),
            ("enisa_good_practice_incident_mgmt", "html"),
            ("enisa_good_practice_incident_mgmt", "pdf"),
        }
        seen_entries = set()
        for r in rows:
            seen_entries.add((r.get("doc_id", ""), r.get("source_type", "")))
        if len(rows) == 4 and expected_entries == seen_entries:
            scores["per_document_csv_rows_complete"] = 1.0

        # Recompute counts from extracted text files
        recomputed_counts = _recompute_counts_for_all(extracted_paths_map, keywords)
        # Compare total_words and keyword counts
        all_words_match = True
        all_keyword_counts_match = True
        pages_valid = True
        for r in rows:
            doc_id = r.get("doc_id", "")
            source_type = r.get("source_type", "")
            key = (doc_id, source_type)
            # Verify pages: For HTML blank or 0; For PDF positive integer
            pages_field = r.get("pages", "")
            if source_type == "html":
                if pages_field is None:
                    pages_field = ""
                if pages_field.strip() != "":
                    pval = _parse_int(pages_field)
                    if pval is None or pval != 0:
                        pages_valid = False
                # else blank is acceptable
            elif source_type == "pdf":
                pval = _parse_int(pages_field or "")
                if pval is None or pval <= 0:
                    pages_valid = False
            else:
                pages_valid = False

            if key in recomputed_counts:
                # total_words
                expected_tw = recomputed_counts[key]["total_words"]
                tw_val = _parse_int(str(r.get("total_words", "")).strip())
                if tw_val is None or tw_val != expected_tw:
                    all_words_match = False
                # keyword counts
                for k in keywords:
                    col = f"keyword_{k}"
                    expected_cnt = recomputed_counts[key][col]
                    kv = r.get(col, "")
                    kv_int = _parse_int(str(kv))
                    if kv_int is None or kv_int != expected_cnt:
                        all_keyword_counts_match = False
            else:
                all_words_match = False
                all_keyword_counts_match = False

        if all_words_match:
            scores["per_document_total_words_match"] = 1.0
        if all_keyword_counts_match:
            scores["per_document_keyword_counts_match"] = 1.0
        if pages_valid:
            scores["per_document_pages_fields_valid"] = 1.0

    # Aggregate JSON checks
    agg = _safe_load_json(paths["aggregate_json"])
    if agg is not None and keywords and recomputed_counts:
        # Build totals from recomputed per-document counts
        totals: Dict[str, int] = {k: 0 for k in keywords}
        for _, counts in recomputed_counts.items():
            for k in keywords:
                totals[k] += counts[f"keyword_{k}"]
        # Check total_counts mapping
        tc = agg.get("total_counts")
        if isinstance(tc, dict):
            # Ensure exact keys and counts
            tc_keys = set(tc.keys())
            expected_keys = set(keywords)
            if tc_keys == expected_keys:
                counts_match = True
                for k in keywords:
                    if not isinstance(tc.get(k), int) or tc.get(k) != totals[k]:
                        counts_match = False
                        break
                if counts_match:
                    scores["aggregate_totals_correct"] = 1.0

        # Check top_keywords
        top_list = agg.get("top_keywords")
        if isinstance(top_list, list) and len(top_list) == 3:
            sorted_terms = sorted(totals.items(), key=lambda x: (-x[1], x[0]))
            if sorted_terms:
                third_count = sorted_terms[2][1] if len(sorted_terms) >= 3 else (sorted_terms[-1][1] if sorted_terms else 0)
                valid_terms = {term for term, cnt in totals.items() if cnt >= third_count}
                provided_terms = set()
                provided_counts_ok = True
                for item in top_list:
                    if not isinstance(item, dict):
                        provided_counts_ok = False
                        break
                    term = item.get("term")
                    count_val = item.get("count")
                    if not isinstance(term, str) or not isinstance(count_val, int):
                        provided_counts_ok = False
                        break
                    if term not in totals:
                        provided_counts_ok = False
                        break
                    if totals[term] != count_val:
                        provided_counts_ok = False
                        break
                    provided_terms.add(term)
                if provided_counts_ok and len(provided_terms) == 3 and provided_terms.issubset(valid_terms):
                    scores["aggregate_top_keywords_valid"] = 1.0

    # Report checks
    report_text = _read_text(paths["report_md"])
    if report_text is not None:
        headers = ["Overview:", "Keyword totals:", "Per-document summary:", "Top terms for moderators:"]
        # Overview
        overview = _get_section(report_text, "Overview:", headers)
        if overview is not None:
            ol = overview.lower()
            if ("nist" in ol) and ("enisa" in ol) and ("official" in ol) and ("keyword" in ol) and ("download" in ol) and ("analy" in ol):
                scores["report_overview_valid"] = 1.0

        # To proceed with detailed checks, ensure we have keywords and aggregate totals/computed counts
        if keywords and recomputed_counts:
            # Build totals again for report validation
            totals: Dict[str, int] = {k: 0 for k in keywords}
            for _, counts in recomputed_counts.items():
                for k in keywords:
                    totals[k] += counts[f"keyword_{k}"]

            # Keyword totals section
            kw_section = _get_section(report_text, "Keyword totals:", headers)
            if kw_section is not None:
                all_listed = True
                for term in keywords:
                    pattern = re.compile(rf"\b{re.escape(term)}\b", flags=re.IGNORECASE)
                    found = False
                    for line in kw_section.splitlines():
                        if pattern.search(line):
                            nums = re.findall(r"\d+", line)
                            if nums:
                                if int(nums[0]) == totals[term]:
                                    found = True
                                    break
                    if not found:
                        all_listed = False
                        break
                if all_listed:
                    scores["report_keyword_totals_listed"] = 1.0

            # Per-document summary section
            pds_section = _get_section(report_text, "Per-document summary:", headers)
            if pds_section is not None:
                per_doc_ok = True
                per_doc_rows = _load_csv_dicts(paths["per_document_csv"])
                expected_entries = {
                    ("nist_sp800-61r2", "html"),
                    ("nist_sp800-61r2", "pdf"),
                    ("enisa_good_practice_incident_mgmt", "html"),
                    ("enisa_good_practice_incident_mgmt", "pdf"),
                }
                lines = pds_section.splitlines()
                norm_lines = [ln.strip() for ln in lines]
                for doc_id, source_type in expected_entries:
                    expected_tw = recomputed_counts.get((doc_id, source_type), {}).get("total_words", None)
                    pages_expected: Optional[int] = None
                    if per_doc_rows is not None:
                        header, rows = per_doc_rows
                        for r in rows:
                            if r.get("doc_id") == doc_id and r.get("source_type") == source_type:
                                if source_type == "pdf":
                                    pages_expected = _parse_int(r.get("pages", "") or "")
                                else:
                                    pages_expected = None
                                break
                    found_line = None
                    for line in norm_lines:
                        if line.startswith(("-", "*")) and doc_id in line and source_type in line:
                            found_line = line
                            break
                    if found_line is None:
                        per_doc_ok = False
                        break
                    if expected_tw is None or str(expected_tw) not in found_line:
                        per_doc_ok = False
                        break
                    if source_type == "pdf":
                        if pages_expected is None or pages_expected <= 0 or str(pages_expected) not in found_line:
                            per_doc_ok = False
                            break
                if per_doc_ok:
                    scores["report_per_document_summary_listed"] = 1.0

            # Top terms section
            top_section = _get_section(report_text, "Top terms for moderators:", headers)
            if top_section is not None:
                totals_items = list(totals.items())
                if totals_items:
                    sorted_terms = sorted(totals_items, key=lambda x: (-x[1], x[0]))
                    third_count = sorted_terms[2][1] if len(sorted_terms) >= 3 else (sorted_terms[-1][1] if sorted_terms else 0)
                    valid_top_terms = {term for term, cnt in totals.items() if cnt >= third_count}
                    bullets = [ln.strip() for ln in top_section.splitlines() if ln.strip().startswith(("-", "*"))]
                    validated_terms: set = set()
                    for term in valid_top_terms:
                        cnt = totals[term]
                        for b in bullets:
                            if term in b and str(cnt) in b:
                                validated_terms.add(term)
                                break
                    if len(validated_terms) >= 3:
                        scores["report_top_terms_listed"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()