import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def safe_load_csv_dicts(path: Path) -> Tuple[Optional[List[str]], List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = list(reader.fieldnames) if reader.fieldnames else None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None, []


def build_lexicon(lex_path: Path) -> Optional[List[Tuple[str, str, re.Pattern]]]:
    try:
        terms: List[Tuple[str, str, re.Pattern]] = []
        with lex_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                term = (row.get("term") or "").strip()
                cat = (row.get("category") or "").strip() or "unknown"
                if not term:
                    continue
                # Mirror the script's regex construction exactly
                pattern = re.compile(r"\\b" + re.escape(term) + r"\\b", re.IGNORECASE)
                terms.append((term, cat, pattern))
        return terms
    except Exception:
        return None


def scan_text_for_terms(text: str, lexicon: List[Tuple[str, str, re.Pattern]]) -> List[Tuple[int, str, str, str]]:
    """
    Returns list of (line_no, term, category, line_text) for matches in text,
    following the same logic as scripts/polarity_scan.py.
    """
    flags: List[Tuple[int, str, str, str]] = []
    for i, line in enumerate(text.splitlines(), start=1):
        for term, cat, pat in lexicon:
            try:
                if pat.search(line):
                    flags.append((i, term, cat, line.rstrip("\n")))
            except re.error:
                # Shouldn't happen; if it does, skip this term
                continue
    return flags


def scan_dir_for_flags(in_dir: Path, lex_path: Path) -> Optional[List[Tuple[str, int, str, str, str]]]:
    """
    Mimic scripts/polarity_scan.py scanning to derive expected flags.
    Returns list of (file, line_no, term, category, line_text).
    """
    lexicon = build_lexicon(lex_path)
    if lexicon is None:
        return None
    if not in_dir.is_dir():
        return None
    flags: List[Tuple[str, int, str, str, str]] = []
    # Mimic os.walk sorted traversal
    txt_files = sorted([p for p in in_dir.rglob("*.txt") if p.is_file()])
    for path in txt_files:
        text = safe_read_text(path)
        if text is None:
            continue
        file_flags = scan_text_for_terms(text, lexicon)
        for line_no, term, cat, line_text in file_flags:
            # Use POSIX-like path with forward slashes to match likely CSV entries
            flags.append((str(path.as_posix()), line_no, term, cat, line_text))
    return flags


def contains_no_flagged_terms(text: Optional[str], lexicon: Optional[List[Tuple[str, str, re.Pattern]]]) -> Optional[bool]:
    if text is None or lexicon is None:
        return None
    for _, _, pat in lexicon:
        try:
            if pat.search(text):
                return False
        except re.error:
            continue
    return True


def text_contains_all(text: Optional[str], tokens: List[str], case_insensitive: bool = True) -> Optional[bool]:
    if text is None:
        return None
    hay = text
    if case_insensitive:
        hay = hay.lower()
        toks = [t.lower() for t in tokens]
    else:
        toks = tokens
    for t in toks:
        if t not in hay:
            return False
    return True


def rewrites_json_to_list(obj: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        # Accept dict of objects keyed by input_path
        vals = []
        for v in obj.values():
            if isinstance(v, dict):
                vals.append(v)
        return vals if vals else None
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "run_log_initial_error": 0.0,
        "run_log_first_success": 0.0,
        "run_log_neutral_rescan": 0.0,
        "run_log_runs_in_order": 0.0,
        "flags_csv_header_and_rows": 0.0,
        "flags_csv_expected_counts": 0.0,
        "flags_csv_expected_terms": 0.0,
        "neutral_en_draft1_clean_and_present": 0.0,
        "neutral_en_draft2_clean_and_present": 0.0,
        "neutral_en_draft1_preserves_details": 0.0,
        "neutral_en_draft2_preserves_details": 0.0,
        "neutral_es_draft1_present_with_details": 0.0,
        "neutral_es_draft2_present_with_details": 0.0,
        "concise_en_draft1_length_and_clean": 0.0,
        "concise_en_draft2_length_and_clean": 0.0,
        "concise_en_draft1_preserves_details": 0.0,
        "concise_en_draft2_preserves_details": 0.0,
        "rewrites_json_valid": 0.0,
        "final_post_combined_order": 0.0,
        "neutral_rescan_csv_zero_flags": 0.0,
    }

    # Paths
    drafts_dir = workspace / "drafts"
    draft1_path = drafts_dir / "draft1.txt"
    draft2_path = drafts_dir / "draft2.txt"
    lex_path = workspace / "data" / "political_lexicon.csv"
    flags_csv_path = workspace / "analysis" / "flags.csv"
    neutral_flags_csv_path = workspace / "analysis" / "neutral_flags.csv"
    run_log_path = workspace / "logs" / "run.log"

    neutral_en_dir = workspace / "outputs" / "neutral_en"
    neutral_es_dir = workspace / "outputs" / "neutral_es"
    concise_en_dir = workspace / "outputs" / "concise_en"
    neutral_en_1 = neutral_en_dir / "draft1.txt"
    neutral_en_2 = neutral_en_dir / "draft2.txt"
    neutral_es_1 = neutral_es_dir / "draft1.txt"
    neutral_es_2 = neutral_es_dir / "draft2.txt"
    concise_en_1 = concise_en_dir / "draft1.txt"
    concise_en_2 = concise_en_dir / "draft2.txt"

    rewrites_json_path = workspace / "outputs" / "rewrites.json"
    final_post_path = workspace / "outputs" / "final_post.txt"

    # Build lexicon for checks
    lexicon = build_lexicon(lex_path) if lex_path.exists() else None

    # Compute expected flags by scanning drafts with same logic as the provided script
    expected_flags: Optional[List[Tuple[str, int, str, str, str]]] = None
    if drafts_dir.exists() and lexicon is not None:
        expected_flags = scan_dir_for_flags(drafts_dir, lex_path)

    # Logs checks
    run_log_text = safe_read_text(run_log_path)
    first_cmd = "python3 scripts/polarity_scan.py"
    second_cmd = "python3 scripts/polarity_scan.py --in drafts --lex data/political_lexicon.csv --out analysis/flags.csv"
    third_cmd = "python3 scripts/polarity_scan.py --in outputs/neutral_en --lex data/political_lexicon.csv --out analysis/neutral_flags.csv"
    if run_log_text is not None:
        # Initial error check: command with no args and usage line
        has_first_cmd = first_cmd in run_log_text
        has_usage = "Usage: python3 scripts/polarity_scan.py --in <dir> --lex <csv> --out <csv>" in run_log_text
        if has_first_cmd and has_usage:
            scores["run_log_initial_error"] = 1.0

        # First successful run message
        expect_success_msg = "Scanned 2 files, found 4 flagged occurrences. Output: analysis/flags.csv"
        has_second_cmd = second_cmd in run_log_text
        has_success = expect_success_msg in run_log_text
        if has_second_cmd and has_success:
            scores["run_log_first_success"] = 1.0

        # Neutral rescan message
        expect_zero_msg = "Scanned 2 files, found 0 flagged occurrences. Output: analysis/neutral_flags.csv"
        has_third_cmd = third_cmd in run_log_text
        has_zero = expect_zero_msg in run_log_text
        if has_third_cmd and has_zero:
            scores["run_log_neutral_rescan"] = 1.0

        # Order check: first_cmd position < second_cmd position < third_cmd position (if all present)
        pos1 = run_log_text.find(first_cmd)
        pos2 = run_log_text.find(second_cmd)
        pos3 = run_log_text.find(third_cmd)
        if pos1 != -1 and pos2 != -1 and pos3 != -1 and (pos1 < pos2 < pos3):
            scores["run_log_runs_in_order"] = 1.0

    # flags.csv checks
    header, rows = safe_load_csv_dicts(flags_csv_path)
    header_ok = header == ['file', 'line_no', 'term', 'category', 'line_text']
    if header_ok and rows is not None:
        scores["flags_csv_header_and_rows"] = 1.0
    # Compare to expected
    if expected_flags is not None and header_ok and rows is not None:
        # Map rows from CSV
        csv_rows = []
        valid_rows = True
        for r in rows:
            try:
                file_field = r['file']
                line_no_field = int(r['line_no'])
                term_field = r['term']
                cat_field = r['category']
                line_text_field = r['line_text']
                csv_rows.append((file_field, line_no_field, term_field, cat_field, line_text_field))
            except Exception:
                valid_rows = False
                break
        if valid_rows:
            # Count per file
            csv_counts: Dict[str, int] = {}
            for fr, _, _, _, _ in csv_rows:
                csv_counts[fr] = csv_counts.get(fr, 0) + 1
            exp_counts: Dict[str, int] = {}
            for fr, _, _, _, _ in (expected_flags or []):
                exp_counts[fr] = exp_counts.get(fr, 0) + 1
            # Only consider the two drafts for strictness
            draft1_key = "drafts/draft1.txt"
            draft2_key = "drafts/draft2.txt"
            exp1 = exp_counts.get(draft1_key, 0)
            exp2 = exp_counts.get(draft2_key, 0)
            got1 = csv_counts.get(draft1_key, 0)
            got2 = csv_counts.get(draft2_key, 0)
            if got1 == exp1 and got2 == exp2 and sum(csv_counts.values()) == (exp1 + exp2):
                scores["flags_csv_expected_counts"] = 1.0
            # Expected terms set
            exp_terms_set = set()
            for fr, _, term, _, _ in (expected_flags or []):
                exp_terms_set.add((fr, term))
            got_terms_set = set((r[0], r[2]) for r in csv_rows)
            # Restrict to the expected files
            relevant_got = set([x for x in got_terms_set if x[0] in {draft1_key, draft2_key}])
            relevant_exp = set([x for x in exp_terms_set if x[0] in {draft1_key, draft2_key}])
            if relevant_got == relevant_exp and len(relevant_exp) > 0:
                scores["flags_csv_expected_terms"] = 1.0

    # Neutral English files: presence, no flagged terms, preserve details
    neutral_en_1_text = safe_read_text(neutral_en_1)
    neutral_en_2_text = safe_read_text(neutral_en_2)
    clean1 = contains_no_flagged_terms(neutral_en_1_text, lexicon)
    clean2 = contains_no_flagged_terms(neutral_en_2_text, lexicon)
    if clean1 is True:
        scores["neutral_en_draft1_clean_and_present"] = 1.0
    if clean2 is True:
        scores["neutral_en_draft2_clean_and_present"] = 1.0

    # Preserve details checks (exact tokens from drafts)
    # Draft1 required tokens
    d1_tokens = ["April 22, 2026", "Manchester Apollo", "7:00 PM", "8:00 PM"]
    d2_tokens = ["May 5, 2026", "Brixton Academy", "London", "7:00 PM", "8:00 PM"]
    if text_contains_all(neutral_en_1_text, d1_tokens) is True:
        scores["neutral_en_draft1_preserves_details"] = 1.0
    if text_contains_all(neutral_en_2_text, d2_tokens) is True:
        scores["neutral_en_draft2_preserves_details"] = 1.0

    # Neutral Spanish files: presence with key details and clean of English lexicon terms
    neutral_es_1_text = safe_read_text(neutral_es_1)
    neutral_es_2_text = safe_read_text(neutral_es_2)
    if neutral_es_1_text is not None:
        # Require venue + times + year present (dates may be translated)
        tokens_es1 = ["Manchester Apollo", "7:00", "8:00", "2026"]
        contains_details = text_contains_all(neutral_es_1_text, tokens_es1) is True
        clean_es1 = contains_no_flagged_terms(neutral_es_1_text, lexicon)
        if contains_details and (clean_es1 is True or clean_es1 is None):
            scores["neutral_es_draft1_present_with_details"] = 1.0
    if neutral_es_2_text is not None:
        tokens_es2 = ["Brixton Academy", "London", "7:00", "8:00", "2026"]
        contains_details = text_contains_all(neutral_es_2_text, tokens_es2) is True
        clean_es2 = contains_no_flagged_terms(neutral_es_2_text, lexicon)
        if contains_details and (clean_es2 is True or clean_es2 is None):
            scores["neutral_es_draft2_present_with_details"] = 1.0

    # Concise English: existence, <=300 chars, clean, preserve details
    concise_en_1_text = safe_read_text(concise_en_1)
    concise_en_2_text = safe_read_text(concise_en_2)
    def concise_check(text: Optional[str], tokens: List[str], lex: Optional[List[Tuple[str, str, re.Pattern]]]) -> Tuple[bool, bool]:
        if text is None:
            return False, False
        length_ok = len(text.strip()) <= 300
        clean = contains_no_flagged_terms(text, lex)
        clean_ok = (clean is True) if clean is not None else False
        details_ok = text_contains_all(text, tokens) is True
        return (length_ok and clean_ok), details_ok

    length_clean_ok_1, details_ok_1 = concise_check(concise_en_1_text, d1_tokens, lexicon)
    length_clean_ok_2, details_ok_2 = concise_check(concise_en_2_text, d2_tokens, lexicon)
    if length_clean_ok_1:
        scores["concise_en_draft1_length_and_clean"] = 1.0
    if length_clean_ok_2:
        scores["concise_en_draft2_length_and_clean"] = 1.0
    if details_ok_1:
        scores["concise_en_draft1_preserves_details"] = 1.0
    if details_ok_2:
        scores["concise_en_draft2_preserves_details"] = 1.0

    # rewrites.json checks
    rewrites_text = safe_read_text(rewrites_json_path)
    if rewrites_text is not None:
        try:
            rewrites_obj = json.loads(rewrites_text)
            entries = rewrites_json_to_list(rewrites_obj)
            if isinstance(entries, list) and len(entries) == 2:
                # Prepare counts from flags.csv
                csv_header, csv_rows = safe_load_csv_dicts(flags_csv_path)
                per_file_counts: Dict[str, int] = {}
                if csv_header == ['file', 'line_no', 'term', 'category', 'line_text']:
                    for r in csv_rows:
                        f = r.get("file", "")
                        per_file_counts[f] = per_file_counts.get(f, 0) + 1
                # Validate each entry
                valid_all = True
                expected_map = {
                    "drafts/draft1.txt": {
                        "neutral_en_path": "outputs/neutral_en/draft1.txt",
                        "neutral_es_path": "outputs/neutral_es/draft1.txt",
                        "concise_en_path": "outputs/concise_en/draft1.txt",
                        "required_tokens": d1_tokens,
                        "neutral_text": neutral_en_1_text or ""
                    },
                    "drafts/draft2.txt": {
                        "neutral_en_path": "outputs/neutral_en/draft2.txt",
                        "neutral_es_path": "outputs/neutral_es/draft2.txt",
                        "concise_en_path": "outputs/concise_en/draft2.txt",
                        "required_tokens": d2_tokens,
                        "neutral_text": neutral_en_2_text or ""
                    }
                }
                seen_inputs = set()
                for e in entries:
                    if not isinstance(e, dict):
                        valid_all = False
                        break
                    input_path = e.get("input_path")
                    if input_path not in expected_map:
                        valid_all = False
                        break
                    seen_inputs.add(input_path)
                    # Check path fields
                    if e.get("neutral_en_path") != expected_map[input_path]["neutral_en_path"]:
                        valid_all = False
                        break
                    if e.get("neutral_es_path") != expected_map[input_path]["neutral_es_path"]:
                        valid_all = False
                        break
                    if e.get("concise_en_path") != expected_map[input_path]["concise_en_path"]:
                        valid_all = False
                        break
                    # Check flagged_terms_count matches analysis/flags.csv per file
                    ftc = e.get("flagged_terms_count")
                    expected_count = per_file_counts.get(input_path, None)
                    if expected_count is None or not isinstance(ftc, int) or ftc != expected_count:
                        valid_all = False
                        break
                    # preserved_details
                    pd = e.get("preserved_details")
                    if not isinstance(pd, list) or len(pd) == 0 or any(not isinstance(x, str) for x in pd):
                        valid_all = False
                        break
                    # Ensure preserved_details covers core tokens and are reflected in neutral text
                    tokens_needed = expected_map[input_path]["required_tokens"]
                    combined_pd_text = " ".join(pd)
                    for tok in tokens_needed:
                        # token should appear in preserved details and in the neutral text
                        if tok.lower() not in combined_pd_text.lower():
                            valid_all = False
                            break
                        if tok.lower() not in expected_map[input_path]["neutral_text"].lower():
                            valid_all = False
                            break
                    if not valid_all:
                        break
                if valid_all and seen_inputs == set(expected_map.keys()):
                    scores["rewrites_json_valid"] = 1.0
        except Exception:
            pass

    # final_post.txt check: combines concise in filename order, separated by a blank line
    final_text = safe_read_text(final_post_path)
    if final_text is not None and concise_en_1_text is not None and concise_en_2_text is not None:
        part1 = (concise_en_1_text or "").strip()
        part2 = (concise_en_2_text or "").strip()
        final_trim = final_text.strip()
        expected_join = part1 + "\n\n" + part2
        if final_trim == expected_join:
            scores["final_post_combined_order"] = 1.0

    # neutral flags rescan CSV header-only
    n_header, n_rows = safe_load_csv_dicts(neutral_flags_csv_path)
    if n_header == ['file', 'line_no', 'term', 'category', 'line_text'] and isinstance(n_rows, list) and len(n_rows) == 0:
        scores["neutral_rescan_csv_zero_flags"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()