import csv
import json
import os
import re
import sys
import stat
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        txt = _read_text_safe(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _read_csv_dicts_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                if row is None:
                    continue
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


class ArticleTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_target_table = False
        self.current_table_depth = 0
        self.in_thead = False
        self.in_tbody = False
        self.in_tr = False
        self.in_th = False
        self.in_td = False
        self.headers: List[str] = []
        self.current_row: List[str] = []
        self.rows: List[Dict[str, str]] = []
        self._cell_data: List[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag.lower() == "table":
            self.current_table_depth += 1
            if attrs_dict.get("id") == "articles" and not self.in_target_table:
                self.in_target_table = True
                self.headers = []
                self.rows = []
        if not self.in_target_table:
            return
        if tag.lower() == "thead":
            self.in_thead = True
        elif tag.lower() == "tbody":
            self.in_tbody = True
        elif tag.lower() == "tr":
            self.in_tr = True
            self.current_row = []
        elif tag.lower() == "th":
            self.in_th = True
            self._cell_data = []
        elif tag.lower() == "td":
            self.in_td = True
            self._cell_data = []

    def handle_endtag(self, tag):
        if not self.in_target_table:
            if tag.lower() == "table" and self.current_table_depth > 0:
                self.current_table_depth -= 1
            return
        if tag.lower() == "th":
            self.in_th = False
            cell_text = "".join(self._cell_data).strip()
            self.headers.append(cell_text)
            self._cell_data = []
        elif tag.lower() == "td":
            self.in_td = False
            cell_text = "".join(self._cell_data).strip()
            self.current_row.append(cell_text)
            self._cell_data = []
        elif tag.lower() == "tr":
            if self.in_tr and self.in_tbody and self.current_row:
                mapped: Dict[str, str] = {}
                for i, h in enumerate(self.headers):
                    val = self.current_row[i] if i < len(self.current_row) else ""
                    mapped[h] = val
                self.rows.append(mapped)
            self.in_tr = False
            self.current_row = []
        elif tag.lower() == "thead":
            self.in_thead = False
        elif tag.lower() == "tbody":
            self.in_tbody = False
        elif tag.lower() == "table":
            self.current_table_depth -= 1
            if self.current_table_depth == 0:
                self.in_target_table = False

    def handle_data(self, data):
        if self.in_th or self.in_td:
            self._cell_data.append(data)


def _parse_html_articles(path: Path) -> Optional[List[Dict[str, str]]]:
    text = _read_text_safe(path)
    if text is None:
        return None
    parser = ArticleTableParser()
    try:
        parser.feed(text)
        return parser.rows
    except Exception:
        return None


def _discover_html_files(workspace: Path) -> List[Path]:
    base = workspace / "input" / "articles"
    if not base.exists():
        return []
    return sorted([p for p in base.glob("*.html") if p.is_file()])


def _safe_parse_date(d: str) -> Optional[datetime]:
    try:
        return datetime.strptime(d, "%Y-%m-%d")
    except Exception:
        return None


def _compute_expected_from_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    sources_path = workspace / "input" / "sources.csv"
    sources_rows = _read_csv_dicts_safe(sources_path)
    html_files = _discover_html_files(workspace)
    if sources_rows is None or len(html_files) == 0:
        return None

    all_articles: List[Dict[str, str]] = []
    html_row_counts: Dict[str, int] = {}
    for hf in html_files:
        rows = _parse_html_articles(hf)
        if rows is None:
            return None
        all_articles.extend(rows)
        html_row_counts[hf.name] = len(rows)

    pub_dates: List[datetime] = []
    for r in all_articles:
        d = _safe_parse_date(r.get("publication_date", ""))
        if d is not None:
            pub_dates.append(d)
    if not pub_dates:
        return None
    as_of = max(pub_dates)

    lower_bound = as_of - timedelta(days=365)
    qualifying_articles: List[Dict[str, Any]] = []
    for r in all_articles:
        topic = r.get("topic", "")
        d = _safe_parse_date(r.get("publication_date", ""))
        if topic == "Climate Policy" and d is not None and (lower_bound <= d <= as_of):
            qualifying_articles.append(r)

    kept_sources: List[Dict[str, Any]] = []
    for s in sources_rows:
        try:
            cred = int(str(s.get("credibility_score", "")).strip())
        except Exception:
            continue
        topic = s.get("topic", "")
        note = s.get("reliability_note", "")
        if topic == "Climate Policy" and cred >= 80 and ("conflict" not in (note or "").lower()):
            kept_sources.append(s)

    mentions: Dict[str, int] = {}
    for s in kept_sources:
        sid = s.get("source_id", "")
        mentions[sid] = 0
    for a in qualifying_articles:
        ids = [x.strip() for x in (a.get("source_ids", "") or "").split(",") if x.strip()]
        for sid in ids:
            if sid in mentions:
                mentions[sid] += 1

    def last_contact_dt(srow: Dict[str, str]) -> datetime:
        d = _safe_parse_date(srow.get("last_contact", "1970-01-01"))
        return d if d is not None else datetime(1970, 1, 1)

    expected_sources = []
    for s in kept_sources:
        sid = s.get("source_id", "")
        expected_sources.append({
            "source_id": sid,
            "name": s.get("name", ""),
            "affiliation": s.get("affiliation", ""),
            "topic": s.get("topic", ""),
            "credibility_score": int(s.get("credibility_score", "0") or "0"),
            "last_contact": s.get("last_contact", ""),
            "mentions_in_articles_last_year": mentions.get(sid, 0),
        })

    expected_sources.sort(
        key=lambda r: (
            -int(r["credibility_score"]),
            -int(r["mentions_in_articles_last_year"]),
            -int(_safe_parse_date(r["last_contact"]).timestamp() if _safe_parse_date(r["last_contact"]) else 0),
            r["source_id"],
        )
    )
    for idx, r in enumerate(expected_sources, start=1):
        r["rank"] = idx

    return {
        "html_files": html_files,
        "html_row_counts": html_row_counts,
        "as_of": as_of.strftime("%Y-%m-%d"),
        "qualifying_articles_count": len(qualifying_articles),
        "kept_sources_count": len(expected_sources),
        "filtered_sources_count": len(sources_rows) - len(expected_sources),
        "expected_ranked_sources": expected_sources,
        "sources_rows": sources_rows,
    }


def _parse_csv_with_header(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    rows = _read_csv_dicts_safe(path)
    if rows is None:
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
    except Exception:
        header = list(rows[0].keys()) if rows else []
    return header, rows


def _is_executable_file(path: Path) -> bool:
    try:
        if not path.exists() or not path.is_file():
            return False
        mode = path.stat().st_mode
        if os.name == "nt":
            return os.access(str(path), os.X_OK)
        return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    except Exception:
        return False


def _find_entries_list_from_json(obj: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(obj, list):
        if all(isinstance(x, dict) for x in obj) or obj == []:
            return obj
    if isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, list) and all(isinstance(x, dict) for x in v):
                return v
        for v in obj.values():
            if isinstance(v, list) and (v == []):
                return v
    return None


def _get_html_entry_info(entries: List[Dict[str, Any]], html_path: Path) -> Optional[Dict[str, Any]]:
    target_suffix = str(html_path.as_posix())
    candidates = []
    for e in entries:
        p = e.get("path")
        if not isinstance(p, str):
            continue
        p_norm = Path(p).as_posix()
        if p_norm.endswith(target_suffix) or p_norm.endswith(html_path.name):
            candidates.append(e)
    if candidates:
        for c in candidates:
            p_norm = Path(c.get("path")).as_posix()
            if p_norm.endswith(target_suffix):
                return c
        return candidates[0]
    return None


def _find_row_count_in_entry(entry: Dict[str, Any]) -> Optional[int]:
    for k, v in entry.items():
        if k in ("path", "size_bytes", "mtime"):
            continue
        if isinstance(v, int) and "row" in k.lower():
            return v
    for k, v in entry.items():
        if isinstance(v, list) and "article" in k.lower():
            try:
                return int(len(v))
            except Exception:
                continue
    return None


def _find_number_near(text: str, keywords: List[str]) -> Optional[int]:
    text_lower = text.lower()
    for kw in keywords:
        kw_lower = kw.lower()
        m = re.search(rf"{re.escape(kw_lower)}\s*[:=]?\s*(\d+)", text_lower)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
        m2 = re.search(rf"(\d+)\s+{re.escape(kw_lower)}", text_lower)
        if m2:
            try:
                return int(m2.group(1))
            except Exception:
                pass
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    # Keys must be in a stable expected order
    scores: Dict[str, float] = {
        "script_exists_and_executable": 0.0,
        "weekly_ranked_csv_structure_correct": 0.0,
        "weekly_ranked_csv_content_correct": 0.0,
        "weekly_ranked_csv_sort_and_ranks_correct": 0.0,
        "processed_files_json_present_and_entries": 0.0,
        "processed_files_json_row_counts_correct": 0.0,
        "processed_files_json_sizes_correct": 0.0,
        "run_log_includes_correct_counts": 0.0,
        "schedule_cron_line_valid": 0.0,
    }

    expected = _compute_expected_from_inputs(workspace)

    script_path = workspace / "scripts" / "build_weekly_sources"
    if _is_executable_file(script_path):
        scores["script_exists_and_executable"] = 1.0

    cron_path = workspace / "output" / "schedule" / "weekly_sources_cron.txt"
    cron_ok = False
    if cron_path.exists() and cron_path.is_file():
        content = _read_text_safe(cron_path) or ""
        lines = [ln for ln in content.splitlines() if ln.strip()]
        if len(lines) == 1:
            line = lines[0]
            sched_match = re.match(r"\s*30\s+6\s+\*\s+\*\s+1\s+.+", line)
            has_script = "scripts/build_weekly_sources" in line
            has_append = ">>" in line and "weekly_sources.log" in line and "output/logs" in line
            has_redirect_stderr = "2>&1" in line
            if sched_match and has_script and has_append and has_redirect_stderr:
                cron_ok = True
    scores["schedule_cron_line_valid"] = 1.0 if cron_ok else 0.0

    ranked_csv_path = workspace / "output" / "weekly_ranked_sources.csv"
    header_ok = False
    content_ok = False
    sort_ok = False
    if ranked_csv_path.exists():
        header, rows = _parse_csv_with_header(ranked_csv_path)
        expected_header = [
            "source_id",
            "name",
            "affiliation",
            "topic",
            "credibility_score",
            "last_contact",
            "mentions_in_articles_last_year",
            "rank",
        ]
        if header == expected_header and isinstance(rows, list):
            header_ok = True
            if expected is not None and rows is not None:
                exp_rows = expected["expected_ranked_sources"]
                actual_rows = []
                try:
                    for r in rows:
                        actual_rows.append({
                            "source_id": r.get("source_id", ""),
                            "name": r.get("name", ""),
                            "affiliation": r.get("affiliation", ""),
                            "topic": r.get("topic", ""),
                            "credibility_score": int(r.get("credibility_score", "0") or "0"),
                            "last_contact": r.get("last_contact", ""),
                            "mentions_in_articles_last_year": int(r.get("mentions_in_articles_last_year", "0") or "0"),
                            "rank": int(r.get("rank", "0") or "0"),
                        })
                except Exception:
                    actual_rows = []
                if actual_rows and len(actual_rows) == len(exp_rows):
                    ids_match = [a["source_id"] for a in actual_rows] == [e["source_id"] for e in exp_rows]
                    mentions_match = all(
                        a["mentions_in_articles_last_year"] == e["mentions_in_articles_last_year"]
                        for a, e in zip(actual_rows, exp_rows)
                    )
                    fields_match = all(
                        (a["name"] == e["name"] and
                         a["affiliation"] == e["affiliation"] and
                         a["topic"] == e["topic"] and
                         a["credibility_score"] == e["credibility_score"] and
                         a["last_contact"] == e["last_contact"])
                        for a, e in zip(actual_rows, exp_rows)
                    )
                    content_ok = ids_match and mentions_match and fields_match
                    ranks_seq = [a["rank"] for a in actual_rows] == list(range(1, len(actual_rows) + 1))

                    def to_ts(date_str: str) -> int:
                        d = _safe_parse_date(date_str)
                        return int(d.timestamp()) if d else 0

                    recomputed_sorted = sorted(
                        actual_rows,
                        key=lambda r: (
                            -int(r["credibility_score"]),
                            -int(r["mentions_in_articles_last_year"]),
                            -to_ts(r["last_contact"]),
                            r["source_id"],
                        )
                    )
                    order_ok = [r["source_id"] for r in recomputed_sorted] == [r["source_id"] for r in actual_rows]
                    sort_ok = ranks_seq and order_ok
    scores["weekly_ranked_csv_structure_correct"] = 1.0 if header_ok else 0.0
    scores["weekly_ranked_csv_content_correct"] = 1.0 if content_ok else 0.0
    scores["weekly_ranked_csv_sort_and_ranks_correct"] = 1.0 if sort_ok else 0.0

    processed_path = workspace / "output" / "processed_files.json"
    processed_present_ok = False
    rows_count_ok = False
    sizes_ok = False
    if processed_path.exists() and processed_path.is_file():
        obj = _load_json_safe(processed_path)
        entries = _find_entries_list_from_json(obj) if obj is not None else None
        if entries is not None:
            html_files = _discover_html_files(workspace)
            if len(html_files) > 0:
                all_entries_found = True
                all_rows_ok = True
                all_sizes_ok = True
                for hf in html_files:
                    e = _get_html_entry_info(entries, hf)
                    if e is None:
                        all_entries_found = False
                        break
                    path_present = isinstance(e.get("path"), str)
                    size_present = isinstance(e.get("size_bytes"), (int, float))
                    mtime_present = ("mtime" in e)
                    if not (path_present and size_present and mtime_present):
                        all_entries_found = False
                        break
                    try:
                        actual_size = hf.stat().st_size
                    except Exception:
                        actual_size = None
                    if isinstance(e.get("size_bytes"), (int, float)) and actual_size is not None:
                        if int(e.get("size_bytes")) != int(actual_size):
                            all_sizes_ok = False
                    else:
                        all_sizes_ok = False
                    parsed_rows = _parse_html_articles(hf) or []
                    expected_rows_count = len(parsed_rows)
                    rc = _find_row_count_in_entry(e)
                    if rc is None or int(rc) != int(expected_rows_count):
                        all_rows_ok = False
                processed_present_ok = all_entries_found
                rows_count_ok = all_rows_ok
                sizes_ok = all_sizes_ok
    scores["processed_files_json_present_and_entries"] = 1.0 if processed_present_ok else 0.0
    scores["processed_files_json_row_counts_correct"] = 1.0 if rows_count_ok else 0.0
    scores["processed_files_json_sizes_correct"] = 1.0 if sizes_ok else 0.0

    log_ok = False
    log_path = workspace / "output" / "logs" / "last_run.log"
    if log_path.exists() and log_path.is_file():
        txt = _read_text_safe(log_path) or ""
        if expected is not None:
            kept_expected = int(expected["kept_sources_count"])
            filtered_expected = int(expected["filtered_sources_count"])
            qualifying_articles_expected = int(expected["qualifying_articles_count"])
            kept_found = _find_number_near(txt, ["kept", "sources kept"])
            filtered_found = _find_number_near(txt, ["filtered", "sources filtered"])
            articles_found = None
            for kw in [["qualifying articles"], ["qualifying"], ["articles considered"], ["articles"]]:
                n = _find_number_near(txt, kw)
                if n is not None:
                    articles_found = n
                    break
            if (kept_found == kept_expected and
                filtered_found == filtered_expected and
                articles_found == qualifying_articles_expected):
                log_ok = True
    scores["run_log_includes_correct_counts"] = 1.0 if log_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    # Preserve insertion order without sorting keys
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()