import json
import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path


def _safe_load_json(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_load_csv_dicts(path: Path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return None


def _safe_read_text_lines(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f]
    except Exception:
        return None


def _parse_iso_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None


def _inventory_by_id(workspace: Path):
    inv_path = workspace / "input" / "inventory.csv"
    rows = _safe_load_csv_dicts(inv_path)
    if not rows:
        return None, None
    inv_list = []
    for r in rows:
        try:
            rid = str(int(str(r.get("id", "")).strip()))
        except Exception:
            return None, None
        tags = [t.strip() for t in (r.get("tags", "") or "").split(";") if t.strip()]
        keywords = [k.strip() for k in (r.get("keywords", "") or "").split(";") if k.strip()]
        inv_list.append({
            "id": rid,
            "title": r.get("title", ""),
            "tags": tags,
            "audience": r.get("audience", ""),
            "keywords": keywords,
        })
    try:
        inv_list.sort(key=lambda x: int(x["id"]))
    except Exception:
        return None, None
    by_id = {r["id"]: r for r in inv_list}
    return by_id, inv_list


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        # Config checks (gated on successful outputs)
        "config_publish_days_present_and_correct": 0.0,
        "config_start_date_correct": 0.0,
        "config_weeks_correct": 0.0,
        "config_cadence_per_week_correct": 0.0,
        "config_channels_correct": 0.0,
        "config_keywords_fallback_correct": 0.0,
        "config_other_keys_unchanged": 0.0,
        # Output existence/structure
        "outputs_json_exists_and_valid": 0.0,
        "outputs_csv_exists_and_valid": 0.0,
        "entries_count_json_24": 0.0,
        "entries_count_csv_24": 0.0,
        "schema_fields_csv_exact": 0.0,
        "schema_fields_json_exact": 0.0,
        # Cross-file consistency
        "json_csv_consistency": 0.0,
        # Scheduling and sequencing
        "schedule_dates_match_expected": 0.0,
        "publish_dates_on_mon_thu": 0.0,
        "channels_alternate_sequence": 0.0,
        "week_numbers_correct": 0.0,
        "two_items_per_week": 0.0,
        # Content correctness vs inventory/config
        "primary_tag_from_inventory": 0.0,
        "keywords_handling_correct": 0.0,
        "title_and_audience_match_inventory": 0.0,
        "topic_rotation_order_correct": 0.0,
        # Run log
        "run_log_contains_error_and_success": 0.0,
    }

    # Paths
    cfg_path = workspace / "config" / "config.json"
    out_dir = workspace / "output"
    json_path = out_dir / "content_calendar.json"
    csv_path = out_dir / "content_calendar.csv"
    runlog_path = out_dir / "run_log.txt"

    # Load config
    cfg = _safe_load_json(cfg_path)
    expected_cfg_values = {
        "start_date": "2024-09-02",
        "weeks": 12,
        "cadence_per_week": 2,
        "channels": ["blog", "newsletter"],
        "keywords_fallback": ["Imamate", "Caucasus", "19th century"],
    }

    # Load outputs
    items_json = _safe_load_json(json_path)
    json_valid = False
    json_count_ok = False
    if isinstance(items_json, list):
        required_fields = ["week", "publish_date", "channel", "topic_id", "title", "primary_tag", "audience", "keywords"]
        json_valid_check = True
        for it in items_json:
            if not isinstance(it, dict):
                json_valid_check = False
                break
            if set(it.keys()) != set(required_fields):
                json_valid_check = False
                break
            if not isinstance(it.get("keywords"), list):
                json_valid_check = False
                break
        if json_valid_check:
            json_valid = True
            scores["outputs_json_exists_and_valid"] = 1.0
            scores["schema_fields_json_exact"] = 1.0
            if len(items_json) == 24:
                json_count_ok = True
                scores["entries_count_json_24"] = 1.0
    else:
        items_json = None

    items_csv = _safe_load_csv_dicts(csv_path)
    csv_valid = False
    csv_count_ok = False
    if isinstance(items_csv, list):
        required_fields_csv = ["week", "publish_date", "channel", "topic_id", "title", "primary_tag", "audience", "keywords"]
        csv_header_ok = False
        try:
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
            if header == required_fields_csv:
                csv_header_ok = True
        except Exception:
            csv_header_ok = False
        if csv_header_ok:
            kw_ok = True
            for r in items_csv:
                if "keywords" not in r or not isinstance(r["keywords"], str):
                    kw_ok = False
                    break
            if kw_ok:
                csv_valid = True
                scores["outputs_csv_exists_and_valid"] = 1.0
                scores["schema_fields_csv_exact"] = 1.0
            if len(items_csv) == 24:
                csv_count_ok = True
                scores["entries_count_csv_24"] = 1.0
    else:
        items_csv = None

    # Determine pipeline success gate: both files valid and each has 24 items
    pipeline_success = json_valid and csv_valid and json_count_ok and csv_count_ok

    # Gate config checks on pipeline success to avoid awarding points in scaffold state
    if pipeline_success and isinstance(cfg, dict):
        if isinstance(cfg.get("publish_days"), list) and cfg.get("publish_days") == [0, 3]:
            scores["config_publish_days_present_and_correct"] = 1.0
        if cfg.get("start_date") == expected_cfg_values["start_date"]:
            scores["config_start_date_correct"] = 1.0
        if cfg.get("weeks") == expected_cfg_values["weeks"]:
            scores["config_weeks_correct"] = 1.0
        if cfg.get("cadence_per_week") == expected_cfg_values["cadence_per_week"]:
            scores["config_cadence_per_week_correct"] = 1.0
        if cfg.get("channels") == expected_cfg_values["channels"]:
            scores["config_channels_correct"] = 1.0
        if cfg.get("keywords_fallback") == expected_cfg_values["keywords_fallback"]:
            scores["config_keywords_fallback_correct"] = 1.0
        other_ok = True
        for k, v in expected_cfg_values.items():
            if cfg.get(k) != v:
                other_ok = False
                break
        if other_ok:
            scores["config_other_keys_unchanged"] = 1.0

    # JSON/CSV consistency check
    if items_json is not None and items_csv is not None and len(items_json) == len(items_csv) and len(items_json) > 0:
        consistent = True
        for j, c in zip(items_json, items_csv):
            try:
                if int(c.get("week", "")) != int(j.get("week", 0)):
                    consistent = False
                    break
            except Exception:
                consistent = False
                break
            if c.get("publish_date") != j.get("publish_date"):
                consistent = False
                break
            for k in ["channel", "topic_id", "title", "primary_tag", "audience"]:
                if str(c.get(k, "")) != str(j.get(k, "")):
                    consistent = False
                    break
            if not consistent:
                break
            csv_kw = [s for s in str(c.get("keywords", "")).split(";") if s != ""]
            json_kw = j.get("keywords", [])
            if csv_kw != json_kw:
                consistent = False
                break
        if consistent:
            scores["json_csv_consistency"] = 1.0

    # Expected dates and schedule checks
    if items_json:
        expected_dates = []
        start = _parse_iso_date("2024-09-02")
        if start:
            for w in range(12):
                monday = start + timedelta(days=w * 7)
                thurs = monday + timedelta(days=3)
                expected_dates.append(monday.isoformat())
                expected_dates.append(thurs.isoformat())
            actual_dates = [it.get("publish_date") for it in items_json]
            if actual_dates == expected_dates:
                scores["schedule_dates_match_expected"] = 1.0
            dow_ok = True
            if actual_dates:
                if actual_dates[0] != "2024-09-02":
                    dow_ok = False
                else:
                    for ds in actual_dates:
                        d = _parse_iso_date(ds)
                        if d is None or d.weekday() not in (0, 3):
                            dow_ok = False
                            break
            if dow_ok:
                scores["publish_dates_on_mon_thu"] = 1.0

        expected_channels = []
        pattern = ["blog", "newsletter"]
        for i in range(len(items_json)):
            expected_channels.append(pattern[i % 2])
        actual_channels = [it.get("channel") for it in items_json]
        if actual_channels == expected_channels:
            scores["channels_alternate_sequence"] = 1.0

        week_ok = True
        start_date = _parse_iso_date("2024-09-02")
        if start_date is None:
            week_ok = False
        else:
            for it in items_json:
                d = _parse_iso_date(it.get("publish_date", ""))
                if d is None:
                    week_ok = False
                    break
                expected_week = ((d - start_date).days // 7) + 1
                try:
                    if int(it.get("week")) != expected_week:
                        week_ok = False
                        break
                except Exception:
                    week_ok = False
                    break
        if week_ok:
            scores["week_numbers_correct"] = 1.0

        week_counts = {}
        all_weeks_ok = True
        for it in items_json:
            try:
                wnum = int(it.get("week"))
            except Exception:
                all_weeks_ok = False
                break
            week_counts[wnum] = week_counts.get(wnum, 0) + 1
        if all_weeks_ok and len(week_counts) == 12 and all(week_counts.get(w, 0) == 2 for w in range(1, 13)):
            scores["two_items_per_week"] = 1.0

    # Inventory-based content checks
    inv_by_id, inv_list = _inventory_by_id(workspace)
    if items_json and inv_by_id and inv_list:
        pt_ok = True
        kw_ok = True
        ta_ok = True
        rotation_ok = True

        expected_ids_seq = [r["id"] for r in inv_list]
        cfg_kf = []
        if isinstance(cfg, dict) and isinstance(cfg.get("keywords_fallback"), list):
            cfg_kf = list(cfg.get("keywords_fallback"))

        for idx, it in enumerate(items_json):
            tid = str(it.get("topic_id", ""))
            inv = inv_by_id.get(tid)
            if not inv:
                pt_ok = False
                kw_ok = False
                ta_ok = False
                rotation_ok = False
                break
            primary_tag = inv["tags"][0] if inv["tags"] else ""
            if it.get("primary_tag") != primary_tag:
                pt_ok = False
            if inv["keywords"]:
                if it.get("keywords") != inv["keywords"]:
                    kw_ok = False
            else:
                expected_kw = cfg_kf + ([primary_tag] if primary_tag else [])
                if it.get("keywords") != expected_kw:
                    kw_ok = False
            if it.get("title") != inv["title"] or it.get("audience") != inv["audience"]:
                ta_ok = False
            expected_tid = expected_ids_seq[idx % len(expected_ids_seq)]
            if tid != expected_tid:
                rotation_ok = False

        if pt_ok:
            scores["primary_tag_from_inventory"] = 1.0
        if kw_ok:
            scores["keywords_handling_correct"] = 1.0
        if ta_ok:
            scores["title_and_audience_match_inventory"] = 1.0
        if rotation_ok:
            scores["topic_rotation_order_correct"] = 1.0

    # Run log checks
    run_lines = _safe_read_text_lines(runlog_path)
    if run_lines is not None:
        has_error = False
        has_success = False
        for line in run_lines:
            if line.startswith("ERROR:") and ("Missing required config keys:" in line) and ("publish_days" in line):
                has_error = True
            if line.strip() == "Wrote output/content_calendar.csv and output/content_calendar.json":
                has_success = True
        if has_error and has_success:
            scores["run_log_contains_error_and_success"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()