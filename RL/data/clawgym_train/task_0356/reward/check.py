import json
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from statistics import median
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any


def _slugify_company(name: str) -> str:
    return re.sub(r"\s+", "-", name.strip().lower())


def _safe_read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_companies(workspace: Path) -> Optional[List[Dict[str, str]]]:
    path = workspace / "input" / "companies.csv"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            rows = [dict(r) for r in rdr]
        # Basic header validation
        if not rows and rdr.fieldnames is None:
            return None
        headers = [h.strip().lower() for h in (rdr.fieldnames or [])]
        if "company" not in headers or "domain" not in headers:
            return None
        # Normalize keys
        norm_rows = []
        for r in rows:
            company = r.get("company")
            domain = r.get("domain")
            if company is None or domain is None:
                return None
            norm_rows.append({"company": company.strip(), "domain": domain.strip()})
        return norm_rows
    except Exception:
        return None


def _parse_yaml_keywords(workspace: Path) -> Optional[List[str]]:
    path = workspace / "input" / "keywords.yaml"
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    # Minimal YAML parser for expected structure:
    # keywords:
    #   - term1
    #   - term2
    lines = text.splitlines()
    in_list = False
    keywords: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not in_list:
            if stripped.startswith("keywords:"):
                # If inline list (unlikely), try to parse
                after = stripped[len("keywords:"):].strip()
                if after.startswith("[") and after.endswith("]"):
                    # parse comma-separated items
                    inside = after[1:-1].strip()
                    if inside:
                        parts = [p.strip() for p in inside.split(",")]
                        # remove possible quotes
                        for p in parts:
                            p = p.strip()
                            if (p.startswith("'") and p.endswith("'")) or (p.startswith('"') and p.endswith('"')):
                                p = p[1:-1]
                            if p:
                                keywords.append(p)
                        return keywords if keywords else None
                in_list = True
            continue
        else:
            if stripped.startswith("-"):
                item = stripped[1:].strip()
                # remove possible quotes
                if (item.startswith("'") and item.endswith("'")) or (item.startswith('"') and item.endswith('"')):
                    item = item[1:-1]
                if item:
                    keywords.append(item)
            else:
                # end of list
                break
    return keywords if keywords else None


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    if not path.exists():
        return None
    try:
        records: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                obj = json.loads(s)
                if not isinstance(obj, dict):
                    return None
                records.append(obj)
        return records
    except Exception:
        return None


def _compile_keyword_patterns(keywords: List[str]) -> Dict[str, re.Pattern]:
    patterns: Dict[str, re.Pattern] = {}
    for kw in keywords:
        pat = re.compile(r"\b" + re.escape(kw) + r"\b", flags=re.IGNORECASE | re.UNICODE)
        patterns[kw] = pat
    return patterns


