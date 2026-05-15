import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse


def _safe_read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_read_bytes(p: Path) -> Optional[bytes]:
    try:
        return p.read_bytes()
    except Exception:
        return None


def _load_json(p: Path) -> Optional[dict]:
    try:
        txt = _safe_read_text(p)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _load_json_lines(p: Path) -> Optional[List[dict]]:
    try:
        txt = _safe_read_text(p)
        if txt is None:
            return None
        lines = [ln for ln in txt.splitlines() if ln.strip() != ""]
        recs = []
        for ln in lines:
            try:
                obj = json.loads(ln)
            except Exception:
                return None
            if not isinstance(obj, dict):
                return None
            recs.append(obj)
        return recs
    except Exception:
        return None


def _load_keywords(p: Path) -> Optional[List[str]]:
    try:
        txt = _safe_read_text(p)
        if txt is None:
            return None
        kws = [ln.strip() for ln in txt.splitlines()]
        kws = [k for k in kws if k != ""]
        seen = set()
        uniq = []
        for k in kws:
            if k not in seen:
                uniq.append(k)
                seen.add(k)
        return uniq
    except Exception:
        return None


def _load_sources(p: Path) -> Optional[List[dict]]:
    data = _load_json(p)
    if data is None or not isinstance(data, dict):
        return None
    sources = data.get("sources")
    if not isinstance(sources, list):
        return None
    cleaned = []
    for s in sources:
        if not isinstance(s, dict):
            return None
        name = s.get("name")
        dom = s.get("domain_pattern")
        if not isinstance(name, str) or not isinstance(dom, str):
            return None
        cleaned.append({"name": name, "domain_pattern": dom})
    return cleaned


