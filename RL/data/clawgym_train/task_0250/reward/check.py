import json
import sys
import re
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_jsonl_safe(path: Path) -> Optional[List[Any]]:
    try:
        lines = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    lines.append(obj)
                except Exception:
                    return None
        return lines
    except Exception:
        return None


def _parse_simple_yaml_lists(path: Path) -> Optional[Dict[str, List[str]]]:
    """
    Minimal parser for a simple YAML file with keys mapped to lists of strings.

    Example supported content:
    countries:
      - Peru
      - India

    Ignores comments and blank lines.
    """
    text = _read_text_safe(path)
    if text is None:
        return None
    result: Dict[str, List[str]] = {}
    current_key: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # key:
        if re.match(r"^[A-Za-z0-9_]+\s*:\s*$", line):
            current_key = line.split(":")[0].strip()
            result[current_key] = []
            continue
        # list item
        if current_key is not None and line.startswith("- "):
            item = line[2:].strip()
            # Remove optional surrounding quotes
            if len(item) >= 2 and ((item[0] == item[-1] == '"') or (item[0] == item[-1] == "'")):
                item = item[1:-1]
            result[current_key].append(item)
    return result


def _find_note_files(workspace: Path) -> List[Path]:
    return sorted((workspace / "input" / "notes").glob("*.md"))


def _strip_port(netloc: str) -> str:
    if ":" in netloc:
        return netloc.split(":", 1)[0]
    return netloc


def _domain_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        if not parsed.netloc:
            return None
        return _strip_port(parsed.netloc.lower())
    except Exception:
        return None


def _allowed_domain(url: str, patterns: List[str]) -> bool:
    domain = _domain_from_url(url)
    if not domain:
        return False
    domain = domain.lower()
    for pat in patterns:
        p = pat.strip().lower()
        if not p:
            continue
        # Treat pattern as suffix match
        if domain.endswith(p):
            return True
        # If pattern starts with '.', also allow exact domain without dot
        if p.startswith(".") and domain == p[1:]:
            return True
    return False


