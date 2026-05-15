import json
import csv
import sys
import re
from datetime import datetime
from pathlib import Path


def _safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _safe_parse_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({
                    "date": (row.get("date") or "").strip(),
                    "city": (row.get("city") or "").strip(),
                    "title": (row.get("title") or "").strip(),
                    "artist": (row.get("artist") or "").strip(),
                })
            return rows, None
    except Exception as e:
        return None, str(e)


def _parse_iso_date(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _compute_expected_from_inputs(workspace: Path):
    cfg_path = workspace / "input" / "config.json"
    events_path = workspace / "input" / "events.csv"
    cfg, cfg_err = _safe_load_json(cfg_path)
    if cfg is None:
        return None, None, None, None, "config_load_error:" + str(cfg_err)

    rows, rows_err = _safe_parse_csv_dicts(events_path)
    if rows is None:
        return None, None, None, None, "csv_load_error:" + str(rows_err)

    artist = cfg.get("artist")
    timeframe = cfg.get("timeframe") or {}
    start_s = timeframe.get("start")
    end_s = timeframe.get("end")
    start_d = _parse_iso_date(start_s) if isinstance(start_s, str) else None
    end_d = _parse_iso_date(end_s) if isinstance(end_s, str) else None
    if not artist or start_d is None or end_d is None:
        return None, None, None, None, "config_values_invalid"

    filtered = []
    for r in rows:
        d = _parse_iso_date(r.get("date", ""))
        if d is None:
            continue
        if r.get("artist") == artist and start_d <= d <= end_d:
            filtered.append({
                "date": r["date"],
                "city": r["city"],
                "title": r["title"],
                "artist": r["artist"],
            })

    before_dedupe_count = len(filtered)

    if cfg.get("dedupe") is True:
        seen = set()
        deduped = []
        for r in filtered:
            key = (r["date"], r["city"], r["title"], r["artist"])
            if key not in seen:
                seen.add(key)
                deduped.append(r)
    else:
        deduped = list(filtered)

    after_dedupe_count = len(deduped)

    try:
        deduped_sorted = sorted(deduped, key=lambda r: _parse_iso_date(r["date"]))
    except Exception:
        deduped_sorted = deduped

    unique_cities = len({r["city"] for r in deduped_sorted})

    return deduped_sorted, before_dedupe_count, after_dedupe_count, unique_cities, None


def _check_output_json_structure(data, required_artist: str):
    if not isinstance(data, list):
        return False
    for item in data:
        if not isinstance(item, dict):
            return False
        keys = set(item.keys())
        if keys != {"date", "city", "title", "artist"}:
            return False
        if _parse_iso_date(item.get("date", "")) is None:
            return False
        if item.get("artist") != required_artist:
            return False
    return True


def _is_sorted_by_date_ascending(data):
    dates = [_parse_iso_date(item["date"]) for item in data]
    if any(d is None for d in dates):
        return False
    return dates == sorted(dates)


def _extract_metrics_from_md(md_text: str):
    patterns = {
        "total_input_rows": r"total_input_rows\s*:\s*(\d+)",
        "total_filtered_rows_before_dedup": r"total_filtered_rows_before_dedup\s*:\s*(\d+)",
        "total_filtered_rows_after_dedup": r"total_filtered_rows_after_dedup\s*:\s*(\d+)",
        "unique_cities_for_artist": r"unique_cities_for_artist\s*:\s*(\d+)",
    }
    found = {}
    for k, pat in patterns.items():
        m = re.search(pat, md_text, flags=re.IGNORECASE)
        if m:
            try:
                found[k] = int(m.group(1))
            except Exception:
                found[k] = None
        else:
            found[k] = None
    return found


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_all_fields_updated": 0.0,
        "output_json_exists": 0.0,
        "output_json_structure_valid_and_sorted": 0.0,
        "output_json_exact_match_expected": 0.0,
        "summary_has_required_sections": 0.0,
        "summary_metrics_match_expected": 0.0,
        "message_mentions_team_artist_output": 0.0,
        "message_suggests_next_steps": 0.0,
        "code_not_hardcoding_artist": 0.0,
    }

    # Load config and validate all required fields together for stricter gating
    required_artist = "Hahm Eun-Jung"
    cfg_path = workspace / "input" / "config.json"
    cfg, _ = _safe_load_json(cfg_path)
    cfg_valid = False
    if isinstance(cfg, dict):
        tf = cfg.get("timeframe")
        if (
            cfg.get("artist") == required_artist
            and isinstance(tf, dict)
            and tf.get("start") == "2024-01-01"
            and tf.get("end") == "2025-12-31"
            and cfg.get("dedupe") is True
            and cfg.get("output_events_path") == "outputs/upcoming_eunjung.json"
        ):
            cfg_valid = True
            scores["config_all_fields_updated"] = 1.0

    # Check code for absence of hardcoded artist names
    code_path = workspace / "src" / "generate_schedule.py"
    code_text, _ = _safe_read_text(code_path)
    if code_text is not None:
        # Flag if any specific artist strings are hardcoded in the script source
        hardcoded_patterns = [r"Eunjung", r"H\.E\.J", r"Hahm\s+Eun\-Jung", r"Hahm\s+EunJung", r"Hahm\s+Eunjung"]
        if not any(re.search(pat, code_text) for pat in hardcoded_patterns):
            scores["code_not_hardcoding_artist"] = 1.0

    # Compute expected outputs based on current config and events
    expected_list, expected_before, expected_after, expected_unique_cities, exp_err = _compute_expected_from_inputs(workspace)

    # Check outputs JSON existence and content
    out_path = workspace / "outputs" / "upcoming_eunjung.json"
    out_data, _ = _safe_load_json(out_path)
    if out_data is not None:
        scores["output_json_exists"] = 1.0
        # Validate structure and sorting only if config is available
        if isinstance(cfg, dict) and cfg.get("artist"):
            if _check_output_json_structure(out_data, cfg.get("artist")) and _is_sorted_by_date_ascending(out_data):
                scores["output_json_structure_valid_and_sorted"] = 1.0
        # Exact content match against recomputed expectation (only when config is fully valid and expectation computed)
        if cfg_valid and exp_err is None and expected_list is not None:
            try:
                if out_data == expected_list:
                    scores["output_json_exact_match_expected"] = 1.0
            except Exception:
                pass

    # Check summary markdown
    summary_path = workspace / "outputs" / "refactor_summary.md"
    md_text, _ = _safe_read_text(summary_path)
    if md_text is not None:
        sections = ["Overview", "Code Changes", "Config Changes", "Results", "Next Steps"]
        if all(sec.lower() in md_text.lower() for sec in sections):
            scores["summary_has_required_sections"] = 1.0
        # Metrics comparison only if we can compute expectations (cfg + csv ok)
        metrics = _extract_metrics_from_md(md_text)
        csv_rows, _ = _safe_parse_csv_dicts(workspace / "input" / "events.csv")
        exp_total_rows = len(csv_rows) if csv_rows is not None else None
        ok = True
        if exp_total_rows is None or metrics.get("total_input_rows") != exp_total_rows:
            ok = False
        if cfg_valid and exp_err is None:
            if metrics.get("total_filtered_rows_before_dedup") != expected_before:
                ok = False
            if metrics.get("total_filtered_rows_after_dedup") != expected_after:
                ok = False
            if metrics.get("unique_cities_for_artist") != expected_unique_cities:
                ok = False
        else:
            # If we cannot compute expectations reliably, do not award this check
            ok = False
        if ok:
            scores["summary_metrics_match_expected"] = 1.0

    # Check draft message
    msg_path = workspace / "outputs" / "draft_message.txt"
    msg_text, _ = _safe_read_text(msg_path)
    if msg_text is not None:
        mentions_team = "fan club mod team" in msg_text.lower()
        mentions_artist = "Hahm Eun-Jung" in msg_text
        points_to_output = "outputs/upcoming_eunjung.json" in msg_text
        if mentions_team and mentions_artist and points_to_output:
            scores["message_mentions_team_artist_output"] = 1.0
        suggests_next_steps = ("publish" in msg_text.lower()) or ("publishing" in msg_text.lower()) or ("next steps" in msg_text.lower())
        if suggests_next_steps:
            scores["message_suggests_next_steps"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()