def _is_iso8601(s: str) -> bool:
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _sha256_hex(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _compute_sha256_file(p: Path) -> Optional[str]:
    b = _safe_read_bytes(p)
    if b is None:
        return None
    return _sha256_hex(b)


def _byte_size(p: Path) -> Optional[int]:
    try:
        return p.stat().st_size
    except Exception:
        return None


def _is_relative_path(path_str: str) -> bool:
    try:
        p = Path(path_str)
        return not p.is_absolute()
    except Exception:
        return False


def _path_within(base: Path, target: Path) -> bool:
    try:
        base_res = base.resolve()
        target_res = target.resolve()
        return base_res == target_res or base_res in target_res.parents
    except Exception:
        return False


def _count_keyword_occurrences(text: str, keyword: str) -> int:
    if not text or not keyword:
        return 0
    t = text.lower()
    k = keyword.lower()
    count = 0
    start = 0
    while True:
        idx = t.find(k, start)
        if idx == -1:
            break
        count += 1
        start = idx + max(1, len(k))
    return count


def _parse_csv(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None
        header = rows[0]
        data_rows = rows[1:]
        return header, data_rows
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "outputs_directories_present": 0.0,
        "pages_jsonl_exists": 0.0,
        "pages_record_schema_valid": 0.0,
        "page_files_exist_and_hashes_match": 0.0,
        "paths_relative_and_under_outputs": 0.0,
        "page_urls_match_domain": 0.0,
        "keyword_counts_match_text": 0.0,
        "snippets_valid": 0.0,
        "pages_per_source_exact_two": 0.0,
        "summary_csv_exists": 0.0,
        "summary_rows_per_source": 0.0,
        "summary_aggregates_match_pages": 0.0,
        "files_count_at_least_pages": 0.0,
    }

    inputs_sources_path = workspace / "input" / "sources.json"
    inputs_keywords_path = workspace / "input" / "keywords.txt"
    outputs_dir = workspace / "outputs"
    raw_dir = outputs_dir / "raw_html"
    text_dir = outputs_dir / "text"
    pages_jsonl_path = outputs_dir / "pages.jsonl"
    summary_csv_path = outputs_dir / "summary.csv"

    sources = _load_sources(inputs_sources_path)
    keywords = _load_keywords(inputs_keywords_path)

    raw_exists = raw_dir.exists() and raw_dir.is_dir()
    text_exists = text_dir.exists() and text_dir.is_dir()
    if raw_exists and text_exists:
        scores["outputs_directories_present"] = 1.0

    pages = None
    if pages_jsonl_path.exists() and pages_jsonl_path.is_file():
        pages = _load_json_lines(pages_jsonl_path)
        if pages is not None and isinstance(pages, list) and len(pages) > 0:
            scores["pages_jsonl_exists"] = 1.0

    schema_ok = True
    files_ok = True
    paths_ok = True
    urls_ok = True
    keywords_ok = True
    snippets_ok = True

    pages_by_source: Dict[Tuple[str, str], List[dict]] = {}

    if pages is not None:
        kw_set = set(keywords) if isinstance(keywords, list) else None

        for rec in pages:
            required_keys = [
                "source_name",
                "domain_pattern",
                "page_url",
                "http_status",
                "retrieved_at",
                "raw_html_path",
                "text_path",
                "html_sha256",
                "html_bytes",
                "keyword_counts",
                "snippets",
            ]
            for k in required_keys:
                if k not in rec:
                    schema_ok = False
            if not isinstance(rec.get("source_name"), str):
                schema_ok = False
            if not isinstance(rec.get("domain_pattern"), str):
                schema_ok = False
            if not isinstance(rec.get("page_url"), str):
                schema_ok = False
            if not isinstance(rec.get("http_status"), int):
                schema_ok = False
            else:
                if not (100 <= rec.get("http_status") <= 599):
                    schema_ok = False
            if not isinstance(rec.get("retrieved_at"), str) or not _is_iso8601(rec.get("retrieved_at")):
                schema_ok = False
            if not isinstance(rec.get("raw_html_path"), str) or not isinstance(rec.get("text_path"), str):
                schema_ok = False
            if not isinstance(rec.get("html_sha256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", rec.get("html_sha256") or ""):
                schema_ok = False
            if not isinstance(rec.get("html_bytes"), int) or rec.get("html_bytes") < 0:
                schema_ok = False
            if not isinstance(rec.get("keyword_counts"), dict):
                schema_ok = False
            if not isinstance(rec.get("snippets"), list):
                schema_ok = False
            if isinstance(kw_set, set):
                kc = rec.get("keyword_counts") if isinstance(rec.get("keyword_counts"), dict) else {}
                if set(kc.keys()) != kw_set:
                    schema_ok = False

            raw_rel = rec.get("raw_html_path")
            text_rel = rec.get("text_path")
            if not (_is_relative_path(raw_rel) and _is_relative_path(text_rel)):
                paths_ok = False
            else:
                raw_abs = (workspace / raw_rel).resolve()
                text_abs = (workspace / text_rel).resolve()
                if not _path_within(raw_dir, raw_abs):
                    paths_ok = False
                if not _path_within(text_dir, text_abs):
                    paths_ok = False
                if not raw_abs.exists() or not raw_abs.is_file():
                    files_ok = False
                if not text_abs.exists() or not text_abs.is_file():
                    files_ok = False
                if raw_abs.exists() and raw_abs.is_file():
                    sha = _compute_sha256_file(raw_abs)
                    size = _byte_size(raw_abs)
                    if sha is None or size is None:
                        files_ok = False
                    else:
                        if sha.lower() != (rec.get("html_sha256") or "").lower():
                            files_ok = False
                        if size != rec.get("html_bytes"):
                            files_ok = False

            url = rec.get("page_url")
            dom_pat = rec.get("domain_pattern")
            try:
                parsed = urlparse(url or "")
                if parsed.scheme not in ("http", "https"):
                    urls_ok = False
                hostname = parsed.netloc.lower()
                host = hostname.split("@")[-1]
                host = host.split(":")[0]
                if not host.endswith((dom_pat or "").lower()):
                    urls_ok = False
            except Exception:
                urls_ok = False

            if isinstance(kw_set, set):
                text_abs = (workspace / rec.get("text_path")).resolve() if isinstance(rec.get("text_path"), str) else None
                text_content = _safe_read_text(text_abs) if text_abs else None
                if text_content is None:
                    keywords_ok = False
                else:
                    recorded_counts = rec.get("keyword_counts") if isinstance(rec.get("keyword_counts"), dict) else {}
                    for kw in keywords:
                        rec_val = recorded_counts.get(kw)
                        if not isinstance(rec_val, int) or rec_val < 0:
                            keywords_ok = False
                            break
                        comp = _count_keyword_occurrences(text_content, kw)
                        if comp != rec_val:
                            keywords_ok = False
                            break

            snips = rec.get("snippets")
            if isinstance(snips, list):
                per_kw_counts: Dict[str, int] = {}
                for s in snips:
                    if not isinstance(s, dict):
                        snippets_ok = False
                        break
                    kw = s.get("keyword")
                    txt = s.get("text")
                    if not isinstance(kw, str) or not isinstance(txt, str):
                        snippets_ok = False
                        break
                    if isinstance(kw_set, set) and kw not in kw_set:
                        snippets_ok = False
                        break
                    if len(txt) > 200:
                        snippets_ok = False
                        break
                    if kw and (kw.lower() not in txt.lower()):
                        snippets_ok = False
                        break
                    per_kw_counts[kw] = per_kw_counts.get(kw, 0) + 1
                if snippets_ok and isinstance(kw_set, set):
                    for kw, cnt in per_kw_counts.items():
                        if cnt > 3:
                            snippets_ok = False
                            break
                    if snippets_ok:
                        recorded_counts = rec.get("keyword_counts") if isinstance(rec.get("keyword_counts"), dict) else {}
                        for kw in keywords:
                            cnt = recorded_counts.get(kw, 0)
                            snip_cnt = per_kw_counts.get(kw, 0)
                            if cnt == 0 and snip_cnt != 0:
                                snippets_ok = False
                                break
            else:
                snippets_ok = False

            key = (rec.get("source_name"), rec.get("domain_pattern"))
            pages_by_source.setdefault(key, []).append(rec)

        if schema_ok:
            scores["pages_record_schema_valid"] = 1.0
        if files_ok:
            scores["page_files_exist_and_hashes_match"] = 1.0
        if paths_ok:
            scores["paths_relative_and_under_outputs"] = 1.0
        if urls_ok:
            scores["page_urls_match_domain"] = 1.0
        if keywords is not None and keywords_ok:
            scores["keyword_counts_match_text"] = 1.0
        if snippets_ok:
            scores["snippets_valid"] = 1.0

        if isinstance(sources, list):
            exact_two = True
            for s in sources:
                key = (s["name"], s["domain_pattern"])
                cnt = len(pages_by_source.get(key, []))
                if cnt != 2:
                    exact_two = False
            for k in pages_by_source.keys():
                if {"name": k[0], "domain_pattern": k[1]} not in sources:
                    exact_two = False
            if exact_two:
                scores["pages_per_source_exact_two"] = 1.0

    if summary_csv_path.exists() and summary_csv_path.is_file():
        parsed = _parse_csv(summary_csv_path)
        if parsed is not None:
            header, rows = parsed
            scores["summary_csv_exists"] = 1.0
            rows_ok = True
            aggr_ok = True
            expected_cols = ["source_name", "domain_pattern", "pages_crawled", "total_html_bytes", "total_keyword_hits", "retrieved_at"]
            if header != expected_cols:
                rows_ok = False
            row_map: Dict[Tuple[str, str], dict] = {}
            try:
                for r in rows:
                    if len(r) != len(expected_cols):
                        rows_ok = False
                        break
                    row_dict = dict(zip(header, r))
                    row_dict["pages_crawled"] = int(row_dict["pages_crawled"])
                    row_dict["total_html_bytes"] = int(row_dict["total_html_bytes"])
                    row_dict["total_keyword_hits"] = int(row_dict["total_keyword_hits"])
                    if not _is_iso8601(row_dict["retrieved_at"]):
                        rows_ok = False
                    key = (row_dict["source_name"], row_dict["domain_pattern"])
                    if key in row_map:
                        rows_ok = False
                        break
                    row_map[key] = row_dict
            except Exception:
                rows_ok = False

            if isinstance(sources, list):
                if rows_ok:
                    if len(row_map) != len(sources):
                        rows_ok = False
                    else:
                        for s in sources:
                            key = (s["name"], s["domain_pattern"])
                            if key not in row_map:
                                rows_ok = False
                                break
                if rows_ok and pages is not None:
                    stats: Dict[Tuple[str, str], Dict[str, int]] = {}
                    for rec in pages:
                        key = (rec.get("source_name"), rec.get("domain_pattern"))
                        if key not in stats:
                            stats[key] = {"pages": 0, "bytes": 0, "hits": 0}
                        stats[key]["pages"] += 1
                        stats[key]["bytes"] += int(rec.get("html_bytes") or 0)
                        kc = rec.get("keyword_counts") if isinstance(rec.get("keyword_counts"), dict) else {}
                        stats[key]["hits"] += sum(int(v) for v in kc.values() if isinstance(v, int))
                    for s in sources:
                        key = (s["name"], s["domain_pattern"])
                        row = row_map.get(key)
                        if row is None:
                            aggr_ok = False
                            break
                        st = stats.get(key, {"pages": 0, "bytes": 0, "hits": 0})
                        if row["pages_crawled"] != st["pages"]:
                            aggr_ok = False
                            break
                        if row["total_html_bytes"] != st["bytes"]:
                            aggr_ok = False
                            break
                        if row["total_keyword_hits"] != st["hits"]:
                            aggr_ok = False
                            break
                else:
                    aggr_ok = False
            else:
                rows_ok = False
                aggr_ok = False

            if rows_ok:
                scores["summary_rows_per_source"] = 1.0
            if aggr_ok:
                scores["summary_aggregates_match_pages"] = 1.0

    if pages is not None and raw_dir.exists() and text_dir.exists():
        try:
            raw_files = [p for p in raw_dir.rglob("*") if p.is_file()]
            text_files = [p for p in text_dir.rglob("*") if p.is_file()]
            if len(raw_files) >= len(pages) and len(text_files) >= len(pages):
                scores["files_count_at_least_pages"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()