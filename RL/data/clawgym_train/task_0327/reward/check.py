import json
import csv
import re
import sys
import ast
import statistics
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_read_json(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if reader.fieldnames is None or len(reader.fieldnames) == 0:
                return None
            return rows
    except Exception:
        return None


def parse_stopwords(path: Path) -> Optional[Set[str]]:
    text = safe_read_text(path)
    if text is None:
        return None
    stop: Set[str] = set()
    try:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("|"):  # Snowball comment lines
                continue
            tokens = re.findall(r"[A-Za-z]+", line)
            for tok in tokens:
                stop.add(tok.lower())
        if len(stop) < 100:
            return None
        return stop
    except Exception:
        return None


def whitespace_tokens(text: str) -> List[str]:
    return text.split()


def letters_only_tokens_lower(text: str) -> List[str]:
    return [m.group(0).lower() for m in re.finditer(r"[A-Za-z]+", text)]


def compute_word_count(text: str) -> int:
    return len(whitespace_tokens(text))


def compute_unique_word_count_case_insensitive(text: str) -> int:
    toks = whitespace_tokens(text)
    return len({t.lower() for t in toks})


def compute_sentence_count(text: str) -> int:
    parts = re.split(r"[.!?]", text)
    return sum(1 for p in parts if p.strip() != "")


def compute_avg_sentence_length(word_count: int, sentence_count: int) -> float:
    if sentence_count == 0:
        return 0.0
    return float(word_count) / float(sentence_count)


def top_k_nonstopwords(text: str, stopwords: Set[str], k: int) -> List[str]:
    toks = letters_only_tokens_lower(text)
    filtered = [t for t in toks if t not in stopwords]
    freq: Dict[str, int] = {}
    for t in filtered:
        freq[t] = freq.get(t, 0) + 1
    sorted_items = sorted(freq.items(), key=lambda x: (-x[1], x[0]))
    return [w for w, c in sorted_items[:k]]


def recompute_per_story_metrics(data_rows: List[Dict[str, str]], stopwords: Set[str]) -> Dict[str, Dict[str, object]]:
    result: Dict[str, Dict[str, object]] = {}
    for row in data_rows:
        sid = str(row.get("id", "")).strip()
        title = row.get("title", "")
        text = row.get("text", "")
        wc = compute_word_count(text)
        uwc = compute_unique_word_count_case_insensitive(text)
        sc = compute_sentence_count(text)
        avg_len = compute_avg_sentence_length(wc, sc)
        top5 = top_k_nonstopwords(text, stopwords, 5)
        result[sid] = {
            "id": sid,
            "title": title,
            "word_count": wc,
            "unique_word_count": uwc,
            "sentence_count": sc,
            "avg_sentence_length_words": avg_len,
            "top_5_nonstopwords": top5,
        }
    return result


def recompute_corpus_summary(per_story: Dict[str, Dict[str, object]], stopwords: Set[str], data_rows: List[Dict[str, str]]) -> Dict[str, object]:
    total_stories = len(per_story)
    word_counts = [int(per_story[sid]["word_count"]) for sid in per_story]
    total_words = sum(word_counts)
    mean_wc = (float(total_words) / float(total_stories)) if total_stories > 0 else 0.0
    median_wc = statistics.median([int(x) for x in word_counts]) if total_stories > 0 else 0.0
    all_tokens: Set[str] = set()
    for row in data_rows:
        text = row.get("text", "")
        for t in whitespace_tokens(text):
            all_tokens.add(t.lower())
    vocabulary_size = len(all_tokens)
    all_letters: List[str] = []
    for row in data_rows:
        all_letters.extend(letters_only_tokens_lower(row.get("text", "")))
    filtered = [t for t in all_letters if t not in stopwords]
    freq: Dict[str, int] = {}
    for t in filtered:
        freq[t] = freq.get(t, 0) + 1
    overall_sorted = sorted(freq.items(), key=lambda x: (-x[1], x[0]))
    top10 = [w for w, c in overall_sorted[:10]]
    return {
        "total_stories": total_stories,
        "total_words": total_words,
        "mean_story_word_count": mean_wc,
        "median_story_word_count": median_wc,
        "vocabulary_size": vocabulary_size,
        "top_10_nonstopwords_overall": top10,
    }


def parse_word_counts_file(path: Path) -> Optional[Dict[str, Tuple[str, int]]]:
    text = safe_read_text(path)
    if text is None:
        return None
    result: Dict[str, Tuple[str, int]] = {}
    try:
        for line in text.splitlines():
            if not line.strip():
                continue
            m = re.match(r"^(\s*\d+)\s*,\s*(.+)\s*,\s*words\s*=\s*(\d+)\s*$", line)
            if not m:
                return None
            sid = str(int(m.group(1)))
            title = m.group(2)
            words = int(m.group(3))
            result[sid] = (title, words)
        return result
    except Exception:
        return None


def ast_has_functions_with_docstrings(py_text: str) -> Tuple[int, int]:
    try:
        tree = ast.parse(py_text)
    except Exception:
        return (0, 0)
    func_defs = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    count = len(func_defs)
    with_docs = 0
    for fn in func_defs:
        if fn.body and isinstance(fn.body[0], ast.Expr) and isinstance(getattr(fn.body[0], "value", None), ast.Constant) and isinstance(fn.body[0].value.value, str):
            with_docs += 1
    return (count, with_docs)


def check_cli_flags(py_text: str) -> Tuple[bool, bool, bool, bool]:
    uses_argparse = ("argparse" in py_text and "ArgumentParser" in py_text)
    has_input = ("--input" in py_text)
    has_stop = ("--stopwords" in py_text)
    has_outdir = ("--outdir" in py_text)
    return uses_argparse, has_input, has_stop, has_outdir


def check_cli_defaults(py_text: str) -> Tuple[bool, bool, bool]:
    input_ok = ("data/flash_fiction.csv" in py_text)
    stop_ok = ("resources/english_stopwords.txt" in py_text)
    outdir_ok = re.search(r"\boutput\b", py_text) is not None
    return input_ok, stop_ok, outdir_ok


def tolerant_float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "refactored_functions_and_docstrings": 0.0,
        "cli_arguments_present": 0.0,
        "cli_defaults_workspace_paths": 0.0,
        "stopwords_file_quality": 0.0,
        "provenance_metadata_quality": 0.0,
        "story_metrics_csv_fields_and_values": 0.0,
        "summary_json_values": 0.0,
        "word_counts_format_and_counts": 0.0,
        "consistency_check_values": 0.0,
        "readme_updated_with_usage_and_outputs": 0.0,
        "code_review_notes_present": 0.0,
        "cross_file_consistency": 0.0,
    }

    data_csv = workspace / "data" / "flash_fiction.csv"
    script_py = workspace / "scripts" / "analyze_flash.py"
    stopwords_txt = workspace / "resources" / "english_stopwords.txt"
    provenance_md = workspace / "output" / "PROVENANCE.md"
    story_metrics_csv = workspace / "output" / "story_metrics.csv"
    summary_json = workspace / "output" / "summary.json"
    word_counts_txt = workspace / "output" / "word_counts.txt"
    consistency_json = workspace / "output" / "consistency_check.json"
    readme_md = workspace / "README.md"
    code_review_md = workspace / "output" / "code_review.md"

    data_rows = safe_read_csv_dicts(data_csv)
    script_text = safe_read_text(script_py)
    stopwords_set = parse_stopwords(stopwords_txt)

    if script_text is not None:
        fn_count, fn_with_docs = ast_has_functions_with_docstrings(script_text)
        has_main_guard = "__name__" in script_text and "__main__" in script_text
        if fn_count >= 3 and fn_with_docs >= 1 and has_main_guard:
            scores["refactored_functions_and_docstrings"] = 1.0

    if script_text is not None:
        uses_argparse, has_input, has_stop, has_outdir = check_cli_flags(script_text)
        if uses_argparse and has_input and has_stop and has_outdir:
            scores["cli_arguments_present"] = 1.0

        input_ok, stop_ok, outdir_ok = check_cli_defaults(script_text)
        if input_ok and stop_ok and outdir_ok:
            scores["cli_defaults_workspace_paths"] = 1.0

    if stopwords_set is not None:
        sw_text = safe_read_text(stopwords_txt) or ""
        lines = [ln.strip() for ln in sw_text.splitlines() if ln.strip() and not ln.strip().startswith("|")]
        if len(lines) >= 100:
            alpha_lines = sum(1 for ln in lines if re.fullmatch(r"[A-Za-z]+", ln) is not None)
            ratio = alpha_lines / max(1, len(lines))
            if ratio >= 0.5:
                scores["stopwords_file_quality"] = 1.0

    prov_text = safe_read_text(provenance_md)
    if prov_text is not None:
        has_source = bool(re.search(r"\b(Snowball|NLTK)\b", prov_text, re.IGNORECASE))
        has_date = bool(re.search(r"\b\d{4}-\d{2}-\d{2}\b", prov_text))
        has_org = ("org" in prov_text.lower()) or bool(re.search(r"\bThe\s+Snowball\b", prov_text)) or bool(re.search(r"\bNatural\s+Language\s+Toolkit\b", prov_text, re.IGNORECASE))
        if has_source and has_date and has_org:
            scores["provenance_metadata_quality"] = 1.0

    per_story_expected: Optional[Dict[str, Dict[str, object]]] = None
    corpus_expected: Optional[Dict[str, object]] = None
    if data_rows is not None and stopwords_set is not None:
        per_story_expected = recompute_per_story_metrics(data_rows, stopwords_set)
        corpus_expected = recompute_corpus_summary(per_story_expected, stopwords_set, data_rows)

    if story_metrics_csv.exists() and per_story_expected is not None:
        rows = safe_read_csv_dicts(story_metrics_csv)
        if rows is not None:
            required_cols = {"id", "title", "word_count", "unique_word_count", "sentence_count", "avg_sentence_length_words", "top_5_nonstopwords"}
            header_ok = required_cols.issubset(set(rows[0].keys())) if rows else False
            match_all = header_ok and len(rows) == len(per_story_expected)
            if header_ok:
                seen_ids = set()
                for r in rows:
                    sid = str(r.get("id", "")).strip()
                    if sid not in per_story_expected:
                        match_all = False
                        break
                    seen_ids.add(sid)
                    exp = per_story_expected[sid]
                    title_ok = str(r.get("title", "")) == str(exp["title"])
                    try:
                        wc_ok = int(r.get("word_count", -1)) == int(exp["word_count"])
                        uwc_ok = int(r.get("unique_word_count", -1)) == int(exp["unique_word_count"])
                        sc_ok = int(r.get("sentence_count", -1)) == int(exp["sentence_count"])
                        avg_val = float(r.get("avg_sentence_length_words", "nan"))
                        avg_ok = tolerant_float_equal(avg_val, float(exp["avg_sentence_length_words"]))
                        top_str = str(r.get("top_5_nonstopwords", ""))
                        top_list_out = [t for t in top_str.split(" ") if t != ""]
                        top_ok = top_list_out == list(exp["top_5_nonstopwords"])
                    except Exception:
                        match_all = False
                        break
                    if not (title_ok and wc_ok and uwc_ok and sc_ok and avg_ok and top_ok):
                        match_all = False
                        break
                if match_all and len(seen_ids) == len(per_story_expected):
                    scores["story_metrics_csv_fields_and_values"] = 1.0

    if summary_json.exists() and corpus_expected is not None:
        sj = safe_read_json(summary_json)
        if isinstance(sj, dict):
            try:
                fields_ok = all(k in sj for k in [
                    "total_stories",
                    "total_words",
                    "mean_story_word_count",
                    "median_story_word_count",
                    "vocabulary_size",
                    "top_10_nonstopwords_overall",
                ])
                if fields_ok:
                    ts_ok = int(sj["total_stories"]) == int(corpus_expected["total_stories"])
                    tw_ok = int(sj["total_words"]) == int(corpus_expected["total_words"])
                    mean_ok = tolerant_float_equal(float(sj["mean_story_word_count"]), float(corpus_expected["mean_story_word_count"]))
                    median_ok = tolerant_float_equal(float(sj["median_story_word_count"]), float(corpus_expected["median_story_word_count"]))
                    vs_ok = int(sj["vocabulary_size"]) == int(corpus_expected["vocabulary_size"])
                    top_ok = list(sj["top_10_nonstopwords_overall"]) == list(corpus_expected["top_10_nonstopwords_overall"])
                    if ts_ok and tw_ok and mean_ok and median_ok and vs_ok and top_ok:
                        scores["summary_json_values"] = 1.0
            except Exception:
                pass

    if word_counts_txt.exists() and data_rows is not None:
        wc_map = parse_word_counts_file(word_counts_txt)
        if wc_map is not None and per_story_expected is not None:
            if len(wc_map) == len(data_rows):
                all_ok = True
                for row in data_rows:
                    sid = str(row.get("id", "")).strip()
                    title = row.get("title", "")
                    text = row.get("text", "")
                    if sid not in wc_map:
                        all_ok = False
                        break
                    title_out, words_out = wc_map[sid]
                    if title_out != title:
                        all_ok = False
                        break
                    expected_wc = compute_word_count(text)
                    if words_out != expected_wc:
                        all_ok = False
                        break
                if all_ok:
                    scores["word_counts_format_and_counts"] = 1.0

    if consistency_json.exists() and story_metrics_csv.exists() and word_counts_txt.exists():
        wc_map = parse_word_counts_file(word_counts_txt)
        sm_rows = safe_read_csv_dicts(story_metrics_csv)
        cj = safe_read_json(consistency_json)
        if wc_map is not None and sm_rows is not None and isinstance(cj, dict):
            try:
                sm_wc_by_id = {}
                for r in sm_rows:
                    sid = str(r.get("id", "")).strip()
                    try:
                        sm_wc_by_id[sid] = int(r.get("word_count", -1))
                    except Exception:
                        sm_wc_by_id[sid] = -1
                ids = set(wc_map.keys()).intersection(set(sm_wc_by_id.keys()))
                mismatched_ids = sorted([sid for sid in ids if wc_map[sid][1] != sm_wc_by_id[sid]], key=lambda x: int(x))
                matching = len(ids) - len(mismatched_ids)
                expected_cj = {
                    "total_stories": len(ids),
                    "matching_word_counts": matching,
                    "mismatching_word_counts": len(mismatched_ids),
                    "mismatched_ids": [str(i) for i in mismatched_ids],
                }
                fields_ok = all(k in cj for k in expected_cj.keys())
                values_ok = (
                    int(cj.get("total_stories", -1)) == expected_cj["total_stories"]
                    and int(cj.get("matching_word_counts", -1)) == expected_cj["matching_word_counts"]
                    and int(cj.get("mismatching_word_counts", -1)) == expected_cj["mismatching_word_counts"]
                    and [str(x) for x in cj.get("mismatched_ids", [])] == expected_cj["mismatched_ids"]
                )
                if fields_ok and values_ok:
                    scores["consistency_check_values"] = 1.0
                if len(mismatched_ids) == 0 and len(ids) > 0:
                    scores["cross_file_consistency"] = 1.0
            except Exception:
                pass

    readme_text = safe_read_text(readme_md)
    if readme_text is not None:
        has_cli = ("--input" in readme_text and "--stopwords" in readme_text and "--outdir" in readme_text)
        has_stopwords_doc = (("stopword" in readme_text.lower()) and (("Snowball" in readme_text) or ("NLTK" in readme_text) or ("resources/english_stopwords.txt" in readme_text)))
        outputs_mentioned = all(p in readme_text for p in [
            "output/story_metrics.csv",
            "output/summary.json",
            "output/word_counts.txt",
            "output/consistency_check.json",
            "output/PROVENANCE.md",
        ])
        if has_cli and has_stopwords_doc and outputs_mentioned:
            scores["readme_updated_with_usage_and_outputs"] = 1.0

    review_text = safe_read_text(code_review_md)
    if review_text is not None:
        long_enough = len(review_text.strip()) >= 300
        mentions_problems = any(kw in review_text.lower() for kw in [
            "problem", "issue", "bug", "naming", "structure", "robust", "robustness", "error", "exception", "global state", "docstring", "validation"
        ])
        mentions_solutions = any(kw in review_text.lower() for kw in [
            "refactor", "fix", "address", "solution", "improve", "cli", "function", "utf-8", "deterministic", "ordering"
        ])
        if long_enough and mentions_problems and mentions_solutions:
            scores["code_review_notes_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()