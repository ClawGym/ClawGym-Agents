import json
import csv
import sys
import re
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        return json.loads(_read_text(path))
    except Exception:
        return None


def _load_jsonl(path: Path):
    items = []
    txt = _read_text(path)
    if txt is None:
        return None
    lines = [ln for ln in txt.splitlines() if ln.strip() != ""]
    for i, line in enumerate(lines, 1):
        try:
            obj = json.loads(line)
            if not isinstance(obj, dict):
                return None
            items.append(obj)
        except Exception:
            return None
    return items


def _parse_tsv(path: Path, expected_header=None):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)
            header = reader.fieldnames
            return header, rows
    except Exception:
        return None, None


def _parse_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames
            return header, rows
    except Exception:
        return None, None


def _normalize_domain(domain: str) -> str:
    if not domain:
        return ""
    d = domain.strip().lower()
    if "://" in d or "/" in d:
        try:
            parsed = urlparse(d if "://" in d else "http://" + d)
            d = parsed.netloc
        except Exception:
            pass
    if d.startswith("www."):
        d = d[4:]
    if ":" in d:
        d = d.split(":")[0]
    return d


def _domain_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc
        return _normalize_domain(netloc)
    except Exception:
        return ""


def _is_excluded_domain(domain: str, excluded: set) -> bool:
    d = _normalize_domain(domain)
    for ex in excluded:
        if d == ex or d.endswith("." + ex) or d.endswith(ex):
            return True
    return False


def _is_official_domain(domain: str) -> bool:
    d = _normalize_domain(domain)
    if not d:
        return False
    if d == "oregon.gov" or d.endswith(".oregon.gov"):
        return True
    if d.endswith(".gov"):
        return True
    if d.endswith(".state.or.us") or d.endswith(".or.us"):
        return True
    if d == "blm.gov" or d.endswith(".blm.gov"):
        return True
    if d == "usda.gov" or d.endswith(".usda.gov"):
        return True
    if d == "fs.usda.gov" or d.endswith(".fs.usda.gov"):
        return True
    if d == "fsc.org" or d.endswith(".fsc.org"):
        return True
    if d == "pefc.org" or d.endswith(".pefc.org"):
        return True
    return False


