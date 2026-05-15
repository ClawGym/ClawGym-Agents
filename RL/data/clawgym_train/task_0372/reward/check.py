import json
import csv
import sys
import re
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            sniffer = csv.Sniffer()
            sample = f.read(2048)
            f.seek(0)
            dialect = None
            try:
                dialect = sniffer.sniff(sample)
            except Exception:
                pass
            reader = csv.reader(f, dialect=dialect)
            rows = list(reader)
            if not rows:
                return None, None
            headers = rows[0]
            dict_rows = []
            for r in rows[1:]:
                # Pad or trim to headers length
                if len(r) < len(headers):
                    r = r + [""] * (len(headers) - len(r))
                elif len(r) > len(headers):
                    r = r[:len(headers)]
                dict_rows.append({h: v for h, v in zip(headers, r)})
            return headers, dict_rows
    except Exception:
        return None, None


def _iso8601_parseable(s: str) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    t = s.strip()
    # Accept Z
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        datetime.fromisoformat(t)
        return True
    except Exception:
        return False


def _domain_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _endswith_domain(netloc: str, domain: str) -> bool:
    netloc = (netloc or "").lower()
    domain = (domain or "").lower()
    return netloc == domain or netloc.endswith("." + domain)


def _norm_text(s: str) -> str:
    if s is None:
        return ""
    # lower, replace punctuation with spaces, collapse spaces
    s2 = s.lower()
    s2 = re.sub(r"[^\w\s]", " ", s2, flags=re.UNICODE)
    s2 = re.sub(r"\s+", " ", s2).strip()
    return s2


def _keyword_in_text(keyword: str, text: str) -> bool:
    # Case-insensitive, robust to simple punctuation: compare normalized forms by substring
    norm_kw = _norm_text(keyword)
    norm_text = _norm_text(text)
    if not norm_kw or not norm_text:
        return False
    return norm_kw in norm_text


def _split_semicolon_list(s: str):
    if not s or not isinstance(s, str):
        return []
    parts = [p.strip() for p in s.split(";")]
    return [p for p in parts if p != ""]


