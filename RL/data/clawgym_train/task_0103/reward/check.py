import json
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json(path: Path):
    try:
        return json.loads(_read_text(path))
    except Exception:
        return None


def _read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return rows, reader.fieldnames
    except Exception:
        return None, None


def _parse_polities_csv(path: Path):
    rows, _ = _read_csv_dicts(path)
    if not rows:
        return []
    polities = []
    for r in rows:
        if "polity" in r and r["polity"]:
            polities.append(r["polity"])
    return polities


def _safe_iso8601(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    # Try Python's ISO parser
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return True
    except Exception:
        pass
    # Fallback regex for ISO8601-like
    iso_regex = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:\d{2})?$")
    return bool(iso_regex.match(s))


def _compute_expected_queries(polity: str, templates: list) -> set:
    expected = set()
    for t in templates:
        expected.add(t.replace("{polity}", polity))
    return expected


def _parse_year(s: str):
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    if re.fullmatch(r"\d{4}", s):
        try:
            return int(s)
        except Exception:
            return None
    return None


def _domain_from_url(url: str):
    try:
        p = urlparse(url)
        if not p.scheme or not p.netloc:
            return None, None
        netloc = p.netloc.lower()
        return netloc, p
    except Exception:
        return None, None


def _get_weight(domain: str, preferred_domains: dict) -> int:
    if not domain:
        return 1
    # domain in CSV is expected to be a suffix like "harvard.edu"
    d = domain.lower()
    return int(preferred_domains.get(d, 1))


def _sort_key(row: dict, preferred_domains: dict, tie_breaker: str):
    domain = (row.get("domain") or "").strip().lower()
    weight = _get_weight(domain, preferred_domains)
    year = _parse_year(row.get("publication_year") or "")
    # None treated as lowest (i.e., -1)
    year_sort = year if isinstance(year, int) else -1
    title = (row.get("title") or "").strip()
    tiebreak = title.lower() if tie_breaker == "title_asc" else title.lower()
    # Sort by: weight desc, year desc, title asc
    return (-weight, -year_sort, tiebreak)


def _top2_titles_by_polity(rows: list, preferred_domains: dict, tie_breaker: str):
    by_pol = {}
    for r in rows:
        pol = r.get("polity", "")
        by_pol.setdefault(pol, []).append(r)
    top2 = {}
    for pol, lst in by_pol.items():
        sorted_rows = sorted(lst, key=lambda r: _sort_key(r, preferred_domains, tie_breaker))
        top2[pol] = [x.get("title", "") for x in sorted_rows[:2]]
    return top2


def _extract_section_blocks(text: str, polity: str):
    # Return content between markers if present
    start_marker = f"<!-- AUTO-SOURCES:{polity} START -->"
    end_marker = f"<!-- AUTO-SOURCES:{polity} END -->"
    start_idx = text.find(start_marker)
    end_idx = text.find(end_marker)
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        inner = text[start_idx + len(start_marker):end_idx]
        return inner.strip()
    return None


