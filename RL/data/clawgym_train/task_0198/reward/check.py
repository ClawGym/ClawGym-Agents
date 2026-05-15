import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set


def read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline='') as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            fieldnames = reader.fieldnames
            return rows, fieldnames
    except Exception:
        return None, None


def safe_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def normalize_lang(lang: str) -> str:
    return (lang or "").strip().lower()


def parse_semicolon_list(s: str) -> List[str]:
    if s is None:
        return []
    parts = [p.strip() for p in str(s).split(";")]
    return [p for p in parts if p != ""]


def set_from_semicolon(s: str) -> Set[str]:
    return set(parse_semicolon_list(s))


def build_codebook_patterns(codebook_rows: List[Dict[str, str]]) -> Dict[str, List[re.Pattern]]:
    patterns = {}
    for row in codebook_rows:
        theme = (row.get("theme") or "").strip()
        kw_str = (row.get("keywords") or "").strip()
        kws = [k.strip() for k in kw_str.split(";") if k.strip()]
        compiled = []
        for kw in kws:
            # Use non-word boundary guards around the full phrase to approximate whole-word/phrase match
            escaped = re.escape(kw)
            pat = re.compile(rf"(?i)(?<!\w){escaped}(?!\w)")
            compiled.append(pat)
        patterns[theme] = compiled
    return patterns


def detect_themes(text: str, theme_patterns: Dict[str, List[re.Pattern]]) -> Set[str]:
    text = text or ""
    detected = set()
    for theme, pats in theme_patterns.items():
        for pat in pats:
            if pat.search(text):
                detected.add(theme)
                break
    return detected


def load_input_maps(workspace: Path) -> Tuple[Optional[Dict[int, Dict[str, str]]], Optional[Dict[int, int]], Optional[Dict[int, str]]]:
    responses_path = workspace / "input" / "responses.csv"
    rows, _ = read_csv_dicts(responses_path)
    if rows is None:
        return None, None, None
    id_to_row = {}
    id_to_age = {}
    id_to_lang = {}
    for r in rows:
        rid = safe_int(r.get("id"))
        if rid is None:
            continue
        id_to_row[rid] = r
        age = safe_int(r.get("child_age"))
        if age is not None:
            id_to_age[rid] = age
        lang = r.get("language", "")
        id_to_lang[rid] = lang
    return id_to_row, id_to_age, id_to_lang