def _find_section_bounds(lines, heading_phrase):
    # Return (start_idx, end_idx) indices for content lines after the heading
    # where start is the line after the heading, end is index of next heading or len(lines)
    hp = heading_phrase.lower()
    start = None
    for i, ln in enumerate(lines):
        if hp in ln.lower():
            start = i + 1
            break
    if start is None:
        return None, None
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].strip().startswith("#"):
            end = j
            break
    return start, end


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "web_raw_doe_html_valid": 0.0,
        "web_raw_nibs_html_valid": 0.0,
        "web_matches_json_valid_schema": 0.0,
        "web_matches_domains_and_urls": 0.0,
        "web_matches_context_quality": 0.0,
        "web_matches_deduplicated": 0.0,
        "project_relevance_csv_structure": 0.0,
        "project_relevance_mapping_accuracy": 0.0,
        "report_sections_present": 0.0,
        "report_highlights_content": 0.0,
        "report_project_relevance_content": 0.0,
        "report_sources_listed": 0.0,
        "report_readme_note_present": 0.0,
    }

    # Paths
    doe_html_path = workspace / "out" / "web" / "raw" / "doe_abc.html"
    nibs_html_path = workspace / "out" / "web" / "raw" / "nibs_oscc.html"
    web_matches_path = workspace / "out" / "data" / "web_matches.json"
    proj_rel_path = workspace / "out" / "data" / "project_relevance.csv"
    report_path = workspace / "out" / "report" / "weekly_update.md"
    input_projects_path = workspace / "input" / "projects.csv"
    input_keywords_path = workspace / "input" / "tech_keywords.json"

    # Load inputs
    proj_headers, proj_rows = _read_csv(input_projects_path)
    keywords_json = _load_json(input_keywords_path)
    categories_map = {}
    if isinstance(keywords_json, dict):
        categories_map = {str(k): [str(x) for x in v] for k, v in keywords_json.items() if isinstance(v, list)}

    # Check HTML files validity
    doe_text = _read_text(doe_html_path)
    if isinstance(doe_text, str) and len(doe_text) > 0:
        # consider valid if contains phrase "Advanced Building Construction" ignoring case
        if "advanced building construction" in doe_text.lower():
            scores["web_raw_doe_html_valid"] = 1.0
    nibs_text = _read_text(nibs_html_path)
    if isinstance(nibs_text, str) and len(nibs_text) > 0:
        t = nibs_text.lower().replace("off-site", "off site")
        if "off site construction council" in t:
            scores["web_raw_nibs_html_valid"] = 1.0

    # Load web matches
    web_matches = _load_json(web_matches_path)
    schema_ok = False
    if isinstance(web_matches, list):
        schema_ok = True
        for item in web_matches:
            if not isinstance(item, dict):
                schema_ok = False
                break
            required_keys = ["source_title", "source_domain", "url", "category", "keyword", "context", "retrieved_at"]
            if any(k not in item for k in required_keys):
                schema_ok = False
                break
            # type checks
            if not all(isinstance(item[k], str) and item[k].strip() != "" for k in ["source_domain", "url", "category", "keyword", "context", "retrieved_at"]):
                schema_ok = False
                break
            if item.get("category") not in categories_map:
                schema_ok = False
                break
            if not _iso8601_parseable(item.get("retrieved_at", "")):
                schema_ok = False
                break
        if schema_ok:
            scores["web_matches_json_valid_schema"] = 1.0

    # Domains and URLs check
    if isinstance(web_matches, list):
        domains_urls_ok = True
        for item in web_matches:
            if not isinstance(item, dict):
                domains_urls_ok = False
                break
            dom = item.get("source_domain", "")
            url = item.get("url", "")
            netloc = _domain_from_url(url)
            # source_domain must be either energy.gov or nibs.org
            if dom not in ("energy.gov", "nibs.org"):
                domains_urls_ok = False
                break
            # URL netloc should match or be subdomain of source_domain
            if not _endswith_domain(netloc, dom):
                domains_urls_ok = False
                break
        if domains_urls_ok:
            scores["web_matches_domains_and_urls"] = 1.0

    # Context quality check: keyword in context and reasonable length
    if isinstance(web_matches, list):
        context_ok = True
        for item in web_matches:
            if not isinstance(item, dict):
                context_ok = False
                break
            kw = item.get("keyword", "")
            ctx = item.get("context", "")
            if not _keyword_in_text(kw, ctx):
                context_ok = False
                break
            if not (90 <= len(ctx) <= 400):
                context_ok = False
                break
        if context_ok:
            scores["web_matches_context_quality"] = 1.0

    # Deduplication check
    if isinstance(web_matches, list):
        seen = set()
        dup_free = True
        for item in web_matches:
            if not isinstance(item, dict):
                dup_free = False
                break
            key = (item.get("url", ""), item.get("keyword", ""), item.get("context", ""))
            if key in seen:
                dup_free = False
                break
            seen.add(key)
        if dup_free:
            scores["web_matches_deduplicated"] = 1.0

    # Project relevance CSV structure
    pr_headers, pr_rows = _read_csv(proj_rel_path)
    expected_headers = ["project_name", "stage", "matched_categories", "matched_keywords", "sources"]
    if pr_headers == expected_headers:
        scores["project_relevance_csv_structure"] = 1.0

    # Project relevance mapping accuracy
    mapping_score = 0.0
    mapping_total = 0
    if pr_headers == expected_headers and isinstance(proj_rows, list) and isinstance(categories_map, dict) and isinstance(web_matches, list):
        # Build expected mapping per project
        # categories with matches present in web_matches
        categories_with_matches = set()
        sources_by_category = {}
        for item in web_matches:
            if not isinstance(item, dict):
                continue
            cat = item.get("category", "")
            srcd = item.get("source_domain", "")
            if cat:
                categories_with_matches.add(cat)
                sources_by_category.setdefault(cat, set()).add(srcd)
        # Normalize keywords per category
        norm_keywords_by_cat = {cat: set([_norm_text(kw) for kw in kws]) for cat, kws in categories_map.items()}
        # Build expected sets per project
        projects_expected = {}
        if isinstance(proj_rows, list):
            # Collect expected projects that have any match category
            for prow in proj_rows:
                pname = prow.get("project_name", "")
                pstage = prow.get("stage", "")
                technologies = prow.get("technologies") or prow.get("Technology") or prow.get("tech") or prow.get("technologies".upper())
                # The input projects.csv has "technologies"; but pr_rows come from out/data/project_relevance.csv which does not include technologies
                # We need to read from input projects.csv instead:
            pass  # This 'pass' will be removed below

    # Compute expected mapping using input projects.csv
    if pr_headers == expected_headers and proj_headers and proj_rows and isinstance(categories_map, dict) and isinstance(web_matches, list):
        categories_with_matches = set()
        sources_by_category = {}
        for item in web_matches:
            if isinstance(item, dict):
                cat = item.get("category", "")
                srcd = item.get("source_domain", "")
                if cat:
                    categories_with_matches.add(cat)
                    sources_by_category.setdefault(cat, set()).add(srcd)

        norm_keywords_by_cat = {cat: set([_norm_text(kw) for kw in kws]) for cat, kws in categories_map.items()}

        # Read the original input projects.csv to get technologies
        in_headers, in_rows = _read_csv(input_projects_path)
        expected_by_project = {}
        if in_headers and in_rows:
            for r in in_rows:
                pname = r.get("project_name", "").strip()
                pstage = r.get("stage", "").strip()
                techs_raw = r.get("technologies", "")
                tokens = []
                if isinstance(techs_raw, str):
                    # split on semicolons or commas
                    parts = re.split(r"[;,]", techs_raw)
                    tokens = [p.strip() for p in parts if p.strip()]
                matched_keywords = set()
                matched_categories = set()
                for t in tokens:
                    nt = _norm_text(t)
                    for cat, kwset in norm_keywords_by_cat.items():
                        for nkw in kwset:
                            if nkw and nkw in nt:
                                if cat in categories_with_matches:
                                    # map to original keyword form best-effort: find the canonical keyword from categories_map
                                    # choose the first keyword that normalizes to this nkw
                                    for original_kw in categories_map.get(cat, []):
                                        if _norm_text(original_kw) == nkw:
                                            matched_keywords.add(original_kw)
                                            break
                                    matched_categories.add(cat)
                # Sources derived from web_matches categories
                sources = set()
                for cat in matched_categories:
                    for s in sources_by_category.get(cat, set()):
                        sources.add(s)
                expected_by_project[pname] = {
                    "stage": pstage,
                    "categories": matched_categories,
                    "keywords": matched_keywords,
                    "sources": sources,
                }

        # Parse student's CSV
        student_rows_by_project = {}
        if pr_rows:
            for r in pr_rows:
                pname = (r.get("project_name") or "").strip()
                if pname:
                    student_rows_by_project[pname] = {
                        "stage": (r.get("stage") or "").strip(),
                        "categories": set([x for x in (p.strip() for p in (r.get("matched_categories") or "").split(";")) if x]),
                        "keywords": set([x for x in (p.strip() for p in (r.get("matched_keywords") or "").split(";")) if x]),
                        "sources": set([x for x in (p.strip() for p in (r.get("sources") or "").split(";")) if x]),
                    }

        # Determine projects expected to be present (with any matched categories)
        projects_with_matches = [p for p, info in expected_by_project.items() if info["categories"]]
        if not expected_by_project:
            mapping_score = 0.0
            mapping_total = 0
        else:
            if len(projects_with_matches) == 0:
                # If no categories matched at all, accept structure-only for mapping accuracy
                mapping_score = 1.0 if pr_headers == expected_headers else 0.0
                mapping_total = 1
            else:
                mapping_total = len(projects_with_matches)
                correct = 0
                for pname in projects_with_matches:
                    exp = expected_by_project.get(pname, None)
                    stu = student_rows_by_project.get(pname, None)
                    if not exp or not stu:
                        continue
                    cats_equal = stu["categories"] == exp["categories"]
                    kws_equal = stu["keywords"] == exp["keywords"]
                    src_equal = stu["sources"] == exp["sources"]
                    if cats_equal and kws_equal and src_equal:
                        correct += 1
                mapping_score = (correct / mapping_total) if mapping_total > 0 else 0.0

        scores["project_relevance_mapping_accuracy"] = mapping_score if mapping_total > 0 else mapping_score

    # Report checks
    report_text = _read_text(report_path)
    if isinstance(report_text, str):
        lines = report_text.splitlines()
        # Sections present
        has_highlights = any("highlights by technology" in ln.lower() for ln in lines)
        has_proj_rel = any("project relevance" in ln.lower() for ln in lines)
        has_sources = any("sources and retrieval" in ln.lower() for ln in lines)
        # Title line with a date-like pattern near top
        top_lines = lines[:5]
        date_pattern = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b", re.IGNORECASE)
        title_has_date = any(date_pattern.search(ln) for ln in top_lines)
        if has_highlights and has_proj_rel and has_sources and title_has_date:
            scores["report_sections_present"] = 1.0

        # README note at top: look for how to run note
        readme_present = False
        for ln in lines[:30]:
            lnl = ln.lower()
            if "readme" in lnl or "usage" in lnl or "how to run" in lnl or "run" in lnl or "python" in lnl or "cli" in lnl or "execute" in lnl:
                readme_present = True
                break
        if readme_present:
            scores["report_readme_note_present"] = 1.0

        # Highlights content
        wm = web_matches if isinstance(web_matches, list) else []
        if wm:
            # Ensure categories with matches are mentioned in Highlights section
            start, end = _find_section_bounds(lines, "Highlights by Technology")
            section_lines = lines[start:end] if start is not None else lines
            section_text = "\n".join(section_lines).lower()
            categories_with_matches = sorted(set(item.get("category", "") for item in wm if isinstance(item, dict) and item.get("category")))
            if categories_with_matches:
                present_count = 0
                for cat in categories_with_matches:
                    if cat.lower() in section_text:
                        present_count += 1
                # Also ensure at least one keyword and one source_domain appear
                any_keyword_present = False
                any_domain_present = False
                for item in wm:
                    kw = (item.get("keyword") or "").lower()
                    sd = (item.get("source_domain") or "").lower()
                    if kw and kw in section_text:
                        any_keyword_present = True
                    if sd and sd in section_text:
                        any_domain_present = True
                    if any_keyword_present and any_domain_present:
                        break
                if categories_with_matches:
                    cat_ratio = present_count / max(1, len(categories_with_matches))
                else:
                    cat_ratio = 1.0
                if cat_ratio > 0 and any_keyword_present and any_domain_present:
                    # Scale by category mention coverage
                    scores["report_highlights_content"] = min(1.0, max(0.0, cat_ratio))
                else:
                    scores["report_highlights_content"] = 0.0
            else:
                # No categories but web_matches non-empty (unlikely), still require some signals
                scores["report_highlights_content"] = 0.0
        else:
            # No matches case: require clear note
            if "no relevant signals" in report_text.lower():
                scores["report_highlights_content"] = 1.0

        # Project relevance content
        wm = web_matches if isinstance(web_matches, list) else []
        categories_with_matches = set(item.get("category", "") for item in wm if isinstance(item, dict) and item.get("category"))
        # Compute expected projects with matches using input projects.csv and categories_map
        proj_names_with_matches = set()
        in_headers, in_rows = _read_csv(input_projects_path)
        if in_headers and in_rows and categories_map:
            norm_keywords_by_cat = {cat: set([_norm_text(kw) for kw in kws]) for cat, kws in categories_map.items()}
            for r in in_rows:
                pname = r.get("project_name", "").strip()
                techs_raw = r.get("technologies", "")
                tokens = []
                if isinstance(techs_raw, str):
                    parts = re.split(r"[;,]", techs_raw)
                    tokens = [p.strip() for p in parts if p.strip()]
                matched_categories = set()
                for t in tokens:
                    nt = _norm_text(t)
                    for cat, kwset in norm_keywords_by_cat.items():
                        for nkw in kwset:
                            if nkw and nkw in nt and cat in categories_with_matches:
                                matched_categories.add(cat)
                if matched_categories:
                    proj_names_with_matches.add(pname)
        # Check presence in report
        if proj_names_with_matches:
            start, end = _find_section_bounds(lines, "Project Relevance")
            section_lines = lines[start:end] if start is not None else lines
            section_text = "\n".join(section_lines)
            present = 0
            for pname in proj_names_with_matches:
                if pname and pname in section_text:
                    present += 1
            if present > 0:
                scores["report_project_relevance_content"] = present / max(1, len(proj_names_with_matches))
        else:
            # If no projects expected, count as satisfied
            scores["report_project_relevance_content"] = 1.0

        # Sources and retrieval section lists URLs
        start, end = _find_section_bounds(lines, "Sources and Retrieval")
        section_lines = lines[start:end] if start is not None else []
        section_text = "\n".join(section_lines) if section_lines else ""
        if isinstance(web_matches, list) and web_matches:
            urls = sorted(set([item.get("url", "") for item in web_matches if isinstance(item, dict) and item.get("url")]))
            if urls:
                listed = 0
                for u in urls:
                    if u and u in section_text:
                        listed += 1
                if listed > 0:
                    scores["report_sources_listed"] = listed / max(1, len(urls))
        else:
            # No matches: section presence was already ensured; consider this satisfied
            if has_sources:
                scores["report_sources_listed"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()