def _parse_iso8601(s: str):
    if not s or not isinstance(s, str):
        return None
    val = s.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", val):
            dt = datetime.strptime(val, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt
        if val.endswith("Z"):
            val = val[:-1] + "+00:00"
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _semilist(s: str):
    if s is None:
        return []
    parts = [p.strip() for p in s.split(";")]
    return [p for p in parts if p != ""]


def _count_occurrences(text: str, sub: str) -> int:
    if not text or not sub:
        return 0
    t = text.lower()
    q = sub.lower()
    count = 0
    start = 0
    while True:
        idx = t.find(q, start)
        if idx == -1:
            break
        count += 1
        start = idx + 1
    return count


def _compute_relevance_score(title: str, excerpt: str, location: str, weights: dict, priority_names: list) -> float:
    title = title or ""
    excerpt = excerpt or ""
    location = location or ""
    corpus = f"{title} {excerpt} {location}".lower()
    score = 0.0
    for kw, w in weights.items():
        score += _count_occurrences(corpus, kw.lower()) * float(w)
    title_lower = title.lower()
    unique_bonus_names = set()
    for name in priority_names:
        if name and name.lower() in title_lower:
            unique_bonus_names.add(name.lower())
    score += 2.0 * len(unique_bonus_names)
    return float(score)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "search_log_exists_and_format": 0.0,
        "search_log_queries_cover_all_areas": 0.0,
        "search_log_domains_allowed_and_excluded_respected": 0.0,
        "raw_pages_count_and_domains_coverage": 0.0,
        "notices_jsonl_structure_and_dates": 0.0,
        "filtered_csv_structure_and_dedup": 0.0,
        "filtered_date_range_and_area_match": 0.0,
        "relevance_score_correctness": 0.0,
        "top_20_correctness": 0.0,
        "summary_fields_and_consistency": 0.0,
    }

    priority_csv = workspace / "input" / "priority_areas.csv"
    _, priority_rows = _parse_csv(priority_csv) if priority_csv.exists() else (None, None)
    priority_areas = []
    if priority_rows is not None:
        for r in priority_rows:
            name = (r.get("area_name") or "").strip()
            if name:
                priority_areas.append(name)

    kw_weights_path = workspace / "input" / "keyword_weights.json"
    keyword_weights = _load_json(kw_weights_path) if kw_weights_path.exists() else None
    if not isinstance(keyword_weights, dict):
        keyword_weights = None
    else:
        keyword_weights = {str(k).lower(): float(v) for k, v in keyword_weights.items()}

    exclude_path = workspace / "input" / "exclude_domains.txt"
    excluded_domains = set()
    if exclude_path.exists():
        txt = _read_text(exclude_path) or ""
        for line in txt.splitlines():
            dom = line.strip().lower()
            if dom:
                if dom.startswith("www."):
                    dom = dom[4:]
                excluded_domains.add(dom)

    search_log_path = workspace / "logs" / "search_log.tsv"
    raw_pages_dir = workspace / "data" / "raw_pages"
    notices_jsonl_path = workspace / "data" / "extracted" / "notices.jsonl"
    filtered_csv_path = workspace / "data" / "filtered" / "filtered_notices.csv"
    top20_csv_path = workspace / "reports" / "top_20.csv"
    summary_json_path = workspace / "logs" / "summary.json"

    raw_pages = []
    if raw_pages_dir.exists():
        raw_pages = list(raw_pages_dir.rglob("*.html"))

    sl_header, sl_rows = (None, None)
    if search_log_path.exists():
        sl_header, sl_rows = _parse_tsv(search_log_path)

    search_log_ok = False
    if sl_header and sl_rows is not None:
        expected = ["timestamp_utc", "area_name", "query", "urls_saved_count", "domains_saved"]
        if sl_header == expected and len(sl_rows) > 0:
            per_row_ok = True
            query_terms = [
                "public notice", "public comment", "meeting", "hearing", "permit",
                "logging", "timber", "harvest", "timber sale", "forest management plan"
            ]
            for r in sl_rows:
                ts = (r.get("timestamp_utc") or "").strip()
                area = (r.get("area_name") or "").strip()
                query = (r.get("query") or "").strip().lower()
                urls_saved = r.get("urls_saved_count")
                domains_saved = (r.get("domains_saved") or "").strip()
                dt = _parse_iso8601(ts)
                if dt is None:
                    per_row_ok = False
                    break
                if priority_areas:
                    if area not in priority_areas:
                        per_row_ok = False
                        break
                if area and area.lower() not in query:
                    per_row_ok = False
                    break
                if not any(t in query for t in query_terms):
                    per_row_ok = False
                    break
                try:
                    usi = int(str(urls_saved).strip())
                    if usi < 0:
                        per_row_ok = False
                        break
                except Exception:
                    per_row_ok = False
                    break
                doms = [_normalize_domain(d) for d in _semilist(domains_saved)]
                if len(doms) != len(set(doms)):
                    per_row_ok = False
                    break
            search_log_ok = per_row_ok
    scores["search_log_exists_and_format"] = 1.0 if search_log_ok else 0.0

    cover_ok = False
    if sl_rows is not None and priority_areas:
        areas_found = set()
        for r in sl_rows:
            area = (r.get("area_name") or "").strip()
            if area:
                areas_found.add(area)
        cover_ok = all(a in areas_found for a in priority_areas)
    scores["search_log_queries_cover_all_areas"] = 1.0 if cover_ok else 0.0

    domains_ok = False
    if sl_rows is not None and len(sl_rows) > 0:
        all_doms = []
        allowed = True
        for r in sl_rows:
            doms = [_normalize_domain(d) for d in _semilist((r.get("domains_saved") or "").strip())]
            all_doms.extend(doms)
            for d in doms:
                if _is_excluded_domain(d, excluded_domains):
                    allowed = False
                    break
                if not _is_official_domain(d):
                    allowed = False
                    break
            if not allowed:
                break
        domains_ok = allowed and len(all_doms) > 0
    scores["search_log_domains_allowed_and_excluded_respected"] = 1.0 if domains_ok else 0.0

    pages_ok = False
    pages_count = len(raw_pages)
    unique_domains_logged = set()
    if sl_rows:
        for r in sl_rows:
            for d in _semilist((r.get("domains_saved") or "").strip()):
                unique_domains_logged.add(_normalize_domain(d))
    if pages_count >= 10 and len(unique_domains_logged) >= 3:
        pages_ok = True
    scores["raw_pages_count_and_domains_coverage"] = 1.0 if pages_ok else 0.0

    notices = _load_jsonl(notices_jsonl_path) if notices_jsonl_path.exists() else None

    notices_ok = False
    if isinstance(notices, list) and len(notices) > 0 and isinstance(keyword_weights, dict):
        required_fields = ["source_url", "source_domain", "page_title", "notice_title", "notice_date", "text_excerpt", "keywords_matched"]
        all_ok = True
        for obj in notices:
            for k in required_fields:
                if k not in obj or (isinstance(obj[k], str) and obj[k].strip() == ""):
                    all_ok = False
                    break
            if not all_ok:
                break
            nd = _parse_iso8601(str(obj.get("notice_date")))
            if nd is None:
                all_ok = False
                break
            km = _semilist(obj.get("keywords_matched"))
            if any(k.lower() not in keyword_weights for k in km):
                all_ok = False
                break
            tex = (obj.get("text_excerpt") or "")
            if km:
                if not any(k.lower() in tex.lower() for k in km):
                    all_ok = False
                    break
        notices_ok = all_ok
    scores["notices_jsonl_structure_and_dates"] = 1.0 if notices_ok else 0.0

    f_header, f_rows = (None, None)
    if filtered_csv_path.exists():
        f_header, f_rows = _parse_csv(filtered_csv_path)

    notice_index = {}
    if notices:
        for n in notices:
            key = (
                (n.get("source_url") or "").strip(),
                (n.get("notice_title") or "").strip(),
                (n.get("notice_date") or "").strip(),
            )
            notice_index.setdefault(key, []).append(n)

    filtered_structure_ok = False
    if f_header and f_rows is not None and isinstance(keyword_weights, dict):
        expected_header = [
            "id", "source_url", "source_domain", "notice_title", "notice_date",
            "location", "matched_areas", "relevance_score", "keywords_matched"
        ]
        if f_header == expected_header:
            try:
                ids_seen = set()
                triples_seen = set()
                per_row_ok = True
                for r in f_rows:
                    rid = (r.get("id") or "").strip()
                    if not rid or rid in ids_seen:
                        per_row_ok = False
                        break
                    ids_seen.add(rid)
                    rs = r.get("relevance_score")
                    _ = float(str(rs))
                    km = _semilist(r.get("keywords_matched"))
                    if any(k.lower() not in keyword_weights for k in km):
                        per_row_ok = False
                        break
                    triple = (
                        (r.get("notice_title") or "").strip().lower(),
                        (r.get("notice_date") or "").strip(),
                        (r.get("source_domain") or "").strip().lower()
                    )
                    if triple in triples_seen:
                        per_row_ok = False
                        break
                    triples_seen.add(triple)
                    key = (
                        (r.get("source_url") or "").strip(),
                        (r.get("notice_title") or "").strip(),
                        (r.get("notice_date") or "").strip(),
                    )
                    if key not in notice_index:
                        per_row_ok = False
                        break
                filtered_structure_ok = per_row_ok
            except Exception:
                filtered_structure_ok = False
    scores["filtered_csv_structure_and_dedup"] = 1.0 if filtered_structure_ok else 0.0

    date_area_ok = False
    if f_rows is not None and notices:
        today = datetime.utcnow().replace(tzinfo=timezone.utc)
        horizon = today + timedelta(days=365)
        per_row_ok = True
        for r in f_rows:
            nds = (r.get("notice_date") or "").strip()
            nd = _parse_iso8601(nds)
            if nd is None:
                per_row_ok = False
                break
            if not (nd >= today and nd <= horizon):
                per_row_ok = False
                break
            mas = _semilist(r.get("matched_areas"))
            if not mas:
                per_row_ok = False
                break
            if priority_areas:
                for m in mas:
                    if m not in priority_areas:
                        per_row_ok = False
                        break
                if not per_row_ok:
                    break
            key = (
                (r.get("source_url") or "").strip(),
                (r.get("notice_title") or "").strip(),
                (r.get("notice_date") or "").strip(),
            )
            nlist = notice_index.get(key, [])
            if not nlist:
                per_row_ok = False
                break
            n = nlist[0]
            title = (r.get("notice_title") or "")
            loc = (r.get("location") or "")
            excerpt = (n.get("text_excerpt") or "")
            combined = f"{title} {loc} {excerpt}".lower()
            for m in mas:
                if m.lower() not in combined:
                    per_row_ok = False
                    break
            if not per_row_ok:
                break
        date_area_ok = per_row_ok
    scores["filtered_date_range_and_area_match"] = 1.0 if date_area_ok else 0.0

    rel_ok = False
    if f_rows is not None and notices and keyword_weights is not None:
        try:
            per_row_ok = True
            for r in f_rows:
                key = (
                    (r.get("source_url") or "").strip(),
                    (r.get("notice_title") or "").strip(),
                    (r.get("notice_date") or "").strip(),
                )
                nlist = notice_index.get(key)
                if not nlist:
                    per_row_ok = False
                    break
                n = nlist[0]
                title = (r.get("notice_title") or "")
                excerpt = (n.get("text_excerpt") or "")
                loc = (r.get("location") or "")
                computed = _compute_relevance_score(title, excerpt, loc, keyword_weights, priority_areas or [])
                try:
                    provided = float(str(r.get("relevance_score")))
                except Exception:
                    per_row_ok = False
                    break
                if abs(computed - provided) > 1e-6:
                    per_row_ok = False
                    break
            rel_ok = per_row_ok
        except Exception:
            rel_ok = False
    scores["relevance_score_correctness"] = 1.0 if rel_ok else 0.0

    top_ok = False
    t_header, t_rows = (None, None)
    if top20_csv_path.exists():
        t_header, t_rows = _parse_csv(top20_csv_path)
    if f_rows is not None and t_header and t_rows is not None:
        expected_header = [
            "id", "source_url", "source_domain", "notice_title", "notice_date",
            "location", "matched_areas", "relevance_score", "keywords_matched"
        ]
        if t_header == expected_header:
            def sort_key(row):
                try:
                    rs = float(str(row.get("relevance_score")))
                except Exception:
                    rs = float("-inf")
                nd = _parse_iso8601((row.get("notice_date") or "").strip())
                nd_key = nd if nd is not None else datetime.max.replace(tzinfo=timezone.utc)
                title_key = (row.get("notice_title") or "").lower()
                return (-rs, nd_key, title_key)

            sorted_filtered = sorted(f_rows, key=sort_key)
            top_n = min(20, len(sorted_filtered))
            expected_ids = [r["id"] for r in sorted_filtered[:top_n]]
            got_ids = [r.get("id") for r in t_rows]
            if len(t_rows) == top_n and expected_ids == got_ids:
                top_ok = True
    scores["top_20_correctness"] = 1.0 if top_ok else 0.0

    summary_ok = False
    summary = _load_json(summary_json_path) if summary_json_path.exists() else None
    if isinstance(summary, dict):
        required_keys = ["total_pages_downloaded", "distinct_domains_count", "total_notices_extracted", "filtered_notices_count", "top_domains", "coverage_ok"]
        types_ok = all(k in summary for k in required_keys)
        if types_ok:
            try:
                tpd = int(summary["total_pages_downloaded"])
                ddc = int(summary["distinct_domains_count"])
                tne = int(summary["total_notices_extracted"])
                fnc = int(summary["filtered_notices_count"])
                cov = bool(summary["coverage_ok"])
                td = summary["top_domains"]
                pages_count_actual = len(raw_pages)
                notices_count_actual = len(notices) if notices else 0
                filtered_rows_count = len(f_rows) if f_rows else 0
                cond = True
                if pages_count_actual != tpd:
                    cond = False
                if notices_count_actual != tne:
                    cond = False
                if filtered_rows_count != fnc:
                    cond = False
                expected_cov = (tpd >= 10 and ddc >= 3)
                if bool(cov) != expected_cov:
                    cond = False
                if not isinstance(td, list) or len(td) > 10:
                    cond = False
                else:
                    sum_counts = None
                    if len(td) == 0:
                        sum_counts = 0
                    else:
                        all_dicts = all(isinstance(x, dict) and ("domain" in x) and ("count" in x) for x in td)
                        if all_dicts:
                            try:
                                sum_counts = sum(int(x["count"]) for x in td)
                            except Exception:
                                sum_counts = None
                    if sum_counts is not None and sum_counts != tpd:
                        cond = False
                summary_ok = cond
            except Exception:
                summary_ok = False
    scores["summary_fields_and_consistency"] = 1.0 if summary_ok else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()