import json
import csv
import sys
import re
from pathlib import Path
from urllib.parse import urlparse
from statistics import median


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        text = safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def safe_read_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fieldnames = reader.fieldnames or []
            return rows, fieldnames
    except Exception:
        return None, None


def load_keywords(path: Path):
    rows, fieldnames = safe_read_csv_rows(path)
    if rows is None or fieldnames is None:
        return None
    header_lower = [h.strip().lower() for h in fieldnames]
    if "keyword" not in header_lower:
        return None
    keyword_idx = header_lower.index("keyword")
    kws = []
    for r in rows:
        # DictReader keys may preserve original case; normalize
        keys = list(r.keys())
        key = keys[keyword_idx]
        val = (r.get(key) or "").strip()
        if val:
            kws.append(val)
    # normalize to lowercase for matching
    return [k.lower() for k in kws]


def canonical_domain_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        # Remove leading www. if present
        while netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def tld_from_domain(domain: str) -> str:
    d = domain.lower()
    if d.endswith(".edu") or d == "edu":
        return "edu"
    if d.endswith(".gov") or d == "gov":
        return "gov"
    if d.endswith(".org") or d == "org":
        return "org"
    return ""


def list_files_in_dir(dir_path: Path):
    if not dir_path.exists() or not dir_path.is_dir():
        return []
    return [p for p in dir_path.iterdir() if p.is_file()]


def basenames(files):
    return [p.name for p in files]


def lower_contains(text: str, needle: str) -> bool:
    return needle.lower() in text.lower()


def tokenize_words(text: str):
    # Simple whitespace split for word count
    return [w for w in re.split(r"\s+", text.strip()) if w]


def compute_keyword_presence(text: str, keywords: list) -> set:
    text_l = text.lower()
    present = set()
    for kw in keywords:
        if kw in text_l:
            present.add(kw)
    return present


def compute_top_pairs(keyword_sets: list, top_n: int = 10):
    from itertools import combinations
    counts = {}
    for s in keyword_sets:
        if len(s) < 2:
            continue
        for a, b in combinations(sorted(s), 2):
            counts[(a, b)] = counts.get((a, b), 0) + 1
    # sort by count desc, then lex
    sorted_pairs = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    result = []
    for (a, b), c in sorted_pairs[:top_n]:
        result.append({"pair": [a, b], "count": c})
    return result


