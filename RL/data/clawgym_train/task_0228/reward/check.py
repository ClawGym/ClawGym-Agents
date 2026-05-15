import csv
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse


EXPECTED_METADATA_COLUMNS = [
    "query_id",
    "url",
    "source_domain",
    "saved_path",
    "http_status",
    "title",
    "h1",
    "published_date_iso",
    "matched_keywords",
    "content_length",
]


def _safe_load_json(path: Path) -> Tuple[Optional[object], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return None, f"read_error:{e}"
    try:
        return json.loads(text), None
    except Exception as e:
        return None, f"json_parse_error:{e}"


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore"), None
    except Exception as e:
        return None, f"read_error:{e}"


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = list(reader)
            return rows, header, None
    except Exception as e:
        return None, None, f"csv_read_error:{e}"


def _hostname_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.split("@")[-1]
        host = host.split(":")[0]
        return host.lower()
    except Exception:
        return None


class TitleH1Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.in_h1 = False
        self.title_parts: List[str] = []
        self.h1_parts: List[str] = []
        self.h1_captured = False

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "title":
            self.in_title = True
        elif tag.lower() == "h1" and not self.h1_captured:
            self.in_h1 = True

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title = False
        elif tag.lower() == "h1":
            if self.in_h1:
                self.h1_captured = True
            self.in_h1 = False

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
        if self.in_h1:
            self.h1_parts.append(data)

    def get_title(self) -> str:
        return _normalize_ws("".join(self.title_parts))

    def get_h1(self) -> str:
        return _normalize_ws("".join(self.h1_parts))


class VisibleTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_ignored = 0
        self.text_parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("script", "style", "noscript"):
            self.in_ignored += 1

    def handle_endtag(self, tag):
        if tag.lower() in ("script", "style", "noscript"):
            if self.in_ignored > 0:
                self.in_ignored -= 1

    def handle_data(self, data):
        if self.in_ignored == 0:
            self.text_parts.append(data)

    def get_text(self) -> str:
        return _normalize_ws(" ".join(self.text_parts))


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _is_iso8601_like(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    pattern = r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?(Z|[+-]\d{2}:\d{2})?)?$"
    return re.match(pattern, s) is not None


def _is_http_status_valid(val: str) -> bool:
    s = str(val).strip()
    if not s:
        return False
    try:
        num = int(s)
        return 100 <= num <= 599
    except Exception:
        return True


def _list_saved_html_files(workspace: Path, query_ids: Optional[Set[str]] = None) -> Set[str]:
    base = workspace / "output" / "pages"
    saved: Set[str] = set()
    if not base.exists():
        return saved
    if query_ids is None:
        subdirs = [p for p in base.iterdir() if p.is_dir()]
    else:
        subdirs = [base / q for q in query_ids if (base / q).is_dir()]
    for sub in subdirs:
        for f in sub.iterdir():
            if f.is_file() and f.suffix.lower() == ".html":
                rel = f.relative_to(workspace).as_posix()
                saved.add(rel)
    return saved


def _sequential_numbering_ok(workspace: Path, query_ids: Optional[Set[str]] = None) -> Tuple[int, int]:
    base = workspace / "output" / "pages"
    if not base.exists():
        return 0, 0
    total_dirs = 0
    ok_dirs = 0
    if query_ids is None:
        dirs = [p for p in base.iterdir() if p.is_dir()]
    else:
        dirs = [base / q for q in query_ids if (base / q).is_dir()]
    for sub in dirs:
        nums: List[Optional[int]] = []
        for f in sub.iterdir():
            if f.is_file() and f.suffix.lower() == ".html":
                m = re.match(r"^(\d+)\.html$", f.name)
                if m:
                    nums.append(int(m.group(1)))
                else:
                    nums.append(None)
        if not nums:
            continue
        total_dirs += 1
        if None in nums:
            continue
        nums_sorted = sorted(nums)
        if nums_sorted[0] == 1 and nums_sorted == list(range(1, len(nums_sorted) + 1)):
            ok_dirs += 1
    return ok_dirs, total_dirs


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present": 0.0,
        "metadata_csv_exists_and_header": 0.0,
        "manifest_exists_and_schema": 0.0,
        "pages_saved_present": 0.0,
        "saved_paths_exist_and_format": 0.0,
        "content_length_matches_file": 0.0,
        "source_domain_matches_url": 0.0,
        "allowed_domain_filtering": 0.0,
        "max_results_respected": 0.0,
        "title_matches_html": 0.0,
        "h1_matches_html": 0.0,
        "matched_keywords_valid": 0.0,
        "published_date_iso_format": 0.0,
        "http_status_valid": 0.0,
        "manifest_covers_saved_pages": 0.0,
        "manifest_matches_metadata": 0.0,
        "sequential_numbering_per_query": 0.0,
        "duplicate_urls_avoided": 0.0,
    }

    # Script presence
    script_path = workspace / "tools" / "build_media_briefing.py"
    if script_path.exists() and script_path.is_file():
        try:
            if script_path.stat().st_size > 0:
                scores["script_present"] = 1.0
        except Exception:
            pass

    # Load inputs
    queries_json_path = workspace / "input" / "queries.json"
    keywords_json_path = workspace / "input" / "keywords.json"
    queries_data, _ = _safe_load_json(queries_json_path)
    keywords_data, _ = _safe_load_json(keywords_json_path)

    allowed_domains_map: Dict[str, Set[str]] = {}
    max_results_map: Dict[str, int] = {}
    query_ids_from_input: Set[str] = set()

    if isinstance(queries_data, dict) and isinstance(queries_data.get("queries"), list):
        for q in queries_data["queries"]:
            try:
                qid = str(q.get("query_id"))
                allowed = set(str(d).lower() for d in (q.get("allowed_domains") or []))
                max_res = int(q.get("max_results"))
                if qid and allowed and max_res >= 0:
                    allowed_domains_map[qid] = allowed
                    max_results_map[qid] = max_res
                    query_ids_from_input.add(qid)
            except Exception:
                continue

    keywords_set_casefold: Optional[Set[str]] = None
    if isinstance(keywords_data, dict):
        kws: List[str] = []
        for k in ("keywords_en", "keywords_fr"):
            arr = keywords_data.get(k)
            if isinstance(arr, list):
                kws.extend([str(x) for x in arr])
        if kws:
            keywords_set_casefold = set(x.casefold() for x in kws)

    # Load metadata CSV
    metadata_path = workspace / "output" / "pages_metadata.csv"
    metadata_rows: List[Dict[str, str]] = []
    metadata_header: Optional[List[str]] = None
    rows, header, _ = _safe_read_csv_dicts(metadata_path)
    if rows is not None and header is not None:
        metadata_rows = rows
        metadata_header = header
        if header == EXPECTED_METADATA_COLUMNS:
            scores["metadata_csv_exists_and_header"] = 1.0

    # Load manifest JSON
    manifest_path = workspace / "output" / "pages_manifest.json"
    manifest_data, _ = _safe_load_json(manifest_path)
    manifest_entries: List[dict] = []
    manifest_schema_ok = False
    if isinstance(manifest_data, list):
        manifest_entries = [x for x in manifest_data if isinstance(x, dict)]
        valid_count = 0
        for entry in manifest_entries:
            if not all(k in entry for k in ("query_id", "url", "saved_path", "http_status")):
                continue
            if not isinstance(entry.get("query_id"), str):
                continue
            if not isinstance(entry.get("url"), str):
                continue
            if not isinstance(entry.get("saved_path"), str):
                continue
            hs = entry.get("http_status")
            if not (isinstance(hs, int) or isinstance(hs, str)):
                continue
            valid_count += 1
        manifest_schema_ok = (valid_count == len(manifest_entries))
    scores["manifest_exists_and_schema"] = 1.0 if (manifest_path.exists() and manifest_schema_ok) else 0.0

    # Pages saved present
    saved_files_set = _list_saved_html_files(workspace, query_ids_from_input if query_ids_from_input else None)
    scores["pages_saved_present"] = 1.0 if len(saved_files_set) > 0 else 0.0

    total_rows = len(metadata_rows)

    if total_rows > 0:
        saved_ok = 0
        size_ok = 0
        domain_ok = 0
        title_ok = 0
        h1_ok = 0
        http_ok = 0
        keywords_ok = 0
        published_ok = 0
        allowed_domain_ok = 0
        urls_seen: Set[str] = set()

        for row in metadata_rows:
            query_id = (row.get("query_id") or "").strip()
            url = (row.get("url") or "").strip()
            source_domain = (row.get("source_domain") or "").strip().lower()
            saved_path_rel = (row.get("saved_path") or "").strip()
            http_status = (row.get("http_status") or "")
            title_val = _normalize_ws(row.get("title") or "")
            h1_val = _normalize_ws(row.get("h1") or "")
            published_date_iso = (row.get("published_date_iso") or "").strip()
            matched_keywords = (row.get("matched_keywords") or "")
            content_length = (row.get("content_length") or "").strip()

            # saved path existence and format
            fpath = workspace / saved_path_rel
            m = re.match(rf"^output/pages/{re.escape(query_id)}/(\d+)\.html$", saved_path_rel)
            if m and fpath.exists() and fpath.is_file():
                saved_ok += 1

            # content length check
            try:
                expected_len = int(content_length)
                actual_len = fpath.stat().st_size if fpath.exists() else -1
                if expected_len == actual_len and actual_len >= 0:
                    size_ok += 1
            except Exception:
                pass

            # source_domain vs url
            host = _hostname_from_url(url) or ""
            if host and host == source_domain:
                domain_ok += 1

            # allowed domains
            if query_id in allowed_domains_map and host:
                allowed_domains = allowed_domains_map[query_id]
                for dom in allowed_domains:
                    if host == dom or host.endswith("." + dom):
                        allowed_domain_ok += 1
                        break

            # http status validity
            if _is_http_status_valid(str(http_status)):
                http_ok += 1

            # Parse HTML for title/h1 and keywords
            if fpath.exists():
                html_text, _ = _safe_read_text(fpath)
                if html_text is not None:
                    p = TitleH1Parser()
                    try:
                        p.feed(html_text)
                    except Exception:
                        pass
                    parsed_title = p.get_title()
                    parsed_h1 = p.get_h1()
                    if parsed_title == title_val:
                        title_ok += 1
                    if (parsed_h1 or "") == h1_val:
                        h1_ok += 1

                    if keywords_set_casefold is not None:
                        tokens = [t.strip() for t in matched_keywords.split(";") if t.strip()]
                        ve = VisibleTextExtractor()
                        try:
                            ve.feed(html_text)
                        except Exception:
                            pass
                        visible = ve.get_text().casefold()
                        all_valid = True
                        for t in tokens:
                            if t.casefold() not in keywords_set_casefold:
                                all_valid = False
                                break
                            if t.casefold() not in visible:
                                all_valid = False
                                break
                        if all_valid:
                            keywords_ok += 1

            # published date iso-like or blank
            if published_date_iso == "" or _is_iso8601_like(published_date_iso):
                published_ok += 1

            # track duplicate URL uniqueness
            urls_seen.add(url.strip())

        scores["saved_paths_exist_and_format"] = saved_ok / total_rows
        scores["content_length_matches_file"] = size_ok / total_rows
        scores["source_domain_matches_url"] = domain_ok / total_rows
        if allowed_domains_map:
            scores["allowed_domain_filtering"] = allowed_domain_ok / total_rows
        else:
            scores["allowed_domain_filtering"] = 0.0
        scores["title_matches_html"] = title_ok / total_rows
        scores["h1_matches_html"] = h1_ok / total_rows
        if keywords_set_casefold is not None:
            scores["matched_keywords_valid"] = keywords_ok / total_rows
        else:
            scores["matched_keywords_valid"] = 0.0
        scores["published_date_iso_format"] = published_ok / total_rows
        scores["http_status_valid"] = http_ok / total_rows
        unique_count = len(urls_seen)
        scores["duplicate_urls_avoided"] = (unique_count / total_rows) if total_rows > 0 else 0.0

    # max_results respected: only evaluate if there is at least one metadata row for at least one query
    if max_results_map and metadata_rows:
        compliant = 0
        considered = 0
        for qid, max_res in max_results_map.items():
            count = sum(1 for r in metadata_rows if (r.get("query_id") or "").strip() == qid)
            if count > 0:
                considered += 1
                if count <= max_res:
                    compliant += 1
        if considered > 0:
            scores["max_results_respected"] = compliant / considered
        else:
            scores["max_results_respected"] = 0.0
    else:
        scores["max_results_respected"] = 0.0

    # Manifest coverage of saved pages
    manifest_paths = set()
    for e in manifest_entries:
        sp = e.get("saved_path")
        if isinstance(sp, str) and sp:
            manifest_paths.add(sp)

    target_saved_files = _list_saved_html_files(workspace, query_ids_from_input if query_ids_from_input else None)
    if len(target_saved_files) > 0:
        covered = len([p for p in target_saved_files if p in manifest_paths])
        scores["manifest_covers_saved_pages"] = covered / len(target_saved_files)
    else:
        # No saved pages to cover; do not award credit by default
        scores["manifest_covers_saved_pages"] = 0.0

    # Manifest and metadata consistency: saved_path sets equal
    metadata_saved_paths = set()
    for r in metadata_rows:
        sp = (r.get("saved_path") or "").strip()
        if sp:
            metadata_saved_paths.add(sp)
    if manifest_path.exists() and metadata_path.exists():
        scores["manifest_matches_metadata"] = 1.0 if manifest_paths == metadata_saved_paths else 0.0
    else:
        scores["manifest_matches_metadata"] = 0.0

    # Sequential numbering per query
    ok_dirs, total_dirs = _sequential_numbering_ok(workspace, query_ids_from_input if query_ids_from_input else None)
    if total_dirs > 0:
        scores["sequential_numbering_per_query"] = ok_dirs / total_dirs
    else:
        scores["sequential_numbering_per_query"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()