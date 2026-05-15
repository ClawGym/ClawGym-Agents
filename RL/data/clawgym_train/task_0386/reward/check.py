import json
import csv
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_read_json(path: Path) -> Optional[Any]:
    try:
        txt = _safe_read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _safe_read_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    items: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                if not isinstance(obj, dict):
                    return None
                items.append(obj)
        return items
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # Ensure all keys are present
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _load_watchlist(workspace: Path) -> Optional[List[Dict[str, str]]]:
    wl = workspace / "input" / "watchlist.csv"
    rows = _safe_read_csv_dicts(wl)
    if rows is None:
        return None
    # Validate header presence
    # DictReader uses header line; if missing columns, their keys won't be present
    expected_cols = ["org_name", "domain"]
    if set([c.strip() for c in expected_cols]).issubset(set([k.strip() for k in rows[0].keys()])) if rows else True:
        return rows
    return None


def _normalize_domain(domain: str) -> str:
    return domain.strip().lower()


def _extract_watchlist_orgs_domains(rows: List[Dict[str, str]]) -> List[Tuple[str, str]]:
    result: List[Tuple[str, str]] = []
    for r in rows:
        org = (r.get("org_name") or "").strip()
        dom = _normalize_domain(r.get("domain") or "")
        if org and dom:
            result.append((org, dom))
    return result


def _group_log_by_domain(log_rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    d: Dict[str, List[Dict[str, Any]]] = {}
    for r in log_rows:
        dom = _normalize_domain(str(r.get("domain", "")))
        if not dom:
            continue
        d.setdefault(dom, []).append(r)
    return d


def _parse_int(value: Any) -> Optional[int]:
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    except Exception:
        return None
    return None


def _is_email(s: str) -> bool:
    # basic email check
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s) is not None


def _is_normalized_phone(s: str) -> bool:
    return re.match(r"^\+?\d+$", s) is not None


def _unfold_ics_lines(text: str) -> List[str]:
    # Unfold according to RFC 5545: lines that begin with space or tab are continuations
    lines = text.replace("\r\n", "\n").split("\n")
    unfolded: List[str] = []
    for line in lines:
        if not unfolded:
            unfolded.append(line)
        else:
            if line.startswith(" ") or line.startswith("\t"):
                unfolded[-1] += line[1:]
            else:
                unfolded.append(line)
    return unfolded


def _parse_ics_events(text: str) -> List[Dict[str, str]]:
    if text is None:
        return []
    lines = _unfold_ics_lines(text)
    events: List[Dict[str, str]] = []
    in_event = False
    current: Dict[str, str] = {}
    for line in lines:
        if line.strip() == "BEGIN:VEVENT":
            in_event = True
            current = {}
            continue
        if line.strip() == "END:VEVENT":
            if current:
                events.append(current)
            in_event = False
            current = {}
            continue
        if in_event:
            if ":" in line:
                key, val = line.split(":", 1)
                # Remove parameters from key (e.g., DTSTART;VALUE=DATE)
                key = key.split(";", 1)[0].strip().upper()
                current[key] = val.strip()
    return events


def _read_summary_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    return _safe_read_csv_dicts(path)


