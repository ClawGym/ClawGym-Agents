import json
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, None
    except Exception as e:
        return None, str(e)


def _safe_read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if not text:
            return None, None, "empty_csv"
        reader = csv.DictReader(text)
        headers = reader.fieldnames
        if headers is None:
            return None, None, "no_headers"
        rows = [row for row in reader]
        return headers, rows, None
    except Exception as e:
        return None, None, str(e)


def _is_official_domain(domain: Optional[str], patterns: List[str]) -> bool:
    if not domain:
        return False
    d = domain.lower()
    for pat in patterns:
        if pat.lower() in d:
            return True
    return False


def _infer_source_org(domain: Optional[str]) -> Optional[str]:
    if not domain:
        return None
    d = domain.lower()
    if "fao.org" in d:
        return "FAO"
    if any(p in d for p in ["gov", "ministry", "agric"]):
        return "Government/Extension"
    return None


def _ext_from_path(p: Path) -> Optional[str]:
    name = p.name.lower()
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".html") or name.endswith(".htm"):
        return "html"
    return None


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        v = value.strip()
        if v.isdigit():
            try:
                return int(v)
            except Exception:
                return None
    return None


def _recompute_score(doc: Dict[str, Any], criteria: Dict[str, Any]) -> Optional[int]:
    try:
        rules = criteria.get("scoring_rules", {})
        points_map = rules.get("points", {})
        score = 0
        # keyword_threshold
        kw_list = doc.get("matched_keywords", [])
        if isinstance(kw_list, list):
            kw_count = len(kw_list)
        else:
            kw_count = 0
        kw_threshold = rules.get("keyword_threshold", 0)
        if kw_count >= kw_threshold:
            score += int(points_map.get("keyword_threshold", 0))

        # official_domain
        domain = doc.get("source_domain")
        official_patterns = criteria.get("official_domain_patterns", [])
        if _is_official_domain(domain, official_patterns):
            score += int(points_map.get("official_domain", 0))

        # recent_publication_year
        min_year = rules.get("min_publication_year", 0)
        year_val = _coerce_int(doc.get("publication_year"))
        if year_val is not None and year_val >= int(min_year):
            score += int(points_map.get("recent_publication_year", 0))

        # file_type_known
        known_types = set([t.lower() for t in criteria.get("file_types_considered_known", [])])
        file_type = doc.get("file_type", "")
        if isinstance(file_type, str) and file_type.lower() in known_types:
            score += int(points_map.get("file_type_known", 0))

        # section_terms_present
        section_terms = doc.get("matched_section_terms", [])
        if isinstance(section_terms, list) and len(section_terms) > 0:
            score += int(points_map.get("section_terms_present", 0))

        return score
    except Exception:
        return None


def _recompute_classification(score: Optional[int], criteria: Dict[str, Any]) -> Optional[str]:
    try:
        if score is None:
            return None
        threshold = criteria.get("scoring_rules", {}).get("actionable_threshold", None)
        if threshold is None:
            return None
        return "actionable" if score >= int(threshold) else "reference-only"
    except Exception:
        return None


