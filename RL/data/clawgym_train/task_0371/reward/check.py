import json
import re
import sys
import csv
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def parse_bibtex_entries(text: str) -> Optional[List[Dict]]:
    if text is None:
        return None
    entries = []
    i = 0
    n = len(text)
    while i < n:
        at = text.find('@', i)
        if at == -1:
            break
        brace_open = text.find('{', at)
        if brace_open == -1:
            break
        entry_type = text[at + 1:brace_open].strip()
        j = brace_open
        depth = 0
        end = None
        while j < n:
            ch = text[j]
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = j
                    break
            j += 1
        if end is None:
            break
        inside = text[brace_open + 1:end].strip()
        if ',' not in inside:
            i = end + 1
            continue
        key_part, fields_part = inside.split(',', 1)
        key = key_part.strip()
        fields = _parse_bib_fields(fields_part)
        entries.append({
            "type": entry_type,
            "key": key,
            "fields": fields,
            "raw": text[at:end + 1],
        })
        i = end + 1
    return entries


def _parse_bib_fields(fields_part: str) -> Dict[str, str]:
    result = {}
    s = fields_part.strip().rstrip(',')
    i = 0
    n = len(s)
    current = []
    parts = []
    depth_brace = 0
    depth_quote = False
    while i < n:
        ch = s[i]
        if ch == '"' and depth_brace == 0:
            depth_quote = not depth_quote
            current.append(ch)
        elif ch == '{' and not depth_quote:
            depth_brace += 1
            current.append(ch)
        elif ch == '}' and not depth_quote:
            depth_brace = max(0, depth_brace - 1)
            current.append(ch)
        elif ch == ',' and depth_brace == 0 and not depth_quote:
            parts.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    if current:
        leftover = ''.join(current).strip()
        if leftover:
            parts.append(leftover)
    for p in parts:
        if '=' not in p:
            continue
        name, val = p.split('=', 1)
        name = name.strip().lower()
        val = val.strip().rstrip(',')
        if val.startswith('{') and val.endswith('}'):
            val_clean = val[1:-1].strip()
        elif val.startswith('"') and val.endswith('"'):
            val_clean = val[1:-1].strip()
        else:
            val_clean = val.strip()
        result[name] = val_clean
    return result


def count_non_empty_fields(fields: Dict[str, str]) -> int:
    cnt = 0
    for _, v in fields.items():
        if v is None:
            continue
        if str(v).strip() != "":
            cnt += 1
    return cnt


def deduplicate_bib_by_doi(entries: List[Dict]) -> Tuple[List[Dict], Dict[str, str]]:
    groups: Dict[Optional[str], List[Dict]] = {}
    for e in entries:
        doi_val = e["fields"].get("doi")
        norm_doi = doi_val.strip().lower() if doi_val is not None else None
        groups.setdefault(norm_doi, []).append(e)
    kept = []
    mapping = {}
    for doi, group in groups.items():
        if doi is None:
            for e in group:
                kept.append(e)
            continue
        best = None
        best_count = -1
        for e in group:
            c = count_non_empty_fields(e["fields"])
            if c > best_count:
                best = e
                best_count = c
            elif c == best_count:
                if best is None or e["key"] < best["key"]:
                    best = e
        for e in group:
            if e["key"] == best["key"]:
                kept.append(e)
            else:
                mapping[e["key"]] = best["key"]
    kept_keys = {e["key"] for e in kept}
    ordered_kept = [e for e in entries if e["key"] in kept_keys]
    return ordered_kept, mapping


def parse_yaml_front_matter(text: str) -> Tuple[Optional[Dict[str, str]], Optional[str], Optional[str]]:
    if text is None:
        return None, None, None
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return None, None, text
    yaml_lines = []
    end_index = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == '---':
            end_index = idx
            break
        yaml_lines.append(lines[idx])
    if end_index is None:
        return None, None, text
    yaml_text = '\n'.join(yaml_lines)
    body_text = '\n'.join(lines[end_index + 1:]) + ('\n' if text.endswith('\n') else '')
    yaml_dict = {}
    for ln in yaml_lines:
        if ':' not in ln:
            continue
        k, v = ln.split(':', 1)
        key = k.strip()
        val = v.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        yaml_dict[key] = val
    return yaml_dict, yaml_text, body_text