def _validate_contacts_schema(contacts: Any, expected_orgs_domains: List[Tuple[str, str]]) -> Tuple[bool, Dict[str, Dict[str, Any]]]:
    """
    Returns (valid_schema, mapping_by_domain)
    """
    if not isinstance(contacts, list):
        return (False, {})
    expected_keys = {"org_name", "domain", "fetched_urls", "rss_feeds_discovered", "emails", "phones", "latest_items"}
    mapping: Dict[str, Dict[str, Any]] = {}
    # Basic schema check: all items dicts with exact keys and proper types
    for item in contacts:
        if not isinstance(item, dict):
            return (False, {})
        if set(item.keys()) != expected_keys:
            return (False, {})
        # types
        if not isinstance(item["org_name"], str):
            return (False, {})
        if not isinstance(item["domain"], str):
            return (False, {})
        if not isinstance(item["fetched_urls"], list):
            return (False, {})
        if not isinstance(item["rss_feeds_discovered"], list):
            return (False, {})
        if not isinstance(item["emails"], list):
            return (False, {})
        if not isinstance(item["phones"], list):
            return (False, {})
        if not isinstance(item["latest_items"], list):
            return (False, {})
        # latest_items structure
        for li in item["latest_items"]:
            if not isinstance(li, dict):
                return (False, {})
            if set(li.keys()) != {"title", "link", "source"}:
                return (False, {})
            if not isinstance(li["title"], str):
                return (False, {})
            if not isinstance(li["link"], str):
                return (False, {})
            if li["source"] not in {"feed", "page"}:
                return (False, {})
        # map by domain
        dom = _normalize_domain(item["domain"])
        mapping[dom] = item
    # ensure one per org expected
    # allow extra entries? The spec says "one object per org". We'll enforce exactly as many as watchlist.
    if len(contacts) != len(expected_orgs_domains):
        # still return mapping but schema considered invalid
        return (False, mapping)
    return (True, mapping)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_cli_exists": 0.0,
        "web_raw_structure": 0.0,
        "raw_file_naming": 0.0,
        "fetch_log_schema": 0.0,
        "fetch_log_coverage": 0.0,
        "success_fetch_limit": 0.0,
        "log_saved_path_consistency": 0.0,
        "contacts_json_schema": 0.0,
        "contacts_orgs_match": 0.0,
        "contacts_emails_normalized": 0.0,
        "contacts_phones_normalized": 0.0,
        "latest_items_structure_and_limit": 0.0,
        "contacts_fetched_urls_from_log": 0.0,
        "rss_feeds_subset_and_fetched": 0.0,
        "summary_csv_schema": 0.0,
        "summary_counts_match_contacts": 0.0,
        "reminders_ics_structure": 0.0,
        "reminders_emails_coverage": 0.0,
        "reminders_summaries_include_email_org": 0.0,
        "reminders_descriptions_include_domain_url": 0.0,
        "reminders_all_day_dtstart": 0.0,
    }

    # Load watchlist
    watchlist_rows = _load_watchlist(workspace)
    if not watchlist_rows:
        # Without watchlist, many checks cannot proceed, but keep zeros and return.
        return scores
    expected = _extract_watchlist_orgs_domains(watchlist_rows)
    expected_domains = [d for (_, d) in expected]
    expected_orgs_by_domain = {d: o for (o, d) in expected}

    # Check script CLI presence and flags
    script_path = workspace / "scripts" / "iot_watchlist.py"
    if script_path.is_file():
        txt = _safe_read_text(script_path) or ""
        # Look for argparse-like flags --watchlist and --out
        has_watchlist = "--watchlist" in txt or "'--watchlist'" in txt or '"--watchlist"' in txt
        has_out = "--out" in txt or "'--out'" in txt or '"--out"' in txt
        if has_watchlist and has_out:
            scores["script_cli_exists"] = 1.0

    # Check raw structure under web_raw/<domain>/
    web_raw_root = workspace / "web_raw"
    domains_with_dir = 0
    domains_with_named_file = 0
    if web_raw_root.is_dir():
        for dom in expected_domains:
            sub = web_raw_root / dom
            if sub.is_dir():
                domains_with_dir += 1
                # Check there exists at least one file with resource hint and timestamp digits
                found_named = False
                if sub.exists():
                    for p in sub.rglob("*"):
                        if p.is_file():
                            name = p.name.lower()
                            # resource hint
                            if any(h in name for h in ["homepage", "feed", "news", "press", "blog", "media", "events"]):
                                # timestamp: sequence of >=8 digits
                                if re.search(r"\d{8,}", name):
                                    found_named = True
                                    break
                if found_named:
                    domains_with_named_file += 1
        if expected_domains:
            scores["web_raw_structure"] = domains_with_dir / len(expected_domains)
            scores["raw_file_naming"] = domains_with_named_file / len(expected_domains)

    # Load fetch log
    log_path = workspace / "output" / "logs" / "fetch_log.jsonl"
    log_rows = _safe_read_jsonl(log_path) if log_path.exists() else None
    if log_rows is not None and len(log_rows) > 0:
        # Validate schema for each row
        required_keys = {"timestamp", "org_name", "domain", "url_attempted", "status_code", "content_type", "bytes_written", "saved_path"}
        schema_ok = True
        saved_path_consistency_count = 0
        for r in log_rows:
            if set(r.keys()).issuperset(required_keys):
                # Basic type checks
                if not isinstance(r.get("timestamp"), str):
                    schema_ok = False
                    break
                if not isinstance(r.get("org_name"), str):
                    schema_ok = False
                    break
                if not isinstance(r.get("domain"), str):
                    schema_ok = False
                    break
                if not isinstance(r.get("url_attempted"), str):
                    schema_ok = False
                    break
                sc = _parse_int(r.get("status_code"))
                if sc is None:
                    schema_ok = False
                    break
                bw = _parse_int(r.get("bytes_written"))
                if bw is None:
                    schema_ok = False
                    break
                # content_type may be None or str
                ct = r.get("content_type", None)
                if ct is not None and not isinstance(ct, str):
                    schema_ok = False
                    break
                # saved_path null or string; if string, file should exist
                sp = r.get("saved_path", None)
                if sp is None:
                    # ensure bytes_written == 0
                    if bw == 0:
                        saved_path_consistency_count += 1
                    else:
                        # inconsistent bytes_written
                        pass
                elif isinstance(sp, str):
                    # Check existence
                    p = (workspace / sp) if not sp.startswith("/") else Path(sp)
                    # If absolute path given, ensure exists; else relative to workspace
                    exists = p.exists()
                    if exists and bw and bw > 0:
                        saved_path_consistency_count += 1
                    else:
                        # allow slight variations: if file missing, mark inconsistent
                        pass
                else:
                    schema_ok = False
                    break
            else:
                schema_ok = False
                break
        if schema_ok:
            scores["fetch_log_schema"] = 1.0

        # Coverage per domain
        log_by_dom = _group_log_by_domain(log_rows)
        covered = sum(1 for d in expected_domains if d in log_by_dom and len(log_by_dom[d]) > 0)
        if expected_domains:
            scores["fetch_log_coverage"] = covered / len(expected_domains)
        # Success fetch <= 3 per org
        ok_limits = 0
        for d in expected_domains:
            entries = log_by_dom.get(d, [])
            success = [e for e in entries if _parse_int(e.get("status_code")) == 200]
            if len(success) <= 3:
                ok_limits += 1
        if expected_domains:
            scores["success_fetch_limit"] = ok_limits / len(expected_domains)
        # Saved path consistency score out of total rows (only rows that met consistency condition counted)
        # We'll compute as consistency across all rows
        if len(log_rows) > 0:
            scores["log_saved_path_consistency"] = saved_path_consistency_count / len(log_rows)
    else:
        # No log: keep zeros
        pass

    # Contacts JSON
    contacts_path = workspace / "output" / "extracted" / "contacts.json"
    contacts = _safe_read_json(contacts_path) if contacts_path.exists() else None
    contacts_schema_ok = False
    contacts_map: Dict[str, Dict[str, Any]] = {}
    if contacts is not None:
        schema_ok, mapping = _validate_contacts_schema(contacts, expected)
        contacts_schema_ok = schema_ok
        contacts_map = mapping
        scores["contacts_json_schema"] = 1.0 if schema_ok else 0.0

        # Orgs match: ensure each expected domain present with matching org_name
        matched = 0
        for d in expected_domains:
            item = contacts_map.get(d)
            if item and item.get("org_name") == expected_orgs_by_domain.get(d):
                matched += 1
        if expected_domains:
            scores["contacts_orgs_match"] = matched / len(expected_domains)

        # Emails normalized (lowercased, deduped)
        emails_norm_ok = 0
        for d in expected_domains:
            item = contacts_map.get(d)
            if not item:
                continue
            emails = item.get("emails", [])
            if isinstance(emails, list):
                # all lowercase and unique
                unique = len(set(emails)) == len(emails)
                all_lower = all((isinstance(e, str) and e == e.lower()) for e in emails)
                # if there are emails ensure they look like emails
                format_ok = all(_is_email(e) for e in emails)
                if unique and all_lower and format_ok:
                    emails_norm_ok += 1
                elif len(emails) == 0:
                    # empty acceptable
                    emails_norm_ok += 1
        if expected_domains:
            scores["contacts_emails_normalized"] = emails_norm_ok / len(expected_domains)

        # Phones normalized (digits and optional leading +)
        phones_norm_ok = 0
        for d in expected_domains:
            item = contacts_map.get(d)
            if not item:
                continue
            phones = item.get("phones", [])
            if isinstance(phones, list):
                if len(phones) == 0:
                    phones_norm_ok += 1
                else:
                    if all(isinstance(p, str) and _is_normalized_phone(p) for p in phones):
                        phones_norm_ok += 1
        if expected_domains:
            scores["contacts_phones_normalized"] = phones_norm_ok / len(expected_domains)

        # latest_items structure and limit (up to 5)
        latest_ok = 0
        for d in expected_domains:
            item = contacts_map.get(d)
            if not item:
                continue
            latest = item.get("latest_items", [])
            if isinstance(latest, list) and len(latest) <= 5:
                good = True
                for li in latest:
                    if not isinstance(li, dict):
                        good = False
                        break
                    if set(li.keys()) != {"title", "link", "source"}:
                        good = False
                        break
                    if not isinstance(li["title"], str) or not isinstance(li["link"], str):
                        good = False
                        break
                    if li["source"] not in {"feed", "page"}:
                        good = False
                        break
                if good:
                    latest_ok += 1
        if expected_domains:
            scores["latest_items_structure_and_limit"] = latest_ok / len(expected_domains)

        # Compare fetched_urls with log success URLs (200)
        log_ok = 0
        if log_rows is not None:
            log_by_dom = _group_log_by_domain(log_rows)
            for d in expected_domains:
                item = contacts_map.get(d)
                if not item:
                    continue
                fetched_urls = item.get("fetched_urls", [])
                if not isinstance(fetched_urls, list):
                    continue
                # set of 200 urls from log for that domain
                entries = log_by_dom.get(d, [])
                success_urls = [e.get("url_attempted") for e in entries if _parse_int(e.get("status_code")) == 200 and isinstance(e.get("url_attempted"), str)]
                # Compare as sets
                if set(fetched_urls) == set(success_urls):
                    log_ok += 1
        if expected_domains:
            scores["contacts_fetched_urls_from_log"] = log_ok / len(expected_domains)

        # rss_feeds_discovered subset of fetched_urls and same domain
        rss_ok = 0
        for d in expected_domains:
            item = contacts_map.get(d)
            if not item:
                continue
            feeds = item.get("rss_feeds_discovered", [])
            fetched = item.get("fetched_urls", [])
            if not isinstance(feeds, list) or not isinstance(fetched, list):
                continue
            # All feed URLs should be in fetched and belong to same domain suffix (allow subdomains)
            good = True
            for fu in feeds:
                if fu not in fetched:
                    good = False
                    break
                try:
                    # Check domain inclusion by simple contains due to stdlib limitation
                    # Accept if expected domain string appears in URL
                    if _normalize_domain(d) not in fu.lower():
                        good = False
                        break
                except Exception:
                    good = False
                    break
            if good:
                rss_ok += 1
        if expected_domains:
            scores["rss_feeds_subset_and_fetched"] = rss_ok / len(expected_domains)

    # Summary CSV
    summary_path = workspace / "output" / "summary.csv"
    summary_rows = _read_summary_csv(summary_path) if summary_path.exists() else None
    if summary_rows is not None and isinstance(summary_rows, list) and len(summary_rows) >= 0:
        # Validate header columns
        # DictReader provides keys in rows; take first row for key set; if empty, still must enforce columns
        header_cols = ["org_name", "domain", "emails_count", "phones_count", "rss_feeds_count", "latest_items_count"]
        # Check presence by inspecting fieldnames via reading again
        try:
            with summary_path.open("r", encoding="utf-8", newline="") as f:
                first_line = f.readline().strip()
        except Exception:
            first_line = ""
        header_ok = False
        if first_line:
            header_ok = (first_line.replace("\ufeff", "") == ",".join(header_cols))
        # Row count equals number of orgs
        rows_ok = (len(summary_rows) == len(expected_domains))
        # Ensure numeric fields are ints
        nums_ok = True
        for r in summary_rows:
            for k in header_cols:
                if k not in r:
                    nums_ok = False
                    break
            if not nums_ok:
                break
            for k in ["emails_count", "phones_count", "rss_feeds_count", "latest_items_count"]:
                if _parse_int(r.get(k)) is None:
                    nums_ok = False
                    break
            if not nums_ok:
                break
        if header_ok and rows_ok and nums_ok:
            scores["summary_csv_schema"] = 1.0

        # Counts consistency with contacts.json
        if contacts is not None and contacts_map:
            count_ok = 0
            for r in summary_rows:
                d = _normalize_domain(r.get("domain", ""))
                item = contacts_map.get(d)
                if not item:
                    continue
                em_cnt = _parse_int(r.get("emails_count"))
                ph_cnt = _parse_int(r.get("phones_count"))
                rf_cnt = _parse_int(r.get("rss_feeds_count"))
                li_cnt = _parse_int(r.get("latest_items_count"))
                if em_cnt is None or ph_cnt is None or rf_cnt is None or li_cnt is None:
                    continue
                if em_cnt == len(item.get("emails", [])) and ph_cnt == len(item.get("phones", [])) and rf_cnt == len(item.get("rss_feeds_discovered", [])) and li_cnt == len(item.get("latest_items", [])):
                    count_ok += 1
            if expected_domains:
                scores["summary_counts_match_contacts"] = count_ok / len(expected_domains)

    # Reminders ICS
    ics_path = workspace / "output" / "reminders" / "followups.ics"
    if ics_path.exists() and ics_path.is_file():
        ics_text = _safe_read_text(ics_path)
        if ics_text:
            has_vcal = "BEGIN:VCALENDAR" in ics_text and "END:VCALENDAR" in ics_text
            events = _parse_ics_events(ics_text)
            if has_vcal:
                scores["reminders_ics_structure"] = 1.0
            # emails coverage
            unique_emails: List[str] = []
            if contacts_map:
                for d in expected_domains:
                    item = contacts_map.get(d)
                    if item:
                        for e in item.get("emails", []):
                            if e not in unique_emails:
                                unique_emails.append(e)
            n_unique = len(unique_emails)
            n_events = len(events)
            if n_unique == n_events:
                scores["reminders_emails_coverage"] = 1.0
            elif n_unique == 0 and n_events == 0:
                scores["reminders_emails_coverage"] = 1.0
            else:
                scores["reminders_emails_coverage"] = 0.0

            # summaries include email and org
            if events and contacts_map:
                ok_count = 0
                # Build reverse map email -> set(orgs,domains,fetched_urls)
                email_map: Dict[str, Dict[str, Any]] = {}
                for d in expected_domains:
                    item = contacts_map.get(d)
                    if not item:
                        continue
                    org = item.get("org_name", "")
                    fetched = item.get("fetched_urls", [])
                    for e in item.get("emails", []):
                        rec = email_map.get(e, {"orgs": set(), "domains": set(), "fetched_urls": set()})
                        rec["orgs"].add(org)
                        rec["domains"].add(d)
                        for u in fetched:
                            rec["fetched_urls"].add(u)
                        email_map[e] = rec
                for ev in events:
                    summ = ev.get("SUMMARY", "")
                    # Expect pattern "Reach out to <org_name> press/contact: <email>"
                    # We'll extract email in summary by regex
                    email_matches = re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", summ or "")
                    if not email_matches:
                        continue
                    email_in = email_matches[0].lower()
                    # Validate email present in contacts
                    if email_in in email_map:
                        # check that summary begins with expected prefix
                        if summ.startswith("Reach out to ") and " press/contact: " in summ:
                            ok_count += 1
                if len(events) > 0:
                    scores["reminders_summaries_include_email_org"] = ok_count / len(events)

            # descriptions include domain and one fetched URL
            if events and contacts_map:
                ok_desc = 0
                # build domains and fetched url sets for search
                domain_to_urls: Dict[str, set] = {}
                for d in expected_domains:
                    item = contacts_map.get(d)
                    if not item:
                        continue
                    domain_to_urls[d] = set(item.get("fetched_urls", []))
                for ev in events:
                    desc = ev.get("DESCRIPTION", "") or ""
                    # must include any watchlist domain and any fetched URL as substring
                    has_domain = any(d in desc for d in expected_domains)
                    has_url = any(any(url in desc for url in urls) for urls in domain_to_urls.values())
                    if has_domain and has_url:
                        ok_desc += 1
                if len(events) > 0:
                    scores["reminders_descriptions_include_domain_url"] = ok_desc / len(events)

            # all-day dtstart format (YYYYMMDD)
            if events:
                ok_dt = 0
                for ev in events:
                    dt = ev.get("DTSTART", "")
                    if isinstance(dt, str) and re.match(r"^\d{8}$", dt):
                        ok_dt += 1
                scores["reminders_all_day_dtstart"] = ok_dt / len(events) if len(events) > 0 else 1.0
            else:
                # If no events, we can't verify DTSTART format; consider neutral as 1.0
                scores["reminders_all_day_dtstart"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()