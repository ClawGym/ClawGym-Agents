import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_yaml_config_basic(path: Path) -> Optional[dict]:
    """
    Minimalistic parser tailored to the provided config.yaml structure.
    Expects:
      schedule: "..."
      sources:
        - id: "..."
          organization: "..."
          domain: "..."
          title_hint: "..."
          keywords: ["...", ...]
    """
    txt = _read_text(path)
    if txt is None:
        return None

    # Remove trailing comments preserving inline values
    lines = txt.splitlines()
    # schedule
    m = re.search(r'(?m)^\s*schedule\s*:\s*"(.*?)"\s*', txt)
    if not m:
        return None
    schedule = m.group(1)

    # Sources block
    sources: List[Dict[str, Any]] = []
    in_sources = False
    current: Optional[Dict[str, Any]] = None

    # track indentation of sources list
    for i, raw_line in enumerate(lines):
        line = raw_line.rstrip("\n")
        # Skip full-line comments
        if re.match(r'^\s*#', line):
            continue

        if not in_sources:
            if re.match(r'^\s*sources\s*:\s*$', line):
                in_sources = True
            continue

        # We are inside sources
        m_id = re.match(r'^\s*-\s+id\s*:\s*"?([^"#]+?)"?\s*(?:#.*)?\s*$', line)
        if m_id:
            # start new source
            if current:
                sources.append(current)
            current = {"id": m_id.group(1).strip(), "keywords": []}
            continue

        if current is None:
            # Skip until we find first - id:
            continue

        # organization (not strictly needed)
        m_org = re.match(r'^\s*organization\s*:\s*"(.*?)"\s*(?:#.*)?\s*$', line)
        if m_org:
            current["organization"] = m_org.group(1)
            continue

        m_domain = re.match(r'^\s*domain\s*:\s*"(.*?)"\s*(?:#.*)?\s*$', line)
        if m_domain:
            current["domain"] = m_domain.group(1)
            continue

        m_title = re.match(r'^\s*title_hint\s*:\s*"(.*?)"\s*(?:#.*)?\s*$', line)
        if m_title:
            current["title_hint"] = m_title.group(1)
            continue

        m_keywords = re.match(r'^\s*keywords\s*:\s*\[(.*?)\]\s*(?:#.*)?\s*$', line)
        if m_keywords:
            inner = m_keywords.group(1)
            # split by commas not inside quotes (simple split works since quoted items do not contain commas in provided config)
            parts = [p.strip() for p in inner.split(",") if p.strip() != ""]
            cleaned: List[str] = []
            for p in parts:
                # remove surrounding quotes if present
                q = p
                if q.startswith('"') and q.endswith('"'):
                    q = q[1:-1]
                elif q.startswith("'") and q.endswith("'"):
                    q = q[1:-1]
                cleaned.append(q)
            current["keywords"] = cleaned
            continue

        # Stop if we reached end of sources block (encounter non-indented new section)
        if re.match(r'^\S', line):
            # new top-level key likely
            continue

    if current:
        sources.append(current)

    # Validate structure minimally
    if not isinstance(sources, list) or len(sources) == 0:
        return None
    for s in sources:
        if "id" not in s or "keywords" not in s:
            return None
        if not isinstance(s["keywords"], list):
            return None
    return {"schedule": schedule, "sources": sources}


def _find_script_file(workspace: Path) -> Optional[Path]:
    scripts_dir = workspace / "scripts"
    if not scripts_dir.exists():
        return None
    candidates: List[Path] = []
    for p in scripts_dir.iterdir():
        if not p.is_file():
            continue
        name = p.name
        if name == "fetch_official_pages" or name.startswith("fetch_official_pages."):
            candidates.append(p)
    if not candidates:
        return None
    # Choose the first deterministically sorted
    candidates.sort()
    return candidates[0]


def _list_raw_files_for_source(workspace: Path, source_id: str) -> Dict[str, Path]:
    raw_dir = workspace / "data" / "raw"
    res: Dict[str, Path] = {}
    if not raw_dir.exists():
        return res
    pattern = re.compile(rf'^{re.escape(source_id)}_(\d{{8}})\.html$')
    for p in raw_dir.iterdir():
        if not p.is_file():
            continue
        m = pattern.match(p.name)
        if m:
            date = m.group(1)
            res[date] = p
    return res


