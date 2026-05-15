import json
import csv
import sys
import re
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Optional, Tuple


class _VisibleTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._texts: List[str] = []
        self._skip_stack: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("script", "style", "noscript"):
            self._skip_stack.append(tag.lower())

    def handle_endtag(self, tag):
        if self._skip_stack and self._skip_stack[-1] == tag.lower():
            self._skip_stack.pop()

    def handle_data(self, data):
        if not self._skip_stack:
            if data and data.strip():
                self._texts.append(data.strip())

    def get_text(self) -> str:
        return " ".join(self._texts)


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _safe_write_text(path: Path, text: str) -> bool:
    # Not used by grader; placeholder for completeness if needed in future.
    try:
        path.write_text(text, encoding="utf-8")
        return True
    except Exception:
        return False


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return json.loads(text)
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return None
    results = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                results.append(obj)
        except Exception:
            # Malformed line; include a placeholder None to signal parse problem
            results.append(None)
    return results


def _parse_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _extract_visible_text_from_html(html: str) -> str:
    parser = _VisibleTextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # fallback: strip tags with regex if parser fails
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
        text = re.sub(r"(?s)<.*?>", " ", text)
        return re.sub(r"\s+", " ", text).strip()
    text = parser.get_text()
    return re.sub(r"\s+", " ", text).strip()


def _canonical_raw_path(country: str, page_type: str) -> str:
    return f"data/raw/{country}_{page_type}.html"


def _load_keywords(path: Path) -> Optional[Dict[str, List[str]]]:
    obj = _safe_load_json(path)
    if not isinstance(obj, dict):
        return None
    # Ensure categories are lists of strings
    for k, v in obj.items():
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            return None
    return obj


def _read_column_brief_sections(md_path: Path) -> Dict[str, Tuple[int, int]]:
    """
    Returns a mapping of section heading (normalized to the explicit required headings)
    to (start_index, end_index_exclusive) in lines.
    If a section is missing, it will not be included.
    """
    sections_required = [
        "Overview",
        "Method and Sources",
        "Findings (Top 10 Table)",
        "Notable Gaps and Caveats",
        "Story Angles to Pursue",
    ]
    text = _safe_read_text(md_path)
    if text is None:
        return {}
    lines = text.splitlines()
    # Find heading lines; accept any heading level (#, ##, ###) and allow leading/trailing spaces.
    headings_positions: Dict[str, int] = {}
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            # remove leading hashes and spaces
            heading_text = stripped.lstrip("#").strip()
            for req in sections_required:
                if heading_text.lower() == req.lower():
                    headings_positions[req] = idx
    # Determine section ranges
    sorted_headings = sorted(headings_positions.items(), key=lambda kv: kv[1])
    ranges: Dict[str, Tuple[int, int]] = {}
    for i, (name, start) in enumerate(sorted_headings):
        end = len(lines)
        if i + 1 < len(sorted_headings):
            end = sorted_headings[i + 1][1]
        ranges[name] = (start, end)
    return ranges


