import json
import csv
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def _read_text_safe(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return text, None
    except Exception as e:
        return None, f"read_error:{e}"


def _load_json_safe(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, dict):
            return None, "not_a_object"
        return data, None
    except Exception as e:
        return None, f"json_error:{e}"


def _load_csv_dicts_safe(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = [dict(r) for r in reader]
            return rows, None
    except Exception as e:
        return None, f"csv_error:{e}"


def _tokenize_words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z]+", text.lower())


def _count_keywords(text: str, keywords: List[str]) -> Dict[str, int]:
    tokens = _tokenize_words(text)
    counts: Dict[str, int] = {kw.lower(): 0 for kw in keywords}
    for t in tokens:
        if t in counts:
            counts[t] += 1
    return counts


def _first_n_nonempty_lines(text: str, n: int) -> List[str]:
    lines: List[str] = []
    for line in text.splitlines():
        if line.strip():
            lines.append(line)
            if len(lines) >= n:
                break
    return lines


def _has_heading_sections(md: str, required_sections: List[str]) -> bool:
    found = set()
    for line in md.splitlines():
        stripped = line.strip().lower()
        if not stripped:
            continue
        for sec in required_sections:
            sec_l = sec.lower()
            if stripped.startswith("#") and sec_l in stripped:
                found.add(sec_l)
            elif stripped == sec_l:
                found.add(sec_l)
    return all(sec.lower() in found for sec in required_sections)


def _contains_reproducibility_command(md: str) -> bool:
    # Require a concrete invocation reference to the orchestrator path
    return ("scripts/run.sh" in md) or ("bash scripts/run.sh" in md) or ("sh scripts/run.sh" in md)


def _no_direct_urls_in_text(text: str) -> bool:
    # Disallow direct URLs in docs/scripts
    return (("http://" not in text) and ("https://" not in text))


def _parse_token_counts_csv(path: Path) -> Tuple[Optional[List[Tuple[str, int]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            reader = csv.reader(fh)
            rows = list(reader)
        if not rows:
            return None, "empty_csv"
        header = rows[0]
        if header != ["token", "count"]:
            return None, "bad_header"
        data: List[Tuple[str, int]] = []
        for i, r in enumerate(rows[1:], start=2):
            if len(r) != 2:
                return None, f"row_{i}_bad_cols"
            tok = r[0]
            try:
                cnt = int(r[1])
            except Exception:
                return None, f"row_{i}_count_not_int"
            if cnt < 0:
                return None, f"row_{i}_count_negative"
            data.append((tok, cnt))
        return data, None
    except Exception as e:
        return None, f"csv_read_error:{e}"


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "architecture_doc_exists_and_sections": 0.0,
        "architecture_reproducibility_commands_present": 0.0,
        "error_handling_documented": 0.0,
        "no_direct_urls_in_docs_and_scripts": 0.0,
        "raw_page_html_present_and_plain_text_mention": 0.0,
        "raw_memoir_txt_present_and_nontrivial_length": 0.0,
        "orchestrator_script_present": 0.0,
        "summary_json_structure_valid": 0.0,
        "summary_title_author_from_preferred_set": 0.0,
        "summary_validation_title_author_match_correct": 0.0,
        "summary_keyword_counts_correct": 0.0,
        "token_counts_csv_structure_and_ordering": 0.0,
        "token_counts_excludes_common_stopwords": 0.0,
        "error_test_log_present_and_contains_error": 0.0,
        "summary_title_author_in_input_csv": 0.0,
        "docs_mentions_project_gutenberg": 0.0,
    }

    arch_md = workspace / "docs" / "architecture.md"
    page_html = workspace / "workspace" / "raw" / "page.html"
    memoir_txt = workspace / "workspace" / "raw" / "memoir.txt"
    summary_json = workspace / "workspace" / "summary.json"
    token_counts_csv = workspace / "workspace" / "token_counts.csv"
    error_log = workspace / "workspace" / "error_test.log"
    run_sh = workspace / "scripts" / "run.sh"
    input_csv = workspace / "input" / "memoirs.csv"
    input_keywords = workspace / "input" / "keywords.txt"

    # Architecture doc checks
    md_text, _ = _read_text_safe(arch_md)
    required_sections = ["Overview", "Components", "Data Flow", "Validation & Error Handling", "Reproducibility"]
    if md_text is not None:
        has_sections = _has_heading_sections(md_text, required_sections)
        if has_sections:
            scores["architecture_doc_exists_and_sections"] = 1.0
        if _contains_reproducibility_command(md_text):
            scores["architecture_reproducibility_commands_present"] = 1.0
        # Error handling documented: reference to the error log and error/failed terms
        if ("error_test.log" in md_text) or ("validation & error handling".lower() in md_text.lower() and re.search(r"\b(error|fail|failed|retry|exception)\b", md_text, flags=re.IGNORECASE)):
            scores["error_handling_documented"] = 1.0
        if "project gutenberg" in md_text.lower():
            scores["docs_mentions_project_gutenberg"] = 1.0

    # No direct URLs in docs and scripts: only evaluate if at least one artifact exists
    checked_any = False
    no_urls_violation = False
    if md_text is not None:
        checked_any = True
        if not _no_direct_urls_in_text(md_text):
            no_urls_violation = True
    scripts_dir = workspace / "scripts"
    if scripts_dir.exists() and scripts_dir.is_dir():
        for p in scripts_dir.rglob("*"):
            if p.is_file():
                checked_any = True
                t, _ = _read_text_safe(p)
                if t is not None and not _no_direct_urls_in_text(t):
                    no_urls_violation = True
                    break
    if checked_any and not no_urls_violation:
        scores["no_direct_urls_in_docs_and_scripts"] = 1.0

    # Raw page HTML must mention Plain Text and Project Gutenberg (landing page nature)
    page_text, _ = _read_text_safe(page_html)
    if page_text is not None:
        if re.search(r"plain\s*text", page_text, flags=re.IGNORECASE) and re.search(r"project\s+gutenberg", page_text, flags=re.IGNORECASE):
            scores["raw_page_html_present_and_plain_text_mention"] = 1.0

    # Memoir text presence and length
    memoir_text, _ = _read_text_safe(memoir_txt)
    if memoir_text is not None and len(memoir_text) >= 1000:
        scores["raw_memoir_txt_present_and_nontrivial_length"] = 1.0

    # Orchestrator script presence
    if run_sh.exists() and run_sh.is_file():
        scores["orchestrator_script_present"] = 1.0

    # Summary JSON checks
    summary, _ = _load_json_safe(summary_json)
    if summary is not None:
        required_keys = [
            "title",
            "author",
            "source",
            "total_words",
            "unique_words",
            "avg_sentence_length_words",
            "keyword_counts",
            "validation",
        ]
        has_keys = all(k in summary for k in required_keys)
        types_ok = True
        if has_keys:
            types_ok = (
                isinstance(summary["title"], str)
                and isinstance(summary["author"], str)
                and summary.get("source") == "Project Gutenberg"
                and isinstance(summary["total_words"], int)
                and isinstance(summary["unique_words"], int)
                and isinstance(summary["avg_sentence_length_words"], (int, float))
                and isinstance(summary["keyword_counts"], dict)
                and isinstance(summary["validation"], dict)
                and isinstance(summary["validation"].get("title_author_match", None), bool)
            )
            if types_ok:
                if not (summary["total_words"] >= summary["unique_words"] >= 0):
                    types_ok = False
                # avg sentence length should be positive numeric
                if not (summary["avg_sentence_length_words"] > 0):
                    types_ok = False
        if has_keys and types_ok:
            scores["summary_json_structure_valid"] = 1.0

    # Title/Author pair should be one of the preferred set
    preferred_pairs = [
        ("The Story of My Life", "Helen Keller"),
        ("Up From Slavery", "Booker T. Washington"),
    ]
    if summary is not None:
        t = summary.get("title")
        a = summary.get("author")
        if isinstance(t, str) and isinstance(a, str):
            if (t, a) in preferred_pairs:
                scores["summary_title_author_from_preferred_set"] = 1.0

    # Also verify title/author exists in input/memoirs.csv
    rows, _ = _load_csv_dicts_safe(input_csv)
    if summary is not None and rows is not None:
        t = summary.get("title")
        a = summary.get("author")
        if isinstance(t, str) and isinstance(a, str):
            in_csv = any((r.get("title") == t and r.get("author") == a) for r in rows)
            if in_csv:
                scores["summary_title_author_in_input_csv"] = 1.0

    # Validation check: compare reported with computed from first 100 non-empty lines
    if summary is not None and memoir_text is not None:
        t = summary.get("title")
        a = summary.get("author")
        if isinstance(t, str) and isinstance(a, str):
            first_lines = _first_n_nonempty_lines(memoir_text, 100)
            first_chunk = "\n".join(first_lines).lower()
            computed_match = (t.lower() in first_chunk) and (a.lower() in first_chunk)
            reported_match = summary.get("validation", {}).get("title_author_match")
            if isinstance(reported_match, bool) and (reported_match == computed_match):
                scores["summary_validation_title_author_match_correct"] = 1.0

    # Keywords counts correctness: recompute from memoir and input/keywords.txt
    keywords_list: List[str] = []
    kw_text, _ = _read_text_safe(input_keywords)
    if kw_text is not None:
        for line in kw_text.splitlines():
            s = line.strip()
            if s:
                keywords_list.append(s)
    if memoir_text is not None and summary is not None and isinstance(summary.get("keyword_counts"), dict) and keywords_list:
        computed_kw = _count_keywords(memoir_text, keywords_list)
        kc = summary.get("keyword_counts", {})
        kc_lower = {str(k).lower(): v for k, v in kc.items()}
        keys_match = set(kc_lower.keys()) == set(k.lower() for k in keywords_list)
        counts_match = keys_match and all(isinstance(kc_lower[k], int) and kc_lower[k] == computed_kw[k] for k in computed_kw.keys())
        if keys_match and counts_match:
            scores["summary_keyword_counts_correct"] = 1.0

    # Token counts CSV: structure and ordering and exactly top 50
    tokens_data, _ = _parse_token_counts_csv(token_counts_csv)
    if tokens_data is not None:
        length_ok = len(tokens_data) == 50  # exactly 50 as required
        ordering_ok = all(tokens_data[i][1] >= tokens_data[i + 1][1] for i in range(len(tokens_data) - 1))
        if length_ok and ordering_ok:
            scores["token_counts_csv_structure_and_ordering"] = 1.0
        # Stopwords exclusion
        common_stop = {
            "the", "and", "to", "of", "a", "in", "that", "is", "it", "for", "on", "with", "as", "at", "by", "from",
            "this", "be", "or", "an", "are", "was", "were", "but", "not", "have", "had", "has", "he", "she", "they",
            "you", "i", "we", "his", "her", "their", "them", "my", "our", "which", "who", "whom", "what", "when",
            "where", "why", "how", "into", "out", "up", "down", "over", "under", "so", "than", "then", "there", "here"
        }
        tokens_lower = [str(t[0]).strip().lower() for t in tokens_data]
        if not any(tok in common_stop for tok in tokens_lower):
            scores["token_counts_excludes_common_stopwords"] = 1.0

    # Error log presence and contains error-like content
    err_text, _ = _read_text_safe(error_log)
    if err_text is not None and err_text.strip():
        if re.search(r"\b(error|fail|failed|exception|not found|unable)\b", err_text, flags=re.IGNORECASE):
            scores["error_test_log_present_and_contains_error"] = 1.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()