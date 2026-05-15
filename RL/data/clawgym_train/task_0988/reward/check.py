import csv
import json
import re
import sys
import hashlib
import ast
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _basic_yaml_load(path: Path) -> Optional[dict]:
    """
    Minimal YAML loader for flat key: value pairs and simple lists.
    Handles:
      - key: value (strings, ints, floats, booleans)
      - key:
          - item1
          - item2
    """
    text = _read_text(path)
    if text is None:
        return None
    data = {}
    current_list_key = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if re.match(r"^\S.*:\s*$", line) and not line.strip().endswith("-"):
            # key: (possibly list start)
            key = line.split(":")[0].strip()
            current_list_key = key
            data[key] = []
            continue
        if ":" in line and not line.startswith("  - "):
            # key: value
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "":
                # This is a list starter; handled above
                continue
            # Parse booleans, numbers, quoted strings
            if val.lower() in ("true", "false"):
                data[key] = val.lower() == "true"
            else:
                # strip quotes if present
                if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
                    data[key] = val[1:-1]
                else:
                    # try int/float
                    try:
                        if "." in val:
                            data[key] = float(val)
                        else:
                            data[key] = int(val)
                    except ValueError:
                        data[key] = val
            current_list_key = None
        elif line.strip().startswith("- "):
            # list item
            if current_list_key is None:
                # malformed structure; ignore
                continue
            item = line.strip()[2:]
            # strip quotes
            if (item.startswith("'") and item.endswith("'")) or (item.startswith('"') and item.endswith('"')):
                item = item[1:-1]
            data[current_list_key].append(item)
        else:
            # ignore unhandled cases
            pass
    return data


def _load_glossary_from_py(path: Path) -> Optional[Dict[str, str]]:
    """
    Safely parse a Python file defining PREFERRED_SPANISH = {...}
    """
    text = _read_text(path)
    if text is None:
        return None
    try:
        module_ast = ast.parse(text, filename=str(path))
        for node in module_ast.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "PREFERRED_SPANISH":
                        value = ast.literal_eval(node.value)
                        if isinstance(value, dict):
                            # ensure all keys and values are strings
                            clean = {}
                            for k, v in value.items():
                                if isinstance(k, str) and isinstance(v, str):
                                    clean[k] = v
                            return clean
        return None
    except Exception:
        return None


def _parse_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _read_csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            first = f.readline()
        if not first:
            return None
        return [h.strip() for h in first.rstrip("\n").split(",")]
    except Exception:
        return None


def _extract_ul_li_texts(html_text: str, ul_id: str) -> List[str]:
    # Find the UL section with given id
    # Regex robust enough for simple HTML
    ul_pattern = re.compile(rf'<ul[^>]*\bid\s*=\s*"{re.escape(ul_id)}"[^>]*>(.*?)</ul>', re.IGNORECASE | re.DOTALL)
    m = ul_pattern.search(html_text)
    if not m:
        return []
    inner = m.group(1)
    # Extract li items
    li_pattern = re.compile(r"<li[^>]*>(.*?)</li>", re.IGNORECASE | re.DOTALL)
    items = []
    for m2 in li_pattern.finditer(inner):
        content = m2.group(1)
        # remove any nested tags
        content = re.sub(r"<[^>]+>", "", content)
        content = content.strip()
        # Unwrap surrounding quotes if present
        if (content.startswith('"') and content.endswith('"')) or (content.startswith("“") and content.endswith("”")):
            content = content[1:-1].strip()
        items.append(content)
    return items


def _parse_markdown_bullets(md_text: str) -> List[str]:
    bullets = []
    for line in md_text.splitlines():
        m = re.match(r'^\s*[-*]\s+(.*\S)\s*$', line)
        if m:
            bullets.append(m.group(1).strip())
    return bullets


def _load_audit_json(path: Path) -> Optional[dict]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _parse_intake_notes(path: Path) -> Dict[str, str]:
    text = _read_text(path)
    if text is None:
        return {}
    mapping = {}
    for line in text.splitlines():
        if ":" in line:
            cid, note = line.split(":", 1)
            cid = cid.strip()
            note = note.strip()
            if cid and note:
                mapping[cid] = note
    return mapping


def _get_content_tokens(text: str) -> List[str]:
    # Words longer than 4 letters
    tokens = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\-']{5,}", text)
    return [t.lower() for t in tokens]