def _slice_section_text(md_path: Path, heading: str) -> Optional[str]:
    ranges = _read_column_brief_sections(md_path)
    if heading not in ranges:
        return None
    text = _safe_read_text(md_path)
    if text is None:
        return None
    lines = text.splitlines()
    start, end = ranges[heading]
    section = "\n".join(lines[start:end])
    return section


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "search_log_present": 0.0,
        "search_log_per_federation_coverage": 0.0,
        "search_log_schema_valid": 0.0,
        "extracted_json_schema_valid": 0.0,
        "extracted_keyword_categories_match": 0.0,
        "extracted_pages_raw_paths_exist": 0.0,
        "extracted_aggregate_consistency": 0.0,
        "summary_csv_exists": 0.0,
        "summary_columns_correct": 0.0,
        "summary_matches_extracted": 0.0,
        "ranked_top10_exists": 0.0,
        "ranked_top10_correct": 0.0,
        "column_brief_exists": 0.0,
        "column_brief_headings_present": 0.0,
        "column_brief_findings_traceable": 0.0,
        "column_brief_method_coverage": 0.0,
    }

    # Load inputs
    federations_csv = workspace / "input" / "federations.csv"
    keywords_json = workspace / "input" / "keywords.json"
    fed_rows = _parse_csv(federations_csv) or []
    fed_expected = []
    fed_by_country = {}
    for r in fed_rows:
        country = r.get("country", "").strip()
        fedname = r.get("federation_name", "").strip()
        if country and fedname:
            fed_expected.append((country, fedname))
            fed_by_country[country] = fedname

    # SEARCH LOG checks
    search_log_path = workspace / "logs" / "search_log.jsonl"
    if search_log_path.exists():
        scores["search_log_present"] = 1.0
        jsonl = _safe_load_jsonl(search_log_path)
        if jsonl is not None:
            # Schema validity: proportion of non-None entries with required keys and types
            valid_entries = 0
            total_entries = 0
            for entry in jsonl:
                if entry is None:
                    total_entries += 1
                    continue
                total_entries += 1
                if not isinstance(entry, dict):
                    continue
                cond = True
                cond = cond and isinstance(entry.get("country"), str) and entry.get("country").strip() != ""
                cond = cond and isinstance(entry.get("federation_name"), str) and entry.get("federation_name").strip() != ""
                cond = cond and isinstance(entry.get("queries"), list) and all(isinstance(q, str) for q in entry.get("queries", [])) and len(entry.get("queries", [])) >= 1
                # chosen_urls can be empty list but must be list of strings
                cond = cond and isinstance(entry.get("chosen_urls"), list) and all(isinstance(u, str) for u in entry.get("chosen_urls", []))
                # timestamp as string
                cond = cond and isinstance(entry.get("timestamp"), str)
                if cond:
                    valid_entries += 1
            if total_entries > 0:
                scores["search_log_schema_valid"] = valid_entries / total_entries
            else:
                scores["search_log_schema_valid"] = 0.0

            # Coverage: for each federation in input, at least one valid entry exists
            valid_map = {}
            if jsonl:
                for entry in jsonl:
                    if not isinstance(entry, dict):
                        continue
                    # Check minimally valid to count for coverage
                    if isinstance(entry.get("country"), str) and isinstance(entry.get("federation_name"), str) and isinstance(entry.get("queries"), list) and len(entry.get("queries", [])) >= 1:
                        key = (entry["country"].strip(), entry["federation_name"].strip())
                        valid_map.setdefault(key, 0)
                        valid_map[key] += 1
            if fed_expected:
                covered = sum(1 for key in fed_expected if key in valid_map)
                scores["search_log_per_federation_coverage"] = covered / len(fed_expected)
            else:
                scores["search_log_per_federation_coverage"] = 0.0
        else:
            scores["search_log_schema_valid"] = 0.0
            scores["search_log_per_federation_coverage"] = 0.0
    else:
        scores["search_log_present"] = 0.0
        scores["search_log_schema_valid"] = 0.0
        scores["search_log_per_federation_coverage"] = 0.0

    # Extracted JSON checks
    extracted_dir = workspace / "data" / "extracted"
    keywords = _load_keywords(keywords_json)
    # List extracted files for countries in input
    extracted_files: Dict[str, Path] = {}
    if extracted_dir.exists():
        for country, _fedname in fed_expected:
            p = extracted_dir / f"{country}.json"
            if p.exists():
                extracted_files[country] = p

    # If no extracted files, leave related scores at 0.0
    total_extracted = len(extracted_files)
    valid_schema_count = 0
    keyword_categories_match_count = 0
    raw_paths_total = 0
    raw_paths_exist_count = 0
    aggregate_total = 0
    aggregate_consistent_count = 0

    # For summary reconciliation
    derived_summary: Dict[str, dict] = {}  # country -> summary metrics

    for country, path in extracted_files.items():
        obj = _safe_load_json(path)
        schema_valid = False
        categories_match = False
        aggregate_consistent = False
        raw_path_checks_for_country_total = 0
        raw_path_checks_for_country_ok = 0

        if isinstance(obj, dict):
            if (
                obj.get("country") == country
                and isinstance(obj.get("federation_name"), str)
                and isinstance(obj.get("pages"), list)
                and len(obj.get("pages")) >= 1
                and isinstance(obj.get("aggregate"), dict)
            ):
                # validate pages entries
                pages_ok = True
                total_text_length = 0
                agg_youth = 0
                agg_coaching = 0
                agg_events = 0
                page_count = 0
                for page in obj["pages"]:
                    page_ok = True
                    if not isinstance(page, dict):
                        pages_ok = False
                        break
                    page_type = page.get("page_type")
                    source_url = page.get("source_url")
                    local_path = page.get("local_path")
                    text_length = page.get("text_length")
                    keyword_hits = page.get("keyword_hits")
                    if page_type not in {"programs", "calendar"}:
                        page_ok = False
                    if not (isinstance(source_url, str) and source_url.strip() != ""):
                        page_ok = False
                    if not (isinstance(local_path, str) and local_path.strip() != ""):
                        page_ok = False
                    # Check canonical local path naming
                    expected_local = _canonical_raw_path(country, page_type if isinstance(page_type, str) else "")
                    raw_path_checks_for_country_total += 1
                    if local_path == expected_local:
                        raw_file_path = workspace / local_path
                        if raw_file_path.exists():
                            # Also ensure non-empty
                            content = _safe_read_text(raw_file_path)
                            if content is not None and len(content) > 0:
                                raw_path_checks_for_country_ok += 1
                    # text_length should be int >= 0
                    if not (isinstance(text_length, int) and text_length >= 0):
                        page_ok = False
                    # keyword_hits should be dict of non-negative ints
                    if not isinstance(keyword_hits, dict):
                        page_ok = False
                    else:
                        if not all(isinstance(v, int) and v >= 0 for v in keyword_hits.values()):
                            page_ok = False
                    if not page_ok:
                        pages_ok = False
                        break
                    total_text_length += int(text_length)
                    agg_youth += int(keyword_hits.get("youth", 0))
                    agg_coaching += int(keyword_hits.get("coaching", 0))
                    agg_events += int(keyword_hits.get("events", 0))
                    page_count += 1

                # validate aggregate
                ag = obj.get("aggregate", {})
                if (
                    isinstance(ag.get("youth"), int)
                    and isinstance(ag.get("coaching"), int)
                    and isinstance(ag.get("events"), int)
                    and isinstance(ag.get("total_score"), int)
                ):
                    aggregate_consistent = (
                        ag["youth"] == agg_youth
                        and ag["coaching"] == agg_coaching
                        and ag["events"] == agg_events
                        and ag["total_score"] == (agg_youth + agg_coaching + agg_events)
                    )

                # categories match keywords.json
                if isinstance(keywords, dict):
                    required_keys = set(keywords.keys())
                    # The task categories must be used as-is; expect exactly the same keys
                    categories_match = required_keys == {"youth", "coaching", "events"}
                    # Also ensure each page has exactly these keys
                    if categories_match:
                        for page in obj["pages"]:
                            kh = page.get("keyword_hits", {})
                            if not (set(kh.keys()) == required_keys):
                                categories_match = False
                                break
                        # and aggregate keys
                        if not (set(obj.get("aggregate", {}).keys()) == {"youth", "coaching", "events", "total_score"}):
                            categories_match = False
                else:
                    categories_match = False

                schema_valid = pages_ok and isinstance(obj.get("federation_name"), str)

                # Build derived summary for later comparison
                if schema_valid:
                    derived_summary[country] = {
                        "country": country,
                        "federation_name": obj.get("federation_name"),
                        "pages_crawled": page_count,
                        "total_text_length": total_text_length,
                        "youth_hits": agg_youth,
                        "coaching_hits": agg_coaching,
                        "events_hits": agg_events,
                        "total_score": agg_youth + agg_coaching + agg_events,
                    }

        if schema_valid:
            valid_schema_count += 1
        if categories_match:
            keyword_categories_match_count += 1
        raw_paths_total += raw_path_checks_for_country_total
        raw_paths_exist_count += raw_path_checks_for_country_ok
        aggregate_total += 1
        if aggregate_consistent:
            aggregate_consistent_count += 1

    if total_extracted > 0:
        scores["extracted_json_schema_valid"] = valid_schema_count / total_extracted
        scores["extracted_keyword_categories_match"] = keyword_categories_match_count / total_extracted
        scores["extracted_aggregate_consistency"] = aggregate_consistent_count / total_extracted
    else:
        scores["extracted_json_schema_valid"] = 0.0
        scores["extracted_keyword_categories_match"] = 0.0
        scores["extracted_aggregate_consistency"] = 0.0

    if raw_paths_total > 0:
        scores["extracted_pages_raw_paths_exist"] = raw_paths_exist_count / raw_paths_total
    else:
        scores["extracted_pages_raw_paths_exist"] = 0.0

    # SUMMARY checks
    summary_path = workspace / "outputs" / "summary.csv"
    if summary_path.exists():
        scores["summary_csv_exists"] = 1.0
        rows = _parse_csv(summary_path)
        header_valid = False
        rows_list = rows or []
        # Validate header order strictly
        try:
            with summary_path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
                header_line = f.readline().strip()
            header_valid = (
                header_line == "country,federation_name,pages_crawled,total_text_length,youth_hits,coaching_hits,events_hits,total_score"
            )
        except Exception:
            header_valid = False
        scores["summary_columns_correct"] = 1.0 if header_valid else 0.0

        # Compare with derived summary
        # Build dict from file rows
        file_summary = {}
        all_rows_parsed = True
        for r in rows_list:
            try:
                country = r.get("country", "").strip()
                federation_name = r.get("federation_name", "").strip()
                pages_crawled = int(r.get("pages_crawled", "").strip()) if str(r.get("pages_crawled", "")).strip() != "" else -1
                total_text_length = int(r.get("total_text_length", "").strip()) if str(r.get("total_text_length", "")).strip() != "" else -1
                youth_hits = int(r.get("youth_hits", "").strip()) if str(r.get("youth_hits", "")).strip() != "" else -1
                coaching_hits = int(r.get("coaching_hits", "").strip()) if str(r.get("coaching_hits", "")).strip() != "" else -1
                events_hits = int(r.get("events_hits", "").strip()) if str(r.get("events_hits", "")).strip() != "" else -1
                total_score = int(r.get("total_score", "").strip()) if str(r.get("total_score", "")).strip() != "" else -1
            except Exception:
                all_rows_parsed = False
                break
            if not country:
                all_rows_parsed = False
                break
            file_summary[country] = {
                "country": country,
                "federation_name": federation_name,
                "pages_crawled": pages_crawled,
                "total_text_length": total_text_length,
                "youth_hits": youth_hits,
                "coaching_hits": coaching_hits,
                "events_hits": events_hits,
                "total_score": total_score,
            }
        # Expected set of countries = derived_summary keys (from extracted files)
        expected_countries = set(derived_summary.keys())
        file_countries = set(file_summary.keys())
        # The file should include only federations with processed pages (i.e., derived_summary)
        if all_rows_parsed and file_countries == expected_countries:
            # Check per-country metrics match exactly
            if len(expected_countries) == 0:
                # If no processed countries, matching empty set is acceptable
                scores["summary_matches_extracted"] = 1.0
            else:
                matches = 0
                for country in expected_countries:
                    a = derived_summary[country]
                    b = file_summary[country]
                    if (
                        a["federation_name"] == b["federation_name"]
                        and a["pages_crawled"] == b["pages_crawled"]
                        and a["total_text_length"] == b["total_text_length"]
                        and a["youth_hits"] == b["youth_hits"]
                        and a["coaching_hits"] == b["coaching_hits"]
                        and a["events_hits"] == b["events_hits"]
                        and a["total_score"] == b["total_score"]
                    ):
                        matches += 1
                scores["summary_matches_extracted"] = matches / len(expected_countries) if expected_countries else 0.0
        else:
            scores["summary_matches_extracted"] = 0.0
    else:
        scores["summary_csv_exists"] = 0.0
        scores["summary_columns_correct"] = 0.0
        scores["summary_matches_extracted"] = 0.0

    # RANKED TOP10 checks
    ranked_path = workspace / "outputs" / "ranked_top10.csv"
    if ranked_path.exists():
        scores["ranked_top10_exists"] = 1.0
        ranked_rows = _parse_csv(ranked_path) or []
        # We require at least country, federation_name, total_score columns
        required_cols = {"country", "federation_name", "total_score"}
        has_required = False
        try:
            with ranked_path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
                header_line = f.readline().strip()
                header_cols = [h.strip() for h in header_line.split(",") if h.strip() != ""]
                has_required = required_cols.issubset(set(header_cols))
        except Exception:
            has_required = False

        # Build expected top10 from summary
        # If summary missing or invalid, we cannot compute expected; in that case, leave 0.0
        if scores["summary_matches_extracted"] > 0.0:
            # Use file_summary previously constructed
            # Reconstruct file_summary from summary file again to avoid scope issues
            summary_rows = _parse_csv(summary_path) or []
            parsed_summary = []
            ok_parse = True
            for r in summary_rows:
                try:
                    parsed_summary.append({
                        "country": r.get("country", "").strip(),
                        "federation_name": r.get("federation_name", "").strip(),
                        "total_score": int(str(r.get("total_score", "")).strip()) if str(r.get("total_score", "")).strip() != "" else -1,
                    })
                except Exception:
                    ok_parse = False
                    break
            if ok_parse:
                # Sort by total_score desc, tie by country A-Z
                parsed_summary = [x for x in parsed_summary if x["country"]]
                expected_sorted = sorted(parsed_summary, key=lambda x: (-x["total_score"], x["country"]))
                expected_top = expected_sorted[: min(10, len(expected_sorted))]
                # Load ranked rows of interest
                ranked_min = []
                ok_ranked = True
                for r in ranked_rows:
                    try:
                        ranked_min.append({
                            "country": r.get("country", "").strip(),
                            "federation_name": r.get("federation_name", "").strip(),
                            "total_score": int(str(r.get("total_score", "")).strip()) if str(r.get("total_score", "")).strip() != "" else -1,
                        })
                    except Exception:
                        ok_ranked = False
                        break
                # Validate order and length
                if ok_ranked and has_required and len(ranked_min) == len(expected_top):
                    correct = 0
                    for i in range(len(expected_top)):
                        if (
                            ranked_min[i]["country"] == expected_top[i]["country"]
                            and ranked_min[i]["federation_name"] == expected_top[i]["federation_name"]
                            and ranked_min[i]["total_score"] == expected_top[i]["total_score"]
                        ):
                            correct += 1
                    scores["ranked_top10_correct"] = correct / len(expected_top) if expected_top else 0.0
                else:
                    scores["ranked_top10_correct"] = 0.0
            else:
                scores["ranked_top10_correct"] = 0.0
        else:
            scores["ranked_top10_correct"] = 0.0
    else:
        scores["ranked_top10_exists"] = 0.0
        scores["ranked_top10_correct"] = 0.0

    # COLUMN BRIEF checks
    column_brief_path = workspace / "outputs" / "column_brief.md"
    if column_brief_path.exists():
        scores["column_brief_exists"] = 1.0
        # Headings presence
        sections = _read_column_brief_sections(column_brief_path)
        required_headings = [
            "Overview",
            "Method and Sources",
            "Findings (Top 10 Table)",
            "Notable Gaps and Caveats",
            "Story Angles to Pursue",
        ]
        have_all = all(h in sections for h in required_headings)
        scores["column_brief_headings_present"] = 1.0 if have_all else 0.0

        # Method coverage: mention searches, downloads, and keyword signals
        method_text = _slice_section_text(column_brief_path, "Method and Sources") or ""
        method_lower = method_text.lower()
        method_hits = 0
        method_hits += 1 if ("search" in method_lower or "búsqu" in method_lower or "pesquisa" in method_lower) else 0
        method_hits += 1 if ("download" in method_lower or "descarg" in method_lower or "baix" in method_lower) else 0
        method_hits += 1 if ("keyword" in method_lower or "palabra clave" in method_lower or "palavras-chave" in method_lower) else 0
        scores["column_brief_method_coverage"] = method_hits / 3.0

        # Findings traceability: Include ranked Top 10 with total_score and cite local paths and source URLs
        findings_text = _slice_section_text(column_brief_path, "Findings (Top 10 Table)") or ""
        findings_lower = findings_text.lower()
        # Build expected list from ranked_top10.csv if available and correct
        top10_list = []
        if (workspace / "outputs" / "ranked_top10.csv").exists():
            ranked_rows2 = _parse_csv(workspace / "outputs" / "ranked_top10.csv") or []
            for r in ranked_rows2:
                try:
                    top10_list.append((r.get("country", "").strip(), int(str(r.get("total_score", "")).strip())))
                except Exception:
                    continue
        # For each top10 country, we expect mention of the country and its total_score, and at least one local_path and one source_url cited from extracted JSON
        trace_count = 0
        trace_total = 0
        for country, score_val in top10_list:
            if not country:
                continue
            trace_total += 1
            has_country = country.lower() in findings_lower
            has_score = str(score_val) in findings_text
            # find extracted JSON for that country and collect local paths and source urls
            p = extracted_files.get(country)
            local_paths = []
            source_urls = []
            if p and p.exists():
                obj = _safe_load_json(p)
                if isinstance(obj, dict) and isinstance(obj.get("pages"), list):
                    for pg in obj["pages"]:
                        lp = pg.get("local_path")
                        su = pg.get("source_url")
                        if isinstance(lp, str):
                            local_paths.append(lp)
                        if isinstance(su, str):
                            source_urls.append(su)
            has_any_local = any(lp in findings_text for lp in local_paths) if local_paths else False
            has_any_source = any(su in findings_text for su in source_urls) if source_urls else False
            if has_country and has_score and has_any_local and has_any_source:
                trace_count += 1
        if trace_total > 0:
            scores["column_brief_findings_traceable"] = trace_count / trace_total
        else:
            # If no ranked rows, we still expect the section exists; give 0 if empty or no traceability needed
            scores["column_brief_findings_traceable"] = 0.0
    else:
        scores["column_brief_exists"] = 0.0
        scores["column_brief_headings_present"] = 0.0
        scores["column_brief_findings_traceable"] = 0.0
        scores["column_brief_method_coverage"] = 0.0

    return scores


def main() -> None:
        workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade(transcript=[], workspace_path=workspace_path)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()