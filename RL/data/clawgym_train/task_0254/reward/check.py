import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
        return rows
    except Exception:
        return None


def _read_csv_with_header(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None, None
            rows = [row for row in reader]
            return [h.strip() for h in header], rows
    except Exception:
        return None, None


def _load_jsonl(path: Path) -> Optional[List[Dict]]:
    items = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _slugify(text: str) -> str:
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-")
    return s


def _is_subpath(child: Path, parent: Path) -> bool:
    try:
        child_resolved = child.resolve()
        parent_resolved = parent.resolve()
        return parent_resolved in child_resolved.parents or child_resolved == parent_resolved
    except Exception:
        return False


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _is_iso_date(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return False
    try:
        date.fromisoformat(s)
        return True
    except Exception:
        return False


def _is_iso_datetime(s: str) -> bool:
    if not isinstance(s, str):
        return False
    try:
        s_mod = s.replace("Z", "+00:00") if isinstance(s, str) and s.endswith("Z") else s
        datetime.fromisoformat(s_mod)
        return True
    except Exception:
        return False


def _in_domain(url: str, domain: str) -> bool:
    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        dom = (domain or "").lower()
        return host == dom or host.endswith("." + dom)
    except Exception:
        return False


def _word_count(text: str) -> int:
    if not isinstance(text, str) or not text.strip():
        return 0
    return len(re.findall(r"\b\w+\b", text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "entrypoint_exists": 0.0,
        "raw_dir_per_source_present": 0.0,
        "manifest_structure_valid": 0.0,
        "manifest_landing_pages_per_source_valid": 0.0,
        "manifest_article_limits_and_domain_valid": 0.0,
        "manifest_local_paths_and_sizes_valid": 0.0,
        "items_structure_valid": 0.0,
        "items_deduplicated_by_url": 0.0,
        "items_domain_and_mapping_consistent": 0.0,
        "items_sector_and_keyword_filtering_valid": 0.0,
        "items_word_count_consistent_with_excerpt": 0.0,
        "items_local_path_matches_manifest": 0.0,
        "report_summary_by_region_sector_correct": 0.0,
        "report_summary_by_source_correct": 0.0,
    }

    # Check entrypoint existence
    entry_py = workspace / "scripts" / "fetch_and_analyze.py"
    entry_sh = workspace / "scripts" / "fetch_and_analyze.sh"
    if entry_py.exists() or entry_sh.exists():
        scores["entrypoint_exists"] = 1.0

    # Load inputs
    sources_csv = workspace / "input" / "sources.csv"
    sectors_csv = workspace / "input" / "sectors.csv"
    sources_rows = _read_csv_dicts(sources_csv)
    sectors_rows = _read_csv_dicts(sectors_csv)

    # Prepare mappings
    source_to_domain: Dict[str, str] = {}
    source_to_region: Dict[str, str] = {}
    allowed_sectors: List[str] = []
    if sources_rows is not None:
        for r in sources_rows:
            if "source" in r and "domain" in r and "region" in r:
                source_to_domain[r["source"]] = r["domain"]
                source_to_region[r["source"]] = r["region"]
    if sectors_rows is not None:
        for r in sectors_rows:
            if "sector" in r:
                allowed_sectors.append(r["sector"])

    # Check raw dirs per source
    if sources_rows is not None and len(sources_rows) > 0:
        ok_count = 0
        for r in sources_rows:
            slug = _slugify(r.get("source", ""))
            raw_dir = workspace / "data" / "raw" / slug
            if raw_dir.exists() and raw_dir.is_dir():
                html_files = list(raw_dir.rglob("*.html")) + list(raw_dir.rglob("*.htm"))
                if len(html_files) > 0:
                    ok_count += 1
        scores["raw_dir_per_source_present"] = ok_count / max(len(sources_rows), 1)
    else:
        scores["raw_dir_per_source_present"] = 0.0

    # Load and validate manifest structure
    manifest_path = workspace / "data" / "fetch_manifest.csv"
    manifest_header, manifest_rows_list = _read_csv_with_header(manifest_path)
    manifest_cols_required = ["source", "domain", "region", "url", "type", "http_status", "local_html_path", "bytes"]
    manifest_valid_header = manifest_header == manifest_cols_required
    if manifest_valid_header and manifest_rows_list is not None:
        scores["manifest_structure_valid"] = 1.0
        manifest_dict_rows: List[Dict[str, str]] = []
        for row in manifest_rows_list:
            if len(row) != len(manifest_cols_required):
                manifest_dict_rows = []
                break
            manifest_dict_rows.append({manifest_cols_required[i]: row[i] for i in range(len(manifest_cols_required))})
    else:
        manifest_dict_rows = []

    # Validate landing pages per source
    if sources_rows is not None and len(sources_rows) > 0 and manifest_dict_rows:
        landing_ok = 0
        news_keywords = ["news", "media", "press", "stories", "insights", "blog"]
        for r in sources_rows:
            src = r["source"]
            dom = r["domain"]
            landings = [m for m in manifest_dict_rows if m.get("source") == src and m.get("type") == "landing"]
            if len(landings) == 1:
                landing = landings[0]
                url = landing.get("url", "")
                path_part = urlparse(url).path.lower()
                contains_kw = any(kw in path_part for kw in news_keywords)
                in_dom = _in_domain(url, dom)
                if contains_kw and in_dom:
                    landing_ok += 1
        scores["manifest_landing_pages_per_source_valid"] = landing_ok / max(len(sources_rows), 1)
    else:
        scores["manifest_landing_pages_per_source_valid"] = 0.0

    # Validate article limits and on-domain
    if sources_rows is not None and len(sources_rows) > 0 and manifest_dict_rows:
        article_ok = 0
        for r in sources_rows:
            src = r["source"]
            dom = r["domain"]
            articles = [m for m in manifest_dict_rows if m.get("source") == src and m.get("type") == "article"]
            if len(articles) <= 10 and all(_in_domain(a.get("url", ""), dom) for a in articles):
                article_ok += 1
        scores["manifest_article_limits_and_domain_valid"] = article_ok / max(len(sources_rows), 1)
    else:
        scores["manifest_article_limits_and_domain_valid"] = 0.0

    # Validate local paths and sizes for 200-status rows
    if manifest_dict_rows:
        considered = 0
        good = 0
        data_raw_root = workspace / "data" / "raw"
        for m in manifest_dict_rows:
            status = _parse_int(m.get("http_status", ""))
            if status == 200:
                considered += 1
                local_path_str = m.get("local_html_path", "")
                bytes_str = m.get("bytes", "")
                size_decl = _parse_int(bytes_str)
                if local_path_str and size_decl is not None:
                    lp = (workspace / local_path_str) if not local_path_str.startswith("/") else Path(local_path_str)
                    if lp.exists() and lp.is_file() and _is_subpath(lp, data_raw_root):
                        try:
                            real_size = lp.stat().st_size
                            if real_size == size_decl:
                                good += 1
                        except Exception:
                            pass
        if considered > 0:
            scores["manifest_local_paths_and_sizes_valid"] = good / considered
        else:
            scores["manifest_local_paths_and_sizes_valid"] = 0.0
    else:
        scores["manifest_local_paths_and_sizes_valid"] = 0.0

    # Load items.jsonl and validate structure
    items_path = workspace / "data" / "extracted" / "items.jsonl"
    items = _load_jsonl(items_path)
    if items is None or len(items) == 0:
        pass
    else:
        # items_deduplicated_by_url
        urls = [it.get("url") for it in items]
        unique_urls = set([u for u in urls if isinstance(u, str)])
        scores["items_deduplicated_by_url"] = 1.0 if len(unique_urls) == len(items) else 0.0

        # Structure validation
        required_fields = [
            "source",
            "domain",
            "region",
            "url",
            "local_html_path",
            "title",
            "publish_date",
            "text_excerpt",
            "word_count",
            "sectors",
            "matched_keywords",
            "retrieved_at",
        ]
        data_raw_root = workspace / "data" / "raw"
        struct_total = 0
        struct_good = 0
        for it in items:
            struct_total += 1
            ok = True
            for f in required_fields:
                if f not in it:
                    ok = False
                    break
            if not ok:
                continue
            if not isinstance(it.get("source"), str) or not isinstance(it.get("domain"), str) or not isinstance(it.get("region"), str):
                ok = False
            if not isinstance(it.get("url"), str) or not it.get("url"):
                ok = False
            if not isinstance(it.get("local_html_path"), str) or not it.get("local_html_path"):
                ok = False
            if not isinstance(it.get("title"), str) or not it.get("title").strip():
                ok = False
            pub = it.get("publish_date")
            if pub is not None and not _is_iso_date(pub):
                ok = False
            if not isinstance(it.get("text_excerpt"), str):
                ok = False
            if not isinstance(it.get("word_count"), int) or it.get("word_count") < 0:
                ok = False
            if not isinstance(it.get("sectors"), list):
                ok = False
            if not isinstance(it.get("matched_keywords"), list):
                ok = False
            if not _is_iso_datetime(it.get("retrieved_at")):
                ok = False
            lp = (workspace / it.get("local_html_path")) if not it.get("local_html_path", "").startswith("/") else Path(it.get("local_html_path"))
            if not (lp.exists() and lp.is_file() and _is_subpath(lp, data_raw_root)):
                ok = False
            if ok:
                struct_good += 1
        scores["items_structure_valid"] = struct_good / max(struct_total, 1)

        # Domain and mapping consistency
        dom_total = 0
        dom_good = 0
        for it in items:
            dom_total += 1
            src = it.get("source")
            dom = it.get("domain")
            reg = it.get("region")
            url = it.get("url")
            expected_dom = source_to_domain.get(src)
            expected_reg = source_to_region.get(src)
            if expected_dom is None or expected_reg is None:
                continue
            if dom != expected_dom:
                continue
            if reg != expected_reg:
                continue
            if not _in_domain(url, expected_dom):
                continue
            dom_good += 1
        if dom_total > 0 and source_to_domain:
            scores["items_domain_and_mapping_consistent"] = dom_good / dom_total
        else:
            scores["items_domain_and_mapping_consistent"] = 0.0

        # Sector and keyword filtering validity
        filt_total = 0
        filt_good = 0
        generic_keywords = ["invest", "trade", "export", "industry"]
        allowed_set = set(allowed_sectors) if allowed_sectors else None
        for it in items:
            filt_total += 1
            sectors = it.get("sectors", [])
            mk = it.get("matched_keywords", [])
            title = it.get("title", "")
            excerpt = it.get("text_excerpt", "")
            cond = False
            if isinstance(sectors, list) and len(sectors) > 0:
                if allowed_set is not None:
                    if not all(isinstance(s, str) and s in allowed_set for s in sectors):
                        cond = False
                    else:
                        cond = True
                else:
                    cond = False
                if not isinstance(mk, list) or len(mk) == 0:
                    cond = False
            else:
                text_l = f"{title} {excerpt}".lower()
                if any(gk in text_l for gk in generic_keywords):
                    cond = True
            if cond:
                filt_good += 1
        if filt_total > 0 and allowed_sectors:
            scores["items_sector_and_keyword_filtering_valid"] = filt_good / filt_total
        else:
            scores["items_sector_and_keyword_filtering_valid"] = 0.0

        # Word count >= excerpt words
        wc_total = 0
        wc_good = 0
        for it in items:
            wc_total += 1
            wc = it.get("word_count", 0)
            excerpt = it.get("text_excerpt", "")
            if isinstance(wc, int) and wc >= _word_count(excerpt):
                wc_good += 1
        scores["items_word_count_consistent_with_excerpt"] = wc_good / max(wc_total, 1)

        # Items' local path matches manifest article rows
        if manifest_dict_rows:
            manifest_article_map: Dict[str, str] = {}
            for m in manifest_dict_rows:
                if m.get("type") == "article":
                    manifest_article_map[m.get("url", "")] = m.get("local_html_path", "")
            lm_total = 0
            lm_good = 0
            for it in items:
                lm_total += 1
                u = it.get("url", "")
                lp = it.get("local_html_path", "")
                if u in manifest_article_map and manifest_article_map[u] == lp:
                    lm_good += 1
            scores["items_local_path_matches_manifest"] = lm_good / max(lm_total, 1)
        else:
            scores["items_local_path_matches_manifest"] = 0.0

        # Reports validation
        region_sector_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        for it in items:
            reg = it.get("region")
            if not isinstance(it.get("sectors"), list):
                continue
            for sec in it.get("sectors"):
                if isinstance(sec, str):
                    region_sector_counts[(reg, sec)] += 1

        rs_path = workspace / "reports" / "summary_by_region_sector.csv"
        rs_header, rs_rows = _read_csv_with_header(rs_path)
        if rs_header == ["region", "sector", "article_count"] and rs_rows is not None:
            reported_counts: Dict[Tuple[str, str], int] = {}
            valid_rows = True
            for row in rs_rows:
                if len(row) != 3:
                    valid_rows = False
                    break
                reg, sec, cnt = row[0], row[1], row[2]
                icnt = _parse_int(cnt)
                if icnt is None:
                    valid_rows = False
                    break
                reported_counts[(reg, sec)] = icnt
            if valid_rows and reported_counts == region_sector_counts:
                scores["report_summary_by_region_sector_correct"] = 1.0
            else:
                scores["report_summary_by_region_sector_correct"] = 0.0
        else:
            scores["report_summary_by_region_sector_correct"] = 0.0

        ss_path = workspace / "reports" / "summary_by_source.csv"
        ss_header, ss_rows = _read_csv_with_header(ss_path)
        if ss_header == ["source", "domain", "total_articles", "avg_word_count"] and ss_rows is not None:
            by_source_items: Dict[str, List[Dict]] = defaultdict(list)
            for it in items:
                if isinstance(it.get("source"), str):
                    by_source_items[it["source"]].append(it)
            expected: Dict[str, Tuple[str, int, float]] = {}
            for src, its in by_source_items.items():
                dom = source_to_domain.get(src, "")
                total = len(its)
                avg_wc = sum([it.get("word_count", 0) for it in its]) / total if total > 0 else 0.0
                expected[src] = (dom, total, avg_wc)

            reported: Dict[str, Tuple[str, int, float]] = {}
            valid_rows = True
            for row in ss_rows:
                if len(row) != 4:
                    valid_rows = False
                    break
                src, dom, total_str, avg_str = row
                tot = _parse_int(total_str)
                try:
                    avg = float(avg_str)
                except Exception:
                    valid_rows = False
                    break
                if tot is None:
                    valid_rows = False
                    break
                reported[src] = (dom, tot, avg)
            if valid_rows:
                if set(reported.keys()) == set(expected.keys()) and len(expected) > 0:
                    all_match = True
                    for src, (dom_e, tot_e, avg_e) in expected.items():
                        dom_r, tot_r, avg_r = reported.get(src, ("", 0, 0.0))
                        if dom_r != dom_e:
                            all_match = False
                            break
                        if tot_r != tot_e:
                            all_match = False
                            break
                        if abs(avg_r - avg_e) > 0.01:
                            all_match = False
                            break
                    scores["report_summary_by_source_correct"] = 1.0 if all_match else 0.0
                else:
                    scores["report_summary_by_source_correct"] = 0.0
            else:
                scores["report_summary_by_source_correct"] = 0.0
        else:
            scores["report_summary_by_source_correct"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()