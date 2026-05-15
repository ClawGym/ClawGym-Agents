import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _parse_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        s2 = s.replace("Z", "+00:00")
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _load_csv_with_header(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data_rows = []
        for r in rows[1:]:
            if len(r) != len(header):
                return None, None
            data_rows.append({header[i]: r[i] for i in range(len(header))})
        return header, data_rows
    except Exception:
        return None, None


def _parse_wishlist_md(md_text: str) -> List[Tuple[str, str, str]]:
    entries = []
    if not isinstance(md_text, str):
        return entries
    lines = md_text.splitlines()
    pattern = re.compile(
        r'^\s*-\s+(?P<title>.+?)\s+—\s+(?P<author>[^()]+?)(?:\s+\(ISBN:\s*(?P<isbn>\d+)\s*\))?\s*$'
    )
    for line in lines:
        m = pattern.match(line)
        if m:
            title = m.group("title").strip()
            author = m.group("author").strip()
            isbn = (m.group("isbn") or "").strip()
            entries.append((title, author, isbn))
    norm_seen = set()
    unique_entries = []
    for t, a, i in entries:
        key = (t.strip().lower(), a.strip().lower(), i.strip())
        if key not in norm_seen:
            norm_seen.add(key)
            unique_entries.append((t, a, i))
    return unique_entries


def _domain_for_source(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        return parsed.hostname
    except Exception:
        return None


def _is_blank(s: Optional[str]) -> bool:
    return (s or "").strip() == ""


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "csv_header_and_path_valid": 0.0,
        "csv_rows_match_wishlist": 0.0,
        "no_duplicate_entries_in_csv": 0.0,
        "per_book_json_records_complete": 0.0,
        "found_items_html_and_hash_valid": 0.0,
        "domain_and_source_consistency": 0.0,
        "not_found_items_blank_fields": 0.0,
        "description_and_subjects_format": 0.0,
        "trigger_log_present_and_consistent": 0.0,
    }

    wishlist_path = workspace / "input" / "wishlist_2024-Notes.md"
    wishlist_text = _read_text_safe(wishlist_path)
    if wishlist_text is None:
        return scores
    expected_entries = _parse_wishlist_md(wishlist_text)
    expected_set = {(t, a, i) for (t, a, i) in expected_entries}
    expected_count = len(expected_entries)

    csv_path = workspace / "output" / "metadata" / "books.csv"
    header, rows = _load_csv_with_header(csv_path)

    required_header = [
        "input_title",
        "input_author",
        "input_isbn",
        "found",
        "source",
        "source_url",
        "resolved_title",
        "resolved_authors",
        "first_publish_year",
        "subjects",
        "description_excerpt",
        "html_sha256",
    ]

    if header == required_header and rows is not None:
        scores["csv_header_and_path_valid"] = 1.0
    else:
        return scores

    try:
        csv_set = {(r["input_title"].strip(), r["input_author"].strip(), r["input_isbn"].strip()) for r in rows}
        if csv_set == expected_set and len(rows) == expected_count:
            scores["csv_rows_match_wishlist"] = 1.0
    except Exception:
        pass

    try:
        seen = set()
        dup = False
        for r in rows:
            key = (r["input_title"].strip().lower(), r["input_author"].strip().lower(), r["input_isbn"].strip())
            if key in seen:
                dup = True
                break
            seen.add(key)
        if not dup:
            scores["no_duplicate_entries_in_csv"] = 1.0
    except Exception:
        pass

    json_dir = workspace / "output" / "metadata" / "books"
    json_files = []
    try:
        if json_dir.exists():
            json_files = sorted([p for p in json_dir.glob("*.json") if p.is_file()])
    except Exception:
        json_files = []
    json_map: Dict[Tuple[str, str, str], dict] = {}
    json_ok = True
    for p in json_files:
        data = _load_json_safe(p)
        if not isinstance(data, dict):
            json_ok = False
            break
        t = (str(data.get("input_title", "")).strip(),
             str(data.get("input_author", "")).strip(),
             str(data.get("input_isbn", "")).strip())
        if any(x == "" for x in t[:2]):
            json_ok = False
            break
        json_map.setdefault(t, data)
    per_book_json_complete = True
    for r in rows:
        key = (r["input_title"].strip(), r["input_author"].strip(), r["input_isbn"].strip())
        jd = json_map.get(key)
        if jd is None:
            per_book_json_complete = False
            break
        if "found" not in jd or not isinstance(jd["found"], bool):
            per_book_json_complete = False
            break
        if "search_query_used" not in jd or _is_blank(jd.get("search_query_used")):
            per_book_json_complete = False
            break
        if "retrieved_at" not in jd or not _parse_iso8601(str(jd.get("retrieved_at"))):
            per_book_json_complete = False
            break
        for k in ["resolved_title", "resolved_authors", "first_publish_year", "subjects", "description_excerpt"]:
            if k not in jd:
                per_book_json_complete = False
                break
        if not per_book_json_complete:
            break
    if json_ok and per_book_json_complete and len(json_map) >= len(rows):
        scores["per_book_json_records_complete"] = 1.0

    found_items_ok = True
    domain_source_ok = True
    not_found_fields_ok = True
    desc_subjects_ok = True

    for r in rows:
        key = (r["input_title"].strip(), r["input_author"].strip(), r["input_isbn"].strip())
        jd = json_map.get(key)
        if jd is None:
            found_items_ok = False
            domain_source_ok = False
            not_found_fields_ok = False
            desc_subjects_ok = False
            break

        csv_found_raw = r["found"]
        if csv_found_raw not in ("true", "false"):
            domain_source_ok = False
        csv_found = (csv_found_raw == "true")
        json_found = bool(jd.get("found", False))

        if csv_found != json_found:
            found_items_ok = False
            domain_source_ok = False

        source_csv = r.get("source", "")
        source_json = str(jd.get("source", "")) if jd.get("source") is not None else ""
        source_url_csv = r.get("source_url", "")
        source_url_json = str(jd.get("source_url", "")) if jd.get("source_url") is not None else ""

        if csv_found:
            dl_path = jd.get("downloaded_html_path")
            if not isinstance(dl_path, str) or _is_blank(dl_path):
                found_items_ok = False
            else:
                html_path = (workspace / dl_path).resolve()
                try:
                    html_rel = html_path.relative_to(workspace)
                except Exception:
                    found_items_ok = False
                    html_rel = None
                if html_rel is None or not str(html_rel).startswith("output/webpages/") or not str(html_rel).endswith(".html"):
                    found_items_ok = False
                if not html_path.exists():
                    found_items_ok = False
                else:
                    actual_hash = _compute_sha256(html_path)
                    if not actual_hash:
                        found_items_ok = False
                    else:
                        if r.get("html_sha256", "") != actual_hash or str(jd.get("html_sha256", "")) != actual_hash:
                            found_items_ok = False

            if source_csv not in ("openlibrary", "loc") or source_json not in ("openlibrary", "loc"):
                domain_source_ok = False
            if _is_blank(source_url_csv) or _is_blank(source_url_json):
                domain_source_ok = False
            else:
                domain_csv = _domain_for_source(source_url_csv)
                domain_json = _domain_for_source(source_url_json)
                if domain_csv is None or domain_json is None:
                    domain_source_ok = False
                else:
                    if source_csv == "openlibrary" and not domain_csv.endswith("openlibrary.org"):
                        domain_source_ok = False
                    if source_csv == "loc" and not domain_csv.endswith("loc.gov"):
                        domain_source_ok = False
                    if source_json == "openlibrary" and not domain_json.endswith("openlibrary.org"):
                        domain_source_ok = False
                    if source_json == "loc" and not domain_json.endswith("loc.gov"):
                        domain_source_ok = False
                if source_csv != source_json or source_url_csv != source_url_json:
                    domain_source_ok = False

            desc_csv = r.get("description_excerpt", "")
            if "\n" in desc_csv or "\r" in desc_csv or len(desc_csv) > 320:
                desc_subjects_ok = False

            subjects_csv = r.get("subjects", "")
            if not _is_blank(subjects_csv):
                parts = [p for p in subjects_csv.split(";") if p != ""]
                if len(parts) > 5:
                    desc_subjects_ok = False

        else:
            if not _is_blank(r.get("resolved_title", "")):
                not_found_fields_ok = False
            if not _is_blank(r.get("resolved_authors", "")):
                not_found_fields_ok = False
            if not _is_blank(r.get("first_publish_year", "")):
                not_found_fields_ok = False
            if not _is_blank(r.get("subjects", "")):
                not_found_fields_ok = False
            if not _is_blank(r.get("description_excerpt", "")):
                not_found_fields_ok = False
            if not _is_blank(r.get("html_sha256", "")):
                not_found_fields_ok = False
            if not _is_blank(source_csv) or not _is_blank(source_url_csv):
                not_found_fields_ok = False
            if not _is_blank(str(jd.get("downloaded_html_path", "") or "")):
                not_found_fields_ok = False
            if not _is_blank(str(jd.get("html_sha256", "") or "")):
                not_found_fields_ok = False
            if not _is_blank(str(jd.get("source", "") or "")) or not _is_blank(str(jd.get("source_url", "") or "")):
                not_found_fields_ok = False

    if found_items_ok:
        scores["found_items_html_and_hash_valid"] = 1.0
    if domain_source_ok:
        scores["domain_and_source_consistency"] = 1.0
    if not_found_fields_ok:
        scores["not_found_items_blank_fields"] = 1.0
    if desc_subjects_ok:
        scores["description_and_subjects_format"] = 1.0

    logs_dir = workspace / "output" / "logs"
    log_files = []
    try:
        if logs_dir.exists():
            log_files = sorted([p for p in logs_dir.glob("trigger_*.json") if p.is_file()])
    except Exception:
        log_files = []
    log_ok = False
    if log_files:
        latest_log = log_files[-1]
        log_data = _load_json_safe(latest_log)
        if isinstance(log_data, dict):
            triggered_by = str(log_data.get("triggered_by", ""))
            timestamp = log_data.get("timestamp")
            total_books_detected = log_data.get("total_books_detected")
            found_count = log_data.get("found_count")
            statuses = log_data.get("statuses")
            try:
                tb_ok = isinstance(triggered_by, str) and triggered_by.endswith(str(Path("input") / "wishlist_2024-Notes.md"))
                ts_ok = isinstance(timestamp, str) and len(timestamp) > 0
                tbd_ok = isinstance(total_books_detected, int) and total_books_detected == expected_count
                fc_ok = isinstance(found_count, int)
                st_ok = isinstance(statuses, list) and all(isinstance(x, dict) and "slug" in x and "found" in x and isinstance(x["found"], bool) for x in statuses)
                csv_found_count = sum(1 for r in rows if r.get("found") == "true")
                fc_match = fc_ok and found_count == csv_found_count
                len_match = isinstance(statuses, list) and len(statuses) == expected_count
                if tb_ok and ts_ok and tbd_ok and fc_match and st_ok and len_match:
                    log_ok = True
            except Exception:
                log_ok = False
    if log_ok:
        scores["trigger_log_present_and_consistent"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()