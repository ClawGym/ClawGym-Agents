import json
import csv
import re
import sys
import subprocess
from datetime import datetime
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json(path: Path):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv(path: Path):
    try:
        with path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return None


def _parse_glossary_terms(md_text: str):
    lines = md_text.splitlines()
    terms = []
    i = 0
    while i < len(lines):
        if "Glossary terms (English):" in lines[i]:
            i += 1
            while i < len(lines):
                raw = lines[i]
                line = raw.strip("\n")
                if line.strip().startswith("- "):
                    term = line.strip()[2:].strip()
                    if term:
                        terms.append(term)
                    i += 1
                    continue
                if line.strip() == "":
                    i += 1
                    break
                else:
                    break
            break
        i += 1
    return terms


def _count_sentences(text: str) -> int:
    # Naive sentence count: split on ., !, ? and count non-empty segments
    parts = re.split(r"[.!?]+", text)
    return sum(1 for p in parts if p.strip())


def _is_spanish_like(text: str) -> bool:
    # Basic Spanish markers as used by the provided validator
    es_markers = {' el ', ' la ', ' los ', ' las ', ' de ', ' y ', ' para ', ' estudiantes '}
    t = ' ' + text.lower() + ' '
    return sum(1 for m in es_markers if m in t) >= 2


def _word_count(text: str) -> int:
    words = re.findall(r"\b[\wáéíóúüñÁÉÍÓÚÜÑ'-]+\b", text, flags=re.UNICODE)
    return len(words)


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _run_validator(workspace: Path):
    script = workspace / "scripts" / "validate_output.py"
    if not script.exists():
        return None, None, None
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
        )
        out = proc.stdout.decode("utf-8", errors="replace")
        code = proc.returncode
        return code, out, None
    except Exception as e:
        return None, None, str(e)