def _bool_from_csv(value: str) -> Optional[bool]:
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("true", "t", "yes", "y", "1"):
        return True
    if v in ("false", "f", "no", "n", "0"):
        return False
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "docs_count_minimum": 0.0,
        "fao_minimum_count": 0.0,
        "government_minimum_count": 0.0,
        "official_domains_only": 0.0,
        "doc_ids_unique": 0.0,
        "source_org_inference_correct": 0.0,
        "download_paths_exist_and_under_data_raw": 0.0,
        "file_type_matches_extension_known": 0.0,
        "matched_fields_types_valid": 0.0,
        "score_recomputed_matches": 0.0,
        "classification_consistent_with_threshold": 0.0,
        "critique_csv_columns_and_rows": 0.0,
        "critique_csv_consistency": 0.0,
        "review_mentions_actionable_docs": 0.0,
        "review_mentions_reference_docs": 0.0,
        "search_log_includes_queries_and_files": 0.0,
    }

    # Load criteria
    criteria_path = workspace / "input" / "criteria.json"
    criteria, criteria_err = _safe_load_json(criteria_path)
    if criteria is None:
        # Cannot compute much without criteria; return zeros.
        return scores

    # Load docs_metadata
    docs_path = workspace / "output" / "docs_metadata.json"
    docs, docs_err = _safe_load_json(docs_path)
    if not isinstance(docs, list):
        docs = []

    # docs_count_minimum
    if len(docs) >= 5:
        scores["docs_count_minimum"] = 1.0

    # Compute FAO and government counts based on source_domain
    fao_count = 0
    gov_count = 0
    official_patterns = criteria.get("official_domain_patterns", [])
    for doc in docs:
        domain = (doc.get("source_domain") or "")
        dlow = domain.lower()
        if "fao.org" in dlow:
            fao_count += 1
        if any(p in dlow for p in ["gov", "ministry", "agric"]):
            gov_count += 1
    scores["fao_minimum_count"] = 1.0 if fao_count >= 3 else 0.0
    scores["government_minimum_count"] = 1.0 if gov_count >= 2 else 0.0

    # official_domains_only
    if docs:
        official_ok = 0
        for doc in docs:
            domain = doc.get("source_domain")
            if _is_official_domain(domain, official_patterns):
                official_ok += 1
        scores["official_domains_only"] = official_ok / max(1, len(docs))
    else:
        scores["official_domains_only"] = 0.0

    # doc_ids_unique
    doc_ids = []
    for doc in docs:
        doc_ids.append(doc.get("doc_id"))
    if docs and None not in doc_ids and len(doc_ids) == len(set(doc_ids)):
        scores["doc_ids_unique"] = 1.0
    else:
        scores["doc_ids_unique"] = 0.0 if docs else 0.0

    # source_org_inference_correct
    if docs:
        correct = 0
        total = 0
        for doc in docs:
            total += 1
            inferred = _infer_source_org(doc.get("source_domain"))
            reported = doc.get("source_org")
            if inferred is not None and reported == inferred:
                correct += 1
        scores["source_org_inference_correct"] = correct / max(1, total)
    else:
        scores["source_org_inference_correct"] = 0.0

    # download_paths_exist_and_under_data_raw and file_type_matches_extension_known
    raw_dir = workspace / "data" / "raw"
    if docs:
        exist_and_under = 0
        type_match = 0
        total = 0
        for doc in docs:
            total += 1
            dl_path_str = doc.get("download_path")
            if isinstance(dl_path_str, str):
                dl_path = workspace / dl_path_str
                # Check within raw_dir
                under_raw = False
                try:
                    dl_path_res = dl_path.resolve()
                    raw_res = raw_dir.resolve()
                    try:
                        # Check dl_path is under raw_res (or equal)
                        dl_path_res.relative_to(raw_res)
                        under_raw = True
                    except Exception:
                        under_raw = False
                except Exception:
                    under_raw = False
                # Check exists
                exists = dl_path.is_file()
                if under_raw and exists:
                    exist_and_under += 1
                # File type match and known
                ext = _ext_from_path(dl_path)
                reported_type = doc.get("file_type")
                known_types = [t.lower() for t in criteria.get("file_types_considered_known", [])]
                if ext is not None and isinstance(reported_type, str):
                    if reported_type.lower() == ext and reported_type.lower() in known_types:
                        type_match += 1
            # If download_path missing or invalid, don't increment counts
        scores["download_paths_exist_and_under_data_raw"] = exist_and_under / max(1, len(docs))
        scores["file_type_matches_extension_known"] = type_match / max(1, len(docs))
    else:
        scores["download_paths_exist_and_under_data_raw"] = 0.0
        scores["file_type_matches_extension_known"] = 0.0

    # matched_fields_types_valid
    if docs:
        ok = 0
        for doc in docs:
            mk = doc.get("matched_keywords")
            ms = doc.get("matched_section_terms")
            title = doc.get("title", "")
            year = doc.get("publication_year", None)
            mk_ok = isinstance(mk, list) and all(isinstance(x, str) for x in mk)
            ms_ok = isinstance(ms, list) and all(isinstance(x, str) for x in ms)
            title_ok = isinstance(title, str)
            year_ok = (year is None) or isinstance(year, int) or (isinstance(year, str) and _coerce_int(year) is not None)
            if mk_ok and ms_ok and title_ok and year_ok:
                ok += 1
        scores["matched_fields_types_valid"] = ok / max(1, len(docs))
    else:
        scores["matched_fields_types_valid"] = 0.0

    # score_recomputed_matches and classification_consistent_with_threshold
    if docs:
        score_ok = 0
        class_ok = 0
        for doc in docs:
            recomputed_score = _recompute_score(doc, criteria)
            reported_score = doc.get("score", None)
            # consider int reported_score; allow numeric types
            rs_ok = isinstance(reported_score, int)
            # Sometimes reported score may be string; try to coerce
            if not rs_ok and isinstance(reported_score, str) and reported_score.strip().isdigit():
                try:
                    reported_score = int(reported_score.strip())
                    rs_ok = True
                except Exception:
                    rs_ok = False
            if rs_ok and recomputed_score is not None and int(reported_score) == int(recomputed_score):
                score_ok += 1
            recomputed_class = _recompute_classification(recomputed_score, criteria)
            rep_class = doc.get("classification", None)
            if isinstance(rep_class, str) and recomputed_class is not None and rep_class.strip().lower() == recomputed_class:
                class_ok += 1
        scores["score_recomputed_matches"] = score_ok / max(1, len(docs))
        scores["classification_consistent_with_threshold"] = class_ok / max(1, len(docs))
    else:
        scores["score_recomputed_matches"] = 0.0
        scores["classification_consistent_with_threshold"] = 0.0

    # critique_summary.csv checks
    csv_path = workspace / "output" / "critique_summary.csv"
    headers, rows, csv_err = _safe_read_csv(csv_path)
    csv_columns_ok = False
    if headers is not None:
        expected_cols = [
            "doc_id",
            "source_org",
            "score",
            "classification",
            "num_matched_keywords",
            "has_section_terms",
            "is_official_domain",
            "is_recent",
        ]
        csv_columns_ok = headers == expected_cols
        if csv_columns_ok and docs and len(rows) == len(docs):
            scores["critique_csv_columns_and_rows"] = 1.0
        else:
            scores["critique_csv_columns_and_rows"] = 0.0
    else:
        scores["critique_csv_columns_and_rows"] = 0.0

    # critique_csv_consistency
    if rows is not None and docs:
        # Map docs by doc_id
        doc_by_id: Dict[str, Dict[str, Any]] = {}
        for d in docs:
            did = d.get("doc_id")
            if isinstance(did, str):
                doc_by_id[did] = d
        consistent = 0
        total = 0
        rules = criteria.get("scoring_rules", {})
        min_year = rules.get("min_publication_year", 0)
        for row in rows:
            total += 1
            rid = row.get("doc_id")
            if rid not in doc_by_id:
                continue
            d = doc_by_id[rid]
            # Check fields
            row_source_org = row.get("source_org", "")
            row_score = row.get("score", "")
            row_class = row.get("classification", "")
            row_num_kw = row.get("num_matched_keywords", "")
            row_has_sections = row.get("has_section_terms", "")
            row_is_official = row.get("is_official_domain", "")
            row_is_recent = row.get("is_recent", "")

            # Compute from d
            expected_source_org = d.get("source_org", "")
            expected_score = _recompute_score(d, criteria)
            expected_class = _recompute_classification(expected_score, criteria)
            mk = d.get("matched_keywords", [])
            ms = d.get("matched_section_terms", [])
            domain = d.get("source_domain")
            official = _is_official_domain(domain, criteria.get("official_domain_patterns", []))
            year_val = _coerce_int(d.get("publication_year"))
            recent = (year_val is not None) and (year_val >= int(min_year))

            # Compare
            ok = True
            # source_org
            if row_source_org != expected_source_org:
                ok = False
            # score
            try:
                row_score_int = int(str(row_score).strip())
            except Exception:
                row_score_int = None
            if expected_score is None or row_score_int is None or row_score_int != int(expected_score):
                ok = False
            # classification
            if isinstance(row_class, str):
                if expected_class is None or row_class.strip().lower() != expected_class:
                    ok = False
            else:
                ok = False
            # num_matched_keywords
            try:
                row_num_kw_int = int(str(row_num_kw).strip())
            except Exception:
                row_num_kw_int = None
            if row_num_kw_int is None or row_num_kw_int != (len(mk) if isinstance(mk, list) else 0):
                ok = False
            # has_section_terms
            row_has_sections_bool = _bool_from_csv(str(row_has_sections))
            if row_has_sections_bool is None or row_has_sections_bool != (len(ms) > 0 if isinstance(ms, list) else False):
                ok = False
            # is_official_domain
            row_is_official_bool = _bool_from_csv(str(row_is_official))
            if row_is_official_bool is None or row_is_official_bool != official:
                ok = False
            # is_recent
            row_is_recent_bool = _bool_from_csv(str(row_is_recent))
            if row_is_recent_bool is None or row_is_recent_bool != recent:
                ok = False

            if ok:
                consistent += 1
        scores["critique_csv_consistency"] = consistent / max(1, len(rows))
    else:
        scores["critique_csv_consistency"] = 0.0

    # review.md checks
    review_path = workspace / "output" / "review.md"
    review_text = _safe_read_text(review_path) or ""
    if docs and review_text:
        # actionable and reference-only sets
        actionable_ids = []
        reference_ids = []
        for d in docs:
            rec_score = _recompute_score(d, criteria)
            rec_class = _recompute_classification(rec_score, criteria)
            if rec_class == "actionable":
                if isinstance(d.get("doc_id"), str):
                    actionable_ids.append(d["doc_id"])
            elif rec_class == "reference-only":
                if isinstance(d.get("doc_id"), str):
                    reference_ids.append(d["doc_id"])
        # Check mentions
        review_lower = review_text.lower()
        mentions_actionable_word = "actionable" in review_lower
        mentions_reference_word = "reference" in review_lower
        all_actionable_listed = all((aid in review_text) for aid in actionable_ids)
        all_reference_listed = all((rid in review_text) for rid in reference_ids)
        # also check that reasons likely included by referencing rule-based checks
        reason_tokens = ["score", "keyword", "official", "recent", "section", "threshold"]
        mentions_reason = any(tok in review_lower for tok in reason_tokens)

        scores["review_mentions_actionable_docs"] = 1.0 if (mentions_actionable_word and all_actionable_listed and mentions_reason) else 0.0
        scores["review_mentions_reference_docs"] = 1.0 if (mentions_reference_word and all_reference_listed and mentions_reason) else 0.0
    else:
        scores["review_mentions_actionable_docs"] = 0.0
        scores["review_mentions_reference_docs"] = 0.0

    # search_log.txt checks
    search_log_path = workspace / "output" / "search_log.txt"
    search_log = _safe_read_text(search_log_path) or ""
    if docs and search_log:
        # Must include at least one query line (contains 'query' or 'search')
        lower_log = search_log.lower()
        has_query_line = ("query" in lower_log) or ("search" in lower_log)
        # Must list each downloaded file and its source domain
        listed_count = 0
        for d in docs:
            dl = d.get("download_path", "")
            dom = d.get("source_domain", "")
            if isinstance(dl, str) and isinstance(dom, str) and (dl in search_log) and (dom in search_log):
                listed_count += 1
        fraction_listed = listed_count / max(1, len(docs))
        scores["search_log_includes_queries_and_files"] = fraction_listed if has_query_line else 0.0
    else:
        scores["search_log_includes_queries_and_files"] = 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()