def _find_report_section(text: str, polity: str):
    # Try to find a "## {polity}" header and get the section content (roughly)
    lines = text.splitlines()
    indices = [i for i, line in enumerate(lines) if re.match(rf"^##\s*{re.escape(polity)}\b", line.strip())]
    if not indices:
        return None
    start = indices[0]
    # Find next header or end
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^##\s+", lines[i].strip()):
            end = i
            break
    return "\n".join(lines[start:end])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "scripts_dir_present": 0.0,
        "watcher_logic_present": 0.0,
        "search_results_csv_exists": 0.0,
        "search_results_csv_schema": 0.0,
        "queries_match_templates": 0.0,
        "must_include_terms_applied": 0.0,
        "exclusion_regex_applied": 0.0,
        "urls_and_domains_valid": 0.0,
        "source_name_non_empty": 0.0,
        "polity_names_match_input": 0.0,
        "dedup_urls": 0.0,
        "per_polity_min_results": 0.0,
        "ranks_correct_and_contiguous": 0.0,
        "rank_reason_includes_weight_and_tie_breaker": 0.0,
        "report_md_exists": 0.0,
        "report_includes_top2_per_polity": 0.0,
        "run_log_exists": 0.0,
        "run_log_latest_entry_valid": 0.0,
        "log_counts_match_results": 0.0,
        "notes_auto_sources_blocks_present": 0.0,
        "notes_blocks_match_top2": 0.0,
    }

    # Load inputs
    polities_csv = workspace / "input" / "polities.csv"
    preferences_json = workspace / "input" / "preferences.json"
    notes_md = workspace / "notes" / "boundary_notes.md"
    scripts_dir = workspace / "scripts"
    search_results_csv = workspace / "output" / "search_results.csv"
    report_md = workspace / "output" / "report.md"
    run_log = workspace / "output" / "logs" / "run.log"

    polities = _parse_polities_csv(polities_csv)
    preferences = _load_json(preferences_json) or {}
    preferred_domains = preferences.get("preferred_domains", {}) if isinstance(preferences, dict) else {}
    templates = preferences.get("query_templates", []) if isinstance(preferences, dict) else []
    must_include_terms = [t.lower() for t in preferences.get("must_include_terms", [])] if isinstance(preferences, dict) else []
    exclusion_regex = preferences.get("exclusion_terms_regex") if isinstance(preferences, dict) else None
    results_per_polity_required = preferences.get("results_per_polity", 0) if isinstance(preferences, dict) else 0
    tie_breaker = preferences.get("tie_breaker", "title_asc") if isinstance(preferences, dict) else "title_asc"

    # scripts_dir_present
    if scripts_dir.exists() and scripts_dir.is_dir():
        # Ensure at least one file exists in scripts
        any_file = any(p.is_file() for p in scripts_dir.rglob("*"))
        if any_file:
            scores["scripts_dir_present"] = 1.0

        # watcher_logic_present: look for scripts referencing input/polities.csv and watching behavior
        found_watch = False
        for p in scripts_dir.rglob("*"):
            if not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            # Must reference polities.csv
            if "input/polities.csv" in text and (
                "watch" in text.lower() or "mtime" in text.lower() or "hashlib" in text.lower() or "time.sleep" in text
            ):
                found_watch = True
                break
        if found_watch:
            scores["watcher_logic_present"] = 1.0

    # search_results_csv_exists
    if search_results_csv.exists():
        scores["search_results_csv_exists"] = 1.0

    # Load search_results.csv
    rows, header = _read_csv_dicts(search_results_csv) if search_results_csv.exists() else (None, None)
    expected_columns = [
        "polity",
        "query",
        "title",
        "source_name",
        "domain",
        "url",
        "snippet",
        "publication_year",
        "rank",
        "rank_reason",
    ]
    if header == expected_columns:
        scores["search_results_csv_schema"] = 1.0

    # If rows present, evaluate several checks
    if rows:
        # queries_match_templates
        total_rows = len(rows)
        valid_query_count = 0
        must_include_count = 0
        exclusion_valid_count = 0
        urls_valid_count = 0
        source_name_non_empty_count = 0
        polity_match_rows = 0

        # Build set of expected queries per polity
        expected_queries_per_polity = {pol: _compute_expected_queries(pol, templates) for pol in polities}
        # For exclusion regex
        ex_re = None
        try:
            if exclusion_regex:
                ex_re = re.compile(exclusion_regex)
        except Exception:
            ex_re = None

        seen_urls = set()
        duplicate_found = False
        # URL/domain validation accumulators
        for r in rows:
            pol = (r.get("polity") or "").strip()
            qry = (r.get("query") or "")
            title = (r.get("title") or "")
            snippet = (r.get("snippet") or "")
            source_name = (r.get("source_name") or "")
            domain = (r.get("domain") or "").strip().lower()
            url = (r.get("url") or "").strip()

            # queries_match_templates: must be one of generated templates
            if pol in expected_queries_per_polity and qry in expected_queries_per_polity[pol]:
                valid_query_count += 1

            # must_include_terms_applied: title or snippet contains at least one term
            combined = f"{title} {snippet}".lower()
            if must_include_terms:
                if any(term in combined for term in must_include_terms):
                    must_include_count += 1
            else:
                # If no must_include_terms provided, consider as pass
                must_include_count += 1

            # exclusion_regex_applied: title/snippet must not match regex
            if ex_re:
                if not (ex_re.search(title) or ex_re.search(snippet)):
                    exclusion_valid_count += 1
            else:
                # If no regex provided, consider as pass
                exclusion_valid_count += 1

            # urls_and_domains_valid
            netloc, parsed = _domain_from_url(url)
            if netloc:
                # Check domain matches suffix of netloc
                if domain and netloc.endswith(domain):
                    urls_valid_count += 1

            # source_name_non_empty
            if source_name.strip():
                source_name_non_empty_count += 1

            # polity_names_match_input
            if pol in polities:
                polity_match_rows += 1

            # dedup_urls: check duplicates
            if url in seen_urls:
                duplicate_found = True
            else:
                seen_urls.add(url)

        scores["queries_match_templates"] = valid_query_count / total_rows if total_rows else 0.0
        scores["must_include_terms_applied"] = must_include_count / total_rows if total_rows else 0.0
        scores["exclusion_regex_applied"] = exclusion_valid_count / total_rows if total_rows else 0.0
        scores["urls_and_domains_valid"] = urls_valid_count / total_rows if total_rows else 0.0
        scores["source_name_non_empty"] = source_name_non_empty_count / total_rows if total_rows else 0.0
        scores["polity_names_match_input"] = polity_match_rows / total_rows if total_rows else 0.0
        scores["dedup_urls"] = 1.0 if not duplicate_found and total_rows > 0 else 0.0

        # per_polity_min_results
        per_pol_counts = {}
        for r in rows:
            pol = r.get("polity", "")
            per_pol_counts[pol] = per_pol_counts.get(pol, 0) + 1
        polities_with_min = 0
        expected_polities = polities if polities else list(per_pol_counts.keys())
        for pol in expected_polities:
            cnt = per_pol_counts.get(pol, 0)
            if cnt >= max(0, int(results_per_polity_required)):
                polities_with_min += 1
        if expected_polities:
            scores["per_polity_min_results"] = polities_with_min / len(expected_polities)

        # ranks_correct_and_contiguous and rank_reason_includes_weight_and_tie_breaker
        by_pol = {}
        for r in rows:
            pol = r.get("polity", "")
            by_pol.setdefault(pol, []).append(r)

        correct_ranks_polities = 0
        polities_checked = 0
        rr_ok_count = 0
        rr_total = 0

        for pol, lst in by_pol.items():
            if not lst:
                continue
            polities_checked += 1
            # Compute expected order
            sorted_rows = sorted(lst, key=lambda r: _sort_key(r, preferred_domains, tie_breaker))
            # Check ranks 1..k in that order
            ranks_ok = True
            for idx, r in enumerate(sorted_rows, start=1):
                rank_str = (r.get("rank") or "").strip()
                try:
                    rank_val = int(rank_str)
                except Exception:
                    ranks_ok = False
                    break
                if rank_val != idx:
                    ranks_ok = False
                    break
            if ranks_ok:
                correct_ranks_polities += 1

            # rank_reason checks for each row in this polity
            for r in lst:
                rr_total += 1
                domain = (r.get("domain") or "").strip().lower()
                w = _get_weight(domain, preferred_domains)
                rr = (r.get("rank_reason") or "").lower()
                if str(w) in rr and (tie_breaker.lower() in rr or "title" in rr):
                    rr_ok_count += 1

        scores["ranks_correct_and_contiguous"] = (correct_ranks_polities / polities_checked) if polities_checked else 0.0
        scores["rank_reason_includes_weight_and_tie_breaker"] = (rr_ok_count / rr_total) if rr_total else 0.0

    # report_md_exists
    if report_md.exists():
        scores["report_md_exists"] = 1.0

    # report_includes_top2_per_polity
    if report_md.exists() and rows:
        report_text = _read_text(report_md)
        if report_text:
            top2 = _top2_titles_by_polity(rows, preferred_domains, tie_breaker)
            total = 0
            good = 0
            for pol in polities if polities else top2.keys():
                titles = top2.get(pol, [])
                if not titles:
                    continue
                total += 1
                # Check section exists and includes both titles
                section = _find_report_section(report_text, pol)
                if section is None:
                    # fallback: search entire report for titles
                    section = report_text
                all_present = all(title and (title in section) for title in titles[:2])
                if all_present:
                    good += 1
            if total:
                scores["report_includes_top2_per_polity"] = good / total

    # run_log_exists
    if run_log.exists():
        scores["run_log_exists"] = 1.0

    # run_log_latest_entry_valid and log_counts_match_results
    if run_log.exists():
        log_text = _read_text(run_log)
        lines = [ln for ln in log_text.splitlines() if ln.strip()]
        if lines:
            last = lines[-1]
            try:
                obj = json.loads(last)
            except Exception:
                obj = None
            if isinstance(obj, dict):
                ts_ok = _safe_iso8601(obj.get("timestamp"))
                pol_processed = obj.get("polities_processed")
                rpp_map = obj.get("results_per_polity")
                if ts_ok and isinstance(pol_processed, int) and isinstance(rpp_map, dict):
                    # Validate counts
                    expected_polities = polities
                    counts_match = True
                    if rows and expected_polities:
                        by_pol_count = {}
                        for r in rows:
                            pol = r.get("polity", "")
                            by_pol_count[pol] = by_pol_count.get(pol, 0) + 1
                        for pol in expected_polities:
                            if by_pol_count.get(pol, 0) != int(rpp_map.get(pol, -1)):
                                counts_match = False
                                break
                        if pol_processed != len(expected_polities):
                            counts_match = False
                    scores["run_log_latest_entry_valid"] = 1.0 if ts_ok else 0.0
                    scores["log_counts_match_results"] = 1.0 if counts_match else 0.0

    # notes_auto_sources_blocks_present and notes_blocks_match_top2
    if notes_md.exists() and rows:
        notes_text = _read_text(notes_md)
        total_pol = 0
        present_pol = 0
        match_pol = 0
        top2 = _top2_titles_by_polity(rows, preferred_domains, tie_breaker)
        for pol in polities if polities else top2.keys():
            total_pol += 1
            block = _extract_section_blocks(notes_text, pol)
            if block is not None:
                present_pol += 1
                # Check it has at least two bullet points that include the top 2 titles and domain
                titles = top2.get(pol, [])
                # Count bullet lines
                bullet_lines = [ln for ln in block.splitlines() if ln.strip().startswith(("-", "*"))]
                has_two_bullets = len(bullet_lines) >= 2
                # Check top2 titles present and domains present in the lines
                titles_ok = True
                for t in titles[:2]:
                    if not t:
                        titles_ok = False
                        break
                    # Find a bullet line containing title and (domain if present in CSV row)
                    found_line = False
                    # Fetch the domain for that title in this polity (first matching row)
                    domain_for_title = None
                    for r in rows:
                        if r.get("polity") == pol and (r.get("title") == t):
                            domain_for_title = (r.get("domain") or "").strip().lower()
                            break
                    for bl in bullet_lines:
                        if t in bl and (not domain_for_title or domain_for_title in bl.lower()):
                            found_line = True
                            break
                    if not found_line:
                        titles_ok = False
                        break
                if has_two_bullets and titles_ok:
                    match_pol += 1
        if total_pol:
            scores["notes_auto_sources_blocks_present"] = present_pol / total_pol
            scores["notes_blocks_match_top2"] = match_pol / total_pol
        else:
            scores["notes_auto_sources_blocks_present"] = 0.0
            scores["notes_blocks_match_top2"] = 0.0
    else:
        # If notes file missing or no rows, keep 0.0
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()