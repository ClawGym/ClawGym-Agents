import json
import hashlib
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _compute_sha256_hex(path: Path) -> Optional[str]:
    data = _read_bytes(path)
    if data is None:
        return None
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    # Minimal YAML parser for simple key: value pairs (quoted strings or integers)
    text = _read_text(path)
    if text is None:
        return None
    cfg: Dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^([A-Za-z0-9_]+)\s*:\s*(.*)$', line)
        if not m:
            return None
        key = m.group(1)
        val = m.group(2)
        # Remove inline comments that follow with space-hash
        if " #" in val:
            val = val.split(" #", 1)[0].rstrip()
        if val.startswith(("\"", "'")) and val.endswith(("\"", "'")) and len(val) >= 2:
            val = val[1:-1]
        elif re.fullmatch(r'[-+]?\d+', val):
            try:
                val = int(val)
            except Exception:
                pass
        cfg[key] = val
    return cfg


def _parse_unicode_data(path: Path) -> Optional[Tuple[Dict[int, str], List[Tuple[int, int, str]], bool, bool]]:
    """
    Returns:
      - mapping: dict of codepoint int -> general category str
      - ranges: list of (start, end, category)
      - contains_arabic_literal: bool if the file contains 'ARABIC' text
      - contains_latin_literal: bool if the file contains 'LATIN' text
    """
    text = _read_text(path)
    if text is None:
        return None
    mapping: Dict[int, str] = {}
    ranges: List[Tuple[int, int, str]] = []
    contains_arabic_literal = "ARABIC" in text
    contains_latin_literal = "LATIN" in text
    pending_start: Optional[Tuple[int, str, str]] = None  # (start_cp, category, name_tag)
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split(";")
        if len(parts) < 3:
            continue
        cp_hex = parts[0].strip()
        name = parts[1].strip()
        gc = parts[2].strip()
        try:
            cp = int(cp_hex, 16)
        except Exception:
            continue
        if name.startswith("<") and name.endswith("First>"):
            pending_start = (cp, gc, name)
            continue
        if name.startswith("<") and name.endswith("Last>") and pending_start is not None:
            start_cp, start_gc, start_name = pending_start
            # We assume matching First/Last pairs correspond correctly
            ranges.append((start_cp, cp, start_gc))
            pending_start = None
            continue
        # Non-range single code point
        mapping[cp] = gc
    return mapping, ranges, contains_arabic_literal, contains_latin_literal


def _lookup_general_category(cp: int, mapping: Dict[int, str], ranges: List[Tuple[int, int, str]]) -> Optional[str]:
    if cp in mapping:
        return mapping[cp]
    for start, end, cat in ranges:
        if start <= cp <= end:
            return cat
    return None


def _parse_motd(motd_path: Path) -> Optional[Tuple[str, List[Dict[str, str]]]]:
    text = _read_text(motd_path)
    if text is None:
        return None
    lines = text.splitlines()
    if not lines:
        return None
    header = lines[0]
    entries: List[Dict[str, str]] = []
    # Regex: - [lang] text — attribution
    # Use greedy for text to the last ' — ' sequence
    for idx, line in enumerate(lines[1:], start=2):
        # Must start with "- "
        if not line.startswith("- "):
            return None
        # Extract [lang]
        m = re.match(r"^- \[([A-Za-z0-9_\-]+)\] (.*)$", line)
        if not m:
            return None
        lang = m.group(1)
        rest = m.group(2)
        # Split by last ' — ' (em dash U+2014 with spaces)
        sep = " — "
        if sep not in rest:
            return None
        # Use rsplit to split on last occurrence
        left, right = rest.rsplit(sep, 1)
        text_part = left
        attribution = right
        if lang == "" or text_part == "" or attribution == "":
            return None
        entries.append({"language": lang, "text": text_part, "attribution": attribution})
    return header, entries


def _load_quotes(path: Path) -> Optional[List[Dict[str, Any]]]:
    data = _load_json(path)
    if not isinstance(data, dict):
        return None
    quotes = data.get("quotes")
    if not isinstance(quotes, list):
        return None
    # Validate minimal fields
    cleaned: List[Dict[str, Any]] = []
    for q in quotes:
        if not isinstance(q, dict):
            return None
        if not all(k in q for k in ("id", "language", "text", "attribution")):
            return None
        cleaned.append(q)
    return cleaned


