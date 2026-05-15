import json
import csv
import re
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        # Ensure required columns
        required = {"term", "en_definition", "es-ES", "fr-FR"}
        if rows is None:
            return None
        if len(rows) == 0:
            # Empty CSV is technically parsable but provides no rows
            return []
        if not required.issubset(set(rows[0].keys())):
            return None
        return rows
    except Exception:
        return None


def _load_json_array(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        else:
            return None
    except Exception:
        return None


def _parse_yaml_languages(path: Path) -> Optional[Dict[str, Dict[str, List[str]]]]:
    """
    Minimal YAML parser for expected structure:
    languages:
      <lang>:
        accepted_terms:
          - ...
        keep_untranslated:
          - ...
        brand_names:
          - ...
    Returns dict: { lang: { field_name: [values...] } }
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    inside_languages = False
    current_lang = None
    current_field = None
    data: Dict[str, Dict[str, List[str]]] = {}
    for raw in lines:
        line = raw.rstrip("\n")
        if not inside_languages:
            if line.strip().startswith("languages:"):
                inside_languages = True
            continue
        if line.strip() == "":
            continue
        indent = len(line) - len(line.lstrip(' '))
        stripped = line.strip()
        if indent == 0 and not stripped.startswith("languages:"):
            break
        if indent == 2 and stripped.endswith(":"):
            key = stripped[:-1].strip()
            current_lang = key
            data.setdefault(current_lang, {})
            current_field = None
            continue
        if indent == 4 and stripped.endswith(":"):
            field = stripped[:-1].strip()
            current_field = field
            data.setdefault(current_lang, {})
            data[current_lang][current_field] = []
            continue
        if indent >= 6 and stripped.startswith("- "):
            value = stripped[2:].strip()
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            if current_lang is not None and current_field is not None:
                data[current_lang].setdefault(current_field, []).append(value)
            continue
    return data


def _extract_terms_from_post(content: str, terms: List[str]) -> List[str]:
    """Return terms that appear in the post content. Exact substring match, case-sensitive."""
    present = []
    for term in terms:
        if term in content:
            present.append(term)
    return present


def _heading_levels(markdown_text: str) -> List[int]:
    """Extract heading levels in order from a Markdown document."""
    levels = []
    for line in markdown_text.splitlines():
        if line.startswith("#"):
            i = 0
            while i < len(line) and line[i] == "#":
                i += 1
            if i < len(line) and line[i] == " ":
                levels.append(i)
    return levels


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "translation_files_exist": 0.0,
        "markdown_structure_preserved_es": 0.0,
        "markdown_structure_preserved_fr": 0.0,
        "brand_names_preserved_es": 0.0,
        "brand_names_preserved_fr": 0.0,
        "sources_file_complete_and_valid": 0.0,
        "glossary_extended_complete_and_valid": 0.0,
        "translations_match_extended_es": 0.0,
        "translations_match_extended_fr": 0.0,
        "provided_terms_translated_es": 0.0,
        "provided_terms_translated_fr": 0.0,
        "config_has_language_sections": 0.0,
        "config_en_unchanged": 0.0,
        "config_accepted_terms_match_outputs": 0.0,
        "config_keep_untranslated_has_brands": 0.0,
        "email_announcement_valid": 0.0,
    }

    # Paths
    post_en_path = workspace / "input" / "content" / "post_en.md"
    glossary_csv_path = workspace / "input" / "glossary" / "base_glossary.csv"
    style_yml_path = workspace / "config" / "style.yml"
    post_es_path = workspace / "output" / "post_es-ES.md"
    post_fr_path = workspace / "output" / "post_fr-FR.md"
    sources_json_path = workspace / "sources" / "terms_sources.json"
    glossary_ext_path = workspace / "output" / "glossary_extended.json"
    email_path = workspace / "output" / "email_announcement.txt"

    # Read inputs
    post_en = _read_text(post_en_path) or ""
    post_es = _read_text(post_es_path)
    post_fr = _read_text(post_fr_path)
    csv_rows = _load_csv(glossary_csv_path)
    sources_arr = _load_json_array(sources_json_path)
    glossary_ext_arr = _load_json_array(glossary_ext_path)
    languages_cfg = _parse_yaml_languages(style_yml_path)

    # translation_files_exist
    if post_es is not None and post_fr is not None:
        scores["translation_files_exist"] = 1.0

    # Prepare glossary info
    terms = []
    provided_translations = {
        "es-ES": {},
        "fr-FR": {},
    }
    missing_pairs: List[Tuple[str, str]] = []
    appears_in_post: List[str] = []
    if csv_rows is not None and post_en:
        terms = [row["term"] for row in csv_rows if "term" in row]
        appears_in_post = _extract_terms_from_post(post_en, terms)
        for row in csv_rows:
            term = row["term"]
            for lang in ("es-ES", "fr-FR"):
                val = row.get(lang, "")
                if val is None:
                    val = ""
                val = val.strip()
                if val:
                    provided_translations[lang][term] = val
                else:
                    if term in appears_in_post:
                        missing_pairs.append((term, lang))

    # markdown_structure_preserved checks
    if post_es is not None:
        src_levels = _heading_levels(post_en or "")
        es_levels = _heading_levels(post_es)
        if src_levels == es_levels and len(src_levels) > 0:
            scores["markdown_structure_preserved_es"] = 1.0
    if post_fr is not None:
        src_levels = _heading_levels(post_en or "")
        fr_levels = _heading_levels(post_fr)
        if src_levels == fr_levels and len(src_levels) > 0:
            scores["markdown_structure_preserved_fr"] = 1.0

    # Brand names preserved checks
    brand_names = ["Figma", "Photoshop", "Illustrator"]
    if post_es is not None:
        scores["brand_names_preserved_es"] = 1.0 if all(b in post_es for b in brand_names) else 0.0
    if post_fr is not None:
        scores["brand_names_preserved_fr"] = 1.0 if all(b in post_fr for b in brand_names) else 0.0

    # Validate sources file
    sources_valid = False
    sources_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if sources_arr is not None:
        all_ids = set()
        pair_counts: Dict[Tuple[str, str], int] = {}
        structure_ok = True
        id_pattern = re.compile(r"^[A-Za-z0-9_\-:.]+$")
        date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        for obj in sources_arr:
            if not isinstance(obj, dict):
                structure_ok = False
                break
            required_fields = [
                "id",
                "language",
                "term",
                "chosen_translation",
                "organization_name",
                "source_title",
                "url",
                "retrieval_date",
                "note",
            ]
            if not all(k in obj and isinstance(obj[k], str) and obj[k].strip() for k in required_fields):
                structure_ok = False
                break
            if obj["language"] not in {"es-ES", "fr-FR"}:
                structure_ok = False
                break
            if not id_pattern.match(obj["id"]):
                structure_ok = False
                break
            if obj["id"] in all_ids:
                structure_ok = False
                break
            if not (obj["url"].startswith("http://") or obj["url"].startswith("https://")):
                structure_ok = False
                break
            if not date_pattern.match(obj["retrieval_date"]):
                structure_ok = False
                break
            key = (obj["term"], obj["language"])
            pair_counts[key] = pair_counts.get(key, 0) + 1
            if key not in sources_map:
                sources_map[key] = obj
            all_ids.add(obj["id"])
        if structure_ok:
            all_required_pairs = set(missing_pairs)
            missing_ok = all(pair_counts.get(p, 0) == 1 for p in all_required_pairs)
            no_dupes_for_all = all(c == 1 for c in pair_counts.values())
            if missing_ok and no_dupes_for_all:
                sources_valid = True
    if sources_valid:
        scores["sources_file_complete_and_valid"] = 1.0

    # Validate extended glossary and cross-check with sources and provided translations
    glossary_valid = False
    ext_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if glossary_ext_arr is not None and csv_rows is not None:
        required_pairs = set((term, lang) for term in appears_in_post for lang in ("es-ES", "fr-FR"))
        structure_ok = True
        ext_pairs_seen: Dict[Tuple[str, str], int] = {}
        for obj in glossary_ext_arr:
            if not isinstance(obj, dict):
                structure_ok = False
                break
            if not all(k in obj for k in ("term", "language", "translation", "source_id")):
                structure_ok = False
                break
            term = obj["term"]
            lang = obj["language"]
            translation = obj["translation"]
            source_id = obj["source_id"]
            if not isinstance(term, str) or not isinstance(lang, str) or not isinstance(translation, str) or not isinstance(source_id, str):
                structure_ok = False
                break
            if lang not in {"es-ES", "fr-FR"}:
                structure_ok = False
                break
            key = (term, lang)
            ext_pairs_seen[key] = ext_pairs_seen.get(key, 0) + 1
            if key in required_pairs:
                if term in provided_translations[lang]:
                    if translation != provided_translations[lang][term]:
                        structure_ok = False
                        break
                    if source_id != "local:base_glossary":
                        structure_ok = False
                        break
                else:
                    if sources_arr is None:
                        structure_ok = False
                        break
                    src_obj = sources_map.get(key)
                    if src_obj is None:
                        structure_ok = False
                        break
                    if source_id != src_obj["id"]:
                        structure_ok = False
                        break
                    if translation != src_obj["chosen_translation"]:
                        structure_ok = False
                        break
            if key not in ext_map:
                ext_map[key] = obj
        if structure_ok:
            coverage_ok = all(ext_pairs_seen.get(p, 0) == 1 for p in required_pairs)
            glossary_valid = coverage_ok
    if glossary_valid:
        scores["glossary_extended_complete_and_valid"] = 1.0

    # Translations match extended glossary: ensure translated posts contain the translation strings
    if glossary_valid and post_es is not None:
        ok = True
        for term in appears_in_post:
            key = (term, "es-ES")
            ext_entry = ext_map.get(key)
            if not ext_entry:
                ok = False
                break
            trans_str = ext_entry["translation"]
            if trans_str not in post_es:
                ok = False
                break
        if ok:
            scores["translations_match_extended_es"] = 1.0
    if glossary_valid and post_fr is not None:
        ok = True
        for term in appears_in_post:
            key = (term, "fr-FR")
            ext_entry = ext_map.get(key)
            if not ext_entry:
                ok = False
                break
            trans_str = ext_entry["translation"]
            if trans_str not in post_fr:
                ok = False
                break
        if ok:
            scores["translations_match_extended_fr"] = 1.0

    # Provided terms translated: verify provided translations appear in the translated posts
    if post_es is not None and csv_rows is not None:
        ok = True
        for term in terms:
            if term in appears_in_post and term in provided_translations["es-ES"]:
                if provided_translations["es-ES"][term] not in post_es:
                    ok = False
                    break
        if ok:
            scores["provided_terms_translated_es"] = 1.0

    if post_fr is not None and csv_rows is not None:
        ok = True
        for term in terms:
            if term in appears_in_post and term in provided_translations["fr-FR"]:
                if provided_translations["fr-FR"][term] not in post_fr:
                    ok = False
                    break
        if ok:
            scores["provided_terms_translated_fr"] = 1.0

    # Config checks
    if languages_cfg is not None:
        has_es = "es-ES" in languages_cfg
        has_fr = "fr-FR" in languages_cfg
        if has_es and has_fr:
            scores["config_has_language_sections"] = 1.0

        # Only award en unchanged if es-ES and fr-FR sections exist (to avoid awarding for pre-existing input state)
        if has_es and has_fr and "en" in languages_cfg:
            original_en_accepted = {
                "Pomodoro Technique",
                "mood board",
                "grid system",
                "keyboard shortcuts",
                "Do Not Disturb mode",
                "timeboxing",
                "deep work",
                "standing desk",
                "ergonomic chair",
            }
            en_terms = set(languages_cfg["en"].get("accepted_terms", []))
            if en_terms == original_en_accepted:
                scores["config_en_unchanged"] = 1.0

        # config accepted_terms match outputs (based on translations actually used per language for terms appearing in post)
        match_ok = True
        if glossary_valid and has_es and has_fr:
            for lang in ("es-ES", "fr-FR"):
                expected = set()
                for term in appears_in_post:
                    entry = ext_map.get((term, lang))
                    if entry:
                        expected.add(entry["translation"])
                cfg_terms = set(languages_cfg.get(lang, {}).get("accepted_terms", []))
                if expected != cfg_terms:
                    match_ok = False
                    break
        else:
            match_ok = False
        if match_ok:
            scores["config_accepted_terms_match_outputs"] = 1.0

        # keep_untranslated contains brand names for es and fr
        kut_ok = True
        if has_es and has_fr:
            for lang in ("es-ES", "fr-FR"):
                kut = set(languages_cfg.get(lang, {}).get("keep_untranslated", []))
                if not set(brand_names).issubset(kut):
                    kut_ok = False
                    break
        else:
            kut_ok = False
        if kut_ok:
            scores["config_keep_untranslated_has_brands"] = 1.0

    # Email announcement checks
    email_text = _read_text(email_path)
    if email_text is not None:
        lines = [ln for ln in email_text.splitlines() if ln.strip() != ""]
        has_subject = False
        if lines:
            first = lines[0].strip()
            if first.lower().startswith("subject:"):
                has_subject = True
        paths_present = ("output/post_es-ES.md" in email_text) and ("output/post_fr-FR.md" in email_text)
        feedback_present = ("feedback" in email_text.lower())
        if has_subject and paths_present and feedback_present:
            scores["email_announcement_valid"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()