def _find_any_name_in_text(names, text: str) -> bool:
    t = text.lower()
    for n in names:
        if n.strip() and n.strip().lower() in t:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "deliverables_exist": 0.0,
        "guide_json_valid_and_keys": 0.0,
        "intro_en_grounded_and_length": 0.0,
        "intro_es_spanish_and_length": 0.0,
        "last_updated_iso_format": 0.0,
        "campus_resources_all_fields_present": 0.0,
        "campus_resources_all_categories_covered": 0.0,
        "campus_resources_names_align_with_csv": 0.0,
        "campus_resources_tip_sentence_count_1_to_2": 0.0,
        "community_programs_topics_and_programs": 0.0,
        "community_programs_has_summary_sentence": 0.0,
        "glossary_complete": 0.0,
        "guide_en_mentions_resource_and_program": 0.0,
        "guide_en_word_count_400_600": 0.0,
        "guide_es_spanish_and_comparable_length": 0.0,
        "validator_passed": 0.0,
        "validation_log_captured_full_output": 0.0,
    }

    # Paths
    guide_json_path = workspace / "output" / "guide.json"
    guide_en_md_path = workspace / "output" / "guide_en.md"
    guide_es_md_path = workspace / "output" / "guide_es.md"
    validation_log_path = workspace / "output" / "validation_log.txt"
    campus_csv_path = workspace / "input" / "resources" / "campus_resources.csv"
    community_json_path = workspace / "input" / "resources" / "community_programs.json"
    notes_md_path = workspace / "input" / "notes" / "professor_notes.md"

    # Deliverables exist
    if guide_json_path.exists() and guide_en_md_path.exists() and guide_es_md_path.exists() and validation_log_path.exists():
        scores["deliverables_exist"] = 1.0

    # Load inputs
    campus_rows = _load_csv(campus_csv_path)
    community_rows = _load_json(community_json_path)
    notes_text = _read_text(notes_md_path)
    glossary_terms = _parse_glossary_terms(notes_text) if notes_text else []

    # Load outputs
    g = _load_json(guide_json_path)
    en_md = _read_text(guide_en_md_path)
    es_md = _read_text(guide_es_md_path)

    # Validate guide.json structure and keys
    required_keys = {'intro_en', 'intro_es', 'campus_resources', 'community_programs', 'glossary', 'last_updated'}
    if isinstance(g, dict) and required_keys.issubset(g.keys()):
        scores["guide_json_valid_and_keys"] = 1.0

        # intro_en grounded and length
        intro_en = g.get("intro_en", "")
        if isinstance(intro_en, str) and len(intro_en.strip()) >= 100:
            # Grounded markers from notes
            grounded_markers = [
                "Stockton", "waterfront", "downtown", "neighborhood", "RTD", "U-Pass",
                "office hours", "service-learning", "Food Pantry", "Campus Night Escort", "campus", "students"
            ]
            lower_intro = intro_en.lower()
            hits = 0
            for m in grounded_markers:
                if m.lower() in lower_intro:
                    hits += 1
            if hits >= 2:
                scores["intro_en_grounded_and_length"] = 1.0

        # intro_es spanish and length
        intro_es = g.get("intro_es", "")
        if isinstance(intro_es, str) and len(intro_es.strip()) >= 100 and _is_spanish_like(intro_es):
            scores["intro_es_spanish_and_length"] = 1.0

        # last_updated ISO format and valid date
        last_updated = g.get("last_updated")
        if isinstance(last_updated, str):
            try:
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", last_updated):
                    datetime.strptime(last_updated, "%Y-%m-%d")
                    scores["last_updated_iso_format"] = 1.0
            except Exception:
                pass

        # campus_resources checks
        cr = g.get("campus_resources")
        if isinstance(cr, list) and len(cr) > 0:
            # all fields present
            fields_ok = True
            tips_ok = True
            for item in cr:
                if not isinstance(item, dict):
                    fields_ok = False
                    tips_ok = False
                    break
                for k in ['category', 'name', 'description', 'location', 'tip']:
                    if k not in item or not str(item.get(k, "")).strip():
                        fields_ok = False
                # tip 1-2 sentences
                tip = str(item.get("tip", ""))
                s_count = _count_sentences(tip)
                if s_count < 1 or s_count > 2:
                    tips_ok = False
            if fields_ok:
                scores["campus_resources_all_fields_present"] = 1.0
            if tips_ok:
                scores["campus_resources_tip_sentence_count_1_to_2"] = 1.0

            # categories covered and names align with CSV
            if isinstance(campus_rows, list) and len(campus_rows) > 0:
                csv_categories = {r.get('category', '').strip().lower() for r in campus_rows if r.get('category') is not None}
                # coverage
                have_by_cat = {}
                for item in cr:
                    cat = str(item.get('category', '')).strip().lower()
                    nm = str(item.get('name', '')).strip().lower()
                    if cat:
                        have_by_cat.setdefault(cat, set()).add(nm)
                coverage_ok = True
                name_align_ok = True
                # build mapping of CSV names per category
                csv_by_cat_names = {}
                for r in campus_rows:
                    c = r.get('category', '')
                    n = r.get('name', '')
                    if c is None or n is None:
                        continue
                    c = c.strip().lower()
                    n = n.strip().lower()
                    csv_by_cat_names.setdefault(c, set()).add(n)
                for c in csv_categories:
                    if c not in have_by_cat or len(have_by_cat[c]) == 0:
                        coverage_ok = False
                    else:
                        # must include at least one known CSV name for that category
                        if have_by_cat[c].isdisjoint(csv_by_cat_names.get(c, set())):
                            name_align_ok = False
                if coverage_ok:
                    scores["campus_resources_all_categories_covered"] = 1.0
                if name_align_ok:
                    scores["campus_resources_names_align_with_csv"] = 1.0

        # community_programs checks
        cp = g.get("community_programs")
        if isinstance(cp, dict) and isinstance(community_rows, list):
            # construct expected topics and names
            topics = {}
            for r in community_rows:
                try:
                    t = str(r['topic']).strip()
                    n = str(r['program_name']).strip()
                except Exception:
                    continue
                if t:
                    topics.setdefault(t, set()).add(n)
            topics_ok = True
            summary_ok = True
            for t, names in topics.items():
                lst = cp.get(t)
                if not isinstance(lst, list) or len(lst) == 0:
                    topics_ok = False
                else:
                    listed_names = {str(x.get('program_name', '')).strip() for x in lst if isinstance(x, dict)}
                    if listed_names.isdisjoint(names):
                        topics_ok = False
                    # check summary presence and looks like one sentence
                    for x in lst:
                        if not isinstance(x, dict):
                            summary_ok = False
                            continue
                        summ = str(x.get("summary", "")).strip()
                        if not summ:
                            summary_ok = False
                        else:
                            # one sentence heuristic: at least 1 sentence, not more than 2
                            sc = _count_sentences(summ)
                            if sc < 1 or sc > 2:
                                summary_ok = False
            if topics_ok:
                scores["community_programs_topics_and_programs"] = 1.0
            if summary_ok:
                scores["community_programs_has_summary_sentence"] = 1.0

        # glossary completeness
        gl = g.get("glossary")
        if isinstance(gl, dict) and len(glossary_terms) > 0:
            missing = False
            for term in glossary_terms:
                val = gl.get(term)
                if val is None or not str(val).strip():
                    missing = True
                    break
            if not missing:
                scores["glossary_complete"] = 1.0

    # Markdown checks: mentions and lengths
    # Mention at least one campus resource and one community program by name in guide_en.md
    resource_names = []
    if isinstance(campus_rows, list):
        resource_names = [str(r.get("name", "")).strip() for r in campus_rows if r.get("name")]
    program_names = []
    if isinstance(community_rows, list):
        program_names = [str(r.get("program_name", "")).strip() for r in community_rows if r.get("program_name")]
    if en_md:
        has_resource = _find_any_name_in_text(resource_names, en_md)
        has_program = _find_any_name_in_text(program_names, en_md)
        if has_resource and has_program:
            scores["guide_en_mentions_resource_and_program"] = 1.0

    # English word count 400–600
    if en_md:
        wc_en = _word_count(en_md)
        if 400 <= wc_en <= 600:
            scores["guide_en_word_count_400_600"] = 1.0

    # Spanish guide length and language comparable to English
    if es_md:
        wc_es = _word_count(es_md)
        wc_en = _word_count(en_md) if en_md else 0
        ratio_ok = False
        if wc_en > 0:
            ratio = wc_es / max(wc_en, 1)
            # comparable length heuristic
            ratio_ok = 0.6 <= ratio <= 1.6
        if wc_es >= 300 and _is_spanish_like(es_md) and ratio_ok:
            scores["guide_es_spanish_and_comparable_length"] = 1.0

    # Run provided validator and compare with saved log
    code, out, err = _run_validator(workspace)
    if out is not None and code is not None:
        if code == 0 and out.strip().startswith("PASS:"):
            scores["validator_passed"] = 1.0
        saved_log = _read_text(validation_log_path)
        if saved_log:
            if _normalize_newlines(saved_log).strip() == _normalize_newlines(out).strip():
                scores["validation_log_captured_full_output"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()