import json
import sys
import csv
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _read_bytes_safe(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _parse_iso8601(s: str):
    if not isinstance(s, str) or not s.strip():
        return None
    s = s.strip()
    try:
        if s.endswith("Z"):
            s_mod = s[:-1] + "+00:00"
            return datetime.fromisoformat(s_mod)
        return datetime.fromisoformat(s)
    except Exception:
        fmts = [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S%z",
        ]
        for fmt in fmts:
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
    return None


def _load_csv_strict(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            sample = f.read(2048)
            f.seek(0)
            sniffer = csv.Sniffer()
            try:
                dialect = sniffer.sniff(sample)
            except Exception:
                dialect = csv.excel
            reader = csv.reader(f, dialect=dialect)
            rows = list(reader)
    except Exception:
        return None, None

    if not rows:
        return [], []
    header = rows[0]
    data_rows = rows[1:]
    dict_rows = []
    for r in data_rows:
        r = (r + [""] * len(header))[: len(header)]
        dict_rows.append({header[i]: r[i] for i in range(len(header))})
    return header, dict_rows


def _parse_sources_yaml(path: Path):
    text = _read_text_safe(path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    sources = []
    i = 0
    while i < len(lines) and not lines[i].strip().startswith("sources:"):
        i += 1
    if i < len(lines) and lines[i].strip().startswith("sources:"):
        i += 1

    current = None
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("- id:"):
            if current:
                sources.append(current)
            id_val = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            current = {"id": id_val, "name": None, "domain_patterns": [], "page_hints": []}
            i += 1
            continue
        if current is not None:
            if stripped.startswith("name:"):
                name_val = stripped.split(":", 1)[1].strip()
                if (name_val.startswith('"') and name_val.endswith('"')) or (name_val.startswith("'") and name_val.endswith("'")):
                    name_val = name_val[1:-1]
                current["name"] = name_val
                i += 1
                continue
            if stripped.startswith("domain_patterns:"):
                i += 1
                while i < len(lines) and lines[i].strip().startswith("- "):
                    pat_line = lines[i].strip()[2:].strip()
                    if (pat_line.startswith('"') and pat_line.endswith('"')) or (pat_line.startswith("'") and pat_line.endswith("'")):
                        pat_line = pat_line[1:-1]
                    current["domain_patterns"].append(pat_line)
                    i += 1
                continue
            if stripped.startswith("page_hints:"):
                i += 1
                while i < len(lines) and lines[i].strip().startswith("- "):
                    hint_line = lines[i].strip()[2:].strip()
                    if (hint_line.startswith('"') and hint_line.endswith('"')) or (hint_line.startswith("'") and hint_line.endswith("'")):
                        hint_line = hint_line[1:-1]
                    current["page_hints"].append(hint_line)
                    i += 1
                continue
        i += 1
    if current:
        sources.append(current)
    return {"sources": sources}


def _url_valid_http(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if not parsed.netloc:
            return False
        return True
    except Exception:
        return False


def _match_domain_pattern(url: str, pattern: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    netloc = parsed.netloc or ""
    path = parsed.path or ""
    pat = pattern.strip()
    if "/" in pat:
        parts = pat.split("/", 1)
        dom_pat = parts[0].strip()
        path_pat = "/" + parts[1].strip() if not parts[1].startswith("/") else parts[1].strip()
        if not netloc.endswith(dom_pat):
            return False
        if not path.startswith(path_pat):
            return False
        return True
    else:
        return netloc.endswith(pat)


def _parse_fetch_log_line(line: str):
    line = line.strip()
    if not line:
        return None
    parts = line.split(maxsplit=3)
    if len(parts) < 4:
        return None
    ts_str = parts[0]
    source_id = parts[1]
    url = parts[2]
    status = parts[3]
    ts = _parse_iso8601(ts_str)
    if ts is None:
        return None
    # Require explicit UTC offset
    if ts.tzinfo is None or ts.utcoffset() != timedelta(0):
        return None
    return {"timestamp": ts, "source_id": source_id, "url": url, "status": status}


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "entrypoint_script_exists": 0.0,
        "webpages_saved_per_source": 0.0,
        "fetch_log_present_and_valid": 0.0,
        "fetch_log_domain_matches_config": 0.0,
        "csv_file_present_with_header": 0.0,
        "csv_row_field_validation": 0.0,
        "csv_per_source_rank_rules": 0.0,
        "json_file_present_and_structure": 0.0,
        "json_items_within_60_days_and_action": 0.0,
        "json_items_cross_check_with_csv": 0.0,
    }

    cfg_path = workspace / "input" / "sources.yaml"
    cfg = _parse_sources_yaml(cfg_path)
    if cfg is None or "sources" not in cfg or not isinstance(cfg["sources"], list) or not cfg["sources"]:
        sources_list = []
    else:
        sources_list = cfg["sources"]
    source_ids = [s.get("id") for s in sources_list if isinstance(s.get("id"), str)]
    source_domain_patterns = {s.get("id"): s.get("domain_patterns", []) for s in sources_list if isinstance(s.get("id"), str)}

    entry = workspace / "run_update_digest.sh"
    entry_text = _read_text_safe(entry)
    if entry_text is not None:
        first_line = entry_text.splitlines()[0].strip() if entry_text.splitlines() else ""
        if first_line.startswith("#!") and ("sh" in first_line or "bash" in first_line):
            scores["entrypoint_script_exists"] = 1.0

    # Webpages at exact path: workspace/webpages/{source_id}.html
    if source_ids:
        total = len(source_ids)
        ok = 0
        for sid in source_ids:
            fpath = workspace / "webpages" / f"{sid}.html"
            data = _read_bytes_safe(fpath)
            if data is not None and len(data) > 0:
                ok += 1
        scores["webpages_saved_per_source"] = ok / total if total > 0 else 0.0

    # Fetch log at exact path: workspace/output/fetch.log
    fetch_log_path = workspace / "output" / "fetch.log"
    fetch_log_text = _read_text_safe(fetch_log_path)
    parsed_fetch = []
    if fetch_log_text is not None:
        lines = [ln for ln in fetch_log_text.splitlines() if ln.strip()]
        for ln in lines:
            parsed = _parse_fetch_log_line(ln)
            if parsed is not None:
                parsed_fetch.append(parsed)

    if source_ids and parsed_fetch:
        # Require exactly one valid line per source
        per_source_lines = {sid: [] for sid in source_ids}
        for x in parsed_fetch:
            if x["source_id"] in per_source_lines:
                per_source_lines[x["source_id"]].append(x)
        valid_count = 0
        domain_match_count = 0
        for sid in source_ids:
            lines_for_sid = per_source_lines.get(sid, [])
            # exactly one line
            if len(lines_for_sid) == 1:
                line = lines_for_sid[0]
                url_ok = _url_valid_http(line["url"])
                status_ok = isinstance(line["status"], str) and line["status"].strip() != ""
                if url_ok and status_ok:
                    valid_count += 1
                    patterns = source_domain_patterns.get(sid, [])
                    if patterns and any(_match_domain_pattern(line["url"], pat) for pat in patterns):
                        domain_match_count += 1
        scores["fetch_log_present_and_valid"] = valid_count / len(source_ids) if source_ids else 0.0
        scores["fetch_log_domain_matches_config"] = domain_match_count / len(source_ids) if source_ids else 0.0
    else:
        scores["fetch_log_present_and_valid"] = 0.0
        scores["fetch_log_domain_matches_config"] = 0.0

    # CSV checks at exact path: workspace/output/arg_update_digest.csv
    csv_path = workspace / "output" / "arg_update_digest.csv"
    expected_header = ["source", "item_rank", "date", "title", "item_url", "retrieved_at_utc"]
    csv_header = None
    csv_rows = None
    if csv_path.exists():
        csv_header, csv_rows = _load_csv_strict(csv_path)
    if csv_header == expected_header:
        scores["csv_file_present_with_header"] = 1.0
    else:
        scores["csv_file_present_with_header"] = 0.0

    if csv_rows is not None and csv_header == expected_header:
        total_rows = len(csv_rows)
        valid_rows = 0
        ranks_by_source = {}
        for row in csv_rows:
            src = (row.get("source") or "").strip()
            if not src or src not in source_ids:
                continue
            title = (row.get("title") or "").strip()
            if not title:
                continue
            try:
                rank = int(str(row.get("item_rank", "")).strip())
                if rank < 1:
                    continue
            except Exception:
                continue
            rt = (row.get("retrieved_at_utc") or "").strip()
            if _parse_iso8601(rt) is None:
                continue
            item_url = (row.get("item_url") or "").strip()
            if item_url and not _url_valid_http(item_url):
                continue
            valid_rows += 1
            ranks_by_source.setdefault(src, []).append(rank)
        scores["csv_row_field_validation"] = (valid_rows / total_rows) if total_rows > 0 else 1.0

        if source_ids:
            ok_sources = 0
            for sid in source_ids:
                ranks = ranks_by_source.get(sid, [])
                if not ranks:
                    ok_sources += 1
                    continue
                if len(ranks) > 5:
                    continue
                if sorted(ranks) != list(range(1, len(ranks) + 1)):
                    continue
                ok_sources += 1
            scores["csv_per_source_rank_rules"] = ok_sources / len(source_ids)
        else:
            scores["csv_per_source_rank_rules"] = 0.0
    else:
        scores["csv_row_field_validation"] = 0.0
        scores["csv_per_source_rank_rules"] = 0.0

    # JSON checks at exact path: workspace/output/follow_up_tasks.json
    json_path = workspace / "output" / "follow_up_tasks.json"
    json_items = None
    if json_path.exists():
        try:
            json_items = json.loads(_read_text_safe(json_path))
        except Exception:
            json_items = None

    if json_items is not None and isinstance(json_items, list):
        struct_ok = True
        for item in json_items:
            if not isinstance(item, dict):
                struct_ok = False
                break
            if not isinstance(item.get("source"), str):
                struct_ok = False
                break
            if item.get("source") not in source_ids:
                struct_ok = False
                break
            if not isinstance(item.get("title"), str) or not item.get("title"):
                struct_ok = False
                break
            if not isinstance(item.get("reference_url"), str) or not _url_valid_http(item.get("reference_url")):
                struct_ok = False
                break
            d = item.get("date")
            if not isinstance(d, str) or _parse_iso8601(d) is None:
                struct_ok = False
                break
            sa = item.get("suggested_action")
            expected_sa = f"Review and update local ARG reference for {item.get('source')}"
            if not isinstance(sa, str) or sa != expected_sa:
                struct_ok = False
                break
        scores["json_file_present_and_structure"] = 1.0 if struct_ok else 0.0
    else:
        scores["json_file_present_and_structure"] = 0.0

    if json_items is not None and isinstance(json_items, list):
        if not json_items:
            scores["json_items_within_60_days_and_action"] = 1.0
        else:
            now = datetime.now(timezone.utc)
            ok_count = 0
            for item in json_items:
                d = item.get("date")
                ts = _parse_iso8601(d) if isinstance(d, str) else None
                if ts is None:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                delta = now - ts
                if timedelta(days=0) <= delta <= timedelta(days=60):
                    sa = item.get("suggested_action")
                    expected_sa = f"Review and update local ARG reference for {item.get('source')}"
                    if isinstance(sa, str) and sa == expected_sa:
                        ok_count += 1
            scores["json_items_within_60_days_and_action"] = (ok_count / len(json_items)) if json_items else 1.0
    else:
        scores["json_items_within_60_days_and_action"] = 0.0

    if (
        csv_rows is not None
        and csv_header == expected_header
        and json_items is not None
        and isinstance(json_items, list)
    ):
        if not json_items:
            scores["json_items_cross_check_with_csv"] = 1.0
        else:
            csv_by_source_title = set()
            csv_by_source_url = set()
            for r in csv_rows:
                src = (r.get("source") or "").strip()
                ttl = (r.get("title") or "").strip()
                iurl = (r.get("item_url") or "").strip()
                if src and ttl:
                    csv_by_source_title.add((src, ttl))
                if src and iurl:
                    csv_by_source_url.add((src, iurl))
            matched = 0
            for item in json_items:
                src = item.get("source")
                ttl = (item.get("title") or "").strip()
                ref = (item.get("reference_url") or "").strip()
                if (src, ref) in csv_by_source_url or (src, ttl) in csv_by_source_title:
                    matched += 1
            scores["json_items_cross_check_with_csv"] = (matched / len(json_items)) if json_items else 1.0
    else:
        scores["json_items_cross_check_with_csv"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()