def median_int(values: list) -> int:
    if not values:
        return 0
    m = median(values)
    return int(round(m))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "records_csv_present_and_columns": 0.0,
        "at_least_12_rows": 0.0,
        "no_duplicate_urls": 0.0,
        "tld_and_org_type_valid": 0.0,
        "domain_matches_url": 0.0,
        "http_status_success": 0.0,
        "publication_year_validity": 0.0,
        "raw_and_clean_dirs_exist": 0.0,
        "raw_clean_counts_match_rows": 0.0,
        "raw_clean_basenames_match": 0.0,
        "cleaned_texts_content_requirements": 0.0,
        "cleaned_files_not_html": 0.0,
        "tld_diversity": 0.0,
        "queries_file_valid": 0.0,
        "stats_json_present_and_schema": 0.0,
        "stats_total_pages_consistency": 0.0,
        "stats_pages_by_tld_consistency": 0.0,
        "stats_keyword_counts_consistency": 0.0,
        "stats_avg_median_consistency": 0.0,
        "stats_pages_by_year_consistency": 0.0,
        "stats_top_keyword_pairs_consistency": 0.0,
        "matched_keywords_values_valid": 0.0,
        "word_count_values_valid_positive": 0.0,
    }

    # Load keywords
    keywords_path = workspace / "input" / "keywords.csv"
    keywords = load_keywords(keywords_path)

    # Prepare directories and files
    records_path = workspace / "outputs" / "records.csv"
    stats_path = workspace / "outputs" / "stats.json"
    queries_path = workspace / "outputs" / "queries.txt"
    raw_dir = workspace / "data" / "raw"
    clean_dir = workspace / "data" / "clean"

    raw_files = list_files_in_dir(raw_dir)
    clean_files = list_files_in_dir(clean_dir)

    # records.csv checks
    rows, fieldnames = safe_read_csv_rows(records_path)
    if rows is not None and fieldnames is not None:
        required_cols = ["url", "domain", "tld", "title", "word_count", "matched_keywords", "org_type", "http_status", "publication_year"]
        fieldnames_l = [f.strip() for f in fieldnames]
        has_all = all(col in fieldnames_l for col in required_cols)
        if has_all:
            scores["records_csv_present_and_columns"] = 1.0

        # At least 12 rows
        if len(rows) >= 12:
            scores["at_least_12_rows"] = 1.0

        # Duplicate URLs check (case-insensitive)
        seen = set()
        duplicates = False
        for r in rows:
            u = (r.get("url") or "").strip().lower()
            if not u:
                duplicates = True
                break
            if u in seen:
                duplicates = True
                break
            seen.add(u)
        if not duplicates and len(rows) > 0:
            scores["no_duplicate_urls"] = 1.0

        # domain matches url and tld/org_type valid
        domain_ok = True
        tld_ok = True
        http_ok = True
        pub_year_ok = True
        mk_valid = True
        wc_positive = True
        for r in rows:
            url = (r.get("url") or "").strip()
            dom = (r.get("domain") or "").strip().lower()
            tld = (r.get("tld") or "").strip().lower()
            org_type = (r.get("org_type") or "").strip().lower()
            http_s = (r.get("http_status") or "").strip()
            pub_year = (r.get("publication_year") or "").strip()
            title = (r.get("title") or "").strip()

            # title must be non-empty
            if not title:
                domain_ok = False  # reuse as a failure flag, though it's about title

            # canonicalize domain and compare
            can_dom_from_url = canonical_domain_from_url(url)
            can_dom_field = dom
            while can_dom_field.startswith("www."):
                can_dom_field = can_dom_field[4:]
            if can_dom_field != can_dom_from_url or can_dom_field == "":
                domain_ok = False

            # tld and org_type
            expected_tld = tld_from_domain(can_dom_field)
            if tld not in {"edu", "gov", "org"} or org_type not in {"edu", "gov", "org"}:
                tld_ok = False
            if expected_tld != tld or org_type != tld:
                tld_ok = False

            # http status
            try:
                hs = int(http_s)
                if hs < 200 or hs > 299:
                    http_ok = False
            except Exception:
                http_ok = False

            # publication year validity (blank or 4-digit year)
            if pub_year:
                if not re.fullmatch(r"\d{4}", pub_year):
                    pub_year_ok = False
                else:
                    y = int(pub_year)
                    # reasonable bounds
                    if y < 1900 or y > 2100:
                        pub_year_ok = False

            # matched_keywords validity
            mk = (r.get("matched_keywords") or "").strip()
            if not mk:
                mk_valid = False
            else:
                parts = [p.strip().lower() for p in mk.split(";") if p.strip()]
                # should be unique, non-empty, all in keywords
                if len(parts) == 0 or len(parts) != len(set(parts)):
                    mk_valid = False
                if keywords is None:
                    mk_valid = False
                else:
                    for p in parts:
                        if p not in keywords:
                            mk_valid = False
                            break

            # word_count positive integer
            wc = (r.get("word_count") or "").strip()
            try:
                wci = int(wc)
                if wci <= 0:
                    wc_positive = False
            except Exception:
                wc_positive = False

        if tld_ok:
            scores["tld_and_org_type_valid"] = 1.0
        if domain_ok:
            scores["domain_matches_url"] = 1.0
        if http_ok:
            scores["http_status_success"] = 1.0
        if pub_year_ok:
            scores["publication_year_validity"] = 1.0
        if mk_valid:
            scores["matched_keywords_values_valid"] = 1.0
        if wc_positive:
            scores["word_count_values_valid_positive"] = 1.0

        # TLD diversity (at least two TLD types)
        tlds = set((r.get("tld") or "").strip().lower() for r in rows)
        tlds = {t for t in tlds if t in {"edu", "gov", "org"}}
        if len(tlds) >= 2:
            scores["tld_diversity"] = 1.0

    # Raw and clean dirs existence
    if raw_dir.exists() and raw_dir.is_dir() and clean_dir.exists() and clean_dir.is_dir():
        scores["raw_and_clean_dirs_exist"] = 1.0

    # raw/clean counts match rows
    if rows is not None:
        num_rows = len(rows)
        if num_rows > 0 and len(raw_files) == num_rows and len(clean_files) == num_rows:
            scores["raw_clean_counts_match_rows"] = 1.0

    # raw/clean basenames match
    if raw_files and clean_files:
        raw_b = set(basenames(raw_files))
        clean_b = set(basenames(clean_files))
        if raw_b == clean_b and len(raw_b) == len(raw_files) == len(clean_files):
            scores["raw_clean_basenames_match"] = 1.0

    # cleaned texts content requirements and not HTML
    cleaned_ok = True
    cleaned_not_html = True
    if keywords is not None and clean_files:
        for cf in clean_files:
            txt = safe_read_text(cf)
            if txt is None:
                cleaned_ok = False
                cleaned_not_html = False
                break
            if "<html" in txt.lower() or "<!doctype" in txt.lower():
                cleaned_not_html = False
            # must contain "music therapy" and at least one keyword
            if not lower_contains(txt, "music therapy"):
                cleaned_ok = False
            kw_present = compute_keyword_presence(txt, keywords)
            if len(kw_present) == 0:
                cleaned_ok = False
        if cleaned_ok:
            scores["cleaned_texts_content_requirements"] = 1.0
        if cleaned_not_html:
            scores["cleaned_files_not_html"] = 1.0
    else:
        # If keywords missing or no cleaned files, both checks remain 0.0
        pass

    # queries.txt validation
    queries_valid = False
    if queries_path.exists() and queries_path.is_file() and keywords is not None:
        qtext = safe_read_text(queries_path)
        if qtext is not None:
            lines = [ln.strip() for ln in qtext.splitlines() if ln.strip()]
            if lines:
                # distinctness
                norm_lines = [ln.lower() for ln in lines]
                if len(norm_lines) == len(set(norm_lines)):
                    # each contains "music therapy", at least one keyword, and "site:"
                    all_ok = True
                    for ln in norm_lines:
                        if "music therapy" not in ln:
                            all_ok = False
                            break
                        if "site:" not in ln:
                            all_ok = False
                            break
                        if not any(kw in ln for kw in keywords):
                            all_ok = False
                            break
                    if all_ok:
                        queries_valid = True
    if queries_valid:
        scores["queries_file_valid"] = 1.0

    # raw files contain HTML markers (optional strictness)
    # Not a separate score key per instructions; incorporated in cleaned_files_not_html only.

    # stats.json checks
    stats_obj = safe_load_json(stats_path)
    stats_schema_ok = False
    if stats_obj is not None and isinstance(stats_obj, dict):
        # Required keys
        required_keys = ["total_pages", "pages_by_tld", "keyword_counts", "avg_word_count", "median_word_count", "pages_by_year", "top_keyword_pairs"]
        if all(k in stats_obj for k in required_keys):
            # types
            if isinstance(stats_obj.get("total_pages"), int) and isinstance(stats_obj.get("pages_by_tld"), dict) and isinstance(stats_obj.get("keyword_counts"), dict) and isinstance(stats_obj.get("avg_word_count"), int) and isinstance(stats_obj.get("median_word_count"), int) and isinstance(stats_obj.get("pages_by_year"), dict) and isinstance(stats_obj.get("top_keyword_pairs"), list):
                # pages_by_tld contains edu/gov/org
                pbt = stats_obj.get("pages_by_tld", {})
                if all(k in pbt for k in ["edu", "gov", "org"]) and all(isinstance(pbt[k], int) for k in ["edu", "gov", "org"]):
                    # keyword_counts contains all keywords
                    kc = stats_obj.get("keyword_counts", {})
                    if keywords is not None and isinstance(kc, dict) and all(kw in kc for kw in keywords) and all(isinstance(kc[kw], int) for kw in kc):
                        # top_keyword_pairs schema
                        tkp = stats_obj.get("top_keyword_pairs", [])
                        tkp_schema_ok = True
                        for item in tkp:
                            if not isinstance(item, dict):
                                tkp_schema_ok = False
                                break
                            if "pair" not in item or "count" not in item:
                                tkp_schema_ok = False
                                break
                            if not isinstance(item["pair"], list) or len(item["pair"]) != 2:
                                tkp_schema_ok = False
                                break
                            if not isinstance(item["count"], int):
                                tkp_schema_ok = False
                                break
                        if tkp_schema_ok:
                            stats_schema_ok = True
    if stats_schema_ok:
        scores["stats_json_present_and_schema"] = 1.0

    # stats consistency checks
    if rows is not None and stats_obj is not None and isinstance(stats_obj, dict):
        # total_pages
        expected_total = len(rows)
        if stats_obj.get("total_pages") == expected_total:
            scores["stats_total_pages_consistency"] = 1.0

        # pages_by_tld
        tld_counts = {"edu": 0, "gov": 0, "org": 0}
        for r in rows:
            t = (r.get("tld") or "").strip().lower()
            if t in tld_counts:
                tld_counts[t] += 1
        pbt = stats_obj.get("pages_by_tld")
        if isinstance(pbt, dict):
            if all(pbt.get(k) == tld_counts[k] for k in ["edu", "gov", "org"]):
                scores["stats_pages_by_tld_consistency"] = 1.0

        # avg and median word count from records.csv
        wc_vals = []
        ok_all = True
        for r in rows:
            wc = (r.get("word_count") or "").strip()
            try:
                wc_vals.append(int(wc))
            except Exception:
                ok_all = False
                break
        if ok_all and wc_vals:
            avg_wc = int(round(sum(wc_vals) / len(wc_vals)))
            med_wc = median_int(wc_vals)
            if stats_obj.get("avg_word_count") == avg_wc and stats_obj.get("median_word_count") == med_wc:
                scores["stats_avg_median_consistency"] = 1.0

        # pages_by_year from records.csv (non-empty years only)
        pby_expected = {}
        for r in rows:
            py = (r.get("publication_year") or "").strip()
            if py:
                pby_expected[py] = pby_expected.get(py, 0) + 1
        pby_stats = stats_obj.get("pages_by_year")
        if isinstance(pby_stats, dict):
            # If there are no years, allow empty object; otherwise must match
            if pby_expected:
                if pby_stats == pby_expected:
                    scores["stats_pages_by_year_consistency"] = 1.0
            else:
                if pby_stats == {}:
                    scores["stats_pages_by_year_consistency"] = 1.0

    # keyword_counts and top_keyword_pairs consistency based on cleaned texts
    if stats_obj is not None and isinstance(stats_obj, dict) and keywords is not None and clean_files:
        # Build per-file keyword presence
        per_file_kw_sets = []
        for cf in clean_files:
            txt = safe_read_text(cf)
            if txt is None:
                per_file_kw_sets = []
                break
            per_file_kw_sets.append(compute_keyword_presence(txt, keywords))

        if per_file_kw_sets:
            # keyword_counts
            expected_kc = {kw: 0 for kw in keywords}
            for s in per_file_kw_sets:
                for kw in s:
                    expected_kc[kw] += 1
            kc_stats = stats_obj.get("keyword_counts", {})
            kc_ok = isinstance(kc_stats, dict) and all(k in kc_stats for k in expected_kc)
            if kc_ok:
                # exact match
                if all(isinstance(kc_stats.get(k), int) and kc_stats.get(k) == expected_kc[k] for k in expected_kc):
                    scores["stats_keyword_counts_consistency"] = 1.0

            # top_keyword_pairs
            expected_top_pairs = compute_top_pairs(per_file_kw_sets, top_n=10)
            tkp_stats = stats_obj.get("top_keyword_pairs", [])
            tkp_ok = isinstance(tkp_stats, list)
            if tkp_ok:
                # Allow up to 10 items; must match order and content exactly with expected
                if expected_top_pairs[:len(tkp_stats)] == tkp_stats and len(tkp_stats) <= 10:
                    # Also enforce that if there are fewer than expected, they cut at length
                    scores["stats_top_keyword_pairs_consistency"] = 1.0

        # pages_by_tld sum equals total_pages (redundant cross-check using stats already computed)
        # This is covered by stats_total_pages_consistency and stats_pages_by_tld_consistency.

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()