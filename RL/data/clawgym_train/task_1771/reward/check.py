import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _write_debug(_msg: str) -> None:
    # Intentionally no-op to avoid extra output; reserved for internal debugging if needed.
    pass


def _parse_simple_yaml_themes(path: Path) -> Optional[Dict[str, Dict[str, List[str]]]]:
    """
    Very small YAML parser for the specific themes.yaml structure used in the task.
    Supports:
    themes:
      theme_name:
        keywords_en: ["a", "b"]
        keywords_es: ["c", "d"]
    """
    txt = _read_text(path)
    if txt is None:
        return None
    lines = txt.splitlines()
    themes_section = False
    current_theme = None
    themes: Dict[str, Dict[str, List[str]]] = {}
    for raw in lines:
        line = raw.rstrip()
        # detect themes:
        if not themes_section:
            if line.strip() == "themes:":
                themes_section = True
            continue
        # theme key: two spaces then name ending with colon
        m_theme = re.match(r"^\s{2}([a-zA-Z0-9_]+):\s*$", line)
        if m_theme:
            current_theme = m_theme.group(1)
            themes[current_theme] = {"keywords_en": [], "keywords_es": []}
            continue
        # keywords lines: 4 spaces then keywords_en/es: [ ... ]
        m_kw = re.match(r"^\s{4}(keywords_en|keywords_es):\s*\[(.*)\]\s*$", line)
        if m_kw and current_theme is not None:
            key = m_kw.group(1)
            content = m_kw.group(2).strip()
            items: List[str] = []
            if content:
                # split by commas not inside quotes - simple approach since items don't contain commas in content.
                parts = [p.strip() for p in content.split(",")]
                for p in parts:
                    # remove surrounding quotes if present
                    if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
                        p = p[1:-1]
                    items.append(p)
            themes[current_theme][key] = items
            continue
        # otherwise ignore lines
    if not themes:
        return None
    return themes


def _compute_glossary_counts(anecdotes: List[Dict[str, str]], glossary_seed: List[Dict[str, str]]) -> Dict[str, Dict[str, object]]:
    """
    Returns mapping: spanish -> {'english': str, 'count': int, 'ids': sorted list of ids}
    """
    # Map id to text
    id_to_text = {row["id"]: row["text"] for row in anecdotes if "id" in row and "text" in row}
    result: Dict[str, Dict[str, object]] = {}
    for row in glossary_seed:
        sp = row.get("spanish", "")
        en = row.get("english", "")
        matching_ids = []
        for id_, text in id_to_text.items():
            if sp and text is not None and sp.lower() in text.lower():
                matching_ids.append(id_)
        matching_ids = sorted(set(matching_ids))
        result[sp] = {"english": en, "count": len(set(matching_ids)), "ids": matching_ids}
    return result


def _compute_theme_stats(anecdotes: List[Dict[str, str]], themes: Dict[str, Dict[str, List[str]]]) -> Dict[str, object]:
    """
    Compute expected theme stats based on the rules.
    """
    # Basic numbers
    num_anecdotes = len(anecdotes)
    count_by_lang = {"es": 0, "en": 0}
    sources = {"fan_email", "podcast_snippet", "locker_room_story"}
    # Initialize theme counters
    themes_out: Dict[str, Dict[str, object]] = {}
    for theme_name in themes.keys():
        themes_out[theme_name] = {
            "overall": 0,
            "by_source": {src: 0 for src in ["fan_email", "podcast_snippet", "locker_room_story"]},
        }

    for row in anecdotes:
        lang = row.get("lang", "")
        src = row.get("source", "")
        text = row.get("text", "")
        if lang in count_by_lang:
            count_by_lang[lang] += 1
        # Determine which themes apply (at most once per theme per anecdote)
        for theme_name, kv in themes.items():
            k_en = kv.get("keywords_en", [])
            k_es = kv.get("keywords_es", [])
            matched = False
            t_low = (text or "").lower()
            # match any keyword (case-insensitive)
            for kw in k_en:
                if kw.lower() in t_low:
                    matched = True
                    break
            if not matched:
                for kw in k_es:
                    if kw.lower() in t_low:
                        matched = True
                        break
            if matched:
                themes_out[theme_name]["overall"] += 1
                if src in themes_out[theme_name]["by_source"]:
                    themes_out[theme_name]["by_source"][src] += 1
                else:
                    # ensure all by_source keys exist even if missing; default to count but keep keys uniform later
                    themes_out[theme_name]["by_source"][src] = 1

    # Ensure by_source has all required keys
    for theme_name in themes_out.keys():
        for src in ["fan_email", "podcast_snippet", "locker_room_story"]:
            if src not in themes_out[theme_name]["by_source"]:
                themes_out[theme_name]["by_source"][src] = 0

    return {
        "num_anecdotes": num_anecdotes,
        "count_by_lang": count_by_lang,
        "themes": themes_out,
    }