def strip_yaml_front_matter(text: str) -> str:
    _, _, body = parse_yaml_front_matter(text)
    if body is None:
        return text if text is not None else ""
    return body


def extract_citation_keys_from_markdown(text: str) -> List[str]:
    body = strip_yaml_front_matter(text)
    if body is None:
        return []
    pattern = re.compile(r'@([A-Za-z0-9._:\-]+)')
    keys = pattern.findall(body)
    return keys


def load_csv_as_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open('r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def find_section_index(text: str, title: str) -> int:
    m = re.search(re.escape(title), text, flags=re.IGNORECASE)
    return m.start() if m else -1


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "cleaned_library_exists_and_parse": 0.0,
        "cleaned_library_kept_keys_match_expected": 0.0,
        "citation_map_exists_and_valid": 0.0,
        "citation_map_mappings_match_expected": 0.0,
        "report_dedup_exists": 0.0,
        "report_dedup_yaml_bibliography_path_correct": 0.0,
        "report_dedup_output_html_document_retained": 0.0,
        "report_dedup_citation_replacements_correct": 0.0,
        "citation_check_exists_and_header": 0.0,
        "citation_check_rows_match_expected": 0.0,
        "report_html_exists_and_contains_html": 0.0,
        "clean_bib_r_script_present": 0.0,
        "email_exists": 0.0,
        "email_counts_correct": 0.0,
        "email_deduplicated_entries_list_complete": 0.0,
        "email_missing_citations_list_complete": 0.0,
        "email_closing_sentence_mentions_render_and_paths": 0.0,
    }

    input_bib_path = workspace / "input" / "library.bib"
    input_report_path = workspace / "input" / "report.Rmd"
    output_clean_bib_path = workspace / "output" / "cleaned_library.bib"
    output_citation_map_path = workspace / "output" / "citation_map.csv"
    output_report_dedup_path = workspace / "output" / "report_dedup.Rmd"
    output_citation_check_path = workspace / "output" / "citation_check.csv"
    output_report_html_path = workspace / "output" / "report.html"
    script_clean_bib_r_path = workspace / "scripts" / "clean_bib.R"
    email_path = workspace / "output" / "email_to_advisor.txt"

    input_bib_text = read_text(input_bib_path)
    input_report_text = read_text(input_report_path)

    entries_expected = None
    kept_expected: List[Dict] = []
    mapping_expected: Dict[str, str] = {}
    if input_bib_text is not None:
        entries_expected = parse_bibtex_entries(input_bib_text)
    if entries_expected is not None:
        kept_expected, mapping_expected = deduplicate_bib_by_doi(entries_expected)

    cleaned_bib_text = read_text(output_clean_bib_path)
    cleaned_entries = None
    if cleaned_bib_text is not None:
        cleaned_entries = parse_bibtex_entries(cleaned_bib_text)
    if cleaned_entries is not None:
        scores["cleaned_library_exists_and_parse"] = 1.0
    else:
        scores["cleaned_library_exists_and_parse"] = 0.0

    if kept_expected and cleaned_entries is not None:
        expected_keys = {e["key"] for e in kept_expected}
        actual_keys = {e["key"] for e in cleaned_entries}
        scores["cleaned_library_kept_keys_match_expected"] = 1.0 if expected_keys == actual_keys else 0.0
    else:
        scores["cleaned_library_kept_keys_match_expected"] = 0.0

    citation_map_rows = load_csv_as_rows(output_citation_map_path)
    if citation_map_rows is not None:
        headers_ok = False
        try:
            with (output_citation_map_path.open('r', encoding='utf-8', newline='')) as f:
                header_line = f.readline().strip()
                headers_ok = header_line == "old_key,kept_key"
        except Exception:
            headers_ok = False
        scores["citation_map_exists_and_valid"] = 1.0 if headers_ok else 0.0
    else:
        scores["citation_map_exists_and_valid"] = 0.0

    if mapping_expected is not None and citation_map_rows is not None:
        expected_map = dict(mapping_expected)
        actual_map = {}
        valid_rows = True
        for r in citation_map_rows:
            if "old_key" not in r or "kept_key" not in r:
                valid_rows = False
                break
            actual_map[r["old_key"]] = r["kept_key"]
        if valid_rows and actual_map == expected_map:
            scores["citation_map_mappings_match_expected"] = 1.0
        else:
            scores["citation_map_mappings_match_expected"] = 0.0
    else:
        scores["citation_map_mappings_match_expected"] = 0.0

    report_dedup_text = read_text(output_report_dedup_path)
    if report_dedup_text is not None:
        scores["report_dedup_exists"] = 1.0
    else:
        scores["report_dedup_exists"] = 0.0

    if report_dedup_text is not None:
        yml, _, _ = parse_yaml_front_matter(report_dedup_text)
        if yml is not None:
            bib_val = yml.get("bibliography", "")
            if bib_val == "output/cleaned_library.bib":
                scores["report_dedup_yaml_bibliography_path_correct"] = 1.0
            else:
                scores["report_dedup_yaml_bibliography_path_correct"] = 0.0
            out_val = yml.get("output", "")
            if out_val == "html_document":
                scores["report_dedup_output_html_document_retained"] = 1.0
            else:
                scores["report_dedup_output_html_document_retained"] = 0.0
        else:
            scores["report_dedup_yaml_bibliography_path_correct"] = 0.0
            scores["report_dedup_output_html_document_retained"] = 0.0

    if input_report_text is not None and report_dedup_text is not None and mapping_expected is not None:
        _, _, input_body = parse_yaml_front_matter(input_report_text)
        if input_body is None:
            input_body = input_report_text
        _, _, dedup_body = parse_yaml_front_matter(report_dedup_text)
        if dedup_body is None:
            dedup_body = report_dedup_text
        replacements_ok = True
        for old_key, kept_key in mapping_expected.items():
            pattern_old = re.compile(r'@' + re.escape(old_key) + r'\b')
            pattern_kept = re.compile(r'@' + re.escape(kept_key) + r'\b')
            count_old_in_input = len(pattern_old.findall(input_body))
            count_old_in_dedup = len(pattern_old.findall(dedup_body))
            count_kept_in_dedup = len(pattern_kept.findall(dedup_body))
            if not (count_old_in_dedup == 0 and count_kept_in_dedup >= count_old_in_input):
                replacements_ok = False
                break
        input_cites = extract_citation_keys_from_markdown(input_report_text)
        dedup_cites = extract_citation_keys_from_markdown(report_dedup_text)
        if input_cites is None or dedup_cites is None:
            replacements_ok = False
        else:
            def counts(keys: List[str]) -> Dict[str, int]:
                d = {}
                for k in keys:
                    d[k] = d.get(k, 0) + 1
                return d
            cin = counts(input_cites)
            cded = counts(dedup_cites)
            for k, v in cin.items():
                if k in mapping_expected:
                    continue
                if cded.get(k, 0) != v:
                    replacements_ok = False
                    break
            for old_key, kept_key in mapping_expected.items():
                expected_count = cin.get(kept_key, 0) + cin.get(old_key, 0)
                if cded.get(kept_key, 0) != expected_count:
                    replacements_ok = False
                    break
        scores["report_dedup_citation_replacements_correct"] = 1.0 if replacements_ok else 0.0
    else:
        scores["report_dedup_citation_replacements_correct"] = 0.0

    citation_check_rows = load_csv_as_rows(output_citation_check_path)
    if citation_check_rows is not None:
        header_ok = False
        try:
            with (output_citation_check_path.open('r', encoding='utf-8', newline='')) as f:
                header_line = f.readline().strip()
                header_ok = header_line == "citation_key,status"
        except Exception:
            header_ok = False
        scores["citation_check_exists_and_header"] = 1.0 if header_ok else 0.0
    else:
        scores["citation_check_exists_and_header"] = 0.0

    if cleaned_entries is not None and report_dedup_text is not None and citation_check_rows is not None:
        cleaned_keys = {e["key"] for e in cleaned_entries}
        cited_keys = set(extract_citation_keys_from_markdown(report_dedup_text))
        expected_status = {k: ("ok" if k in cleaned_keys else "missing") for k in cited_keys}
        actual_status = {}
        valid_rows = True
        for r in citation_check_rows:
            if "citation_key" not in r or "status" not in r:
                valid_rows = False
                break
            actual_status[r["citation_key"]] = r["status"]
        if valid_rows and actual_status == expected_status:
            scores["citation_check_rows_match_expected"] = 1.0
        else:
            scores["citation_check_rows_match_expected"] = 0.0
    else:
        scores["citation_check_rows_match_expected"] = 0.0

    if (workspace / "output" / "report.html").exists() and (workspace / "output" / "report.html").is_file():
        try:
            html_text = (workspace / "output" / "report.html").read_text(encoding="utf-8", errors="ignore")
            if "<html" in html_text.lower():
                scores["report_html_exists_and_contains_html"] = 1.0
            else:
                scores["report_html_exists_and_contains_html"] = 0.0
        except Exception:
            scores["report_html_exists_and_contains_html"] = 0.0
    else:
        scores["report_html_exists_and_contains_html"] = 0.0

    if script_clean_bib_r_path.exists() and script_clean_bib_r_path.is_file():
        try:
            txt = script_clean_bib_r_path.read_text(encoding="utf-8")
            scores["clean_bib_r_script_present"] = 1.0 if txt.strip() != "" else 0.0
        except Exception:
            scores["clean_bib_r_script_present"] = 0.0
    else:
        scores["clean_bib_r_script_present"] = 0.0

    email_text = read_text(email_path)
    if email_text is not None:
        scores["email_exists"] = 1.0
    else:
        scores["email_exists"] = 0.0

    if email_text is not None and entries_expected is not None and cleaned_entries is not None:
        input_count = len(entries_expected)
        cleaned_count = len(cleaned_entries)
        removed_count = max(0, input_count - cleaned_count)

        def contains_number(t: str, num: int) -> bool:
            return re.search(r'\b' + re.escape(str(num)) + r'\b', t) is not None

        counts_ok = contains_number(email_text, input_count) and contains_number(email_text, cleaned_count) and contains_number(email_text, removed_count)
        scores["email_counts_correct"] = 1.0 if counts_ok else 0.0
    else:
        scores["email_counts_correct"] = 0.0

    if email_text is not None and mapping_expected is not None:
        dedup_section_ok = True
        title_idx = find_section_index(email_text, "Deduplicated entries")
        if title_idx == -1:
            dedup_section_ok = False
        else:
            for old_key, kept_key in mapping_expected.items():
                pattern = re.compile(re.escape(old_key) + r"\s*->\s*" + re.escape(kept_key))
                if not pattern.search(email_text[title_idx:]):
                    dedup_section_ok = False
                    break
        scores["email_deduplicated_entries_list_complete"] = 1.0 if dedup_section_ok else 0.0
    else:
        scores["email_deduplicated_entries_list_complete"] = 0.0

    if email_text is not None and citation_check_rows is not None:
        missing_keys = sorted([r["citation_key"] for r in citation_check_rows if r.get("status") == "missing"])
        miss_section_ok = True
        title_idx = find_section_index(email_text, "Missing citation keys in report")
        if title_idx == -1:
            miss_section_ok = False
        else:
            for mk in missing_keys:
                if re.search(r'\b' + re.escape(mk) + r'\b', email_text[title_idx:]) is None:
                    miss_section_ok = False
                    break
        scores["email_missing_citations_list_complete"] = 1.0 if miss_section_ok else 0.0
    else:
        scores["email_missing_citations_list_complete"] = 0.0

    if email_text is not None:
        closing_ok = (("output/report_dedup.Rmd" in email_text) and
                      (re.search(r'\bHTML\b', email_text, flags=re.IGNORECASE) is not None) and
                      (re.search(r'cleaned bibliography', email_text, flags=re.IGNORECASE) is not None) and
                      (re.search(r'render', email_text, flags=re.IGNORECASE) is not None))
        scores["email_closing_sentence_mentions_render_and_paths"] = 1.0 if closing_ok else 0.0
    else:
        scores["email_closing_sentence_mentions_render_and_paths"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()