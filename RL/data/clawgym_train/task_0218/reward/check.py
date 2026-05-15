import sys
import json
import csv
import re
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from urllib.parse import urlparse
from datetime import datetime
import xml.etree.ElementTree as ET


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = _read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        lines = []
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if not isinstance(obj, dict):
                        return None
                    lines.append(obj)
                except Exception:
                    return None
        return lines
    except Exception:
        return None


def _load_keywords(path: Path) -> Optional[List[str]]:
    try:
        raw = _read_text(path)
        if raw is None:
            return None
        kws = [ln.strip() for ln in raw.splitlines()]
        kws = [k for k in kws if k != ""]
        return kws
    except Exception:
        return None


def _parse_iso8601_to_year(value: str) -> Optional[str]:
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        try:
            dt = datetime.fromisoformat(s2)
            return str(dt.year)
        except ValueError:
            try:
                dt = datetime.strptime(s[:10], "%Y-%m-%d")
                return str(dt.year)
            except Exception:
                return None
    except Exception:
        return None


def _nearly_equal(a: float, b: float, rel_tol: float = 1e-6, abs_tol: float = 1e-3) -> bool:
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


def _parse_sitemap_locs(xml_text: str) -> List[str]:
    urls: List[str] = []
    if xml_text is None:
        return urls
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return urls
    for elem in root.iter():
        tag = elem.tag
        if isinstance(tag, str) and tag.endswith("loc"):
            if elem.text:
                loc = elem.text.strip()
                if loc:
                    urls.append(loc)
    return urls


