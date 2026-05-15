import json
import csv
import re
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _parse_monitor_yaml(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    cfg: Dict[str, Any] = {}

    # run_id
    m = re.search(r'^\s*run_id:\s*["\']([^"\']+)["\']', text, flags=re.MULTILINE)
    if not m:
        m = re.search(r'^\s*run_id:\s*([^\n#]+)', text, flags=re.MULTILINE)
    cfg["run_id"] = m.group(1).strip() if m else None

    # trip_date
    m = re.search(r'^\s*trip_date:\s*["\']([^"\']+)["\']', text, flags=re.MULTILINE)
    if not m:
        m = re.search(r'^\s*trip_date:\s*([^\n#]+)', text, flags=re.MULTILINE)
    cfg["trip_date"] = m.group(1).strip() if m else None

    # source names
    source_names = re.findall(r'^\s*-\s*name:\s*["\']([^"\']+)["\']', text, flags=re.MULTILINE)
    cfg["source_names"] = source_names

    # detection_keywords include list
    include_list: List[str] = []
    inc_inline = re.search(r'detection_keywords:\s*(?:#.*)?\n(?:.*\n)*?include:\s*\[(.*?)\]', text, flags=re.DOTALL)
    if inc_inline:
        include_list = [s.strip() for s in re.findall(r'["\']([^"\']+)["\']', inc_inline.group(1))]
    else:
        inc_ml = re.search(r'detection_keywords:\s*(?:#.*)?\n(?:.*\n)*?include:\s*\n((?:\s*-\s*.*\n)+)', text, flags=re.DOTALL)
        if inc_ml:
            include_list = [s.strip().strip('"\'' ) for s in re.findall(r'^\s*-\s*(.+)$', inc_ml.group(1), flags=re.MULTILINE)]
    cfg["detection_keywords_include"] = include_list

    # reliability fields
    def _int_field(key: str) -> Optional[int]:
        mm = re.search(r'^\s*' + re.escape(key) + r'\s*:\s*([0-9]+)', text, flags=re.MULTILINE)
        return int(mm.group(1)) if mm else None

    cfg["reliability"] = {
        "timeout_seconds": _int_field("timeout_seconds"),
        "max_retries": _int_field("max_retries"),
        "retry_backoff_seconds": _int_field("retry_backoff_seconds"),
    }

    # output_paths
    def _str_field(pattern: str) -> Optional[str]:
        mm = re.search(pattern, text, flags=re.DOTALL)
        return mm.group(1).strip() if mm else None

    raw_dir = _str_field(r'raw_dir:\s*["\']([^"\']+)["\']')
    processed_json = _str_field(r'processed_incidents_json:\s*["\']([^"\']+)["\']')
    processed_csv = _str_field(r'processed_summary_csv:\s*["\']([^"\']+)["\']')
    cfg["output_paths"] = {
        "raw_dir": raw_dir,
        "processed_incidents_json": processed_json,
        "processed_summary_csv": processed_csv,
    }

    # logging path
    log_path = _str_field(r'logging:\s*(?:#.*)?\s*(?:level:\s*.*\n)?(?:.*\n)*?path:\s*["\']([^"\']+)["\']')
    cfg["logging_path"] = log_path

    return cfg


def _is_absolute_url(s: str) -> bool:
    return isinstance(s, str) and (s.startswith("http://") or s.startswith("https://"))


def _parse_iso_utc(s: str) -> bool:
    # Accept YYYY-MM-DDTHH:MM:SS(.micro)?Z
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$', s))


def _timestamp_in_filename_ok(name: str) -> bool:
    # Expect ..._{YYYYMMDDTHHMMSSZ}.html
    m = re.search(r'_(\d{8}T\d{6}Z)\.html$', name)
    return m is not None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "structured_json_top_level": 0.0,
        "retrieved_at_utc_format": 0.0,
        "json_sources_coverage": 0.0,
        "per_source_fields_valid": 0.0,
        "snapshot_files_exist": 0.0,
        "snapshot_filename_convention": 0.0,
        "advisory_count_matches_items": 0.0,
        "items_fields_valid": 0.0,
        "items_detected_keywords_from_config": 0.0,
        "attractions_crosscheck_consistency": 0.0,
        "summary_csv_matches_json": 0.0,
        "logs_have_entries_per_source": 0.0,
        "script_placeholder_removed": 0.0,
        "script_applies_reliability_settings": 0.0,
        "no_hardcoded_direct_urls_in_script": 0.0,
        "config_bilingual_detection_keywords": 0.0,
        "config_reliability_fields_present": 0.0,
    }

    # Load config
    cfg_path = workspace / "input" / "monitor.yaml"
    cfg = _parse_monitor_yaml(cfg_path) if cfg_path.exists() else None

    # Paths from config
    processed_json_path: Optional[Path] = None
    processed_csv_path: Optional[Path] = None
    raw_dir_path: Optional[Path] = None
    log_path: Optional[Path] = None
    source_names: List[str] = []
    if cfg:
        if cfg.get("output_paths"):
            if cfg["output_paths"].get("processed_incidents_json"):
                processed_json_path = workspace / cfg["output_paths"]["processed_incidents_json"]
            if cfg["output_paths"].get("processed_summary_csv"):
                processed_csv_path = workspace / cfg["output_paths"]["processed_summary_csv"]
            if cfg["output_paths"].get("raw_dir"):
                raw_dir_path = workspace / cfg["output_paths"]["raw_dir"]
        if cfg.get("logging_path"):
            log_path = workspace / cfg["logging_path"]
        if isinstance(cfg.get("source_names"), list):
            source_names = cfg["source_names"]

    # Load incidents JSON
    incidents = _load_json(processed_json_path) if processed_json_path and processed_json_path.exists() else None

    # structured_json_top_level
    if incidents and isinstance(incidents, dict) and cfg:
        top_ok = (
            incidents.get("run_id") == cfg.get("run_id") and
            incidents.get("trip_date") == cfg.get("trip_date") and
            isinstance(incidents.get("retrieved_at_utc"), str) and
            isinstance(incidents.get("sources"), list)
        )
        scores["structured_json_top_level"] = 1.0 if top_ok else 0.0

    # retrieved_at_utc_format
    if incidents and isinstance(incidents.get("retrieved_at_utc"), str):
        scores["retrieved_at_utc_format"] = 1.0 if _parse_iso_utc(incidents["retrieved_at_utc"]) else 0.0

    # json_sources_coverage
    all_sources_present = False
    if incidents and isinstance(incidents.get("sources"), list) and source_names:
        names_in_json = [s.get("source_name") for s in incidents["sources"] if isinstance(s, dict)]
        all_sources_present = (len(names_in_json) == len(source_names) and set(names_in_json) == set(source_names))
        scores["json_sources_coverage"] = 1.0 if all_sources_present else 0.0

    # per_source_fields_valid
    if incidents and isinstance(incidents.get("sources"), list):
        per_ok = True
        for s in incidents["sources"]:
            if not isinstance(s, dict):
                per_ok = False
                break
            if not isinstance(s.get("source_name"), str):
                per_ok = False
                break
            if s.get("fetch_status") not in ("ok", "failed"):
                per_ok = False
                break
            if not isinstance(s.get("raw_snapshot_path"), str) or len(s.get("raw_snapshot_path")) == 0:
                per_ok = False
                break
            if not isinstance(s.get("advisory_count"), int) or s.get("advisory_count") < 0:
                per_ok = False
                break
            if not isinstance(s.get("items"), list):
                per_ok = False
                break
        scores["per_source_fields_valid"] = 1.0 if per_ok else 0.0

    # snapshot_files_exist and filename convention
    if incidents and isinstance(incidents.get("sources"), list) and raw_dir_path:
        exists_ok = True
        namefmt_ok = True
        for s in incidents["sources"]:
            raw_path_str = s.get("raw_snapshot_path")
            if not isinstance(raw_path_str, str):
                exists_ok = False
                namefmt_ok = False
                break
            snap_path = workspace / raw_path_str
            if not snap_path.exists() or not snap_path.is_file():
                exists_ok = False
                namefmt_ok = False
                break
            try:
                snap_resolved = snap_path.resolve()
                raw_resolved = raw_dir_path.resolve()
                if raw_resolved not in snap_resolved.parents and snap_resolved != raw_resolved:
                    exists_ok = False
                    namefmt_ok = False
                    break
            except Exception:
                exists_ok = False
                namefmt_ok = False
                break
            if snap_path.suffix.lower() != ".html":
                exists_ok = False
                namefmt_ok = False
                break
            try:
                if snap_path.stat().st_size <= 0:
                    exists_ok = False
                    namefmt_ok = False
                    break
            except Exception:
                exists_ok = False
                namefmt_ok = False
                break
            # filename convention: {source_name}_{YYYYMMDDTHHMMSSZ}.html
            base = snap_path.name
            src_name = s.get("source_name")
            if not isinstance(src_name, str) or not base.startswith(src_name + "_") or not _timestamp_in_filename_ok(base):
                namefmt_ok = False
        scores["snapshot_files_exist"] = 1.0 if exists_ok else 0.0
        scores["snapshot_filename_convention"] = 1.0 if namefmt_ok else 0.0

    # advisory_count_matches_items
    if incidents and isinstance(incidents.get("sources"), list):
        ok = True
        for s in incidents["sources"]:
            items = s.get("items")
            count = s.get("advisory_count")
            if not isinstance(items, list) or not isinstance(count, int):
                ok = False
                break
            if count != len(items):
                ok = False
                break
        scores["advisory_count_matches_items"] = 1.0 if ok else 0.0

    # items_fields_valid
    if incidents and isinstance(incidents.get("sources"), list):
        ok = True
        for s in incidents["sources"]:
            items = s.get("items", [])
            if not isinstance(items, list):
                ok = False
                break
            for it in items:
                if not isinstance(it, dict):
                    ok = False
                    break
                # title
                if "title" not in it or not isinstance(it["title"], str):
                    ok = False
                    break
                # detected_keywords
                if "detected_keywords" not in it or not isinstance(it["detected_keywords"], list):
                    ok = False
                    break
                # links
                if "links" not in it or not isinstance(it["links"], list):
                    ok = False
                    break
                for lk in it["links"]:
                    if isinstance(lk, str) and len(lk) > 0 and not _is_absolute_url(lk):
                        ok = False
                        break
                if not ok:
                    break
                # impact_on_attractions
                if "impact_on_attractions" not in it or not isinstance(it["impact_on_attractions"], list):
                    ok = False
                    break
            if not ok:
                break
        scores["items_fields_valid"] = 1.0 if ok else 0.0

    # items_detected_keywords_from_config (only if there is at least one item)
    if incidents and isinstance(incidents.get("sources"), list) and cfg and isinstance(cfg.get("detection_keywords_include"), list):
        include_set = set(cfg["detection_keywords_include"])
        any_items = any(isinstance(s.get("items"), list) and len(s.get("items")) > 0 for s in incidents["sources"])
        if any_items:
            all_ok = True
            for s in incidents["sources"]:
                items = s.get("items", [])
                for it in items:
                    dks = it.get("detected_keywords", [])
                    if not isinstance(dks, list):
                        all_ok = False
                        break
                    for dk in dks:
                        if not isinstance(dk, str) or dk not in include_set:
                            all_ok = False
                            break
                    if not all_ok:
                        break
                if not all_ok:
                    break
            scores["items_detected_keywords_from_config"] = 1.0 if all_ok else 0.0
        else:
            scores["items_detected_keywords_from_config"] = 0.0

    # attractions_crosscheck_consistency
    attractions_path = workspace / "input" / "attractions.csv"
    attractions_rows = _load_csv_rows(attractions_path) if attractions_path.exists() else None
    if incidents and isinstance(incidents.get("sources"), list) and attractions_rows is not None:
        valid_names = {r.get("attraction", "") for r in attractions_rows if isinstance(r, dict)}
        valid_names = {n for n in valid_names if isinstance(n, str) and len(n) > 0}
        ok = True
        for s in incidents["sources"]:
            for it in s.get("items", []):
                impacts = it.get("impact_on_attractions", [])
                if not isinstance(impacts, list):
                    ok = False
                    break
                for name in impacts:
                    if not isinstance(name, str) or name not in valid_names:
                        ok = False
                        break
                if not ok:
                    break
            if not ok:
                break
        scores["attractions_crosscheck_consistency"] = 1.0 if ok else 0.0

    # summary_csv_matches_json
    if processed_csv_path and processed_csv_path.exists() and incidents and isinstance(incidents.get("sources"), list):
        try:
            with processed_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            header = [h.strip() for h in rows[0]] if rows else []
            header_ok = header == ["source_name", "fetch_status", "advisory_count"]
            json_map = {}
            for s in incidents["sources"]:
                name = s.get("source_name")
                status = s.get("fetch_status")
                count = s.get("advisory_count")
                if isinstance(name, str):
                    json_map[name] = (status, count)
            data_ok = False
            if header_ok:
                data_rows = rows[1:]
                if len(data_rows) == len(json_map) and len(json_map) > 0:
                    data_ok = True
                    seen = set()
                    for r in data_rows:
                        if len(r) < 3:
                            data_ok = False
                            break
                        name = r[0].strip()
                        status = r[1].strip()
                        try:
                            count = int(r[2].strip())
                        except Exception:
                            data_ok = False
                            break
                        if name not in json_map:
                            data_ok = False
                            break
                        js_status, js_count = json_map[name]
                        if status != js_status or count != js_count:
                            data_ok = False
                            break
                        seen.add(name)
                    if set(seen) != set(json_map.keys()):
                        data_ok = False
            scores["summary_csv_matches_json"] = 1.0 if (header_ok and data_ok) else 0.0
        except Exception:
            scores["summary_csv_matches_json"] = 0.0

    # logs_have_entries_per_source
    if log_path and log_path.exists() and source_names:
        log_text = _read_text(log_path) or ""
        log_lines = log_text.splitlines()
        start_keywords = ["start", "begin", "fetch", "fetching", "started", "beginning"]
        status_keywords = ["ok", "success", "succeeded", "completed", "done", "failed", "fail", "error"]
        all_ok = True
        for name in source_names:
            lines_with_name = [ln for ln in log_lines if name in ln]
            if not lines_with_name:
                all_ok = False
                break
            has_start = any(any(kw in ln.lower() for kw in start_keywords) for ln in lines_with_name)
            has_status = any(any(kw in ln.lower() for kw in status_keywords) for ln in lines_with_name)
            if not (has_start and has_status):
                all_ok = False
                break
        scores["logs_have_entries_per_source"] = 1.0 if all_ok else 0.0

    # Script static checks (gated to avoid awarding points on scaffold placeholders)
    fetcher_path = workspace / "scripts" / "fetcher.py"
    fetcher_text = _read_text(fetcher_path) if fetcher_path.exists() else None

    # Determine if core outputs appear to be implemented
    core_ok = (
        scores["structured_json_top_level"] == 1.0 and
        scores["json_sources_coverage"] == 1.0 and
        scores["per_source_fields_valid"] == 1.0 and
        scores["snapshot_files_exist"] == 1.0
    )

    if fetcher_text is not None:
        # script_placeholder_removed: ensure no TODO placeholder or placeholder print
        placeholder_markers = ["TODO:", "Wrote placeholder outputs"]
        scores["script_placeholder_removed"] = 1.0 if (core_ok and not any(p in fetcher_text for p in placeholder_markers)) else 0.0

        # script_applies_reliability_settings: look for use of cfg['reliability'] fields and retry/backoff usage
        has_rel_keys = all(k in fetcher_text for k in ["cfg['reliability']", "timeout_seconds", "max_retries", "retry_backoff_seconds"])
        has_retry_logic = ("for" in fetcher_text or "while" in fetcher_text) and ("retry" in fetcher_text.lower() or "retries" in fetcher_text.lower())
        has_backoff = ("sleep(" in fetcher_text or "time.sleep" in fetcher_text or "backoff" in fetcher_text.lower())
        has_timeout_usage = ("timeout=" in fetcher_text) or ("setdefaulttimeout" in fetcher_text)
        scores["script_applies_reliability_settings"] = 1.0 if (core_ok and has_rel_keys and has_retry_logic and has_backoff and has_timeout_usage) else 0.0

        # no_hardcoded_direct_urls_in_script: only after core outputs exist
        hardcoded_url = re.search(r"https?://[^\s\'\"]+", fetcher_text) is not None
        scores["no_hardcoded_direct_urls_in_script"] = 1.0 if (core_ok and not hardcoded_url) else 0.0

    # Config checks (gated on core outputs)
    if cfg and core_ok:
        include = cfg.get("detection_keywords_include") or []
        has_english = any(re.search(r"[A-Za-z]", term or "") for term in include)
        has_cjk = any(re.search(r"[\u4e00-\u9fff]", term or "") for term in include)
        scores["config_bilingual_detection_keywords"] = 1.0 if (has_english and has_cjk) else 0.0

        rel = cfg.get("reliability") or {}
        try:
            rel_ok = (
                isinstance(rel.get("timeout_seconds"), int) and rel["timeout_seconds"] > 0 and
                isinstance(rel.get("max_retries"), int) and rel["max_retries"] >= 0 and
                isinstance(rel.get("retry_backoff_seconds"), int) and rel["retry_backoff_seconds"] >= 0
            )
        except Exception:
            rel_ok = False
        scores["config_reliability_fields_present"] = 1.0 if rel_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()