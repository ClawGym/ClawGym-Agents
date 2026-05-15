import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_header_and_rows(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
    except Exception:
        return None, None
    if header is None:
        return None, None
    # Now read again as DictReader
    try:
        with path.open("r", encoding="utf-8", newline="") as f2:
            dict_reader = csv.DictReader(f2)
            rows = list(dict_reader)
    except Exception:
        return header, None
    return header, rows


def _iso8601_parseable(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    t = s.strip()
    # Replace Z with +00:00 for fromisoformat, if present
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    # Try several formats
    for fmt in [None, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
        try:
            if fmt is None:
                datetime.fromisoformat(t)
            else:
                datetime.strptime(s, fmt)
            return True
        except Exception:
            continue
    return False


_slug_re_non_alnum = re.compile(r"[^a-z0-9]+", re.IGNORECASE)


def _slugify(topic: str) -> str:
    t = (topic or "").strip().lower()
    t = _slug_re_non_alnum.sub("-", t)
    t = t.strip("-")
    # collapse multiple hyphens
    t = re.sub(r"-{2,}", "-", t)
    return t


def _allowed_domain(url: str) -> Tuple[bool, str]:
    try:
        parsed = urlparse(url if isinstance(url, str) else "")
        host = parsed.netloc.lower()
        # strip possible credentials and port
        if "@" in host:
            host = host.split("@", 1)[-1]
        if ":" in host:
            host = host.split(":", 1)[0]
        allowed = (
            host.endswith(".edu")
            or host.endswith(".gov")
            or host.endswith("ala.org")
            or host.endswith("ifla.org")
            or host == "ala.org"
            or host == "ifla.org"
        )
        return allowed, host
    except Exception:
        return False, ""
    # Note: treat subdomains of ala.org and ifla.org as allowed by endswith check.


def _sha256_file_hex(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


_title_tag_re = re.compile(r"<\s*title[^>]*>(.*?)</\s*title\s*>", flags=re.IGNORECASE | re.DOTALL)


def _extract_title_from_html_bytes(b: bytes) -> str:
    try:
        text = b.decode("utf-8", errors="replace")
    except Exception:
        return ""
    m = _title_tag_re.search(text)
    if not m:
        return ""
    title = m.group(1)
    # Strip tags within title if any
    title = re.sub(r"<[^>]+>", "", title)
    return title.strip()


def _read_plain_text_counts(path: Path) -> Optional[Tuple[int, int]]:
    try:
        t = path.read_text(encoding="utf-8")
    except Exception:
        try:
            t = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None
    chars = len(t)
    words = len(t.split())
    return chars, words


def _safe_int(s: Any) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _sanitize_rows(rows: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
    return rows if isinstance(rows, list) else []


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "search_log_header_valid": 0.0,
        "search_log_rows_for_topics_drop": 0.0,
        "csv_rows_file_id_correct": 0.0,
        "csv_rows_query_and_slug_valid": 0.0,
        "csv_rows_allowed_domains": 0.0,
        "csv_rows_iso_timestamps": 0.0,
        "csv_rows_sha256_format": 0.0,
        "csv_rows_http_status_and_counts_valid": 0.0,
        "raw_files_integrity_for_200s": 0.0,
        "index_json_exists_and_fields": 0.0,
        "index_json_topics_coverage": 0.0,
        "index_json_urls_subset_of_csv": 0.0,
        "index_json_total_sources_match": 0.0,
        "receipt_json_exists_and_consistency": 0.0,
        "watch_processed_file_present": 0.0,
        "errors_log_present": 0.0,
    }

    # Load input topics from input/topics.txt
    input_topics_path = workspace / "input" / "topics.txt"
    input_topics_text = _read_text(input_topics_path)
    input_topics: List[str] = []
    if input_topics_text is not None:
        for line in input_topics_text.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            input_topics.append(s)

    expected_csv_header = [
        "file_id",
        "topic",
        "topic_slug",
        "query",
        "url",
        "domain",
        "http_status",
        "title",
        "chars",
        "words",
        "sha256_html",
        "retrieved_at_iso",
    ]

    search_log_path = workspace / "outputs" / "search_log.csv"
    header, rows = _read_csv_header_and_rows(search_log_path)
    if header is not None and header == expected_csv_header and rows is not None:
        scores["search_log_header_valid"] = 1.0
    else:
        scores["search_log_header_valid"] = 0.0

    rows_list = _sanitize_rows(rows)
    # Filter rows for our file_id
    file_id_expected = "topics_drop.txt"
    rows_for_file = [r for r in rows_list if r.get("file_id", "") == file_id_expected]
    scores["search_log_rows_for_topics_drop"] = 1.0 if len(rows_for_file) > 0 else 0.0

    # csv_rows_file_id_correct (among rows with any file_id reference to our topics)
    if rows_list:
        correct = sum(1 for r in rows_list if r.get("file_id", "") == file_id_expected)
        scores["csv_rows_file_id_correct"] = correct / max(len(rows_list), 1)
    else:
        scores["csv_rows_file_id_correct"] = 0.0

    # Prepare topic slug and query validation
    total_rows = len(rows_for_file)
    if total_rows > 0:
        valid_count = 0
        for r in rows_for_file:
            topic = r.get("topic", "")
            slug = r.get("topic_slug", "")
            query = r.get("query", "")
            # topic should be one of input topics
            topic_ok = topic in input_topics if input_topics else bool(topic)
            # slug matches our slugify(topic)
            slug_ok = slug == _slugify(topic)
            # query matches exact required pattern: "<topic> site:edu OR site:gov OR site:ala.org OR site:ifla.org"
            expected_query = f"{topic} site:edu OR site:gov OR site:ala.org OR site:ifla.org"
            query_ok = query == expected_query
            if topic_ok and slug_ok and query_ok:
                valid_count += 1
        scores["csv_rows_query_and_slug_valid"] = valid_count / total_rows
    else:
        scores["csv_rows_query_and_slug_valid"] = 0.0

    # Allowed domains and domain field consistency
    if total_rows > 0:
        valid_dom = 0
        for r in rows_for_file:
            url = r.get("url", "")
            allowed, host = _allowed_domain(url)
            domain_field = r.get("domain", "").lower()
            if allowed and domain_field == host:
                valid_dom += 1
        scores["csv_rows_allowed_domains"] = valid_dom / total_rows
    else:
        scores["csv_rows_allowed_domains"] = 0.0

    # ISO timestamps validation
    if total_rows > 0:
        iso_ok = 0
        for r in rows_for_file:
            ts = r.get("retrieved_at_iso", "")
            if _iso8601_parseable(ts):
                iso_ok += 1
        scores["csv_rows_iso_timestamps"] = iso_ok / total_rows
    else:
        scores["csv_rows_iso_timestamps"] = 0.0

    # SHA256 format validation
    if total_rows > 0:
        sha_ok = 0
        for r in rows_for_file:
            sha = r.get("sha256_html", "")
            if isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{64}", sha or ""):
                sha_ok += 1
        scores["csv_rows_sha256_format"] = sha_ok / total_rows
    else:
        scores["csv_rows_sha256_format"] = 0.0

    # HTTP status and counts; for non-200 expect zero counts; for 200 non-negative ints
    if total_rows > 0:
        status_ok = 0
        for r in rows_for_file:
            status_val = _safe_int(r.get("http_status"))
            chars_val = _safe_int(r.get("chars"))
            words_val = _safe_int(r.get("words"))
            if status_val is None or chars_val is None or words_val is None:
                continue
            if not (100 <= status_val <= 599):
                continue
            if status_val == 200:
                if chars_val >= 0 and words_val >= 0:
                    status_ok += 1
            else:
                if chars_val == 0 and words_val == 0:
                    status_ok += 1
        scores["csv_rows_http_status_and_counts_valid"] = status_ok / total_rows
    else:
        scores["csv_rows_http_status_and_counts_valid"] = 0.0

    # Raw files integrity for 200s: match sha256 to an html file under outputs/raw/<topic_slug>/ and check txt counts and title
    if total_rows > 0:
        ok_matches = 0
        considered = 0
        for r in rows_for_file:
            status_val = _safe_int(r.get("http_status"))
            if status_val != 200:
                continue
            considered += 1
            topic_slug = r.get("topic_slug", "")
            sha = (r.get("sha256_html") or "").lower()
            title_csv = (r.get("title") or "").strip()
            txt_chars_csv = _safe_int(r.get("chars"))
            txt_words_csv = _safe_int(r.get("words"))
            raw_dir = workspace / "outputs" / "raw" / topic_slug
            if not raw_dir.exists() or not raw_dir.is_dir():
                continue
            # Map sha->(html_path, txt_path)
            found_match = False
            for html_path in raw_dir.glob("*_raw.html"):
                sha_file = _sha256_file_hex(html_path)
                if sha_file is None:
                    continue
                if sha_file.lower() == sha:
                    # Extract n from filename
                    n_match = re.match(r"(\d+)_raw\.html$", html_path.name)
                    if not n_match:
                        # try any prefix before _raw.html
                        n_part = html_path.name.split("_raw.html")[0]
                        if not n_part.isdigit():
                            # unable to derive n; continue but fail strict pairing check
                            txt_path = None
                        else:
                            txt_path = raw_dir / f"{n_part}.txt"
                    else:
                        n = n_match.group(1)
                        txt_path = raw_dir / f"{n}.txt"
                    # Check txt counts
                    counts_ok = False
                    if txt_path and txt_path.exists():
                        counts = _read_plain_text_counts(txt_path)
                        if counts is not None and txt_chars_csv is not None and txt_words_csv is not None:
                            counts_ok = (counts[0] == txt_chars_csv and counts[1] == txt_words_csv)
                    # Check title from html
                    try:
                        b = html_path.read_bytes()
                    except Exception:
                        b = b""
                    title_extracted = _extract_title_from_html_bytes(b)
                    title_ok = (title_extracted == title_csv)
                    if counts_ok and title_ok:
                        found_match = True
                        break
            if found_match:
                ok_matches += 1
        if considered > 0:
            scores["raw_files_integrity_for_200s"] = ok_matches / considered
        else:
            # If there were no 200 rows, consider this check neutral but to keep strictness return 0.0
            scores["raw_files_integrity_for_200s"] = 0.0
    else:
        scores["raw_files_integrity_for_200s"] = 0.0

    # Index JSON checks
    index_json_path = workspace / "outputs" / "index.json"
    index_data = _load_json(index_json_path)
    index_valid_structure = False
    if isinstance(index_data, list):
        structure_ok = True
        for item in index_data:
            if not isinstance(item, dict):
                structure_ok = False
                break
            if not all(k in item for k in ["topic", "topic_slug", "total_sources", "urls"]):
                structure_ok = False
                break
            if not isinstance(item.get("topic"), str):
                structure_ok = False
                break
            if not isinstance(item.get("topic_slug"), str):
                structure_ok = False
                break
            if not isinstance(item.get("total_sources"), int):
                structure_ok = False
                break
            if not isinstance(item.get("urls"), list) or not all(isinstance(u, str) for u in item.get("urls", [])):
                structure_ok = False
                break
        index_valid_structure = structure_ok
    scores["index_json_exists_and_fields"] = 1.0 if index_valid_structure else 0.0

    # Index topics coverage (must include all input topics)
    if index_valid_structure and input_topics:
        slug_to_item = {item["topic_slug"]: item for item in index_data}  # type: ignore
        coverage = 0
        for t in input_topics:
            slug = _slugify(t)
            item = slug_to_item.get(slug)
            if item and item.get("topic") == t and item.get("topic_slug") == slug:
                coverage += 1
        scores["index_json_topics_coverage"] = coverage / max(len(input_topics), 1)
    else:
        scores["index_json_topics_coverage"] = 0.0

    # Index urls subset of CSV and total_sources match len(urls)
    if index_valid_structure:
        # Build mapping from topic_slug to set of urls in CSV rows for our file
        csv_urls_by_slug: Dict[str, set] = {}
        for r in rows_for_file:
            slug = r.get("topic_slug", "")
            url = r.get("url", "")
            if slug:
                csv_urls_by_slug.setdefault(slug, set()).add(url)
        # Subset check
        total_urls = 0
        subset_ok = 0
        total_sources_entries = 0
        total_sources_ok = 0
        for item in index_data:  # type: ignore
            slug = item.get("topic_slug", "")
            urls = item.get("urls", [])
            total_sources_entries += 1
            if isinstance(urls, list):
                total_urls += len(urls)
                for u in urls:
                    if slug and u in csv_urls_by_slug.get(slug, set()):
                        subset_ok += 1
            # total_sources matches
            if isinstance(item.get("total_sources"), int) and isinstance(urls, list) and item.get("total_sources") == len(urls):
                total_sources_ok += 1
        # If there are zero urls overall, consider subset check satisfied (no contradictions)
        if total_urls == 0 and index_data is not None:
            scores["index_json_urls_subset_of_csv"] = 1.0
        else:
            scores["index_json_urls_subset_of_csv"] = (subset_ok / total_urls) if total_urls > 0 else 0.0
        scores["index_json_total_sources_match"] = (total_sources_ok / total_sources_entries) if total_sources_entries > 0 else 0.0
    else:
        scores["index_json_urls_subset_of_csv"] = 0.0
        scores["index_json_total_sources_match"] = 0.0

    # Receipt JSON checks
    receipt_path = workspace / "outputs" / "processed" / "topics_drop.txt.json"
    receipt = _load_json(receipt_path)
    if isinstance(receipt, dict):
        filename_ok = receipt.get("filename") == "topics_drop.txt"
        processed_topics_ok = isinstance(receipt.get("processed_topics"), int) and (
            (len(input_topics) == receipt.get("processed_topics")) if input_topics else receipt.get("processed_topics") is not None
        )
        # total_sources equals number of CSV rows for this file_id
        total_sources_expected = len(rows_for_file)
        total_sources_ok = isinstance(receipt.get("total_sources"), int) and receipt.get("total_sources") == total_sources_expected
        ts_ok = _iso8601_parseable(str(receipt.get("processed_at_iso", "")))
        if filename_ok and processed_topics_ok and total_sources_ok and ts_ok:
            scores["receipt_json_exists_and_consistency"] = 1.0
        else:
            scores["receipt_json_exists_and_consistency"] = 0.0
    else:
        scores["receipt_json_exists_and_consistency"] = 0.0

    # Watch processed file presence
    watch_processed = workspace / "watch" / "processed" / "topics_drop.txt"
    scores["watch_processed_file_present"] = 1.0 if watch_processed.exists() and watch_processed.is_file() else 0.0

    # Errors log present
    errors_log_path = workspace / "outputs" / "errors.log"
    scores["errors_log_present"] = 1.0 if errors_log_path.exists() and errors_log_path.is_file() else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()