def _find_common_date(workspace: Path, source_ids: List[str]) -> Optional[str]:
    sets: List[set] = []
    for sid in source_ids:
        dmap = _list_raw_files_for_source(workspace, sid)
        sets.append(set(dmap.keys()))
    if not sets:
        return None
    common = sets[0]
    for s in sets[1:]:
        common = common & s
    if not common:
        return None
    # pick the latest date
    return sorted(common)[-1]


def _parse_csv_strict(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None
    if not rows:
        return None
    header = rows[0]
    data = rows[1:]
    return header, data


def _sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _is_iso8601(ts: str) -> bool:
    if not isinstance(ts, str) or not ts:
        return False
    # Accept trailing 'Z'
    try:
        if ts.endswith("Z"):
            datetime.fromisoformat(ts[:-1])
        else:
            datetime.fromisoformat(ts)
        return True
    except Exception:
        # Try a more tolerant parse: basic date-time check
        # YYYY-MM-DDTHH:MM
        if re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$', ts):
            return True
        return False


def _date_from_iso(ts: str) -> Optional[str]:
    # return YYYYMMDD if parsable
    if not isinstance(ts, str) or len(ts) < 10:
        return None
    date_part = ts[:10]
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_part):
        return None
    y, m, d = date_part.split("-")
    return f"{y}{m}{d}"