def _match_motd_entries_to_quotes(motd_entries: List[Dict[str, str]], quotes: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    # Build lookup by (language, text, attribution) -> list of quotes indices (allow duplicates)
    lookup: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for q in quotes:
        key = (q.get("language"), q.get("text"), q.get("attribution"))
        lookup.setdefault(key, []).append(q)
    matched: List[Dict[str, Any]] = []
    for e in motd_entries:
        key = (e.get("language"), e.get("text"), e.get("attribution"))
        if key not in lookup or not lookup[key]:
            return None
        # Pop one to avoid reusing same quote if duplicates are not intended; but allow reuse if duplicates intended
        # We'll not pop to allow duplicates (same quote selected multiple times). Choose the first available.
        matched.append(lookup[key][0])
    return matched


def _load_char_report(path: Path) -> Optional[List[Dict[str, Any]]]:
    data = _load_json(path)
    if data is None:
        return None
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict) and isinstance(data.get("quotes"), list):
        entries = data.get("quotes")
    else:
        return None
    # Validate minimal structure
    cleaned: List[Dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, dict):
            return None
        if not all(k in item for k in ("id", "unique_codepoints_hex", "general_category_counts", "unmapped_characters")):
            return None
        if not isinstance(item["id"], str):
            return None
        if not isinstance(item["unique_codepoints_hex"], list):
            return None
        if not isinstance(item["general_category_counts"], dict):
            return None
        if not isinstance(item["unmapped_characters"], list):
            return None
        cleaned.append(item)
    return cleaned


def _set_eq_list_hex(a: List[str], b: List[str]) -> bool:
    # Normalize to uppercase "U+%X" style
    def norm(x: str) -> str:
        x = x.strip().upper()
        return x
    return set(map(norm, a)) == set(map(norm, b))


