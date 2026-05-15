import json
import csv
import sys
import re
from pathlib import Path
from urllib.parse import urlparse
from typing import List, Dict, Tuple, Optional, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    if not path.exists():
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = [row for row in reader]
            return headers, rows
    except Exception:
        return None, None


def _load_jsonl(path: Path) -> Optional[List[Any]]:
    if not path.exists():
        return None
    result = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                result.append(obj)
        return result
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_allowed_sources_yaml(path: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Very simple, structure-specific YAML parser for allowed_sources.yaml as provided.
    Returns (allowed_list, banned_list) where each element is dict with keys 'name' and 'domain_patterns' (list).
    """
    text = _read_text(path)
    if text is None:
        return [], []
    allowed: List[Dict[str, Any]] = []
    banned: List[Dict[str, Any]] = []
    current_section: Optional[str] = None  # "allowed" or "banned"
    current_item: Optional[Dict[str, Any]] = None
    in_domain_patterns = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "allowed:":
            current_section = "allowed"
            current_item = None
            in_domain_patterns = False
            continue
        if stripped == "banned:":
            current_section = "banned"
            current_item = None
            in_domain_patterns = False
            continue
        if current_section is None:
            continue

        # Start of a new item
        if stripped.startswith("- name:"):
            name_val = stripped[len("- name:"):].strip()
            name_val = _strip_quotes(name_val)
            current_item = {"name": name_val, "domain_patterns": []}
            if current_section == "allowed":
                allowed.append(current_item)
            else:
                banned.append(current_item)
            in_domain_patterns = False
            continue

        # Domain patterns key
        if "domain_patterns:" in stripped:
            in_domain_patterns = True
            continue

        # Domain pattern item
        if in_domain_patterns and stripped.startswith("-"):
            # pattern line: - "example.com"
            pat = stripped[1:].strip()
            pat = _strip_quotes(pat)
            if current_item is not None and pat:
                current_item["domain_patterns"].append(pat)
            continue

        # Any other line is ignored for our simple needs

    return allowed, banned


def _extract_domain(url: str) -> Optional[str]:
    if not url or not isinstance(url, str):
        return None
    u = url.strip()
    if not u:
        return None
    # Ensure scheme for parsing
    if "://" not in u:
        u = "http://" + u
    try:
        parsed = urlparse(u)
        netloc = parsed.netloc.lower()
        # Strip port if present
        if ":" in netloc:
            netloc = netloc.split(":", 1)[0]
        # Remove leading www. for domain matching normalization
        if netloc.startswith("www."):
            netloc = netloc[4:]
        if not netloc:
            return None
        return netloc
    except Exception:
        return None


def _domain_matches_patterns(domain: str, patterns: List[str]) -> bool:
    if not domain:
        return False
    for pat in patterns:
        pat_norm = pat.lower().strip()
        if pat_norm.startswith("*."):
            # wildcard for subdomains
            base = pat_norm[2:]
            if domain == base or domain.endswith("." + base):
                return True
        else:
            if domain == pat_norm or domain.endswith("." + pat_norm):
                return True
    return False


def _normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _normalize_name(s: str) -> str:
    return _normalize_whitespace(s).lower()


def _get_input_titles(workspace: Path) -> Tuple[List[str], bool]:
    input_path = workspace / "input" / "titles_arabic.csv"
    headers, rows = _read_csv_dicts(input_path)
    if headers is None or rows is None:
        return [], False
    if "arabic_title" not in headers:
        return [], False
    titles = []
    for row in rows:
        titles.append(row.get("arabic_title", "").strip())
    return titles, True


def _load_glossary(workspace: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    path = workspace / "out" / "glossary.csv"
    return _read_csv_dicts(path)


def _load_search_log(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    path = workspace / "out" / "search_log.jsonl"
    data = _load_jsonl(path)
    if data is None:
        return None
    # Ensure all entries are dicts
    for item in data:
        if not isinstance(item, dict):
            return None
    return data  # type: ignore[return-value]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "glossary_file_present_and_readable": 0.0,
        "glossary_has_required_columns": 0.0,
        "glossary_uniqueness_of_arabic_title": 0.0,
        "glossary_covers_all_input_titles_in_order": 0.0,
        "glossary_translation_type_fields_valid": 0.0,
        "glossary_authoritative_sources_on_allowed_domains": 0.0,
        "search_log_file_present_and_readable": 0.0,
        "search_log_has_one_entry_per_title": 0.0,
        "search_log_queries_at_least_two_distinct": 0.0,
        "search_log_alternatives_at_least_two": 0.0,
        "cross_consistency_chosen_source_matches_glossary": 0.0,
    }

    # Load configuration for allowed/banned sources
    allowed_sources_path = workspace / "config" / "allowed_sources.yaml"
    allowed_list, banned_list = _parse_allowed_sources_yaml(allowed_sources_path)
    allowed_patterns: List[str] = []
    for entry in allowed_list:
        allowed_patterns.extend(entry.get("domain_patterns", []))
    banned_patterns: List[str] = []
    for entry in banned_list:
        banned_patterns.extend(entry.get("domain_patterns", []))

    # Load input titles
    input_titles, input_ok = _get_input_titles(workspace)

    # Load glossary
    glossary_headers, glossary_rows = _load_glossary(workspace)
    glossary_present = glossary_headers is not None and glossary_rows is not None
    if glossary_present:
        scores["glossary_file_present_and_readable"] = 1.0
    else:
        # If glossary is missing, many dependent checks will remain 0.0
        glossary_headers = []
        glossary_rows = []

    # Validate glossary required columns
    required_columns = ["arabic_title", "english_title", "translation_type", "source_name", "source_url", "notes"]
    if glossary_present:
        has_required_cols = all(col in (glossary_headers or []) for col in required_columns)
        if has_required_cols:
            scores["glossary_has_required_columns"] = 1.0

    # Glossary uniqueness
    if glossary_present and glossary_rows is not None:
        seen = set()
        unique = True
        for row in glossary_rows:
            title = (row.get("arabic_title") or "").strip()
            if title in seen:
                unique = False
                break
            seen.add(title)
        if unique and len(glossary_rows) > 0:
            scores["glossary_uniqueness_of_arabic_title"] = 1.0

    # Coverage and order
    if glossary_present and input_ok:
        glossary_titles = [ (row.get("arabic_title") or "").strip() for row in glossary_rows ]
        coverage_ok = glossary_titles == input_titles
        if coverage_ok and len(glossary_titles) == len(input_titles) and len(glossary_titles) > 0:
            scores["glossary_covers_all_input_titles_in_order"] = 1.0

    # Translation type rules and source domain checks
    trans_type_fields_ok = True
    domain_ok = True
    if glossary_present:
        for row in glossary_rows:
            arabic_title = (row.get("arabic_title") or "").strip()
            english_title = (row.get("english_title") or "").strip()
            translation_type = (row.get("translation_type") or "").strip()
            source_name = (row.get("source_name") or "").strip()
            source_url = (row.get("source_url") or "").strip()
            notes = (row.get("notes") or "").strip()
            # english_title required
            if not english_title:
                trans_type_fields_ok = False
                break
            if translation_type not in ("authoritative", "agent_translation"):
                trans_type_fields_ok = False
                break
            if translation_type == "authoritative":
                # source_name and source_url required non-empty
                if not source_name or not source_url:
                    trans_type_fields_ok = False
                    break
                # domain must be allowed, and not banned
                domain = _extract_domain(source_url)
                if domain is None:
                    domain_ok = False
                    break
                if not _domain_matches_patterns(domain, allowed_patterns):
                    domain_ok = False
                    break
                if banned_patterns and _domain_matches_patterns(domain, banned_patterns):
                    domain_ok = False
                    break
            else:  # agent_translation
                # source fields empty and notes mention phrase
                if source_name or source_url:
                    trans_type_fields_ok = False
                    break
                if "no allowed source found" not in notes.lower():
                    trans_type_fields_ok = False
                    break
        if trans_type_fields_ok:
            scores["glossary_translation_type_fields_valid"] = 1.0
        if domain_ok and trans_type_fields_ok:
            scores["glossary_authoritative_sources_on_allowed_domains"] = 1.0

    # Load search log
    search_log = _load_search_log(workspace)
    search_log_present = search_log is not None
    if search_log_present:
        scores["search_log_file_present_and_readable"] = 1.0

    # Search log coverage
    if search_log_present and input_ok:
        # Must have one entry per input title
        title_counts: Dict[str, int] = {}
        structure_ok = True
        for entry in search_log:
            if not isinstance(entry, dict):
                structure_ok = False
                break
            at = entry.get("arabic_title")
            if not isinstance(at, str):
                structure_ok = False
                break
            t = at.strip()
            title_counts[t] = title_counts.get(t, 0) + 1
        if structure_ok:
            all_present_once = all(title_counts.get(t, 0) == 1 for t in input_titles) and len(title_counts) == len(input_titles)
        else:
            all_present_once = False
        if all_present_once:
            scores["search_log_has_one_entry_per_title"] = 1.0

    # Search log queries at least two distinct and alternatives count
    if search_log_present and input_ok:
        queries_ok = True
        alternatives_ok = True
        for entry in search_log:
            # Validate structure per schema
            queries = entry.get("queries")
            if not isinstance(queries, list):
                queries_ok = False
                break
            norm_queries = set(_normalize_whitespace(str(q)).lower() for q in queries if isinstance(q, str))
            if len(norm_queries) < 2:
                queries_ok = False
                break
            # alternatives must be array of objects with required fields, at least 2 per task requirement
            alternatives = entry.get("alternatives")
            if not isinstance(alternatives, list) or len(alternatives) < 2:
                alternatives_ok = False
                break
            for alt in alternatives:
                if not isinstance(alt, dict):
                    alternatives_ok = False
                    break
                if not isinstance(alt.get("title"), str):
                    alternatives_ok = False
                    break
                if not isinstance(alt.get("source_name"), str):
                    alternatives_ok = False
                    break
                if not isinstance(alt.get("url"), str):
                    alternatives_ok = False
                    break
            if not alternatives_ok:
                break
        if queries_ok:
            scores["search_log_queries_at_least_two_distinct"] = 1.0
        if alternatives_ok:
            scores["search_log_alternatives_at_least_two"] = 1.0

    # Cross-consistency: chosen_source in search log matches glossary authoritative entries
    cross_ok = True
    if glossary_present and search_log_present:
        # Build map from arabic_title to glossary row
        gmap: Dict[str, Dict[str, str]] = {}
        for row in glossary_rows:
            gmap[(row.get("arabic_title") or "").strip()] = row
        # Build map from arabic_title to log entry
        lmap: Dict[str, Dict[str, Any]] = {}
        for entry in search_log:
            title = (entry.get("arabic_title") or "").strip() if isinstance(entry.get("arabic_title"), str) else ""
            if title:
                lmap[title] = entry

        for arabic_title, grow in gmap.items():
            tt = (grow.get("translation_type") or "").strip()
            if tt == "authoritative":
                # must have chosen_source with matching source_name and URL domain
                entry = lmap.get(arabic_title)
                if not entry:
                    cross_ok = False
                    break
                chosen = entry.get("chosen_source", None)
                if not isinstance(chosen, dict):
                    cross_ok = False
                    break
                g_source_name = (grow.get("source_name") or "").strip()
                g_source_url = (grow.get("source_url") or "").strip()
                c_source_name = (chosen.get("source_name") or "").strip() if chosen else ""
                c_url = (chosen.get("url") or "").strip() if chosen else ""
                # compare names case-insensitively
                if _normalize_name(g_source_name) != _normalize_name(c_source_name):
                    cross_ok = False
                    break
                # compare domain equality
                g_domain = _extract_domain(g_source_url or "")
                c_domain = _extract_domain(c_url or "")
                if not g_domain or not c_domain or g_domain != c_domain:
                    cross_ok = False
                    break
            elif tt == "agent_translation":
                # chosen_source should be absent or null/empty
                entry = lmap.get(arabic_title)
                if not entry:
                    cross_ok = False
                    break
                chosen = entry.get("chosen_source", None)
                # Allow missing or None or empty dict; but if there is a non-empty url or source_name, fail
                if isinstance(chosen, dict):
                    has_url = bool((chosen.get("url") or "").strip())
                    has_src = bool((chosen.get("source_name") or "").strip())
                    if has_url or has_src:
                        cross_ok = False
                        break
                elif chosen is not None:
                    # If present and not dict/None, invalid
                    cross_ok = False
                    break
        if cross_ok:
            scores["cross_consistency_chosen_source_matches_glossary"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()