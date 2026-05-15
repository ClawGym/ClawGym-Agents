import json
import sys
import re
import csv
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _read_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_simple_yaml(path: Path) -> dict:
    # Minimal parser for flat key: value pairs with optional quotes
    data = {}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return data
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if val.startswith('"') and val.endswith('"') and len(val) >= 2:
            val = val[1:-1]
        elif val.startswith("'") and val.endswith("'") and len(val) >= 2:
            val = val[1:-1]
        data[key] = val
    return data


def _parse_pandoc_citations(md_text: str) -> dict:
    # Find clusters like [@key] or [@k1; @k2], extract @keys and assign numbers in order of first appearance
    mapping = {}
    next_num = 1
    for m in re.finditer(r"\[@([^\]]+)\]", md_text):
        inside = m.group(1)
        keys = re.findall(r"@([A-Za-z0-9:_\-.]+)", inside)
        for k in keys:
            if k not in mapping:
                mapping[k] = next_num
                next_num += 1
    return mapping


def _extract_references_section(md_text: str) -> str:
    lines = md_text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*#+\s*References\s*$", line):
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    # References until end of file
    ref_text = "\n".join(lines[start_idx:]).strip()
    return ref_text


def _safe_read_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = list(reader)
        return header, rows
    except Exception:
        return None, None