def _is_hex_uplus_list(lst: List[str]) -> bool:
    for s in lst:
        if not re.fullmatch(r'U\+[0-9A-F]{1,6}', s.strip().upper()):
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "builder_script_exists": 0.0,
        "builder_official_unicode_url_in_code": 0.0,
        "unicode_file_present_and_sane": 0.0,
        "unicode_sha256_record_matches": 0.0,
        "motd_file_header_and_count": 0.0,
        "motd_lines_formatted_correctly": 0.0,
        "motd_language_mix_requirement": 0.0,
        "motd_quotes_match_input": 0.0,
        "char_report_exists_and_count": 0.0,
        "char_report_unique_codepoints_match": 0.0,
        "char_report_general_category_counts_match": 0.0,
        "char_report_no_unmapped_characters": 0.0,
        "validate_script_exists_and_mentions": 0.0,
    }

    # Paths
    builder_path = workspace / "scripts" / "build_banner.py"
    validate_path = workspace / "scripts" / "validate.sh"
    unicode_path = workspace / "external" / "unicode" / "UnicodeData.txt"
    sha_out_path = workspace / "out" / "external_checks" / "unicode_sha256.txt"
    motd_path = workspace / "out" / "banner" / "motd.txt"
    char_report_path = workspace / "out" / "reports" / "char_report.json"
    config_path = workspace / "input" / "config.yaml"
    quotes_path = workspace / "input" / "quotes.json"

    # 1) builder_script_exists
    if builder_path.is_file():
        scores["builder_script_exists"] = 1.0

    # 2) builder_official_unicode_url_in_code
    if builder_path.is_file():
        code = _read_text(builder_path) or ""
        has_unicode_org = bool(re.search(r"https?://[^\"'\s]*unicode\.org[^\"'\s]*/UnicodeData\.txt", code))
        has_target_path = "external/unicode/UnicodeData.txt" in code.replace("\\", "/")
        if has_unicode_org and has_target_path:
            scores["builder_official_unicode_url_in_code"] = 1.0

    # Load inputs for MOTD checks
    config = _parse_simple_yaml(config_path) or None
    quotes = _load_quotes(quotes_path) or None

    # Parse MOTD
    motd_parsed = _parse_motd(motd_path) if motd_path.is_file() else None

    # 3) unicode_file_present_and_sane
    if unicode_path.is_file():
        b = _read_bytes(unicode_path)
        if b and len(b) > 0:
            parsed = _parse_unicode_data(unicode_path)
            if parsed is not None:
                _, _, has_arabic, has_latin = parsed
                if has_arabic and has_latin:
                    scores["unicode_file_present_and_sane"] = 1.0

    # 4) unicode_sha256_record_matches
    if unicode_path.is_file() and sha_out_path.is_file():
        actual_hash = _compute_sha256_hex(unicode_path)
        sha_text = _read_text(sha_out_path)
        if actual_hash and sha_text is not None:
            # Use first non-empty line
            line = ""
            for l in sha_text.splitlines():
                if l.strip():
                    line = l.strip()
                    break
            if line:
                # Normalize
                line_clean = line.strip().lower()
                if re.fullmatch(r"[0-9a-f]{64}", line_clean):
                    if line_clean == actual_hash.lower():
                        scores["unicode_sha256_record_matches"] = 1.0

    # 5) motd_file_header_and_count
    if config and motd_parsed:
        header, entries = motd_parsed
        max_quotes = config.get("max_quotes")
        motd_header = config.get("motd_header")
        if isinstance(max_quotes, int) and isinstance(motd_header, str):
            if header == motd_header and len(entries) == max_quotes:
                scores["motd_file_header_and_count"] = 1.0

    # 6) motd_lines_formatted_correctly
    # Ensured by _parse_motd, but also verify line patterns for robustness
    if motd_parsed:
        header, entries = motd_parsed
        ok = True
        for e in entries:
            if not isinstance(e.get("language"), str) or not isinstance(e.get("text"), str) or not isinstance(e.get("attribution"), str):
                ok = False
                break
            # Check formatted pieces are non-empty and characters preserved
            if not e["language"] or not e["text"] or not e["attribution"]:
                ok = False
                break
        if ok:
            scores["motd_lines_formatted_correctly"] = 1.0

    # 7) motd_language_mix_requirement
    if quotes and motd_parsed and config:
        _, entries = motd_parsed
        langs_in_input = set(q.get("language") for q in quotes if isinstance(q, dict))
        selected_langs = set(e.get("language") for e in entries)
        # If both ar and en exist in input and max_quotes >= 2, require both present among entries
        if "ar" in langs_in_input and "en" in langs_in_input:
            # If max_quotes < 2, it's impossible; but per provided config it's 3, so enforce both
            if "ar" in selected_langs and "en" in selected_langs:
                scores["motd_language_mix_requirement"] = 1.0
        else:
            # If one of them missing in input, then no constraint; consider pass if entries are non-empty
            if len(entries) >= 1:
                scores["motd_language_mix_requirement"] = 1.0

    # 8) motd_quotes_match_input
    motd_matched_quotes: Optional[List[Dict[str, Any]]] = None
    if quotes and motd_parsed:
        _, entries = motd_parsed
        matched = _match_motd_entries_to_quotes(entries, quotes)
        if matched is not None and len(matched) == len(entries):
            motd_matched_quotes = matched
            scores["motd_quotes_match_input"] = 1.0

    # 9) char_report_exists_and_count
    char_report = None
    if char_report_path.is_file():
        char_report = _load_char_report(char_report_path)
    if char_report is not None and motd_matched_quotes is not None:
        # Check counts correspond to number of selected motd entries
        if len(char_report) == len(motd_matched_quotes):
            # Verify ids correspond to selected quotes multiset
            expected_ids = [q["id"] for q in motd_matched_quotes]
            # Use multiset comparison
            def multiset(lst: List[str]) -> Dict[str, int]:
                d: Dict[str, int] = {}
                for x in lst:
                    d[x] = d.get(x, 0) + 1
                return d

            got_ids = [e.get("id", "") for e in char_report]
            if all(isinstance(x, str) for x in got_ids):
                if multiset(got_ids) == multiset(expected_ids):
                    scores["char_report_exists_and_count"] = 1.0

    # Prepare Unicode data for category verification
    unicode_parsed = _parse_unicode_data(unicode_path) if unicode_path.is_file() else None
    mapping: Dict[int, str] = {}
    ranges: List[Tuple[int, int, str]] = []
    if unicode_parsed is not None:
        mapping, ranges, _, _ = unicode_parsed

    # 10) char_report_unique_codepoints_match
    if char_report is not None and motd_matched_quotes is not None:
        ok = True
        # Map id -> quote text(s). If duplicate ids present multiple times, align by order.
        id_to_texts: Dict[str, List[str]] = {}
        for q in motd_matched_quotes:
            id_to_texts.setdefault(q["id"], []).append(q["text"])
        # We will consume one text per report id occurrence
        consumption: Dict[str, int] = {}
        for entry in char_report:
            rid = entry["id"]
            texts = id_to_texts.get(rid, [])
            idx = consumption.get(rid, 0)
            if idx >= len(texts):
                ok = False
                break
            quote_text = texts[idx]
            consumption[rid] = idx + 1
            # Compute unique codepoints set
            cps = {ord(ch) for ch in quote_text}
            expected_hex = [f"U+{cp:04X}" if cp <= 0xFFFF else f"U+{cp:06X}" for cp in cps]
            reported = entry.get("unique_codepoints_hex", [])
            if not isinstance(reported, list):
                ok = False
                break
            if not _is_hex_uplus_list(reported):
                ok = False
                break
            if not _set_eq_list_hex(expected_hex, reported):
                ok = False
                break
        if ok:
            scores["char_report_unique_codepoints_match"] = 1.0

    # 11) char_report_general_category_counts_match
    if char_report is not None and motd_matched_quotes is not None and mapping:
        ok = True
        id_to_texts: Dict[str, List[str]] = {}
        for q in motd_matched_quotes:
            id_to_texts.setdefault(q["id"], []).append(q["text"])
        consumption: Dict[str, int] = {}
        for entry in char_report:
            rid = entry["id"]
            texts = id_to_texts.get(rid, [])
            idx = consumption.get(rid, 0)
            if idx >= len(texts):
                ok = False
                break
            quote_text = texts[idx]
            consumption[rid] = idx + 1
            # Compute category counts
            counts: Dict[str, int] = {}
            # Track unmapped to ensure next check can validate
            unmapped: List[str] = []
            for ch in quote_text:
                cp = ord(ch)
                cat = _lookup_general_category(cp, mapping, ranges)
                if cat is None:
                    unmapped.append(ch)
                else:
                    counts[cat] = counts.get(cat, 0) + 1
            # Only include categories with counts > 0
            expected_counts = {k: v for k, v in counts.items() if v > 0}
            reported_counts = entry.get("general_category_counts", {})
            if not isinstance(reported_counts, dict):
                ok = False
                break
            # Ensure all keys are strings and values are integers >= 0
            for k, v in reported_counts.items():
                if not isinstance(k, str) or not isinstance(v, int) or v < 0:
                    ok = False
                    break
            if not ok:
                break
            if expected_counts != reported_counts:
                ok = False
                break
        if ok:
            scores["char_report_general_category_counts_match"] = 1.0

    # 12) char_report_no_unmapped_characters
    if char_report is not None:
        ok = True
        for entry in char_report:
            unmapped = entry.get("unmapped_characters", None)
            if not isinstance(unmapped, list):
                ok = False
                break
            if len(unmapped) != 0:
                ok = False
                break
        if ok:
            scores["char_report_no_unmapped_characters"] = 1.0

    # 13) validate_script_exists_and_mentions
    if validate_path.is_file():
        content = _read_text(validate_path) or ""
        needed_snippets = [
            "external/unicode/UnicodeData.txt",
            "out/external_checks/unicode_sha256.txt",
            "out/banner/motd.txt",
            "out/reports/char_report.json",
            "ARABIC",
            "LATIN",
        ]
        has_all = all(s in content for s in needed_snippets)
        # Look for PASS/FAIL indicators
        mentions_pass_fail = ("PASS" in content and "FAIL" in content)
        if has_all and mentions_pass_fail:
            scores["validate_script_exists_and_mentions"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()