def _find_case_ids_in_csv(rows: List[Dict[str, str]]) -> List[str]:
    return [r.get("case_id", "") for r in rows]


def _count_substring_ci(haystack: str, needle: str) -> int:
    if haystack is None or needle is None:
        return 0
    return haystack.lower().count(needle.lower())


def _contains_substring_ci(haystack: str, needle: str) -> bool:
    return _count_substring_ci(haystack, needle) > 0


def _english_terms_present_in_text(text: str, glossary: Dict[str, str]) -> List[str]:
    present = []
    lowered = text.lower()
    for k in glossary.keys():
        if k.lower() in lowered:
            present.append(k)
    return present


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "cases_csv_header_and_existence": 0.0,
        "cases_row_count_and_order": 0.0,
        "cases_english_plain_nonempty": 0.0,
        "cases_english_includes_intake_notes": 0.0,
        "cases_spanish_presence_by_pref": 0.0,
        "cases_glossary_enforcement": 0.0,
        "phrases_md_structure_and_count": 0.0,
        "phrases_glossary_enforcement": 0.0,
        "audit_json_structure": 0.0,
        "audit_config_used_correct": 0.0,
        "audit_counts_correct": 0.0,
        "audit_glossary_replacements_correct": 0.0,
        "audit_checksums_correct": 0.0,
    }

    # Input and config paths
    cases_csv_path = workspace / "input" / "cases.csv"
    intake_notes_path = workspace / "input" / "intake_notes_en.txt"
    webpage_html_path = workspace / "input" / "webpage.html"
    translation_yaml_path = workspace / "config" / "translation.yaml"
    glossary_py_path = workspace / "config" / "glossary.py"

    # Output paths
    out_cases_path = workspace / "outputs" / "case_summaries_bilingual.csv"
    out_phrases_path = workspace / "outputs" / "de_escalation_phrases_es.md"
    out_audit_path = workspace / "outputs" / "audit.json"

    # Load configs and inputs
    yaml_cfg = _basic_yaml_load(translation_yaml_path) or {}
    target_lang = str(yaml_cfg.get("target_language", "")).strip().lower()
    include_glossary = bool(yaml_cfg.get("include_glossary", False))
    glossary_module_path = yaml_cfg.get("glossary_module", "config/glossary.py")
    apply_to = yaml_cfg.get("apply_to", [])
    if not isinstance(apply_to, list):
        apply_to = []

    # Glossary dict
    glossary_dict = _load_glossary_from_py(workspace / glossary_module_path) or {}
    glossary_keys = list(glossary_dict.keys())

    # Input data
    cases_rows = _parse_csv_dicts(cases_csv_path) or []
    input_case_ids = _find_case_ids_in_csv(cases_rows) if cases_rows else []
    total_cases = len(cases_rows)
    spanish_cases = 0
    for r in cases_rows:
        pref = (r.get("language_pref", "") or "").strip().lower()
        if pref in ("spanish", "es"):
            spanish_cases += 1

    notes_map = _parse_intake_notes(intake_notes_path)
    webpage_html = _read_text(webpage_html_path) or ""
    extracted_phrases = _extract_ul_li_texts(webpage_html, "recommended-phrases")
    phrases_extracted_count = len(extracted_phrases)

    # 1) Validate outputs/case_summaries_bilingual.csv
    header_ok = False
    out_rows = []
    if out_cases_path.exists():
        header = _read_csv_header(out_cases_path)
        if header == ["case_id", "english_plain", "spanish_plain"]:
            header_ok = True
        try:
            with out_cases_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                out_rows = list(reader)
        except Exception:
            out_rows = []
    if header_ok and out_rows:
        scores["cases_csv_header_and_existence"] = 1.0

    # Row count and order
    if out_rows and total_cases > 0:
        out_case_ids = _find_case_ids_in_csv(out_rows)
        if len(out_rows) == total_cases and out_case_ids == input_case_ids:
            scores["cases_row_count_and_order"] = 1.0

    # english_plain non-empty for each row
    if out_rows:
        nonempty_count = sum(1 for r in out_rows if (r.get("english_plain", "") or "").strip() != "")
        if nonempty_count == len(out_rows):
            scores["cases_english_plain_nonempty"] = 1.0

    # english includes notes content for cases with notes (require at least 1 significant token)
    if out_rows and notes_map:
        satisfied = 0
        total_with_notes = 0
        notes_token_cache = {}
        for r in out_rows:
            cid = r.get("case_id", "").strip()
            if cid in notes_map:
                total_with_notes += 1
                note = notes_map[cid]
                if cid not in notes_token_cache:
                    toks = _get_content_tokens(note)
                    notes_token_cache[cid] = toks
                toks = notes_token_cache[cid]
                ep = (r.get("english_plain", "") or "").lower()
                # Count matches of tokens in english summary
                matches = sum(1 for t in toks if t in ep)
                if matches >= 1:
                    satisfied += 1
        if total_with_notes > 0 and satisfied == total_with_notes:
            scores["cases_english_includes_intake_notes"] = 1.0

    # Spanish presence per language preference and target language constraint
    spanish_presence_ok = True
    if out_rows:
        for r in out_rows:
            pref = (next((row.get("language_pref", "") for row in cases_rows if row.get("case_id") == r.get("case_id")), "") or "").strip().lower()
            sp = (r.get("spanish_plain", "") or "").strip()
            if target_lang == "es":
                # Should be non-empty only if Spanish/ES
                if pref in ("spanish", "es"):
                    if sp == "":
                        spanish_presence_ok = False
                else:
                    if sp != "":
                        spanish_presence_ok = False
            else:
                # Should skip Spanish generation: expect empty for all
                if sp != "":
                    spanish_presence_ok = False
        if spanish_presence_ok:
            scores["cases_spanish_presence_by_pref"] = 1.0

    # Glossary enforcement in cases: For any English clinical term present in english_plain, the Spanish must contain the preferred equivalent
    glossary_cases_ok = True
    if out_rows and include_glossary and target_lang == "es" and ("cases" in apply_to or not apply_to):
        for r in out_rows:
            ep = (r.get("english_plain", "") or "")
            sp = (r.get("spanish_plain", "") or "")
            # Determine which keys occur in english_plain
            present_keys = _english_terms_present_in_text(ep, glossary_dict)
            for k in present_keys:
                expected_spanish = glossary_dict[k]
                if not _contains_substring_ci(sp, expected_spanish):
                    glossary_cases_ok = False
                    break
            if not glossary_cases_ok:
                break
        if glossary_cases_ok:
            scores["cases_glossary_enforcement"] = 1.0
    elif out_rows and (not include_glossary or target_lang != "es"):
        # If glossary not required or not Spanish target, consider enforcement not applicable; give full credit.
        scores["cases_glossary_enforcement"] = 1.0

    # 2) Validate outputs/de_escalation_phrases_es.md
    phrases_md_text = _read_text(out_phrases_path) or ""
    if phrases_md_text:
        bullets = _parse_markdown_bullets(phrases_md_text)
        # Title line: first non-empty line not starting with bullet
        non_empty_lines = [ln.rstrip() for ln in phrases_md_text.splitlines() if ln.strip() != ""]
        has_title = False
        if non_empty_lines:
            first = non_empty_lines[0]
            if not re.match(r'^\s*[-*]\s+', first):
                has_title = True
        count_ok = (len(bullets) == phrases_extracted_count and phrases_extracted_count > 0)
        if has_title and count_ok:
            scores["phrases_md_structure_and_count"] = 1.0

        # Glossary enforcement for phrases: For any clinical term in the English phrases, ensure Spanish bullet contains mapped term
        glossary_phrases_ok = True
        if include_glossary and target_lang == "es" and ("phrases" in apply_to or not apply_to) and extracted_phrases:
            # match each bullet to corresponding extracted phrase by order
            if len(bullets) == len(extracted_phrases):
                for eng, es in zip(extracted_phrases, bullets):
                    present_keys = _english_terms_present_in_text(eng, glossary_dict)
                    for k in present_keys:
                        expected_spanish = glossary_dict[k]
                        if not _contains_substring_ci(es, expected_spanish):
                            glossary_phrases_ok = False
                            break
                    if not glossary_phrases_ok:
                        break
            else:
                glossary_phrases_ok = False
            if glossary_phrases_ok:
                scores["phrases_glossary_enforcement"] = 1.0
        elif phrases_md_text and (not include_glossary or target_lang != "es"):
            # Not applicable; give credit
            scores["phrases_glossary_enforcement"] = 1.0

    # 3) Validate outputs/audit.json
    audit_obj = _load_audit_json(out_audit_path)
    if isinstance(audit_obj, dict):
        scores["audit_json_structure"] = 1.0

        # config_used check
        config_ok = False
        cfg_used = audit_obj.get("config_used", {})
        if isinstance(cfg_used, dict):
            tl = str(cfg_used.get("target_language", "")).strip().lower()
            # Accept either "glossary_keys" or "glossary_keys_applied"
            gkeys = cfg_used.get("glossary_keys")
            if gkeys is None:
                gkeys = cfg_used.get("glossary_keys_applied")
            if isinstance(gkeys, list):
                # Expect set equality with glossary keys
                try:
                    gkeys_set = set([str(x) for x in gkeys])
                except Exception:
                    gkeys_set = set()
                if tl == target_lang and gkeys_set == set(glossary_keys):
                    config_ok = True
        if config_ok:
            scores["audit_config_used_correct"] = 1.0

        # counts check
        counts_ok = False
        counts = audit_obj.get("counts", {})
        if isinstance(counts, dict):
            tc = counts.get("total_cases")
            sc = counts.get("spanish_cases")
            pe = counts.get("phrases_extracted")
            if isinstance(tc, int) and isinstance(sc, int) and isinstance(pe, int):
                if tc == total_cases and sc == spanish_cases and pe == phrases_extracted_count:
                    counts_ok = True
        if counts_ok:
            scores["audit_counts_correct"] = 1.0

        # source_checksums check
        checksums_ok = False
        checksums = audit_obj.get("source_checksums", {})
        if isinstance(checksums, dict):
            expected = {
                "input/cases.csv": _compute_sha256(cases_csv_path),
                "input/intake_notes_en.txt": _compute_sha256(intake_notes_path),
                "input/webpage.html": _compute_sha256(webpage_html_path),
                "config/translation.yaml": _compute_sha256(translation_yaml_path),
                "config/glossary.py": _compute_sha256(glossary_py_path),
            }
            # All must be present and match
            have_all = all(k in checksums and isinstance(checksums[k], str) for k in expected.keys())
            match_all = have_all and all((expected[k] is not None and checksums[k] == expected[k]) for k in expected.keys())
            if match_all:
                checksums_ok = True
        if checksums_ok:
            scores["audit_checksums_correct"] = 1.0

        # glossary_replacements check
        replacements_ok = False
        repl = audit_obj.get("glossary_replacements", {})
        if isinstance(repl, dict):
            cases_spanish_map = repl.get("cases_spanish", {})
            phrases_spanish_map = repl.get("phrases_spanish", {})
            if isinstance(cases_spanish_map, dict) and isinstance(phrases_spanish_map, dict):
                # Compute actual counts from outputs
                # Cases spanish counts
                actual_cases_counts = {k: 0 for k in glossary_keys}
                for r in out_rows:
                    sp = (r.get("spanish_plain", "") or "")
                    for k, v in glossary_dict.items():
                        actual_cases_counts[k] += _count_substring_ci(sp, v)

                # Phrases spanish counts
                bullets = _parse_markdown_bullets(phrases_md_text) if phrases_md_text else []
                combined_bullets_text = "\n".join(bullets)
                actual_phrases_counts = {k: 0 for k in glossary_keys}
                for k, v in glossary_dict.items():
                    actual_phrases_counts[k] = _count_substring_ci(combined_bullets_text, v)

                # Validate mapping keys and values
                try:
                    cases_keys_match = set(cases_spanish_map.keys()) == set(glossary_keys)
                    phrases_keys_match = set(phrases_spanish_map.keys()) == set(glossary_keys)
                    cases_vals_match = all(isinstance(cases_spanish_map.get(k), int) and cases_spanish_map.get(k) == actual_cases_counts.get(k, -1) for k in glossary_keys)
                    phrases_vals_match = all(isinstance(phrases_spanish_map.get(k), int) and phrases_spanish_map.get(k) == actual_phrases_counts.get(k, -1) for k in glossary_keys)
                    if cases_keys_match and phrases_keys_match and cases_vals_match and phrases_vals_match:
                        replacements_ok = True
                except Exception:
                    replacements_ok = False
        if replacements_ok:
            scores["audit_glossary_replacements_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()