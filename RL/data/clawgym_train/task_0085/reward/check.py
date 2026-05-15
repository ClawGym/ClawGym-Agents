import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl(path: Path):
    lines = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    lines.append(obj)
                except Exception:
                    # malformed line; return None to signal failure
                    return None
        return lines
    except Exception:
        return None


def _load_csv(path: Path):
    rows = []
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({k: v for k, v in row.items()})
        # Basic header validation
        required = {"fixture_id", "sport", "league", "home_team", "away_team", "date", "venue_city", "country"}
        if not rows and required.issubset(set()):
            return None
        if rows:
            if not required.issubset(set(rows[0].keys())):
                return None
        return rows
    except Exception:
        return None


def _parse_iso(dt_str: str):
    if not isinstance(dt_str, str) or not dt_str.strip():
        return None
    s = dt_str.strip()
    try:
        # Handle 'Z'
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        # Fallback simple patterns
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(dt_str, fmt)
            except Exception:
                continue
    return None


def _domain_from_url(u: str) -> str:
    try:
        p = urlparse(u)
        host = p.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _list_dir_files(d: Path):
    if not d.exists() or not d.is_dir():
        return []
    try:
        return [p for p in d.iterdir() if p.is_file()]
    except Exception:
        return []


def _lower_set(iterable):
    return {str(x).strip().lower() for x in iterable if isinstance(x, str) and str(x).strip()}


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "html_downloads_per_fixture": 0.0,
        "extracted_pages_structure": 0.0,
        "search_log_quality": 0.0,
        "search_queries_quality": 0.0,
        "extracted_urls_from_search": 0.0,
        "downloads_vs_extracted_count": 0.0,
        "bulletin_json_structure": 0.0,
        "bulletin_md_sections": 0.0,
        "alerts_consistency": 0.0,
        "status_classification_consistency": 0.0,
        "no_social_media_sources": 0.0,
    }

    fixtures_path = workspace / "input" / "fixtures.csv"
    keywords_path = workspace / "input" / "keywords.txt"

    fixtures = _load_csv(fixtures_path)
    keywords_text = _read_text(keywords_path)
    keywords = [k.strip() for k in keywords_text.splitlines() if k.strip()]
    keywords_lower = _lower_set(keywords)

    if not fixtures or not keywords_lower:
        # Without fixtures or keywords, we cannot validate meaningful outputs
        return scores

    fixture_ids = [f["fixture_id"] for f in fixtures]
    fixture_by_id = {f["fixture_id"]: f for f in fixtures}

    # Load search log
    search_log_path = workspace / "logs" / "search_log.jsonl"
    search_lines = _load_jsonl(search_log_path)
    # Build mapping per fixture of search log entry (prefer last occurrence if multiple)
    search_by_fixture = {}
    if search_lines is not None:
        for entry in search_lines:
            if not isinstance(entry, dict):
                continue
            fid = entry.get("fixture_id")
            if fid in fixture_by_id:
                search_by_fixture[fid] = entry

    # Load bulletin.json
    bulletin_json_path = workspace / "outputs" / "status" / "bulletin.json"
    bulletin_json = _load_json(bulletin_json_path)
    bulletin_by_fixture = {}
    if isinstance(bulletin_json, list):
        for obj in bulletin_json:
            if isinstance(obj, dict) and obj.get("fixture_id") in fixture_by_id:
                bulletin_by_fixture[obj["fixture_id"]] = obj

    # Load bulletin.md
    bulletin_md_path = workspace / "outputs" / "status" / "bulletin.md"
    bulletin_md = _read_text(bulletin_md_path)

    # Load alerts
    alerts_path = workspace / "outputs" / "alerts" / "new_alerts.json"
    alerts_json = _load_json(alerts_path)

    # Per-fixture aggregations for scoring
    downloads_ok = 0
    extracted_ok = 0
    search_quality_ok = 0
    query_quality_ok = 0
    extracted_url_match_ok = 0
    download_vs_extracted_ok = 0
    bulletin_json_ok = 0
    bulletin_md_ok = 0
    status_logic_ok = 0

    social_domains_blocklist = {
        "twitter.com", "x.com", "facebook.com", "instagram.com", "tiktok.com",
        "weibo.com", "weixin.qq.com", "reddit.com", "youtube.com", "m.facebook.com"
    }
    non_social_fixtures = 0

    # First, gather selected urls per fixture for cross-checks and social sources
    social_violation_fixtures = set()
    for fid in fixture_ids:
        entry = search_by_fixture.get(fid)
        if not isinstance(entry, dict):
            social_violation_fixtures.add(fid)
            continue
        urls = entry.get("selected_urls")
        if not isinstance(urls, list) or not urls:
            social_violation_fixtures.add(fid)
            continue
        has_social = False
        for u in urls:
            if not isinstance(u, str):
                continue
            dom = _domain_from_url(u)
            if dom in social_domains_blocklist:
                has_social = True
        if not has_social:
            non_social_fixtures += 1

    # Validate per fixture
    for f in fixtures:
        fid = f["fixture_id"]
        home = f["home_team"]
        away = f["away_team"]
        league = f["league"]
        date_str = f["date"]
        city = f["venue_city"]

        # Downloads presence
        dl_dir = workspace / "downloads" / "html" / fid
        dl_files = _list_dir_files(dl_dir)
        if len(dl_files) >= 1:
            downloads_ok += 1

        # Extracted structure
        extracted_path = workspace / "outputs" / "extracted" / f"{fid}_pages.json"
        extracted = _load_json(extracted_path)
        extracted_valid = True
        if not isinstance(extracted, list) or len(extracted) == 0:
            extracted_valid = False
        else:
            for item in extracted:
                if not isinstance(item, dict):
                    extracted_valid = False
                    break
                # Required fields
                source_url = item.get("source_url")
                domain = item.get("domain")
                fetched_at = item.get("fetched_at")
                text_length = item.get("text_length")
                keyword_hits = item.get("keyword_hits")
                snippet = item.get("snippet")
                if not isinstance(source_url, str) or not source_url.startswith(("http://", "https://")):
                    extracted_valid = False
                    break
                if not isinstance(domain, str) or not domain:
                    extracted_valid = False
                    break
                # domain matches URL
                if _domain_from_url(source_url) != domain.lower():
                    extracted_valid = False
                    break
                if _parse_iso(fetched_at) is None:
                    extracted_valid = False
                    break
                if not isinstance(text_length, int) or text_length < 0:
                    extracted_valid = False
                    break
                if not isinstance(keyword_hits, list):
                    extracted_valid = False
                    break
                # verify hits are within provided keywords (case-insensitive)
                for h in keyword_hits:
                    if not isinstance(h, str) or h.strip().lower() not in keywords_lower:
                        extracted_valid = False
                        break
                if not isinstance(snippet, str):
                    extracted_valid = False
                    break
                if keyword_hits and len(snippet.strip()) < 10:
                    extracted_valid = False
                    break
                # ok continue
        if extracted_valid:
            extracted_ok += 1

        # Search log quality
        entry = search_by_fixture.get(fid)
        search_entry_ok = True
        if not isinstance(entry, dict):
            search_entry_ok = False
        else:
            query = entry.get("query")
            ts = entry.get("timestamp_iso")
            urls = entry.get("selected_urls")
            notes = entry.get("selection_notes")
            if not isinstance(query, str) or not query.strip():
                search_entry_ok = False
            if _parse_iso(ts) is None:
                search_entry_ok = False
            if not isinstance(urls, list) or len(urls) == 0:
                search_entry_ok = False
            if not isinstance(notes, list) or len(notes) != len(urls):
                search_entry_ok = False
            else:
                # Ensure notes indicate official/authoritative for each URL
                # We only require at least one note per URL containing authority markers
                allowed_markers = ["official", "league", "competition", "stadium", "venue", "club", "team",
                                   "gov", "government", ".gov", "met office", "meteorological", "transport", "authority"]
                for n in notes:
                    if not isinstance(n, str) or not any(m in n.lower() for m in allowed_markers):
                        search_entry_ok = False
                        break
        if search_entry_ok:
            search_quality_ok += 1

        # Search queries quality: include team names, date, and city
        query_ok = False
        if isinstance(entry, dict):
            query = entry.get("query", "")
            if isinstance(query, str):
                ql = query.lower()
                team_ok = (home.lower() in ql) or (away.lower() in ql)
                city_ok = city.lower() in ql
                date_ok = date_str in query  # case-sensitive exact date
                if team_ok and city_ok and date_ok:
                    query_ok = True
        if query_ok:
            query_quality_ok += 1

        # Extracted URLs are from selected URLs
        extracted_urls_ok = False
        if extracted_valid and isinstance(entry, dict):
            urls = entry.get("selected_urls", [])
            urls_set = set(u for u in urls if isinstance(u, str))
            if urls_set:
                all_in = True
                for item in extracted:
                    su = item.get("source_url")
                    if su not in urls_set:
                        all_in = False
                        break
                extracted_urls_ok = all_in
        if extracted_urls_ok:
            extracted_url_match_ok += 1

        # Downloads count >= extracted count
        if extracted_valid:
            if len(dl_files) >= len(extracted) and len(extracted) > 0:
                download_vs_extracted_ok += 1

        # Bulletin JSON structure and coverage
        bj_ok = True
        bobj = bulletin_by_fixture.get(fid)
        if not isinstance(bobj, dict):
            bj_ok = False
        else:
            # Required fields and values
            match_label = bobj.get("match_label")
            if not isinstance(match_label, str):
                bj_ok = False
            else:
                # contains "Home vs Away" and league
                if (f"{home} vs {away}") not in match_label or (league not in match_label):
                    bj_ok = False
            if bobj.get("date") != date_str:
                bj_ok = False
            if bobj.get("venue_city") != city:
                bj_ok = False
            status = bobj.get("status")
            allowed_status = {"none", "risk", "postponed/rescheduled", "canceled"}
            if status not in allowed_status:
                bj_ok = False
            hits_total = bobj.get("hits_total")
            if not isinstance(hits_total, int) or hits_total < 0:
                bj_ok = False
            top_sources = bobj.get("top_sources")
            if not isinstance(top_sources, list) or not (1 <= len(top_sources) <= 3):
                bj_ok = False
            else:
                # top_sources subset of extracted source URLs
                if extracted_valid:
                    ex_urls = {it.get("source_url") for it in extracted if isinstance(it, dict)}
                    for u in top_sources:
                        if not isinstance(u, str) or u not in ex_urls:
                            bj_ok = False
                            break
                else:
                    bj_ok = False
            rationale = bobj.get("rationale")
            if not isinstance(rationale, str) or not rationale.strip():
                bj_ok = False
            # hits_total baseline consistency: >= number of items with non-empty keyword_hits
            if extracted_valid:
                min_hits = sum(1 for it in extracted if isinstance(it, dict) and isinstance(it.get("keyword_hits"), list) and len(it.get("keyword_hits")) > 0)
                if hits_total < min_hits:
                    bj_ok = False
        if bj_ok:
            bulletin_json_ok += 1

        # Bulletin MD section presence: line containing "Home vs Away" and status
        md_ok = False
        if bulletin_md:
            lines = bulletin_md.splitlines()
            target = f"{home} vs {away}"
            status_val = None
            if isinstance(bobj, dict):
                status_val = bobj.get("status")
            for line in lines:
                if target in line and (status_val in line if status_val else True):
                    md_ok = True
                    break
        if md_ok:
            bulletin_md_ok += 1

        # Status classification consistency
        # Build url->category mapping from selection_notes
        status_ok = False
        if extracted_valid and isinstance(entry, dict):
            urls = entry.get("selected_urls", [])
            notes = entry.get("selection_notes", [])
            url_cat = {}
            if isinstance(urls, list) and isinstance(notes, list) and len(urls) == len(notes):
                for u, n in zip(urls, notes):
                    if not isinstance(u, str) or not isinstance(n, str):
                        continue
                    nl = n.lower()
                    cat = "other"
                    if any(k in nl for k in ["official", "club", "league", "competition", "stadium", "venue", "team"]):
                        cat = "official"
                    if any(k in nl for k in ["gov", ".gov", "government", "met office", "meteorological", "transport", "authority"]):
                        # treat as authority if these appear (can override)
                        cat = "authority" if cat != "official" else "official"
                    url_cat[u] = cat
            # Determine expected status
            canceled_keys = {"canceled", "cancelled", "abandoned"}
            postponed_keys = {"postponed", "rescheduled"}
            risk_keys = {"weather alert", "storm", "typhoon", "blizzard", "heavy rain", "transport strike", "travel disruption"}
            exp_status = "none"
            # Official checks
            any_official_cancel = False
            any_official_postpone = False
            for it in extracted:
                su = it.get("source_url")
                kh = [k.strip().lower() for k in it.get("keyword_hits", []) if isinstance(k, str)]
                cat = url_cat.get(su, "other")
                if cat == "official":
                    if any(k in canceled_keys for k in kh):
                        any_official_cancel = True
                    if any(k in postponed_keys for k in kh):
                        any_official_postpone = True
            if any_official_cancel:
                exp_status = "canceled"
            elif any_official_postpone:
                exp_status = "postponed/rescheduled"
            else:
                # Authority risk check
                any_authority_risk = False
                for it in extracted:
                    su = it.get("source_url")
                    kh = [k.strip().lower() for k in it.get("keyword_hits", []) if isinstance(k, str)]
                    cat = url_cat.get(su, "other")
                    if cat == "authority":
                        if any(k in risk_keys for k in kh):
                            any_authority_risk = True
                            break
                if any_authority_risk:
                    exp_status = "risk"
            reported_status = bobj.get("status") if isinstance(bobj, dict) else None
            if reported_status == exp_status:
                status_ok = True
        if status_ok:
            status_logic_ok += 1

    total = len(fixtures) if len(fixtures) > 0 else 1

    scores["html_downloads_per_fixture"] = downloads_ok / total
    scores["extracted_pages_structure"] = extracted_ok / total
    scores["search_log_quality"] = search_quality_ok / total
    scores["search_queries_quality"] = query_quality_ok / total
    scores["extracted_urls_from_search"] = extracted_url_match_ok / total
    scores["downloads_vs_extracted_count"] = download_vs_extracted_ok / total
    scores["bulletin_json_structure"] = bulletin_json_ok / total
    scores["bulletin_md_sections"] = bulletin_md_ok / total
    scores["status_classification_consistency"] = status_logic_ok / total
    scores["no_social_media_sources"] = non_social_fixtures / total

    # Alerts consistency check
    alerts_ok = False
    if isinstance(alerts_json, dict):
        gen = alerts_json.get("generated_at")
        alerts_list = alerts_json.get("alerts")
        gen_ok = _parse_iso(gen) is not None
        if isinstance(alerts_list, list) and gen_ok:
            # Determine expected fixtures with status != 'none'
            expected = set()
            for fid in fixture_ids:
                bobj = bulletin_by_fixture.get(fid)
                if isinstance(bobj, dict) and bobj.get("status") in {"risk", "postponed/rescheduled", "canceled"}:
                    expected.add(fid)
            actual = set()
            for a in alerts_list:
                if isinstance(a, dict) and "fixture_id" in a:
                    actual.add(a["fixture_id"])
                elif isinstance(a, str):
                    actual.add(a)
            if expected == actual:
                alerts_ok = True
    scores["alerts_consistency"] = 1.0 if alerts_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()