def _count_header_lines(path: Path, header: List[str]) -> int:
    try:
        content = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return 0
    hdr_line = ",".join(header)
    return sum(1 for ln in content if ln.strip() == hdr_line)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "script_present": 0.0,
        "raw_files_for_all_sources": 0.0,
        "raw_files_non_empty": 0.0,
        "results_per_run_present": 0.0,
        "results_per_run_header_correct": 0.0,
        "results_all_csv_present": 0.0,
        "results_all_header_single": 0.0,
        "results_rows_schema_valid": 0.0,
        "results_rows_match_rules": 0.0,
        "results_keywords_valid": 0.0,
        "results_hash_matches": 0.0,
        "results_all_contains_per_run": 0.0,
        "status_json_valid": 0.0,
        "status_schedule_matches_config": 0.0,
        "status_stats_consistent": 0.0,
        "cron_txt_valid": 0.0,
        "cron_logs_exist": 0.0,
        "date_consistency_across_artifacts": 0.0,
        "fetched_at_iso_valid": 0.0,
    }

    # Load config
    config_path = workspace / "input" / "config.yaml"
    config = _parse_yaml_config_basic(config_path)
    if not config:
        # Without config we cannot proceed with many checks; fail gracefully
        return scores

    schedule_spec = config.get("schedule")
    sources_cfg = config.get("sources", [])
    source_ids = [s["id"] for s in sources_cfg]

    # script presence
    script_file = _find_script_file(workspace)
    if script_file and script_file.is_file():
        try:
            if script_file.stat().st_size > 0:
                scores["script_present"] = 1.0
        except Exception:
            pass

    # Determine common run date based on raw files per source
    common_date = _find_common_date(workspace, source_ids)

    # raw files presence for all sources
    if common_date:
        all_present = True
        all_non_empty = True
        for sid in source_ids:
            p = _list_raw_files_for_source(workspace, sid).get(common_date)
            if not p or not p.exists():
                all_present = False
                all_non_empty = False
                break
            try:
                if p.stat().st_size <= 0:
                    all_non_empty = False
            except Exception:
                all_non_empty = False
        if all_present:
            scores["raw_files_for_all_sources"] = 1.0
        if all_present and all_non_empty:
            scores["raw_files_non_empty"] = 1.0

    # results per-run CSV presence and header correctness
    expected_header = [
        "source_id",
        "fetched_at_iso",
        "page_title",
        "match_type",
        "match_keyword",
        "link_text",
        "link_href",
        "html_sha256",
    ]
    per_run_csv: Optional[Path] = None
    per_run_header: Optional[List[str]] = None
    per_run_rows: List[List[str]] = []

    if common_date:
        per_run_csv = workspace / "data" / "results" / f"extracted_{common_date}.csv"
        if per_run_csv.exists():
            scores["results_per_run_present"] = 1.0
            parsed = _parse_csv_strict(per_run_csv)
            if parsed:
                h, rows = parsed
                per_run_header = h
                per_run_rows = rows
                if h == expected_header:
                    scores["results_per_run_header_correct"] = 1.0

    # results all.csv presence and header single
    all_csv = workspace / "data" / "results" / "extracted_all.csv"
    all_header: Optional[List[str]] = None
    all_rows: List[List[str]] = []
    if all_csv.exists():
        parsed_all = _parse_csv_strict(all_csv)
        if parsed_all:
            all_header, all_rows = parsed_all
            if all_header == expected_header:
                scores["results_all_csv_present"] = 1.0
                # Ensure only single header line
                header_count = _count_header_lines(all_csv, expected_header)
                if header_count == 1:
                    scores["results_all_header_single"] = 1.0

    # results rows schema validation
    if per_run_header is not None:
        schema_ok = True
        if per_run_header != expected_header:
            schema_ok = False
        else:
            for r in per_run_rows:
                if len(r) != len(expected_header):
                    schema_ok = False
                    break
                # match_type must be 'link' or 'heading'
                mt = r[3].strip()
                if mt not in ("link", "heading"):
                    schema_ok = False
                    break
        if schema_ok:
            scores["results_rows_schema_valid"] = 1.0

    # results rows link/heading rules
    if per_run_header == expected_header:
        rules_ok = True
        for r in per_run_rows:
            mt = r[3].strip()
            link_text = r[5]
            link_href = r[6]
            if mt == "heading":
                if link_text != "" or link_href != "":
                    rules_ok = False
                    break
            elif mt == "link":
                # absolute URL required
                if not link_href or not (link_href.startswith("http://") or link_href.startswith("https://")):
                    rules_ok = False
                    break
            else:
                rules_ok = False
                break
        if rules_ok:
            scores["results_rows_match_rules"] = 1.0

    # results rows keywords valid per source
    if per_run_header == expected_header:
        # Build keyword maps (case-insensitive)
        kw_map: Dict[str, set] = {}
        for s in sources_cfg:
            sid = s["id"]
            kws = s.get("keywords", [])
            kw_map[sid] = set([k.lower() for k in kws if isinstance(k, str)])
        kws_ok = True
        for r in per_run_rows:
            sid = r[0]
            mk = r[4]
            if sid not in kw_map:
                kws_ok = False
                break
            if mk.lower() not in kw_map[sid]:
                kws_ok = False
                break
        if kws_ok:
            scores["results_keywords_valid"] = 1.0

    # results rows html_sha256 matches raw file content
    if per_run_header == expected_header and common_date:
        # Compute per-source hash
        hash_map: Dict[str, Optional[str]] = {}
        for sid in source_ids:
            p = _list_raw_files_for_source(workspace, sid).get(common_date)
            if p and p.exists():
                hash_map[sid] = _sha256_file(p)
            else:
                hash_map[sid] = None
        hashes_ok = True
        any_rows = False
        for r in per_run_rows:
            any_rows = True
            sid = r[0]
            row_hash = r[7]
            if sid not in hash_map or hash_map[sid] is None:
                hashes_ok = False
                break
            if row_hash != hash_map[sid]:
                hashes_ok = False
                break
        # If no rows (header only), we accept as OK (cannot verify)
        if hashes_ok:
            scores["results_hash_matches"] = 1.0

    # all.csv should contain per-run rows (subset check)
    if per_run_header == expected_header and all_header == expected_header:
        # Build set of tuples from all_rows
        all_set = set(tuple(r) for r in all_rows)
        subset_ok = True
        for r in per_run_rows:
            if tuple(r) not in all_set:
                subset_ok = False
                break
        if subset_ok:
            scores["results_all_contains_per_run"] = 1.0

    # status.json validations and consistency
    status_path = workspace / "data" / "status" / "status.json"
    status = _read_json(status_path)
    if isinstance(status, dict):
        # basic structure and types
        required_keys = ["schedule_spec", "last_run_iso", "last_exit_code", "stderr_tail", "stats"]
        basic_ok = all(k in status for k in required_keys)
        if basic_ok:
            sched_ok = isinstance(status["schedule_spec"], str)
            iso_ok = isinstance(status["last_run_iso"], str) and _is_iso8601(status["last_run_iso"])
            exit_ok = isinstance(status["last_exit_code"], int)
            stderr_ok = status["stderr_tail"] is None or isinstance(status["stderr_tail"], str)
            stats = status["stats"]
            stats_ok = isinstance(stats, dict) and all(
                k in stats for k in ["pages_fetched", "matches_found", "bytes_total"]
            )
            if sched_ok and iso_ok and exit_ok and stderr_ok and stats_ok:
                scores["status_json_valid"] = 1.0

        # schedule matches config
        if isinstance(status.get("schedule_spec"), str) and status.get("schedule_spec") == schedule_spec:
            scores["status_schedule_matches_config"] = 1.0

        # stats consistency with observed artifacts
        if common_date and per_run_header == expected_header:
            # pages_fetched == number of raw files for common_date
            count_raw = 0
            bytes_total = 0
            for sid in source_ids:
                p = _list_raw_files_for_source(workspace, sid).get(common_date)
                if p and p.exists():
                    count_raw += 1
                    try:
                        bytes_total += p.stat().st_size
                    except Exception:
                        pass
            matches_found = len(per_run_rows)
            st = status.get("stats", {})
            if (
                isinstance(st.get("pages_fetched"), int)
                and isinstance(st.get("matches_found"), int)
                and isinstance(st.get("bytes_total"), int)
                and st["pages_fetched"] == count_raw
                and st["matches_found"] == matches_found
                and st["bytes_total"] == bytes_total
            ):
                scores["status_stats_consistent"] = 1.0

    # cron spec file validation
    cron_path = workspace / "schedule" / "cron.txt"
    cron_valid = False
    if cron_path.exists():
        cron_lines = (_read_text(cron_path) or "").splitlines()
        nonempty = [ln for ln in cron_lines if ln.strip() != ""]
        if len(nonempty) == 1:
            line = nonempty[0].strip()
            # line should start with schedule_spec and include script path and redirects
            # Accept any whitespace between fields
            starts_with_sched = line.startswith(schedule_spec + " ")
            script_included = "scripts/fetch_official_pages" in line
            out_redirect = re.search(r'>\s*logs/cron\.out', line) is not None
            err_redirect = re.search(r'2>\s*logs/cron\.err', line) is not None
            if starts_with_sched and script_included and out_redirect and err_redirect:
                cron_valid = True
    if cron_valid:
        scores["cron_txt_valid"] = 1.0

    # cron logs existence
    logs_dir = workspace / "logs"
    cron_out = logs_dir / "cron.out"
    cron_err = logs_dir / "cron.err"
    logs_ok = False
    try:
        if logs_dir.exists() and cron_out.exists() and cron_err.exists():
            logs_ok = True
    except Exception:
        logs_ok = False
    # Accept either presence of both cron logs or at least a last_run.log file
    last_run_log = logs_dir / "last_run.log"
    if last_run_log.exists():
        logs_ok = True
    if logs_ok:
        scores["cron_logs_exist"] = 1.0

    # Date consistency across artifacts
    # Check that per-run results filename date matches raw files common_date and status last_run_iso date part
    date_consistent = False
    if common_date and per_run_csv and per_run_csv.exists() and isinstance(status, dict):
        status_iso = status.get("last_run_iso")
        status_date = _date_from_iso(status_iso) if isinstance(status_iso, str) else None
        if status_date == common_date:
            date_consistent = True
    if date_consistent:
        scores["date_consistency_across_artifacts"] = 1.0

    # fetched_at_iso validity per row (and matches date)
    fetched_iso_ok = False
    if per_run_header == expected_header and common_date:
        # If there are rows, validate each fetched_at_iso is ISO and date equals common_date
        # If there are zero rows, we still consider this check as passed (header-only acceptable)
        per_row_ok = True
        for r in per_run_rows:
            ts = r[1]
            if not _is_iso8601(ts):
                per_row_ok = False
                break
            d = _date_from_iso(ts)
            if d != common_date:
                per_row_ok = False
                break
        if per_row_ok:
            fetched_iso_ok = True
    if fetched_iso_ok:
        scores["fetched_at_iso_valid"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()