def _count_words(text: str) -> int:
    # Count words as sequences of word chars
    return len(re.findall(r"\b\w+\b", text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "watch_script_present": 0.0,
        "outputs_generated_normalized_md": 0.0,
        "outputs_generated_citation_map": 0.0,
        "outputs_generated_references_csv": 0.0,
        "outputs_generated_polished_email": 0.0,
        "citation_map_numbers_correct": 0.0,
        "references_csv_content_correct": 0.0,
        "normalized_md_citations_replaced": 0.0,
        "normalized_md_references_regenerated": 0.0,
        "polished_email_subject_and_placeholders": 0.0,
        "polished_email_word_count_ok": 0.0,
        "cross_consistency_between_outputs": 0.0,
    }

    # Paths
    script_path = workspace / "tools" / "watch_and_process.py"
    normalized_md_path = workspace / "out" / "manuscript_draft.normalized.md"
    citation_map_path = workspace / "out" / "citation_map.json"
    references_csv_path = workspace / "out" / "references.csv"
    email_polished_path = workspace / "out" / "email_to_editor.polished.txt"

    incoming_md_path = workspace / "incoming" / "manuscript_draft.md"
    biblio_path = workspace / "input" / "bibliography.json"
    metadata_yaml_path = workspace / "input" / "metadata.yaml"

    # Check script presence and --once behavior (basic static check)
    if script_path.exists() and script_path.is_file():
        try:
            content = _read_text(script_path)
            if "--once" in content:
                scores["watch_script_present"] = 1.0
        except Exception:
            pass

    # Existence of outputs
    if normalized_md_path.exists():
        scores["outputs_generated_normalized_md"] = 1.0
    if citation_map_path.exists():
        scores["outputs_generated_citation_map"] = 1.0
    if references_csv_path.exists():
        scores["outputs_generated_references_csv"] = 1.0
    if email_polished_path.exists():
        scores["outputs_generated_polished_email"] = 1.0

    # Compute expected citation mapping from incoming manuscript using pandoc-style [@...] only
    incoming_md_text = _read_text(incoming_md_path) if incoming_md_path.exists() else ""
    expected_mapping = _parse_pandoc_citations(incoming_md_text) if incoming_md_text else {}

    # Check citation_map.json correctness
    actual_map = _read_json(citation_map_path) if citation_map_path.exists() else None
    if isinstance(actual_map, dict) and expected_mapping:
        # compare keys and numbers exact match
        try:
            # Convert keys to strings and values to ints
            normalized_actual = {str(k): int(v) for k, v in actual_map.items()}
            if normalized_actual == expected_mapping:
                scores["citation_map_numbers_correct"] = 1.0
        except Exception:
            pass

    # Check references.csv content correctness
    biblio = _read_json(biblio_path) if biblio_path.exists() else None
    header, rows = _safe_read_csv(references_csv_path) if references_csv_path.exists() else (None, None)

    expected_header = ["number", "key", "authors", "title", "journal", "year", "volume", "issue", "pages", "doi"]
    if header is not None and rows is not None and biblio is not None and expected_mapping:
        try:
            header_ok = header == expected_header
            # Build expected rows sorted by number
            exp_items = sorted(expected_mapping.items(), key=lambda kv: kv[1])
            rows_ok = True
            if len(rows) != len(exp_items):
                rows_ok = False
            else:
                for i, row in enumerate(rows):
                    exp_key, exp_num = exp_items[i]
                    # number and key must match exactly
                    if str(row.get("number", "")).strip() != str(exp_num) or str(row.get("key", "")).strip() != exp_key:
                        rows_ok = False
                        break
                    # Other fields compare to biblio values; authors field must contain each author substring
                    bib = biblio.get(exp_key)
                    if not isinstance(bib, dict):
                        rows_ok = False
                        break
                    # Title
                    if str(row.get("title", "")).strip() != str(bib.get("title", "")):
                        rows_ok = False
                        break
                    # Journal
                    if str(row.get("journal", "")).strip() != str(bib.get("journal", "")):
                        rows_ok = False
                        break
                    # Year
                    if str(row.get("year", "")).strip() != str(bib.get("year", "")):
                        rows_ok = False
                        break
                    # Volume
                    if str(row.get("volume", "")).strip() != str(bib.get("volume", "")):
                        rows_ok = False
                        break
                    # Issue
                    if str(row.get("issue", "")).strip() != str(bib.get("issue", "")):
                        rows_ok = False
                        break
                    # Pages
                    if str(row.get("pages", "")).strip() != str(bib.get("pages", "")):
                        rows_ok = False
                        break
                    # DOI
                    if str(row.get("doi", "")).strip() != str(bib.get("doi", "")):
                        rows_ok = False
                        break
                    # Authors: ensure all names appear as substrings, in any order
                    authors_field = str(row.get("authors", ""))
                    authors_list = bib.get("authors", [])
                    if not isinstance(authors_list, list):
                        rows_ok = False
                        break
                    for a in authors_list:
                        if a not in authors_field:
                            rows_ok = False
                            break
                    if not rows_ok:
                        break
            if header_ok and rows_ok:
                scores["references_csv_content_correct"] = 1.0
        except Exception:
            pass

    # Check normalized manuscript citations replaced and references regenerated
    norm_md_text = _read_text(normalized_md_path) if normalized_md_path.exists() else ""
    if norm_md_text and expected_mapping:
        try:
            # Ensure bracketed citations replaced: no "[@key]" remains for expected keys
            replaced_ok = True
            for k, num in expected_mapping.items():
                if f"[@{k}" in norm_md_text:
                    replaced_ok = False
                    break
                # Ensure numeric bracket present at least once
                if f"[{num}]" not in norm_md_text:
                    replaced_ok = False
                    break
            if replaced_ok:
                scores["normalized_md_citations_replaced"] = 1.0
        except Exception:
            pass

        try:
            refs_section = _extract_references_section(norm_md_text)
            if refs_section:
                # Must not include placeholder text
                if "Will be regenerated" in refs_section:
                    regen_ok = False
                else:
                    # Should include authors for cited items and not include uncited ones
                    regen_ok = True
                    # Authors for expected keys
                    if biblio is None:
                        regen_ok = False
                    else:
                        for k in expected_mapping.keys():
                            bib = biblio.get(k, {})
                            alist = bib.get("authors", [])
                            # If authors list not available, fail
                            if not alist:
                                regen_ok = False
                                break
                            # Check first author appears
                            if alist[0] not in refs_section:
                                regen_ok = False
                                break
                        # Uncited example: miller2018 should not appear
                        if "Miller P" in refs_section and "miller2018" not in expected_mapping:
                            regen_ok = False
                if regen_ok:
                    scores["normalized_md_references_regenerated"] = 1.0
        except Exception:
            pass

    # Check polished email subjects/placeholders and word count
    email_text = _read_text(email_polished_path) if email_polished_path.exists() else ""
    metadata = _parse_simple_yaml(metadata_yaml_path) if metadata_yaml_path.exists() else {}
    if email_text and metadata:
        lines = [ln for ln in email_text.splitlines()]
        nonempty = [ln for ln in lines if ln.strip() != ""]
        subj_ok = False
        placeholders_ok = False
        signoff_ok = False
        if nonempty:
            first_line = nonempty[0]
            # Must begin with Subject:
            if first_line.startswith("Subject:"):
                # Must contain manuscript title and journal
                title = metadata.get("manuscript_title") or metadata.get("manuscript_title".lower())
                journal = metadata.get("journal")
                if title and journal and (title in first_line) and (journal in first_line):
                    subj_ok = True
        # Ensure no '{{' placeholders remain
        if "{{" not in email_text and "}}" not in email_text:
            placeholders_ok = True
        # Sign-off must include corresponding_author and affiliation near the end (last 5 non-empty lines)
        corr = metadata.get("corresponding_author")
        aff = metadata.get("affiliation")
        tail = nonempty[-5:] if len(nonempty) >= 5 else nonempty
        tail_text = "\n".join(tail)
        if corr and aff and (corr in tail_text) and (aff in tail_text):
            signoff_ok = True

        if subj_ok and placeholders_ok and signoff_ok:
            scores["polished_email_subject_and_placeholders"] = 1.0

        # Word count check (body excluding first subject line)
        try:
            # Body is everything after the first line (regardless of empties)
            body_text = "\n".join(lines[1:]) if len(lines) > 1 else ""
            wc = _count_words(body_text)
            if wc <= 120 and wc > 0:
                scores["polished_email_word_count_ok"] = 1.0
        except Exception:
            pass

    # Cross consistency between outputs: citation_map.json and references.csv must align
    if isinstance(actual_map, dict) and header is not None and rows is not None:
        try:
            normalized_actual = {str(k): int(v) for k, v in actual_map.items()}
            # From CSV, derive mapping of key->number
            csv_map = {}
            for row in rows:
                key = str(row.get("key", "")).strip()
                num = int(str(row.get("number", "")).strip()) if str(row.get("number", "")).strip().isdigit() else None
                if key and num is not None:
                    csv_map[key] = num
            if csv_map and normalized_actual and csv_map == normalized_actual:
                scores["cross_consistency_between_outputs"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()