def parse_translated_responses(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    return read_csv_dicts(path)


def compute_expected_included_ids(id_to_age: Dict[int, int]) -> Set[int]:
    return {rid for rid, age in id_to_age.items() if age is not None and 9 <= age <= 16}


def float_equal_two_decimals(a: float, b: float) -> bool:
    return round(a + 0.0, 2) == round(b + 0.0, 2)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "translated_responses_columns_and_presence": 0.0,
        "age_filter_applied_correctly": 0.0,
        "english_rows_preserved_text": 0.0,
        "non_english_rows_translated_present": 0.0,
        "detected_themes_from_codebook_correct": 0.0,
        "distress_flag_correct": 0.0,
        "theme_summary_columns_and_values_correct": 0.0,
        "top_themes_by_condition_columns_and_values_correct": 0.0,
        "priority_cases_columns_and_values_correct": 0.0,
    }

    # Load inputs
    input_responses_path = workspace / "input" / "responses.csv"
    input_codebook_path = workspace / "input" / "codebook.csv"
    responses_rows, responses_fields = read_csv_dicts(input_responses_path)
    codebook_rows, codebook_fields = read_csv_dicts(input_codebook_path)

    # If inputs missing or malformed, many checks will be unable to proceed
    if not responses_rows or not codebook_rows:
        # Attempt graceful exit with zeros
        return scores

    # Build input maps
    id_to_row, id_to_age, id_to_lang = load_input_maps(workspace)
    if id_to_row is None or id_to_age is None:
        return scores

    included_ids_expected = compute_expected_included_ids(id_to_age)

    # Build codebook patterns
    theme_patterns = build_codebook_patterns(codebook_rows)
    codebook_themes = list(theme_patterns.keys())

    # Read output translated responses
    tr_path = workspace / "output" / "translated_responses.csv"
    tr_rows, tr_fields = parse_translated_responses(tr_path)
    expected_tr_fields = [
        "id",
        "child_age",
        "chronic_condition",
        "original_language",
        "original_response_text",
        "english_response_text",
        "detected_themes",
        "distress_flag",
    ]
    if tr_rows is not None and tr_fields == expected_tr_fields:
        scores["translated_responses_columns_and_presence"] = 1.0
    else:
        # If file missing or columns wrong, subsequent checks relying on it will be 0.0
        tr_rows = None

    # If translated responses available, perform checks
    if tr_rows is not None:
        # Age filter and ID set verification
        ids_in_tr = set()
        ages_ok = True
        id_set_matches = True
        cross_consistency_ok = True
        id_seen_multiple = False
        seen_ids = set()
        for row in tr_rows:
            rid = safe_int(row.get("id"))
            if rid is None:
                cross_consistency_ok = False
                continue
            if rid in seen_ids:
                id_seen_multiple = True
            seen_ids.add(rid)
            ids_in_tr.add(rid)
            age_val = safe_int(row.get("child_age"))
            if age_val is None or not (9 <= age_val <= 16):
                ages_ok = False
            # Cross-check with input
            src = id_to_row.get(rid)
            if not src:
                cross_consistency_ok = False
            else:
                # Verify child_age and chronic_condition match input
                src_age = safe_int(src.get("child_age"))
                src_cond = (src.get("chronic_condition") or "").strip()
                out_cond = (row.get("chronic_condition") or "").strip()
                if src_age != age_val or src_cond != out_cond:
                    cross_consistency_ok = False
        if ids_in_tr == included_ids_expected and ages_ok and cross_consistency_ok and not id_seen_multiple:
            scores["age_filter_applied_correctly"] = 1.0

        # English rows preserved and non-English translated presence
        en_preserve_ok = True
        non_en_translated_ok = True
        for row in tr_rows:
            rid = safe_int(row.get("id"))
            if rid is None:
                en_preserve_ok = False
                non_en_translated_ok = False
                continue
            src = id_to_row.get(rid)
            if not src:
                en_preserve_ok = False
                non_en_translated_ok = False
                continue
            src_lang = normalize_lang(src.get("language", ""))
            out_orig_lang = normalize_lang(row.get("original_language", ""))
            if src_lang != out_orig_lang:
                # original_language should match input language
                if src_lang != out_orig_lang:
                    en_preserve_ok = False
                    non_en_translated_ok = False
                    continue
            src_text = src.get("response_text") or ""
            out_orig_text = row.get("original_response_text") or ""
            if src_text != out_orig_text:
                en_preserve_ok = False
                non_en_translated_ok = False
                continue
            eng_text = (row.get("english_response_text") or "")
            if src_lang == "en":
                # For English rows, english_response_text should equal original
                if eng_text != out_orig_text:
                    en_preserve_ok = False
            else:
                # For non-English, english_response_text must be present and differ
                if not eng_text or eng_text.strip() == "" or eng_text == out_orig_text:
                    non_en_translated_ok = False
        scores["english_rows_preserved_text"] = 1.0 if en_preserve_ok else 0.0
        scores["non_english_rows_translated_present"] = 1.0 if non_en_translated_ok else 0.0

        # Detected themes correctness and distress flag correctness
        n_rows = len(tr_rows)
        correct_theme_count = 0
        correct_distress_count = 0

        # Collect recomputed themes for later aggregations
        recomputed_by_id: Dict[int, Set[str]] = {}
        for row in tr_rows:
            rid = safe_int(row.get("id"))
            eng_text = row.get("english_response_text") or ""
            computed_themes = detect_themes(eng_text, theme_patterns)
            recomputed_by_id[rid] = computed_themes
            reported_themes = set_from_semicolon(row.get("detected_themes", ""))
            if reported_themes == computed_themes:
                correct_theme_count += 1
            # Distress flag
            expected_distress = "Yes" if (("Anxiety/Worry" in computed_themes) or ("Sadness/Low mood" in computed_themes)) else "No"
            if (row.get("distress_flag") or "").strip() == expected_distress:
                correct_distress_count += 1

        if n_rows > 0:
            scores["detected_themes_from_codebook_correct"] = correct_theme_count / n_rows
            scores["distress_flag_correct"] = correct_distress_count / n_rows
        else:
            scores["detected_themes_from_codebook_correct"] = 0.0
            scores["distress_flag_correct"] = 0.0

        # Build expected aggregations based on recomputed themes
        # Compute n_condition_responses per condition among included ids
        condition_counts: Dict[str, int] = {}
        id_to_condition: Dict[int, str] = {}
        id_to_age_out: Dict[int, int] = {}
        for row in tr_rows:
            rid = safe_int(row.get("id"))
            cond = (row.get("chronic_condition") or "").strip()
            age = safe_int(row.get("child_age"))
            if rid is None or age is None:
                continue
            id_to_condition[rid] = cond
            id_to_age_out[rid] = age
            condition_counts[cond] = condition_counts.get(cond, 0) + 1

        # Theme counts per condition
        theme_counts_by_condition: Dict[Tuple[str, str], int] = {}
        for row in tr_rows:
            rid = safe_int(row.get("id"))
            if rid is None:
                continue
            cond = id_to_condition.get(rid)
            if cond is None:
                continue
            themes_here = recomputed_by_id.get(rid, set())
            for theme in codebook_themes:
                present = 1 if theme in themes_here else 0
                key = (cond, theme)
                theme_counts_by_condition[key] = theme_counts_by_condition.get(key, 0) + present

        # Expected theme_summary rows
        expected_theme_summary_rows: List[Dict[str, str]] = []
        for cond, n_cond in sorted(condition_counts.items()):
            for theme in sorted(codebook_themes):
                n_with = theme_counts_by_condition.get((cond, theme), 0)
                pct = (n_with / n_cond) if n_cond > 0 else 0.0
                pct_rounded = round(pct + 0.0, 2)
                expected_theme_summary_rows.append({
                    "chronic_condition": cond,
                    "theme": theme,
                    "n_responses_with_theme": str(int(n_with)),
                    "n_condition_responses": str(int(n_cond)),
                    "pct_condition_responses": f"{pct_rounded:.2f}",
                })

        # Read their theme_summary.csv and compare
        ts_path = workspace / "output" / "theme_summary.csv"
        ts_rows, ts_fields = read_csv_dicts(ts_path)
        expected_ts_fields = [
            "chronic_condition",
            "theme",
            "n_responses_with_theme",
            "n_condition_responses",
            "pct_condition_responses",
        ]
        ts_ok = False
        if ts_rows is not None and ts_fields == expected_ts_fields:
            # Normalize and compare ignoring row order
            def norm_ts_row(r: Dict[str, str]) -> Tuple[str, str, int, int, float]:
                cond = (r.get("chronic_condition") or "").strip()
                theme = (r.get("theme") or "").strip()
                n_with = safe_int(r.get("n_responses_with_theme")) or 0
                n_cond = safe_int(r.get("n_condition_responses")) or 0
                # pct may be string; parse to float
                pct_str = (r.get("pct_condition_responses") or "").strip()
                try:
                    pct_val = float(pct_str)
                except Exception:
                    pct_val = math.nan
                return (cond, theme, n_with, n_cond, pct_val)

            theirs = [norm_ts_row(r) for r in ts_rows]
            expected = []
            for r in expected_theme_summary_rows:
                expected.append((
                    r["chronic_condition"],
                    r["theme"],
                    int(r["n_responses_with_theme"]),
                    int(r["n_condition_responses"]),
                    float(r["pct_condition_responses"]),
                ))
            # Build dicts for quick comparison
            theirs_map = {(c, t): (nw, nc, pv) for (c, t, nw, nc, pv) in theirs}
            expected_map = {(c, t): (nw, nc, pv) for (c, t, nw, nc, pv) in expected}
            if set(theirs_map.keys()) == set(expected_map.keys()):
                all_match = True
                for key in expected_map:
                    e_nw, e_nc, e_pv = expected_map[key]
                    t_nw, t_nc, t_pv = theirs_map.get(key, (None, None, None))
                    if e_nw != t_nw or e_nc != t_nc or (not float_equal_two_decimals(e_pv, t_pv)):
                        all_match = False
                        break
                if all_match:
                    ts_ok = True
        scores["theme_summary_columns_and_values_correct"] = 1.0 if ts_ok else 0.0

        # Top themes by condition
        # Compute expected top themes (only non-zero counts; include up to 3)
        expected_top_rows: List[Dict[str, str]] = []
        for cond, n_cond in sorted(condition_counts.items()):
            # Build list of (theme, count)
            tlist = []
            for theme in codebook_themes:
                count = theme_counts_by_condition.get((cond, theme), 0)
                if count > 0:
                    tlist.append((theme, count))
            # Sort by count desc, theme asc; take top 3
            tlist.sort(key=lambda x: (-x[1], x[0]))
            top = tlist[:3]
            rank = 1
            for theme, count in top:
                expected_top_rows.append({
                    "chronic_condition": cond,
                    "rank": str(rank),
                    "theme": theme,
                    "count": str(int(count)),
                })
                rank += 1

        # Read their top_themes_by_condition.csv
        top_path = workspace / "output" / "top_themes_by_condition.csv"
        top_rows, top_fields = read_csv_dicts(top_path)
        expected_top_fields = ["chronic_condition", "rank", "theme", "count"]
        top_ok = False
        if top_rows is not None and top_fields == expected_top_fields:
            # Compare as sets of tuples
            def norm_top_row(r: Dict[str, str]) -> Tuple[str, int, str, int]:
                cond = (r.get("chronic_condition") or "").strip()
                rnk = safe_int(r.get("rank")) or 0
                theme = (r.get("theme") or "").strip()
                cnt = safe_int(r.get("count")) or 0
                return (cond, rnk, theme, cnt)

            theirs_set = set(norm_top_row(r) for r in top_rows)
            expected_set = set((r["chronic_condition"], int(r["rank"]), r["theme"], int(r["count"])) for r in expected_top_rows)
            if theirs_set == expected_set:
                top_ok = True
        scores["top_themes_by_condition_columns_and_values_correct"] = 1.0 if top_ok else 0.0

        # Priority cases
        # Compute expected priority rows: distress Yes only, sorted by child_age desc then id asc
        expected_priority_rows: List[Dict[str, str]] = []
        for row in tr_rows:
            rid = safe_int(row.get("id"))
            if rid is None:
                continue
            age = safe_int(row.get("child_age"))
            if age is None:
                continue
            cond = (row.get("chronic_condition") or "").strip()
            eng_text = row.get("english_response_text") or ""
            themes = recomputed_by_id.get(rid, set())
            distress_yes = ("Anxiety/Worry" in themes) or ("Sadness/Low mood" in themes)
            if distress_yes:
                expected_priority_rows.append({
                    "id": str(rid),
                    "chronic_condition": cond,
                    "child_age": str(age),
                    "detected_themes": ";".join(sorted(list(themes))),
                    "english_response_text": eng_text,
                })
        # Sort expected
        expected_priority_rows.sort(key=lambda r: (-safe_int(r["child_age"]), int(r["id"])))

        # Read their priority_cases.csv
        pc_path = workspace / "output" / "priority_cases.csv"
        pc_rows, pc_fields = read_csv_dicts(pc_path)
        expected_pc_fields = ["id", "chronic_condition", "child_age", "detected_themes", "english_response_text"]
        pc_ok = False
        if pc_rows is not None and pc_fields == expected_pc_fields:
            # Verify sorting
            sorted_check = True
            prev_age = None
            prev_id = None
            for r in pc_rows:
                age = safe_int(r.get("child_age"))
                rid = safe_int(r.get("id"))
                if age is None or rid is None:
                    sorted_check = False
                    break
                if prev_age is None:
                    prev_age = age
                    prev_id = rid
                else:
                    # Should be descending by age, then ascending by id
                    if age > prev_age:
                        sorted_check = False
                        break
                    if age == prev_age and rid < prev_id:
                        sorted_check = False
                        break
                    prev_age = age
                    prev_id = rid
            # Compare content by mapping id to row; ensure exact match
            if sorted_check and len(pc_rows) == len(expected_priority_rows):
                # Compare rows by position since sort must match
                all_match = True
                for i in range(len(expected_priority_rows)):
                    er = expected_priority_rows[i]
                    tr = pc_rows[i]
                    # Check id, condition, age
                    if (str(er["id"]) != (tr.get("id") or "").strip() or
                        str(er["chronic_condition"]) != (tr.get("chronic_condition") or "").strip() or
                        str(er["child_age"]) != (tr.get("child_age") or "").strip()):
                        all_match = False
                        break
                    # Compare detected themes as sets
                    er_set = set_from_semicolon(er["detected_themes"])
                    tr_set = set_from_semicolon(tr.get("detected_themes", ""))
                    if er_set != tr_set:
                        all_match = False
                        break
                    # Compare english_response_text exact
                    if (er["english_response_text"] or "") != (tr.get("english_response_text") or ""):
                        all_match = False
                        break
                if all_match:
                    pc_ok = True
        scores["priority_cases_columns_and_values_correct"] = 1.0 if pc_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()