def _iso8601_valid(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        # Accept Zulu 'Z'
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def _count_phrase_occurrences(text: str, phrase: str) -> int:
    # Case-insensitive exact phrase match, non-overlapping
    if not phrase:
        return 0
    pattern = re.compile(re.escape(phrase), flags=re.IGNORECASE)
    return len(list(pattern.finditer(text)))


def _compute_note_expected(note_path: Path, countries: List[str], sensitive_terms: List[str]) -> Dict[str, Any]:
    content = _read_text_safe(note_path) or ""
    countries_mentioned = []
    for c in countries:
        if re.search(re.escape(c), content, flags=re.IGNORECASE):
            countries_mentioned.append(c)
    term_counts: Dict[str, int] = {}
    sensitive_found: List[str] = []
    for t in sensitive_terms:
        cnt = _count_phrase_occurrences(content, t)
        term_counts[t] = cnt
        if cnt > 0:
            sensitive_found.append(t)
    return {
        "countries_mentioned": sorted(set(countries_mentioned)),
        "sensitive_terms_found": sorted(set(sensitive_found)),
        "term_counts": term_counts,
        "excerpt_char_len": len(content),
    }


def _load_flags_json(path: Path) -> Optional[List[Dict[str, Any]]]:
    data = _load_json_safe(path)
    if not isinstance(data, list):
        return None
    # Ensure objects
    for obj in data:
        if not isinstance(obj, dict):
            return None
    return data


def _collect_country_indices_from_files(files: List[Path], countries: List[str]) -> Dict[str, List[int]]:
    """
    From file names like out/web/raw/{country}_{index}.html or .json, collect indices per country.
    Returns a mapping country -> sorted unique indices found.
    """
    per_country: Dict[str, List[int]] = {c: [] for c in countries}
    for f in files:
        name = f.name
        # Match "{country}_{index}.ext" with exact country token from config
        for c in countries:
            prefix = f"{c}_"
            if name.startswith(prefix):
                # Extract the number between underscore and last dot
                m = re.match(rf"^{re.escape(c)}_(\d+)\.[a-zA-Z0-9]+$", name)
                if m:
                    try:
                        idx = int(m.group(1))
                        per_country[c].append(idx)
                    except Exception:
                        pass
    for c in per_country:
        # Unique and sorted
        per_country[c] = sorted(set(per_country[c]))
    return per_country


def _extract_country_from_filename(file: Path, countries: List[str]) -> Optional[Tuple[str, int]]:
    name = file.name
    for c in countries:
        prefix = f"{c}_"
        if name.startswith(prefix):
            m = re.match(rf"^{re.escape(c)}_(\d+)\.[a-zA-Z0-9]+$", name)
            if m:
                try:
                    idx = int(m.group(1))
                    return c, idx
                except Exception:
                    return None
    return None


def _load_extracted_json_files(dir_path: Path) -> List[Dict[str, Any]]:
    results = []
    if not dir_path.exists():
        return results
    for p in sorted(dir_path.glob("*.json")):
        obj = _load_json_safe(p)
        if isinstance(obj, dict):
            results.append({"path": p, "data": obj})
    return results


def _safe_int(value: Any) -> Optional[int]:
    try:
        if isinstance(value, bool):
            return None
        return int(value)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "flags_json_exists": 0.0,
        "flags_json_structure_valid": 0.0,
        "flags_json_countries_match": 0.0,
        "flags_json_sensitive_terms_match": 0.0,
        "flags_json_term_counts_correct": 0.0,
        "flags_json_excerpt_len_correct": 0.0,
        "search_log_exists": 0.0,
        "search_log_per_country_queries_valid": 0.0,
        "search_log_selected_urls_allowed_domains": 0.0,
        "search_log_selected_urls_count_per_country": 0.0,
        "search_log_candidate_contains_selected": 0.0,
        "search_log_run_at_iso_valid": 0.0,
        "web_raw_files_per_country": 0.0,
        "web_extracted_files_per_country": 0.0,
        "extracted_json_fields_valid": 0.0,
        "extracted_json_domain_consistency": 0.0,
        "extracted_json_sensitive_terms_subset": 0.0,
        "report_exists": 0.0,
        "report_per_note_sections_present": 0.0,
        "report_final_counts_correct": 0.0,
        "workflow_file_exists": 0.0,
        "workflow_job_name_and_triggers": 0.0,
        "workflow_python_setup": 0.0,
        "workflow_validation_step_paths": 0.0,
    }

    # Load config
    config_path = workspace / "input" / "config" / "policy_sources.yaml"
    config = _parse_simple_yaml_lists(config_path)
    countries: List[str] = []
    sensitive_terms: List[str] = []
    allowed_patterns: List[str] = []
    search_templates: List[str] = []
    if config:
        countries = config.get("countries", [])
        sensitive_terms = config.get("sensitive_terms", [])
        allowed_patterns = config.get("allowed_domain_patterns", [])
        search_templates = config.get("search_queries", [])
    # Notes list
    note_files = _find_note_files(workspace)

    # 1) flags.json checks
    flags_path = workspace / "out" / "notes" / "flags.json"
    flags_data = _load_flags_json(flags_path)
    if flags_path.exists():
        scores["flags_json_exists"] = 1.0
    else:
        scores["flags_json_exists"] = 0.0

    if flags_data is not None and countries and sensitive_terms and note_files:
        # Structure validation: length equals notes count; each has fields
        # Map entries by note_path; accept both exact relative path and absolute path; we'll match by suffix
        expected_note_suffixes = {str(p.as_posix()) for p in note_files}
        # Normalize by making all paths posix-like
        entries_by_suffix: Dict[str, Dict[str, Any]] = {}
        valid_structure = True
        for obj in flags_data:
            required_fields = {
                "note_path": str,
                "countries_mentioned": list,
                "sensitive_terms_found": list,
                "term_counts": dict,
                "excerpt_char_len": int,
            }
            for k, t in required_fields.items():
                if k not in obj:
                    valid_structure = False
                    break
            if not valid_structure:
                break
            # type checks
            if not isinstance(obj["note_path"], str):
                valid_structure = False
                break
            if not isinstance(obj["countries_mentioned"], list) or not isinstance(obj["sensitive_terms_found"], list):
                valid_structure = False
                break
            if not isinstance(obj["term_counts"], dict):
                valid_structure = False
                break
            if not isinstance(obj["excerpt_char_len"], int):
                valid_structure = False
                break
            # find suffix match
            note_path_str = obj["note_path"].replace("\\", "/")
            matched_suffix = None
            for suf in expected_note_suffixes:
                if note_path_str.endswith(suf):
                    matched_suffix = suf
                    break
            if matched_suffix is None:
                # Try match by filename only if suffix failed
                fname = Path(note_path_str).name
                for p in note_files:
                    if p.name == fname:
                        matched_suffix = str(p.as_posix())
                        break
            if matched_suffix:
                entries_by_suffix[matched_suffix] = obj
        # Ensure we have entries for all notes
        if len(entries_by_suffix) == len(note_files):
            scores["flags_json_structure_valid"] = 1.0
        else:
            scores["flags_json_structure_valid"] = 0.0

        # Compare content by recomputation
        # For each note, compute expected fields
        countries_ok = []
        terms_ok = []
        term_counts_ok = []
        excerpt_len_ok = []
        for note in note_files:
            suffix = str(note.as_posix())
            obj = entries_by_suffix.get(suffix)
            exp = _compute_note_expected(note, countries, sensitive_terms)
            if obj is None:
                countries_ok.append(0.0)
                terms_ok.append(0.0)
                term_counts_ok.append(0.0)
                excerpt_len_ok.append(0.0)
                continue
            # countries_mentioned: compare as sets
            actual_countries = obj.get("countries_mentioned", [])
            if isinstance(actual_countries, list):
                actual_country_set = set([str(x) for x in actual_countries])
            else:
                actual_country_set = set()
            countries_ok.append(1.0 if actual_country_set == set(exp["countries_mentioned"]) else 0.0)
            # sensitive_terms_found: compare set equals terms with counts > 0
            actual_terms = obj.get("sensitive_terms_found", [])
            if isinstance(actual_terms, list):
                actual_term_set = set([str(x) for x in actual_terms])
            else:
                actual_term_set = set()
            terms_ok.append(1.0 if actual_term_set == set(exp["sensitive_terms_found"]) else 0.0)
            # term_counts mapping equality
            actual_term_counts = obj.get("term_counts", {})
            if isinstance(actual_term_counts, dict):
                # normalize keys to strings and values to ints
                norm_actual = {}
                valid = True
                for k, v in actual_term_counts.items():
                    if not isinstance(k, str):
                        valid = False
                        break
                    iv = _safe_int(v)
                    if iv is None or iv < 0:
                        valid = False
                        break
                    norm_actual[k] = iv
                if valid:
                    term_counts_ok.append(1.0 if norm_actual == exp["term_counts"] else 0.0)
                else:
                    term_counts_ok.append(0.0)
            else:
                term_counts_ok.append(0.0)
            # excerpt_char_len equality
            excerpt_len_ok.append(1.0 if obj.get("excerpt_char_len") == exp["excerpt_char_len"] else 0.0)
        # Aggregate as average across notes
        if countries_ok:
            scores["flags_json_countries_match"] = sum(countries_ok) / len(countries_ok)
        if terms_ok:
            scores["flags_json_sensitive_terms_match"] = sum(terms_ok) / len(terms_ok)
        if term_counts_ok:
            scores["flags_json_term_counts_correct"] = sum(term_counts_ok) / len(term_counts_ok)
        if excerpt_len_ok:
            scores["flags_json_excerpt_len_correct"] = sum(excerpt_len_ok) / len(excerpt_len_ok)
    else:
        # If flags_data is None due to parse or missing, keep zeros
        pass

    # 2) search_log.jsonl checks
    search_log_path = workspace / "out" / "web" / "search_log.jsonl"
    if search_log_path.exists():
        scores["search_log_exists"] = 1.0
    lines = _load_jsonl_safe(search_log_path) if search_log_path.exists() else None
    if lines is not None and countries and search_templates:
        # Validate fields and per-country coverage
        # Collect entries per country
        per_country_entries: Dict[str, List[Dict[str, Any]]] = {c: [] for c in countries}
        run_at_ok_flags: List[float] = []
        for entry in lines:
            if not isinstance(entry, dict):
                continue
            c = entry.get("country")
            qs = entry.get("queries")
            cand = entry.get("candidate_urls")
            sel = entry.get("selected_urls")
            run_at = entry.get("run_at_iso")
            # Validate types
            if not isinstance(c, str) or not isinstance(qs, list) or not isinstance(cand, list) or not isinstance(sel, list):
                continue
            if c in per_country_entries:
                per_country_entries[c].append(entry)
            # Run_at validation
            run_at_ok_flags.append(1.0 if _iso8601_valid(run_at) else 0.0)
        # run_at_iso_valid
        if run_at_ok_flags:
            scores["search_log_run_at_iso_valid"] = sum(run_at_ok_flags) / len(run_at_ok_flags)
        # Queries must include combinations of country + each template (strings containing both)
        per_country_queries_ok = []
        per_country_selected_domains_ok = []
        per_country_selected_count_ok = []
        per_country_candidates_include_selected_ok = []
        for c in countries:
            entries = per_country_entries.get(c, [])
            if not entries:
                per_country_queries_ok.append(0.0)
                per_country_selected_domains_ok.append(0.0)
                per_country_selected_count_ok.append(0.0)
                per_country_candidates_include_selected_ok.append(0.0)
                continue
            # Combine across entries
            queries_seen: List[str] = []
            selected_urls: List[str] = []
            candidate_urls: List[str] = []
            for e in entries:
                qlist = e.get("queries", [])
                slist = e.get("selected_urls", [])
                clist = e.get("candidate_urls", [])
                # ensure list types
                qlist = [q for q in qlist if isinstance(q, str)]
                slist = [u for u in slist if isinstance(u, str)]
                clist = [u for u in clist if isinstance(u, str)]
                queries_seen.extend(qlist)
                selected_urls.extend(slist)
                candidate_urls.extend(clist)
            # Queries check: For each template, at least one query that contains both the country and the full template substring (case-insensitive)
            q_ok_flags = []
            for templ in search_templates:
                templ_l = templ.lower()
                found = False
                for q in queries_seen:
                    ql = q.lower()
                    if c.lower() in ql and templ_l in ql:
                        found = True
                        break
                q_ok_flags.append(1.0 if found else 0.0)
            per_country_queries_ok.append(sum(q_ok_flags) / len(q_ok_flags) if q_ok_flags else 0.0)
            # Selected URLs allowed domains and count up to 2
            sel_unique = []
            seen = set()
            for u in selected_urls:
                if u not in seen:
                    seen.add(u)
                    sel_unique.append(u)
            domains_ok = all(_allowed_domain(u, allowed_patterns) for u in sel_unique) if sel_unique else False
            per_country_selected_domains_ok.append(1.0 if domains_ok else 0.0)
            count_ok = 1.0 if 1 <= len(sel_unique) <= 2 else 0.0
            per_country_selected_count_ok.append(count_ok)
            # Candidate URLs should include selected URLs
            cand_set = set(candidate_urls)
            subset_ok = 1.0 if sel_unique and all(u in cand_set for u in sel_unique) else 0.0
            per_country_candidates_include_selected_ok.append(subset_ok)
        if per_country_queries_ok:
            scores["search_log_per_country_queries_valid"] = sum(per_country_queries_ok) / len(per_country_queries_ok)
        if per_country_selected_domains_ok:
            scores["search_log_selected_urls_allowed_domains"] = sum(per_country_selected_domains_ok) / len(per_country_selected_domains_ok)
        if per_country_selected_count_ok:
            scores["search_log_selected_urls_count_per_country"] = sum(per_country_selected_count_ok) / len(per_country_selected_count_ok)
        if per_country_candidates_include_selected_ok:
            scores["search_log_candidate_contains_selected"] = sum(per_country_candidates_include_selected_ok) / len(per_country_candidates_include_selected_ok)
    else:
        # Keep zeros if missing or malformed
        pass

    # 3) Downloaded raw and extracted checks
    raw_dir = workspace / "out" / "web" / "raw"
    extracted_dir = workspace / "out" / "web" / "extracted"
    raw_files = sorted(raw_dir.glob("*.html")) if raw_dir.exists() else []
    extracted_files = sorted(extracted_dir.glob("*.json")) if extracted_dir.exists() else []

    if countries:
        # For each country, ensure at least one raw and one extracted
        raw_indices = _collect_country_indices_from_files(raw_files, countries)
        extracted_indices = _collect_country_indices_from_files(extracted_files, countries)
        raw_per_country_ok = []
        extracted_per_country_ok = []
        for c in countries:
            raw_ok = 1.0 if raw_indices.get(c) and len(raw_indices.get(c)) >= 1 else 0.0
            extracted_ok = 1.0 if extracted_indices.get(c) and len(extracted_indices.get(c)) >= 1 else 0.0
            raw_per_country_ok.append(raw_ok)
            extracted_per_country_ok.append(extracted_ok)
        if raw_per_country_ok:
            scores["web_raw_files_per_country"] = sum(raw_per_country_ok) / len(raw_per_country_ok)
        if extracted_per_country_ok:
            scores["web_extracted_files_per_country"] = sum(extracted_per_country_ok) / len(extracted_per_country_ok)

    # Validate extracted JSON files content
    extracted_jsons = _load_extracted_json_files(extracted_dir)
    if extracted_jsons and sensitive_terms:
        fields_ok_flags = []
        domain_consistency_ok_flags = []
        sensitive_subset_ok_flags = []
        for item in extracted_jsons:
            data = item["data"]
            # Required fields types
            required = {
                "country": str,
                "url": str,
                "source_domain": str,
                "http_status": int,
                "retrieved_at_iso": str,
                "page_title": str,
                "headings": list,
                "word_count": int,
                "matched_sensitive_terms": list,
            }
            valid_fields = True
            for k, t in required.items():
                if k not in data:
                    valid_fields = False
                    break
                if t is int:
                    if _safe_int(data[k]) is None:
                        valid_fields = False
                        break
                else:
                    if not isinstance(data[k], t):
                        valid_fields = False
                        break
            # Validate ISO for retrieved_at_iso, len of headings list elements
            if valid_fields:
                if not _iso8601_valid(data.get("retrieved_at_iso", "")):
                    valid_fields = False
            if valid_fields:
                if not all(isinstance(h, str) for h in data.get("headings", [])):
                    valid_fields = False
            fields_ok_flags.append(1.0 if valid_fields else 0.0)
            # source_domain matches parsed domain of url
            url = data.get("url")
            src_dom = data.get("source_domain")
            parsed_dom = _domain_from_url(url) or ""
            domain_consistency_ok_flags.append(1.0 if isinstance(src_dom, str) and src_dom.lower() == parsed_dom else 0.0)
            # matched_sensitive_terms should be subset of configured sensitive terms (case-insensitive)
            terms = data.get("matched_sensitive_terms", [])
            subset_ok = True
            st_lower = set([t.lower() for t in sensitive_terms])
            if isinstance(terms, list):
                for t in terms:
                    if not isinstance(t, str):
                        subset_ok = False
                        break
                    if t.lower() not in st_lower:
                        subset_ok = False
                        break
            else:
                subset_ok = False
            sensitive_subset_ok_flags.append(1.0 if subset_ok else 0.0)
        if fields_ok_flags:
            scores["extracted_json_fields_valid"] = sum(fields_ok_flags) / len(fields_ok_flags)
        if domain_consistency_ok_flags:
            scores["extracted_json_domain_consistency"] = sum(domain_consistency_ok_flags) / len(domain_consistency_ok_flags)
        if sensitive_subset_ok_flags:
            scores["extracted_json_sensitive_terms_subset"] = sum(sensitive_subset_ok_flags) / len(sensitive_subset_ok_flags)

    # 4) Report checks
    report_path = workspace / "out" / "report.md"
    report_text = _read_text_safe(report_path) if report_path.exists() else None
    if report_path.exists():
        scores["report_exists"] = 1.0

    if report_text is not None and countries:
        # Per-note sections present: ensure each note filename appears in report
        note_ok_flags = []
        for nf in note_files:
            note_ok_flags.append(1.0 if nf.name in report_text else 0.0)
        if note_ok_flags:
            scores["report_per_note_sections_present"] = sum(note_ok_flags) / len(note_ok_flags)

        # Final counts by country: pages_downloaded, total_word_count, notes referencing
        # Compute expected
        # pages_downloaded: number of extracted JSON files for that country (by filename prefix)
        extracted_counts = _collect_country_indices_from_files(extracted_files, countries)
        # total_word_count: sum of word_count fields in extracted JSON by country
        word_counts_by_country: Dict[str, int] = {c: 0 for c in countries}
        for item in extracted_jsons:
            data = item["data"]
            c = data.get("country")
            wc = _safe_int(data.get("word_count"))
            if isinstance(c, str) and c in word_counts_by_country and wc is not None:
                word_counts_by_country[c] += wc
        # notes referenced per country: based on expected from notes
        notes_ref_counts: Dict[str, int] = {c: 0 for c in countries}
        for nf in note_files:
            exp = _compute_note_expected(nf, countries, sensitive_terms)
            for c in exp["countries_mentioned"]:
                notes_ref_counts[c] = notes_ref_counts.get(c, 0) + 1

        # Look for lines containing country and all three numbers
        lines = report_text.splitlines()
        per_country_ok = []
        for c in countries:
            pages = len(extracted_counts.get(c, []))
            total_wc = word_counts_by_country.get(c, 0)
            notes_ref = notes_ref_counts.get(c, 0)
            found_line = False
            for line in lines:
                if c in line and str(pages) in line and str(total_wc) in line and str(notes_ref) in line:
                    found_line = True
                    break
            per_country_ok.append(1.0 if found_line else 0.0)
        if per_country_ok:
            scores["report_final_counts_correct"] = sum(per_country_ok) / len(per_country_ok)

    # 5) CI workflow file checks
    workflow_path = workspace / ".github" / "workflows" / "policy-check.yml"
    if workflow_path.exists():
        scores["workflow_file_exists"] = 1.0
        wtext = _read_text_safe(workflow_path) or ""
        # Job named "policy-check" under jobs:
        job_ok = False
        # Find "jobs:" and then a line with "policy-check:"
        if "jobs:" in wtext:
            # Simple regex to detect job id
            if re.search(r"(?m)^\s*policy-check\s*:\s*$", wtext):
                job_ok = True
        # Triggers push and pull_request
        triggers_ok = ("on:" in wtext) and ("push" in wtext) and ("pull_request" in wtext)
        scores["workflow_job_name_and_triggers"] = 1.0 if (job_ok and triggers_ok) else 0.0
        # Python 3.10+ setup
        py_ok = bool(re.search(r"python-version\s*:\s*['\"]?(3\.(1[0-9]|[4-9]))", wtext)) or ("3.10" in wtext) or ("3.11" in wtext) or ("3.12" in wtext) or ("3.13" in wtext)
        scores["workflow_python_setup"] = 1.0 if py_ok else 0.0
        # Validation step references required paths
        val_paths = [
            "out/notes/flags.json",
            "out/web/search_log.jsonl",
            "out/report.md",
            "out/web/raw/",
            "out/web/extracted/",
        ]
        val_ok_flags = []
        for pstr in val_paths:
            val_ok_flags.append(1.0 if pstr in wtext else 0.0)
        # Require all to be mentioned
        scores["workflow_validation_step_paths"] = 1.0 if all(v == 1.0 for v in val_ok_flags) else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()