def _count_keywords_in_text(text: str, patterns: Dict[str, re.Pattern]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for kw, pat in patterns.items():
        counts[kw] = len(pat.findall(text))
    return counts


def _validate_date(date_str: Optional[str]) -> Tuple[bool, Optional[int]]:
    if date_str is None:
        return True, None
    if isinstance(date_str, str):
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            return True, dt.year
        except Exception:
            return False, None
    return False, None


def _parse_float(s: Any) -> Optional[float]:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


def _parse_int(s: Any) -> Optional[int]:
    if s is None:
        return None
    if isinstance(s, int):
        return s
    try:
        return int(str(s).strip())
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "metadata_jsonl_valid": 0.0,
        "files_linked_and_exist": 0.0,
        "keyword_counts_match_text": 0.0,
        "urls_on_official_domains": 0.0,
        "years_within_range_and_consistent": 0.0,
        "search_log_valid_and_coverage": 0.0,
        "summary_csv_valid": 0.0,
        "summary_metrics_correct": 0.0,
        "consistency_between_metadata_and_summary": 0.0,
        "memo_structure_and_content": 0.0,
    }

    # Load inputs
    companies_rows = _load_companies(workspace)
    keywords = _parse_yaml_keywords(workspace)
    companies_map: Dict[str, str] = {}
    companies_list: List[str] = []
    if companies_rows:
        for r in companies_rows:
            companies_map[r["company"]] = r["domain"]
            companies_list.append(r["company"])
    # Load metadata jsonl
    metadata_path = workspace / "output" / "metadata" / "press_releases.jsonl"
    metadata_records = _load_jsonl(metadata_path)
    # Validate metadata structure
    metadata_valid = False
    metadata_details_ok: List[bool] = []
    if metadata_records is not None and companies_map and keywords:
        # Validate each record fields
        required_fields = {"company", "domain", "url", "page_title", "published_date", "year", "company_slug", "basename", "keyword_hits", "total_keyword_hits"}
        metadata_valid = True
        for rec in metadata_records:
            # Required keys
            if set(rec.keys()).issuperset(required_fields) is False:
                metadata_valid = False
                break
            company = rec.get("company")
            domain = rec.get("domain")
            url = rec.get("url")
            page_title = rec.get("page_title", None)
            published_date = rec.get("published_date", None)
            year = rec.get("year")
            company_slug = rec.get("company_slug")
            basename = rec.get("basename")
            keyword_hits = rec.get("keyword_hits")
            total_keyword_hits = rec.get("total_keyword_hits")

            # Basic type checks
            if not isinstance(company, str) or company.strip() == "":
                metadata_valid = False
                break
            if company not in companies_map:
                metadata_valid = False
                break
            if not isinstance(domain, str) or domain.strip() == "":
                metadata_valid = False
                break
            if companies_map.get(company) != domain:
                metadata_valid = False
                break
            if not isinstance(url, str) or url.strip() == "":
                metadata_valid = False
                break
            if not (isinstance(page_title, (str, type(None)))):
                metadata_valid = False
                break
            ok_date, date_year = _validate_date(published_date)
            if not ok_date:
                metadata_valid = False
                break
            if not isinstance(year, int):
                metadata_valid = False
                break
            if not isinstance(company_slug, str) or company_slug != _slugify_company(company):
                metadata_valid = False
                break
            if not isinstance(basename, str) or basename.strip() == "":
                metadata_valid = False
                break
            if not isinstance(keyword_hits, dict):
                metadata_valid = False
                break
            # keyword_hits keys should exactly match keywords
            kw_set = set(keywords)
            if set(keyword_hits.keys()) != kw_set:
                metadata_valid = False
                break
            # values ints >= 0
            for v in keyword_hits.values():
                if not isinstance(v, int) or v < 0:
                    metadata_valid = False
                    break
            if not isinstance(total_keyword_hits, int) or total_keyword_hits < 0:
                metadata_valid = False
                break
            # Not checking sums here; covered in a later check
            if date_year is not None and date_year != year:
                # year must match published_date year if provided
                metadata_valid = False
                break
            metadata_details_ok.append(True)
    scores["metadata_jsonl_valid"] = 1.0 if (metadata_valid and len(metadata_details_ok) == len(metadata_records or [])) and len(metadata_records or []) > 0 else 0.0

    # Files existence and consistency check for HTML and text
    files_exist_fraction = 0.0
    if metadata_valid and metadata_records:
        total = len(metadata_records)
        hits = 0
        for rec in metadata_records:
            company = rec["company"]
            company_slug = rec["company_slug"]
            basename = rec["basename"]
            # Expected paths
            html_path = workspace / "output" / "raw_html" / company_slug / f"{basename}.html"
            txt_path = workspace / "output" / "text" / company_slug / f"{basename}.txt"
            if html_path.exists() and txt_path.exists():
                # Also ensure the slug matches the company
                if company_slug == _slugify_company(company):
                    hits += 1
        files_exist_fraction = hits / total if total > 0 else 0.0
    scores["files_linked_and_exist"] = files_exist_fraction if metadata_valid else 0.0

    # Keyword counts vs text
    kw_counts_fraction = 0.0
    if metadata_valid and metadata_records and keywords:
        total = len(metadata_records)
        hits = 0
        patterns = _compile_keyword_patterns(keywords)
        for rec in metadata_records:
            company_slug = rec["company_slug"]
            basename = rec["basename"]
            txt_path = workspace / "output" / "text" / company_slug / f"{basename}.txt"
            text = _safe_read_text(txt_path)
            if text is None:
                continue
            recomputed = _count_keywords_in_text(text, patterns)
            if recomputed == rec["keyword_hits"] and sum(recomputed.values()) == rec["total_keyword_hits"]:
                hits += 1
        kw_counts_fraction = hits / total if total > 0 else 0.0
    scores["keyword_counts_match_text"] = kw_counts_fraction if metadata_valid else 0.0

    # URLs on official domains
    url_domain_fraction = 0.0
    if metadata_valid and metadata_records:
        total = len(metadata_records)
        hits = 0
        for rec in metadata_records:
            domain = rec["domain"]
            url = rec["url"]
            try:
                parsed = urlparse(url)
                host = parsed.hostname or ""
                scheme_ok = parsed.scheme in ("http", "https")
                # Ensure host ends with domain
                domain_ok = host.endswith(domain)
                if scheme_ok and domain_ok:
                    hits += 1
            except Exception:
                pass
        url_domain_fraction = hits / total if total > 0 else 0.0
    scores["urls_on_official_domains"] = url_domain_fraction if metadata_valid else 0.0

    # Years within range and consistent with published_date
    years_fraction = 0.0
    if metadata_valid and metadata_records:
        total = len(metadata_records)
        hits = 0
        for rec in metadata_records:
            year = rec["year"]
            published_date = rec.get("published_date")
            ok, dyear = _validate_date(published_date)
            if not ok:
                continue
            if year in (2022, 2023, 2024) and (dyear is None or dyear == year):
                hits += 1
        years_fraction = hits / total if total > 0 else 0.0
    scores["years_within_range_and_consistent"] = years_fraction if metadata_valid else 0.0

    # Search log validation and coverage
    search_log_path = workspace / "output" / "logs" / "search_log.jsonl"
    search_records = _load_jsonl(search_log_path)
    search_score = 0.0
    if search_records is not None and companies_map:
        # Structure validation
        structure_valid_count = 0
        for rec in search_records:
            if not isinstance(rec, dict):
                continue
            company = rec.get("company")
            domain = rec.get("domain")
            engine = rec.get("engine")
            query = rec.get("query")
            inspected_urls = rec.get("inspected_urls")
            selected_urls = rec.get("selected_urls")
            if not isinstance(company, str) or company not in companies_map:
                continue
            if not isinstance(domain, str) or domain != companies_map.get(company):
                continue
            if not isinstance(engine, str) or engine.strip() == "":
                continue
            if not isinstance(query, str) or query.strip() == "":
                continue
            # Must contain site: and domain
            if "site:" not in query or domain not in query:
                continue
            if not isinstance(inspected_urls, list) or not isinstance(selected_urls, list):
                continue
            if len(inspected_urls) > 10:
                continue
            # Each must be strings
            if any(not isinstance(u, str) for u in inspected_urls):
                continue
            if any(not isinstance(u, str) for u in selected_urls):
                continue
            # selected subset of inspected
            if not set(selected_urls).issubset(set(inspected_urls)):
                continue
            structure_valid_count += 1
        structure_ok = (structure_valid_count == len(search_records)) and structure_valid_count > 0
        # Ensure at least one query per company present in metadata
        companies_in_meta = set([rec["company"] for rec in metadata_records]) if (metadata_records and metadata_valid) else set()
        companies_in_log = set([rec.get("company") for rec in search_records if isinstance(rec.get("company"), str)])
        companies_covered = companies_in_meta.issubset(companies_in_log) if companies_in_meta else False

        # Coverage: all metadata URLs appear at least once in selected_urls in logs
        selected_union: set = set()
        for rec in search_records:
            sel = rec.get("selected_urls")
            if isinstance(sel, list):
                for u in sel:
                    if isinstance(u, str):
                        selected_union.add(u)
        meta_urls: set = set()
        if metadata_valid and metadata_records:
            for r in metadata_records:
                url = r.get("url")
                if isinstance(url, str):
                    meta_urls.add(url)
        coverage_ok = meta_urls.issubset(selected_union) if meta_urls else False

        # Combine: structure (including company coverage) and coverage of URLs
        structure_score = 1.0 if (structure_ok and companies_covered) else 0.0
        coverage_score = 1.0 if coverage_ok else 0.0
        search_score = 0.5 * structure_score + 0.5 * coverage_score
    else:
        search_score = 0.0
    scores["search_log_valid_and_coverage"] = search_score

    # Summary CSV validation
    summary_path = workspace / "output" / "summary" / "keyword_stats.csv"
    summary_rows: Optional[List[Dict[str, Any]]] = None
    summary_valid = False
    if summary_path.exists():
        try:
            with summary_path.open("r", encoding="utf-8") as f:
                rdr = csv.DictReader(f)
                rows = [dict(r) for r in rdr]
            headers = [h.strip() for h in (rdr.fieldnames or [])]
            required_cols = ["company", "num_releases", "total_keyword_hits", "avg_hits_per_release", "median_avg_hits_across_companies", "ratio_vs_median", "signal"]
            if all(c in headers for c in required_cols) and rows:
                # Check ALL row last
                last_row = rows[-1]
                if last_row.get("company") == "ALL":
                    # Ratio and signal blank for ALL
                    ratio_all = last_row.get("ratio_vs_median", "")
                    signal_all = last_row.get("signal", "")
                    if (ratio_all is None or str(ratio_all).strip() == "") and (signal_all is None or str(signal_all).strip() == ""):
                        # Ensure one row per input company (if available)
                        if companies_list:
                            companies_in_summary = [r.get("company") for r in rows[:-1]]  # exclude ALL
                            companies_present_ok = set(companies_in_summary) == set(companies_list)
                        else:
                            companies_present_ok = True
                        summary_rows = rows
                        summary_valid = companies_present_ok
        except Exception:
            summary_valid = False
    scores["summary_csv_valid"] = 1.0 if summary_valid else 0.0

    # Consistency summary vs metadata and metrics correctness
    metrics_score = 0.0
    consistency_score = 0.0
    if summary_valid and metadata_valid and metadata_records and companies_list:
        # Compute per-company aggregates from metadata
        per_company_pages: Dict[str, List[Dict[str, Any]]] = {}
        for r in metadata_records:
            per_company_pages.setdefault(r["company"], []).append(r)
        per_company_num = {c: len(per_company_pages.get(c, [])) for c in companies_list}
        per_company_total_hits = {c: sum([p["total_keyword_hits"] for p in per_company_pages.get(c, [])]) for c in companies_list}
        per_company_avg = {}
        for c in companies_list:
            n = per_company_num[c]
            per_company_avg[c] = (per_company_total_hits[c] / n) if n > 0 else 0.0
        # Median across companies
        median_across = median([per_company_avg[c] for c in companies_list]) if companies_list else 0.0

        # Map summary by company
        summary_by_company: Dict[str, Dict[str, Any]] = {row["company"]: row for row in summary_rows if row.get("company") and row.get("company") != "ALL"}  # type: ignore

        # Check each company metrics
        company_checks: List[float] = []
        for c in companies_list:
            row = summary_by_company.get(c)
            if row is None:
                company_checks.append(0.0)
                continue
            num_releases = _parse_int(row.get("num_releases"))
            total_hits = _parse_int(row.get("total_keyword_hits"))
            avg_hits = _parse_float(row.get("avg_hits_per_release"))
            median_rep = _parse_float(row.get("median_avg_hits_across_companies"))
            ratio_vs_median = _parse_float(row.get("ratio_vs_median"))
            signal = row.get("signal", "").strip()

            ok = True
            if num_releases is None or num_releases != per_company_num[c]:
                ok = False
            if total_hits is None or total_hits != per_company_total_hits[c]:
                ok = False
            # Allow small float tolerance
            def _close(a: Optional[float], b: float, tol: float = 1e-6) -> bool:
                return (a is not None) and (abs(a - b) <= tol)

            if not _close(avg_hits, per_company_avg[c]):
                ok = False
            if not _close(median_rep, median_across):
                ok = False
            # Ratio check only if median > 0
            if median_across > 0:
                expected_ratio = per_company_avg[c] / median_across if median_across != 0 else None
                if expected_ratio is None or not _close(ratio_vs_median, expected_ratio):
                    ok = False
            # Signal rule
            expected_signal = "Aggressive expansion signal" if (per_company_num[c] >= 3 and per_company_avg[c] > 1.5 * median_across) else "Neutral"
            if signal != expected_signal:
                ok = False
            company_checks.append(1.0 if ok else 0.0)

        # ALL row checks
        all_row = summary_rows[-1]
        all_num_releases = _parse_int(all_row.get("num_releases"))
        all_total_hits = _parse_int(all_row.get("total_keyword_hits"))
        all_avg = _parse_float(all_row.get("avg_hits_per_release"))

        expected_all_num = sum(per_company_num.values())
        expected_all_total = sum(per_company_total_hits.values())
        expected_all_avg = (expected_all_total / expected_all_num) if expected_all_num > 0 else 0.0

        all_ok = True
        if all_num_releases is None or all_num_releases != expected_all_num:
            all_ok = False
        if all_total_hits is None or all_total_hits != expected_all_total:
            all_ok = False
        if all_avg is None or abs(all_avg - expected_all_avg) > 1e-6:
            all_ok = False

        # consistency score: compare num_releases and total_keyword_hits only
        consistency_checks: List[float] = []
        for c in companies_list:
            row = summary_by_company.get(c)
            if row is None:
                consistency_checks.append(0.0)
                continue
            num_releases = _parse_int(row.get("num_releases"))
            total_hits = _parse_int(row.get("total_keyword_hits"))
            ok = (num_releases == per_company_num[c]) and (total_hits == per_company_total_hits[c])
            consistency_checks.append(1.0 if ok else 0.0)
        if all_row:
            consistency_checks.append(1.0 if all_ok else 0.0)

        metrics_score = (sum(company_checks) + (1.0 if all_ok else 0.0)) / (len(company_checks) + 1) if company_checks else 0.0
        consistency_score = (sum(consistency_checks) / len(consistency_checks)) if consistency_checks else 0.0

    scores["summary_metrics_correct"] = metrics_score
    scores["consistency_between_metadata_and_summary"] = consistency_score

    # Memo validation
    memo_path = workspace / "output" / "report" / "expansion_signals_memo.md"
    memo_text = _safe_read_text(memo_path)
    memo_score = 0.0
    if memo_text is not None and summary_valid:
        # Word limit <= 400
        words = re.findall(r"\S+", memo_text)
        exists_and_limit = 1.0 if (len(words) <= 400 and len(words) > 0) else 0.0

        # Method summary presence: look for mentions of search and filtering on domains and press/news/IR
        method_ok = 0.0
        lower = memo_text.lower()
        if ("site:" in lower or "search" in lower or "query" in lower) and ("press" in lower or "news" in lower or "ir" in lower) and ("domain" in lower or "official" in lower):
            method_ok = 1.0

        # Per-company metrics presence: company name and signal occurrence
        per_company_ok_count = 0
        flagged_company_names: List[str] = []
        if summary_valid and summary_rows:
            for row in summary_rows:
                comp = row.get("company")
                if comp == "ALL":
                    continue
                signal = row.get("signal", "")
                name_present = comp in memo_text
                signal_present = signal in memo_text
                if name_present and signal_present:
                    per_company_ok_count += 1
                # track flagged
                if signal == "Aggressive expansion signal":
                    flagged_company_names.append(comp)
        per_company_ok = (per_company_ok_count / len(companies_list)) if companies_list else 0.0

        # Flagged companies mentioned in judgement
        if flagged_company_names:
            flags_ok = 1.0 if all(name in memo_text for name in flagged_company_names) else 0.0
        else:
            # If none flagged, don't penalize
            flags_ok = 1.0

        # Combine: weights: existence/limit 0.25, method 0.25, per-company 0.25, flags 0.25
        memo_score = 0.25 * exists_and_limit + 0.25 * method_ok + 0.25 * per_company_ok + 0.25 * flags_ok
    else:
        memo_score = 0.0
    scores["memo_structure_and_content"] = memo_score

    return scores


def main() -> None:
        workspace = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade(transcript=[], workspace_path=workspace)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()