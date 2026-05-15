import sys
import json
import csv
import re
from pathlib import Path
from typing import List, Tuple, Dict, Optional


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path) -> Optional[object]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def parse_simple_yaml(yaml_text: str) -> Optional[Dict[str, object]]:
    result: Dict[str, object] = {}
    lines = yaml_text.splitlines()
    for line in lines:
        if not line.strip():
            continue
        if line.strip().startswith("#"):
            continue
        if ":" not in line:
            return None
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if not key:
            return None
        if val == "":
            result[key] = ""
            continue
        low = val.lower()
        if low == "true":
            result[key] = True
            continue
        if low == "false":
            result[key] = False
            continue
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            if inner == "":
                result[key] = []
            else:
                parts = [p.strip() for p in inner.split(",")]
                cleaned = []
                for p in parts:
                    if (p.startswith("'") and p.endswith("'")) or (p.startswith('"') and p.endswith('"')):
                        p = p[1:-1]
                    cleaned.append(p)
                result[key] = cleaned
            continue
        if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
            result[key] = val[1:-1]
        else:
            result[key] = val
    return result


def parse_markdown_with_front_matter(text: str) -> Optional[Dict[str, object]]:
    if text is None:
        return None
    if not text.startswith("---"):
        return None
    lines = text.splitlines(keepends=True)
    if len(lines) == 0:
        return None
    if not lines[0].strip() == "---":
        return None
    fm_lines = []
    end_index = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_index = i
            break
        fm_lines.append(lines[i])
    if end_index is None:
        return None
    fm_text = "".join(fm_lines)
    front = parse_simple_yaml(fm_text)
    if front is None:
        return None
    body = "".join(lines[end_index + 1 :])
    return {"front_matter": front, "body": body}


def find_code_spans(text: str) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    lines = text.splitlines(keepends=True)
    pos = 0
    in_code = False
    start = 0
    for line in lines:
        stripped = line.lstrip()
        if not in_code:
            if stripped.startswith("```"):
                in_code = True
                start = pos
        else:
            if stripped.startswith("```"):
                end = pos + len(line)
                spans.append((start, end))
                in_code = False
        pos += len(line)
    if in_code:
        spans.append((start, pos))
    return spans


def pos_in_spans(pos: int, spans: List[Tuple[int, int]]) -> bool:
    for s, e in spans:
        if s <= pos < e:
            return True
    return False