def _is_newsroom_domain(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower() == "newsroom.churchofjesuschrist.org"
    except Exception:
        return False


def _list_html_pages(dir_path: Path) -> List[Path]:
    if not dir_path.exists() or not dir_path.is_dir():
        return []
    return sorted([p for p in dir_path.glob("*.html") if p.is_file()])


def _compute_expected_top20_from_sitemap(locs: List[str]) -> List[str]:
    domain_urls = [u for u in locs if _is_newsroom_domain(u)]
    article_urls = [u for u in domain_urls if "/article" in u]
    non_article_urls = [u for u in domain_urls if "/article" not in u]
    ordered = article_urls + non_article_urls
    return ordered[:20]


def _compute_aggregates_from_records(records: List[Dict[str, Any]], keywords: List[str]) -> Dict[str, Any]:
    total_articles = len(records)
    total_words = 0
    year_counts: Dict[str, int] = {}
    agg_kw_counts: Dict[str, int] = {k: 0 for k in keywords}
    for rec in records:
        wc = rec.get("word_count")
        if isinstance(wc, int):
            total_words += wc
        else:
            total_words += 0
        pd = rec.get("published_date", None)
        y = None
        if isinstance(pd, str):
            y = _parse_iso8601_to_year(pd)
        if y is None:
            y = "unknown"
        year_counts[y] = year_counts.get(y, 0) + 1
        kw_counts = rec.get("keyword_counts", {})
        if isinstance(kw_counts, dict):
            for k in keywords:
                v = kw_counts.get(k, 0)
                if isinstance(v, int):
                    agg_kw_counts[k] = agg_kw_counts.get(k, 0) + v
    avg_words = (float(total_words) / float(total_articles)) if total_articles > 0 else 0.0
    return {
        "total_articles": total_articles,
        "total_words": total_words,
        "average_words_per_article": avg_words,
        "articles_per_year": year_counts,
        "aggregate_keyword_counts": agg_kw_counts,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "raw_files_exist": 0.0,
        "robots_txt_has_sitemap_lines": 0.0,
        "sitemap_has_article_urls": 0.0,
        "pages_downloaded_limit": 0.0,
        "articles_jsonl_structure": 0.0,
        "urls_under_correct_domain": 0.0,
        "selection_respects_sitemap_preference": 0.0,
        "unique_urls_limit": 0.0,
        "summary_json_consistency": 0.0,
        "keyword_counts_csv_consistency": 0.0,
        "checks_json_consistency": 0.0,
        "totals_alignment_across_artifacts": 0.0,
    }

    robots_path = workspace / "data" / "raw" / "robots.txt"
    sitemap_path = workspace / "data" / "raw" / "sitemap.xml"
    pages_dir = workspace / "data" / "pages"
    articles_jsonl_path = workspace / "data" / "parsed" / "articles.jsonl"
    summary_json_path = workspace / "data" / "summary" / "summary.json"
    keyword_counts_csv_path = workspace / "data" / "summary" / "keyword_counts.csv"
    checks_json_path = workspace / "data" / "summary" / "checks.json"
    keywords_path = workspace / "input" / "keywords.txt"

    keywords = _load_keywords(keywords_path)

    if robots_path.exists() and sitemap_path.exists():
        scores["raw_files_exist"] = 1.0

    robots_text = _read_text(robots_path) if robots_path.exists() else None
    if robots_text is not None:
        has_sitemap_line = False
        for line in robots_text.splitlines():
            if re.match(r"^\s*Sitemap\s*:\s*https?://", line, flags=re.IGNORECASE):
                has_sitemap_line = True
                break
        scores["robots_txt_has_sitemap_lines"] = 1.0 if has_sitemap_line else 0.0

    sitemap_text = _read_text(sitemap_path) if sitemap_path.exists() else None
    locs = _parse_sitemap_locs(sitemap_text) if sitemap_text is not None else []
    if any(_is_newsroom_domain(u) and "/article" in u for u in locs):
        scores["sitemap_has_article_urls"] = 1.0

    html_pages = _list_html_pages(pages_dir)
    if 1 <= len(html_pages) <= 20:
        scores["pages_downloaded_limit"] = 1.0

    records = _load_jsonl(articles_jsonl_path) if articles_jsonl_path.exists() else None

    structure_ok = True
    if records is None or not isinstance(records, list) or len(records) == 0:
        structure_ok = False
    else:
        if not isinstance(keywords, list) or len(keywords) == 0:
            structure_ok = False
        else:
            keyword_set = set(keywords)
            for rec in records:
                if not isinstance(rec, dict):
                    structure_ok = False
                    break
                if not isinstance(rec.get("url"), str) or rec.get("url") == "":
                    structure_ok = False
                    break
                if not isinstance(rec.get("title"), str) or rec.get("title") == "":
                    structure_ok = False
                    break
                pd = rec.get("published_date", None)
                if pd is not None and not isinstance(pd, str):
                    structure_ok = False
                    break
                if isinstance(pd, str):
                    if _parse_iso8601_to_year(pd) is None:
                        structure_ok = False
                        break
                if not isinstance(rec.get("word_count"), int) or rec.get("word_count") < 0:
                    structure_ok = False
                    break
                kc = rec.get("keyword_counts")
                if not isinstance(kc, dict):
                    structure_ok = False
                    break
                kc_keys = set(kc.keys())
                if kc_keys != keyword_set:
                    structure_ok = False
                    break
                for k in keywords:
                    if not isinstance(kc.get(k), int) or kc.get(k) < 0:
                        structure_ok = False
                        break
                if not structure_ok:
                    break
    if structure_ok:
        scores["articles_jsonl_structure"] = 1.0

    if records and len(locs) > 0:
        urls = [rec.get("url") for rec in records if isinstance(rec, dict)]
        domain_ok = all(_is_newsroom_domain(u) for u in urls)
        in_sitemap_ok = all(u in locs for u in urls)
        if domain_ok and in_sitemap_ok:
            scores["urls_under_correct_domain"] = 1.0

        unique_urls = set(urls)
        if len(unique_urls) == len(urls) and len(urls) <= 20:
            scores["unique_urls_limit"] = 1.0

        expected_top20 = set(_compute_expected_top20_from_sitemap(locs))
        if len(expected_top20) > 0 and set(urls).issubset(expected_top20):
            scores["selection_respects_sitemap_preference"] = 1.0

    summary = _load_json(summary_json_path) if summary_json_path.exists() else None
    if records and isinstance(records, list) and keywords and isinstance(keywords, list) and summary:
        recomputed = _compute_aggregates_from_records(records, keywords)
        required_summary_fields = [
            "total_articles",
            "total_words",
            "average_words_per_article",
            "articles_per_year",
            "aggregate_keyword_counts",
        ]
        has_fields = all(k in summary for k in required_summary_fields)
        if has_fields:
            try:
                ta_ok = int(summary["total_articles"]) == recomputed["total_articles"]
                tw_ok = int(summary["total_words"]) == recomputed["total_words"]
                avg_ok = _nearly_equal(float(summary["average_words_per_article"]), float(recomputed["average_words_per_article"]))
                apy_ok = isinstance(summary["articles_per_year"], dict) and summary["articles_per_year"] == recomputed["articles_per_year"]
                akc_ok = isinstance(summary["aggregate_keyword_counts"], dict) and summary["aggregate_keyword_counts"] == recomputed["aggregate_keyword_counts"]
                if ta_ok and tw_ok and avg_ok and apy_ok and akc_ok:
                    scores["summary_json_consistency"] = 1.0
            except Exception:
                pass

    if keywords and isinstance(keywords, list) and summary:
        try:
            csv_ok = False
            with keyword_counts_csv_path.open("r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows and len(rows) >= 2:
                header = rows[0]
                if header == ["keyword", "count"]:
                    data = rows[1:]
                    csv_map: Dict[str, int] = {}
                    valid_rows = True
                    for r in data:
                        if len(r) != 2:
                            valid_rows = False
                            break
                        k = r[0]
                        try:
                            c = int(r[1])
                        except Exception:
                            valid_rows = False
                            break
                        csv_map[k] = c
                    if valid_rows:
                        expected_counts = summary.get("aggregate_keyword_counts")
                        if isinstance(expected_counts, dict):
                            if set(csv_map.keys()) == set(keywords) and all(csv_map.get(k, None) == expected_counts.get(k, None) for k in keywords):
                                csv_ok = True
            scores["keyword_counts_csv_consistency"] = 1.0 if csv_ok else 0.0
        except Exception:
            scores["keyword_counts_csv_consistency"] = 0.0

    checks = _load_json(checks_json_path) if checks_json_path.exists() else None
    if checks is not None:
        try:
            candidate_urls = [u for u in locs if _is_newsroom_domain(u)]
            expected_feed_candidates = len(candidate_urls)
            expected_pages_downloaded = len(html_pages)
            expected_parsed_records = len(records) if records else 0
            summary_total = int(summary["total_articles"]) if summary and "total_articles" in summary else None
            expected_totals_match = (summary_total is not None and expected_pages_downloaded == expected_parsed_records == summary_total)
            expected_keyword_list = keywords if keywords else None

            c_feed = checks.get("feed_candidates_count", None)
            c_pages = checks.get("pages_downloaded_count", None)
            c_recs = checks.get("parsed_records_count", None)
            c_totals = checks.get("totals_match", None)
            c_kwlist = None
            if "keyword_list" in checks:
                c_kwlist = checks.get("keyword_list")
            elif "keywords" in checks:
                c_kwlist = checks.get("keywords")

            ok = True
            if not isinstance(c_feed, int) or c_feed != expected_feed_candidates:
                ok = False
            if not isinstance(c_pages, int) or c_pages != expected_pages_downloaded:
                ok = False
            if not isinstance(c_recs, int) or c_recs != expected_parsed_records:
                ok = False
            if not isinstance(c_totals, bool) or c_totals != expected_totals_match:
                ok = False
            if expected_keyword_list is None or not isinstance(c_kwlist, list) or c_kwlist != expected_keyword_list:
                ok = False
            scores["checks_json_consistency"] = 1.0 if ok else 0.0
        except Exception:
            scores["checks_json_consistency"] = 0.0

    try:
        html_count = len(html_pages)
        rec_count = len(records) if records else 0
        sum_total = int(summary["total_articles"]) if summary and "total_articles" in summary else None
        if sum_total is not None and html_count == rec_count == sum_total and html_count > 0:
            scores["totals_alignment_across_artifacts"] = 1.0
    except Exception:
        scores["totals_alignment_across_artifacts"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()