def _find_script(workspace: Path) -> Optional[Path]:
    for ext in ("py", "js", "sh"):
        p = workspace / "scripts" / f"process_pack.{ext}"
        if p.exists():
            return p
    return None


def _parse_article_blockquotes(text: str) -> List[str]:
    """
    Return list of blockquote lines content (without leading '> '), preserving exact text.
    """
    lines = text.splitlines()
    quotes = []
    for ln in lines:
        if ln.startswith("> "):
            quotes.append(ln[2:])
    return quotes


def _find_additional_quotes_index(lines: List[str]) -> int:
    """
    Finds the index of a heading or line titled 'Additional quotes' (case-insensitive).
    Accept lines with optional heading markers '#'.
    Returns index of the line, or -1.
    """
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped.lower() == "additional quotes":
            return i
        if stripped.startswith("#"):
            # strip heading markers
            s = stripped.lstrip("#").strip()
            if s.lower() == "additional quotes":
                return i
    return -1


def _normalize_bool_str(v: str) -> str:
    if isinstance(v, str):
        return v.strip().lower()
    return ""


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present": 0.0,
        "translations_csv_structure": 0.0,
        "translations_alignment_with_input": 0.0,
        "translations_english_text_rules": 0.0,
        "translations_in_article_flags_consistency": 0.0,
        "article_ready_placeholders_replaced": 0.0,
        "article_ready_blockquotes_and_section": 0.0,
        "glossary_csv_correctness": 0.0,
        "theme_stats_json_correctness": 0.0,
        "editor_update_consistency": 0.0,
    }

    # Locate files
    script_path = _find_script(workspace)
    if script_path is not None and script_path.exists():
        scores["script_present"] = 1.0

    input_anecdotes_path = workspace / "input" / "anecdotes.csv"
    input_glossary_seed_path = workspace / "input" / "glossary_seed.csv"
    input_themes_yaml_path = workspace / "input" / "themes.yaml"
    input_draft_article_path = workspace / "input" / "draft_article.md"

    output_translations_path = workspace / "output" / "translations.csv"
    output_glossary_path = workspace / "output" / "glossary.csv"
    output_theme_stats_path = workspace / "output" / "theme_stats.json"
    output_article_ready_path = workspace / "output" / "article_ready.md"
    output_editor_update_path = workspace / "output" / "editor_update.md"

    # Load inputs
    anecdotes_rows = _read_csv_dicts(input_anecdotes_path) or []
    glossary_seed = _read_csv_dicts(input_glossary_seed_path) or []
    themes_yaml = _parse_simple_yaml_themes(input_themes_yaml_path)

    # Prepare expected mappings for input alignment checks
    input_by_id = {r.get("id"): r for r in anecdotes_rows if r.get("id")}

    # Validate translations.csv structure
    translations_rows = _read_csv_dicts(output_translations_path)
    if translations_rows is not None:
        # Check header order
        try:
            with output_translations_path.open("r", encoding="utf-8", newline="") as f:
                first_line = f.readline().strip()
        except Exception:
            first_line = ""
        expected_header = "id,source_lang,source,source_text,english_text,in_article"
        if first_line == expected_header:
            # Also ensure there is a row per input id
            ids_out = [r.get("id") for r in translations_rows if "id" in r]
            ids_in = [r.get("id") for r in anecdotes_rows if "id" in r]
            if ids_in and sorted(ids_in) == sorted(ids_out):
                scores["translations_csv_structure"] = 1.0

    # Validate alignment with input (language/source/text)
    if translations_rows is not None and input_by_id:
        ok = True
        for r in translations_rows:
            id_ = r.get("id")
            if not id_ or id_ not in input_by_id:
                ok = False
                break
            in_row = input_by_id[id_]
            # Check alignment
            if r.get("source_lang") != in_row.get("lang"):
                ok = False
            if r.get("source") != in_row.get("source"):
                ok = False
            if r.get("source_text") != in_row.get("text"):
                ok = False
        if ok:
            scores["translations_alignment_with_input"] = 1.0

    # Validate english_text rules
    if translations_rows is not None and input_by_id:
        ok = True
        for r in translations_rows:
            id_ = r.get("id")
            if not id_ or id_ not in input_by_id:
                ok = False
                break
            lang = input_by_id[id_].get("lang")
            src_text = input_by_id[id_].get("text", "")
            eng = r.get("english_text", "")
            if lang == "en":
                if eng != src_text:
                    ok = False
                    break
            elif lang == "es":
                if not isinstance(eng, str) or not eng.startswith("[tr.] "):
                    ok = False
                    break
            else:
                # unexpected lang, fail
                ok = False
                break
        if ok:
            scores["translations_english_text_rules"] = 1.0

    # Validate article_ready contents and in_article flags
    article_ready_text = _read_text(output_article_ready_path)
    if article_ready_text is not None:
        # Check placeholders removed
        if "[QUOTE:" not in article_ready_text:
            scores["article_ready_placeholders_replaced"] = 1.0

        # Check blockquotes and Additional quotes section
        quotes_list = _parse_article_blockquotes(article_ready_text)
        lines = article_ready_text.splitlines()
        add_idx = _find_additional_quotes_index(lines)

        # If translations exist, verify that english_texts appear as blockquotes
        if translations_rows is not None:
            # Create mapping id -> english_text
            id_to_eng = {r.get("id"): r.get("english_text", "") for r in translations_rows}
            # All english_texts should appear as blockquotes
            appear_ok = True
            for id_, eng in id_to_eng.items():
                if eng not in quotes_list:
                    appear_ok = False
                    break

            # Additional quotes section with Q02 and Q04 after the section title
            add_ok = False
            if add_idx >= 0:
                after = lines[add_idx + 1 :]
                after_quotes = [ln[2:] for ln in after if ln.startswith("> ")]
                q02 = id_to_eng.get("Q02", None)
                q04 = id_to_eng.get("Q04", None)
                if q02 and q04 and (q02 in after_quotes) and (q04 in after_quotes):
                    add_ok = True

            if appear_ok and add_ok:
                scores["article_ready_blockquotes_and_section"] = 1.0

        # Validate in_article flags consistency with article: flag true for ids that will appear in article
        if translations_rows is not None:
            id_to_eng = {r.get("id"): r.get("english_text", "") for r in translations_rows}
            id_to_flag = {r.get("id"): _normalize_bool_str(r.get("in_article", "")) for r in translations_rows}
            # Determine presence by english_text appearing as a blockquote
            id_present = {}
            for id_, eng in id_to_eng.items():
                id_present[id_] = eng in quotes_list
            # All that appear should have in_article true, and those not appearing false
            # Based on task, all 5 should appear; but grade generically
            flags_ok = True
            for id_, present in id_present.items():
                flag = id_to_flag.get(id_, "")
                if present and flag != "true":
                    flags_ok = False
                    break
                if (not present) and flag == "true":
                    flags_ok = False
                    break
            if flags_ok:
                scores["translations_in_article_flags_consistency"] = 1.0

    # Validate glossary.csv correctness
    glossary_rows = _read_csv_dicts(output_glossary_path)
    if glossary_rows is not None and anecdotes_rows and glossary_seed:
        # Validate header
        try:
            with output_glossary_path.open("r", encoding="utf-8", newline="") as f:
                header_line = f.readline().strip()
        except Exception:
            header_line = ""
        expected_header = "spanish,english,count,ids"
        header_ok = header_line == expected_header
        # Compute expected counts
        expected_counts = _compute_glossary_counts(anecdotes_rows, glossary_seed)
        # Check each seed term present with correct mapping and values
        map_out = {r.get("spanish"): r for r in glossary_rows if r.get("spanish")}
        all_ok = header_ok
        if all_ok:
            for seed in glossary_seed:
                sp = seed.get("spanish")
                en = seed.get("english")
                if sp not in map_out:
                    all_ok = False
                    break
                out_row = map_out[sp]
                exp = expected_counts.get(sp, None)
                if exp is None:
                    all_ok = False
                    break
                # english
                if out_row.get("english") != en:
                    all_ok = False
                    break
                # count
                try:
                    out_count = int(out_row.get("count", ""))
                except Exception:
                    all_ok = False
                    break
                if out_count != exp["count"]:
                    all_ok = False
                    break
                # ids: semicolon-separated sorted lexicographically
                out_ids = out_row.get("ids", "")
                exp_ids = ";".join(exp["ids"])
                if out_ids != exp_ids:
                    all_ok = False
                    break
        if all_ok:
            scores["glossary_csv_correctness"] = 1.0

    # Validate theme_stats.json correctness
    theme_stats = _load_json(output_theme_stats_path)
    if theme_stats is not None and anecdotes_rows and themes_yaml is not None:
        expected_stats = _compute_theme_stats(anecdotes_rows, themes_yaml)
        ok = True
        # Check structure keys
        for key in ["num_anecdotes", "count_by_lang", "themes"]:
            if key not in theme_stats:
                ok = False
        # Compare num_anecdotes and count_by_lang
        if ok:
            if theme_stats.get("num_anecdotes") != expected_stats.get("num_anecdotes"):
                ok = False
            cb = theme_stats.get("count_by_lang", {})
            exp_cb = expected_stats.get("count_by_lang", {})
            if not isinstance(cb, dict) or cb.get("es") != exp_cb.get("es") or cb.get("en") != exp_cb.get("en"):
                ok = False
        # Compare themes structure: all required themes present and with correct overall and by_source counts
        if ok:
            out_themes = theme_stats.get("themes", {})
            exp_themes = expected_stats.get("themes", {})
            # The task lists exact themes keys; ensure all present and match
            required_theme_keys = set(exp_themes.keys())
            if set(out_themes.keys()) != required_theme_keys:
                ok = False
            else:
                for t in required_theme_keys:
                    out_t = out_themes.get(t, {})
                    exp_t = exp_themes.get(t, {})
                    if out_t.get("overall") != exp_t.get("overall"):
                        ok = False
                        break
                    out_by = out_t.get("by_source", {})
                    exp_by = exp_t.get("by_source", {})
                    for src in ["fan_email", "podcast_snippet", "locker_room_story"]:
                        if out_by.get(src) != exp_by.get(src):
                            ok = False
                            break
                    if not ok:
                        break
        if ok:
            scores["theme_stats_json_correctness"] = 1.0

    # Validate editor_update.md consistency
    editor_text = _read_text(output_editor_update_path)
    if editor_text is not None and theme_stats is not None and glossary_rows is not None:
        # Parse bullet lines
        lines = editor_text.splitlines()
        bullet_lines = [ln.strip() for ln in lines if ln.strip().startswith(("-", "*"))]

        # Helper to find bullet containing keywords
        def find_bullet(predicate) -> Optional[str]:
            for b in bullet_lines:
                if predicate(b):
                    return b
            return None

        # total anecdotes processed
        total_expected = theme_stats.get("num_anecdotes")
        total_ok = False
        if isinstance(total_expected, int):
            b = find_bullet(lambda s: ("total" in s.lower() and "anecdote" in s.lower()))
            if b:
                nums = re.findall(r"\d+", b)
                if nums:
                    if int(nums[0]) == total_expected:
                        total_ok = True

        # number translated (es) -> equals count_by_lang['es']
        es_expected = theme_stats.get("count_by_lang", {}).get("es", None)
        es_ok = False
        if isinstance(es_expected, int):
            b = find_bullet(lambda s: ("translat" in s.lower()) or ("es" in s.lower()))
            if b:
                nums = re.findall(r"\d+", b)
                # pick first number, expect equal to es_expected
                if nums:
                    if int(nums[0]) == es_expected:
                        es_ok = True

        # count_by_lang map bullet - look for "es: 3" and "en: 2"
        cbl_ok = False
        b = find_bullet(lambda s: ("es" in s.lower() and "en" in s.lower()))
        if b:
            m_es = re.search(r"es\s*[:=]\s*(\d+)", b, flags=re.IGNORECASE)
            m_en = re.search(r"en\s*[:=]\s*(\d+)", b, flags=re.IGNORECASE)
            if m_es and m_en:
                try:
                    v_es = int(m_es.group(1))
                    v_en = int(m_en.group(1))
                    if v_es == theme_stats.get("count_by_lang", {}).get("es") and v_en == theme_stats.get("count_by_lang", {}).get("en"):
                        cbl_ok = True
                except Exception:
                    cbl_ok = False

        # top theme by overall count (and its count) - allow any of the themes tied for max with correct count
        themes_info = theme_stats.get("themes", {})
        max_count = None
        top_themes = []
        for tname, tdata in themes_info.items():
            try:
                c = int(tdata.get("overall"))
            except Exception:
                continue
            if max_count is None or c > max_count:
                max_count = c
                top_themes = [tname]
            elif c == max_count:
                top_themes.append(tname)
        top_ok = False
        if max_count is not None:
            # look for a bullet mentioning one of top_themes and the max_count number
            found = False
            for b in bullet_lines:
                for t in top_themes:
                    if t in b:
                        nums = re.findall(r"\d+", b)
                        if str(max_count) in nums or (nums and int(nums[0]) == max_count):
                            found = True
                            break
                if found:
                    break
            top_ok = found

        # glossary compact list: ensure each "spanish:count" pair appears somewhere in the file
        glossary_ok = False
        # Build mapping from glossary_rows
        try:
            gl_map = {r.get("spanish"): int(r.get("count", "0")) for r in glossary_rows if r.get("spanish") is not None}
        except Exception:
            gl_map = {}
        if gl_map:
            all_present = True
            for sp, cnt in gl_map.items():
                pair = f"{sp}:{cnt}"
                if pair not in editor_text:
                    all_present = False
                    break
            glossary_ok = all_present

        # 2–3 sentences in first person, in my voice (The Turnbuckle Poet)
        # Check presence of "I" and "The Turnbuckle Poet" and at least 2 sentences.
        voice_ok = False
        sentences = re.split(r"[.!?]\s+", editor_text.strip())
        sentence_count = len([s for s in sentences if s.strip()])
        if ("the turnbuckle poet" in editor_text.lower()) and (" i " in editor_text.lower() or editor_text.strip().startswith("I")) and (2 <= sentence_count <= 6):
            voice_ok = True

        if total_ok and es_ok and cbl_ok and top_ok and glossary_ok and voice_ok:
            scores["editor_update_consistency"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    # We don't use transcript-based checks; provide empty transcript list
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()