def find_math_spans(text: str, exclude_spans: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        if pos_in_spans(i, exclude_spans):
            for s, e in exclude_spans:
                if s <= i < e:
                    i = e
                    break
            continue
        ch = text[i]
        if ch == "$":
            if i + 1 < n and text[i + 1] == "$":
                j = i + 2
                while True:
                    k = text.find("$$", j)
                    if k == -1:
                        i += 2
                        break
                    if not pos_in_spans(k, exclude_spans):
                        spans.append((i, k + 2))
                        i = k + 2
                        break
                    else:
                        j = k + 2
                continue
            else:
                j = i + 1
                while True:
                    k = text.find("$", j)
                    if k == -1:
                        i += 1
                        break
                    if not pos_in_spans(k, exclude_spans):
                        spans.append((i, k + 1))
                        i = k + 1
                        break
                    else:
                        j = k + 1
                continue
        i += 1
    return spans


def extract_segments(text: str) -> Dict[str, object]:
    code_spans = find_code_spans(text)
    math_spans = find_math_spans(text, code_spans)
    code_blocks = [text[s:e] for s, e in code_spans]
    math_texts = [text[s:e] for s, e in math_spans]
    excluded = sorted(code_spans + math_spans, key=lambda x: x[0])
    prose_parts: List[str] = []
    cursor = 0
    for s, e in excluded:
        if cursor < s:
            prose_parts.append(text[cursor:s])
        cursor = max(cursor, e)
    if cursor < len(text):
        prose_parts.append(text[cursor:])
    prose_text = "".join(prose_parts)
    return {
        "code_spans": code_spans,
        "math_spans": math_spans,
        "code_blocks": code_blocks,
        "math_texts": math_texts,
        "prose_text": prose_text,
    }


def word_count(text: str) -> int:
    tokens = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", text, flags=re.UNICODE)
    return len(tokens)


def load_glossary(glossary_path: Path) -> Optional[List[Tuple[str, str]]]:
    rows = load_csv_dicts(glossary_path)
    if rows is None:
        return None
    pairs: List[Tuple[str, str]] = []
    for r in rows:
        if "english" not in r or "spanish" not in r:
            return None
        eng = (r["english"] or "").strip()
        spa = (r["spanish"] or "").strip()
        if eng == "" or spa == "":
            continue
        pairs.append((eng, spa))
    return pairs


def count_term_occurrences(text: str, term: str) -> int:
    pattern = r"(?i)(?<!\w)" + re.escape(term) + r"(?!\w)"
    return len(re.findall(pattern, text))


def safe_int(x) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "settings_target_languages_es": 0.0,
        "settings_preserve_math_true": 0.0,
        "settings_other_fields_unchanged": 0.0,
        "translated_files_exist": 0.0,
        "front_matter_preserved_and_augmented": 0.0,
        "math_segments_preserved": 0.0,
        "code_blocks_preserved": 0.0,
        "index_json_exists_and_structure": 0.0,
        "index_metadata_matches_source": 0.0,
        "index_counts_correct": 0.0,
        "glossary_coverage_exists_and_header": 0.0,
        "glossary_coverage_rows_correct": 0.0,
        "manifest_exists_and_structure": 0.0,
        "manifest_metrics_correct": 0.0,
    }

    settings_path = workspace / "input" / "settings.yaml"
    settings_text = read_text(settings_path)
    settings = None
    if settings_text is not None:
        settings = parse_simple_yaml(settings_text)

    if settings is not None:
        tl = settings.get("target_languages")
        tl_ok = isinstance(tl, list) and len(tl) == 1 and tl[0] == "es"
        if tl_ok:
            scores["settings_target_languages_es"] = 1.0
        preserve_ok = settings.get("preserve_math") is True
        if preserve_ok:
            scores["settings_preserve_math_true"] = 1.0
        original_unchanged = True
        expected_original = {
            "project_name": "Math-in-Science Notes",
            "source_dir": "input/notes",
            "output_dir": "output",
            "glossary_csv": "input/glossary.csv",
        }
        for k, v in expected_original.items():
            if settings.get(k) != v:
                original_unchanged = False
                break
        if tl_ok and preserve_ok and original_unchanged:
            scores["settings_other_fields_unchanged"] = 1.0

    notes_dir = workspace / "input" / "notes"
    input_notes = []
    if notes_dir.exists():
        for p in sorted(notes_dir.glob("*.md")):
            input_notes.append(p)

    out_es_dir = workspace / "output" / "es"
    expected_out_files = [out_es_dir / p.name for p in input_notes]
    if expected_out_files:
        exist_count = sum(1 for p in expected_out_files if p.exists())
        scores["translated_files_exist"] = exist_count / max(1, len(expected_out_files))

    fm_ok_count = 0
    math_ok_count = 0
    code_ok_count = 0

    index_path = workspace / "output" / "index.json"
    index_data = load_json(index_path)
    index_valid_structure = False
    index_items_by_file: Dict[str, dict] = {}

    if isinstance(index_data, list):
        ok_shape = True
        for item in index_data:
            if not isinstance(item, dict):
                ok_shape = False
                break
            required_keys = [
                "file",
                "title",
                "field",
                "math_topics",
                "keywords",
                "equation_count",
                "word_count_en",
                "word_count_es",
            ]
            for k in required_keys:
                if k not in item:
                    ok_shape = False
                    break
            if not ok_shape:
                break
            if not isinstance(item.get("math_topics"), list) or not isinstance(item.get("keywords"), list):
                ok_shape = False
                break
            if not isinstance(item.get("file"), str):
                ok_shape = False
                break
            index_items_by_file[item["file"]] = item
        if ok_shape and len(index_items_by_file) == len(input_notes):
            index_valid_structure = True
            scores["index_json_exists_and_structure"] = 1.0

    glossary_path = workspace / "input" / "glossary.csv"
    glossary_pairs = load_glossary(glossary_path)

    expected_coverage_rows: List[Dict[str, object]] = []
    index_meta_match_count = 0
    index_counts_match_count = 0

    for src_path in input_notes:
        src_text = read_text(src_path)
        parsed_src = parse_markdown_with_front_matter(src_text or "")
        out_path = out_es_dir / src_path.name
        out_text = read_text(out_path) if out_path.exists() else None
        parsed_out = parse_markdown_with_front_matter(out_text or "") if out_text is not None else None

        fm_ok = False
        if parsed_src and parsed_out:
            src_fm = parsed_src["front_matter"]
            out_fm = parsed_out["front_matter"]
            if isinstance(src_fm, dict) and isinstance(out_fm, dict):
                same = True
                for k, v in src_fm.items():
                    if k not in out_fm:
                        same = False
                        break
                    if isinstance(v, list):
                        if not isinstance(out_fm.get(k), list) or out_fm.get(k) != v:
                            same = False
                            break
                    else:
                        if out_fm.get(k) != v:
                            same = False
                            break
                if same and out_fm.get("lang") == "es" and out_fm.get("translated_from") == "en":
                    fm_ok = True
        if fm_ok:
            fm_ok_count += 1

        m_ok = False
        c_ok = False
        if parsed_src and parsed_out:
            src_body = parsed_src["body"]
            out_body = parsed_out["body"]
            src_segments = extract_segments(src_body)
            out_segments = extract_segments(out_body)
            if src_segments["math_texts"] == out_segments["math_texts"]:
                m_ok = True
            if src_segments["code_blocks"] == out_segments["code_blocks"]:
                c_ok = True

            if glossary_pairs is not None:
                file_rel = str(src_path.relative_to(workspace))
                src_prose = src_segments["prose_text"]
                out_prose = out_segments["prose_text"]
                for eng, spa in glossary_pairs:
                    cnt_src = count_term_occurrences(src_prose, eng)
                    if cnt_src > 0:
                        cnt_out = count_term_occurrences(out_prose, spa)
                        expected_coverage_rows.append(
                            {
                                "file": file_rel,
                                "english_term": eng,
                                "spanish_term": spa,
                                "count_in_source": cnt_src,
                                "count_in_translation": cnt_out,
                            }
                        )

            if index_valid_structure:
                file_key = str(src_path.relative_to(workspace))
                item = index_items_by_file.get(file_key)
                if item:
                    src_fm = parsed_src["front_matter"]
                    meta_ok = (
                        item.get("title") == src_fm.get("title")
                        and item.get("field") == src_fm.get("field")
                        and item.get("math_topics") == src_fm.get("math_topics")
                        and item.get("keywords") == src_fm.get("keywords")
                    )
                    if meta_ok:
                        index_meta_match_count += 1
                    eq_count = len(src_segments["math_texts"])
                    wc_en = word_count(src_segments["prose_text"])
                    wc_es = word_count(out_segments["prose_text"])
                    counts_ok = (
                        safe_int(item.get("equation_count")) == eq_count
                        and safe_int(item.get("word_count_en")) == wc_en
                        and safe_int(item.get("word_count_es")) == wc_es
                    )
                    if counts_ok:
                        index_counts_match_count += 1

        if m_ok:
            math_ok_count += 1
        if c_ok:
            code_ok_count += 1

    if len(input_notes) > 0:
        total_files = len(input_notes)
        scores["front_matter_preserved_and_augmented"] = fm_ok_count / total_files
        scores["math_segments_preserved"] = math_ok_count / total_files
        scores["code_blocks_preserved"] = code_ok_count / total_files

    if index_valid_structure and len(input_notes) > 0:
        total_files = len(input_notes)
        scores["index_metadata_matches_source"] = index_meta_match_count / total_files
        scores["index_counts_correct"] = index_counts_match_count / total_files

    coverage_path = workspace / "output" / "glossary_coverage.csv"
    coverage_rows = None
    coverage_header_ok = False
    if coverage_path.exists():
        try:
            with coverage_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header == ["file", "english_term", "spanish_term", "count_in_source", "count_in_translation"]:
                    coverage_header_ok = True
        except Exception:
            coverage_header_ok = False
    if coverage_header_ok:
        scores["glossary_coverage_exists_and_header"] = 1.0
        coverage_rows = load_csv_dicts(coverage_path)

    if coverage_rows is not None and glossary_pairs is not None:
        expected_map: Dict[Tuple[str, str, str], Tuple[int, int]] = {}
        for row in expected_coverage_rows:
            key = (row["file"], row["english_term"], row["spanish_term"])
            expected_map[key] = (int(row["count_in_source"]), int(row["count_in_translation"]))
        actual_map: Dict[Tuple[str, str, str], Tuple[Optional[int], Optional[int]]] = {}
        valid_rows = True
        for r in coverage_rows:
            try:
                key = (r["file"], r["english_term"], r["spanish_term"])
            except Exception:
                valid_rows = False
                break
            cis = safe_int(r.get("count_in_source"))
            cit = safe_int(r.get("count_in_translation"))
            if cis is None or cit is None:
                valid_rows = False
                break
            actual_map[key] = (cis, cit)
        if valid_rows and actual_map.keys() == expected_map.keys():
            counts_ok = True
            for k, (cis_expected, cit_expected) in expected_map.items():
                cis_actual, cit_actual = actual_map[k]
                if cis_actual != cis_expected:
                    counts_ok = False
                    break
                if cit_actual != cit_expected:
                    counts_ok = False
                    break
                if cit_actual != cis_actual:
                    counts_ok = False
                    break
            if counts_ok:
                scores["glossary_coverage_rows_correct"] = 1.0

    manifest_path = workspace / "output" / "manifest.json"
    manifest = load_json(manifest_path)
    manifest_structure_ok = False
    if isinstance(manifest, dict):
        required_keys = [
            "project_name",
            "languages_processed",
            "source_files",
            "total_equations",
            "glossary_terms_applied_total",
            "cli_invocation",
        ]
        types_ok = all(k in manifest for k in required_keys)
        if types_ok:
            if isinstance(manifest.get("project_name"), str) and \
               isinstance(manifest.get("languages_processed"), list) and \
               isinstance(manifest.get("source_files"), int) and \
               isinstance(manifest.get("total_equations"), int) and \
               isinstance(manifest.get("glossary_terms_applied_total"), int) and \
               isinstance(manifest.get("cli_invocation"), str):
                manifest_structure_ok = True
    if manifest_structure_ok:
        scores["manifest_exists_and_structure"] = 1.0

    if manifest_structure_ok:
        proj_ok = settings is not None and manifest.get("project_name") == settings.get("project_name")
        langs = manifest.get("languages_processed")
        langs_ok = isinstance(langs, list) and len(langs) == 1 and langs[0] == "es"
        src_files_ok = manifest.get("source_files") == len(input_notes)
        total_eq_expected = 0
        for src_path in input_notes:
            src_text = read_text(src_path)
            parsed_src = parse_markdown_with_front_matter(src_text or "")
            if parsed_src:
                segs = extract_segments(parsed_src["body"])
                total_eq_expected += len(segs["math_texts"])
        total_eq_ok = manifest.get("total_equations") == total_eq_expected
        glossary_total_ok = False
        coverage_rows_for_manifest = load_csv_dicts(coverage_path) if coverage_path.exists() else None
        if coverage_rows_for_manifest is not None:
            try:
                sum_cit = 0
                for r in coverage_rows_for_manifest:
                    cit = safe_int(r.get("count_in_translation"))
                    if cit is None:
                        sum_cit = None  # type: ignore
                        break
                    sum_cit += cit
                glossary_total_ok = (sum_cit is not None) and (manifest.get("glossary_terms_applied_total") == sum_cit)  # type: ignore
            except Exception:
                glossary_total_ok = False
        cli_ok = isinstance(manifest.get("cli_invocation"), str) and len(manifest.get("cli_invocation")) > 0

        all_ok = all([proj_ok, langs_ok, src_files_ok, total_eq_ok, glossary_total_ok, cli_ok])
        scores["manifest_metrics_correct"] = 1.0 if all_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()