import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, date, timedelta
from urllib.parse import urlparse


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # Ensure header exists and rows are dicts
        if reader.fieldnames is None:
            return None
        return rows
    except Exception:
        return None


def _parse_simple_yaml(path: Path):
    # Very simple YAML parser for flat key: value pairs
    text = _read_text(path)
    if text is None:
        return None
    data = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # strip surrounding quotes if present
        if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
            val = val[1:-1]
        data[key] = val
    return data


def _parse_iso_date(s: str):
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def _compute_week_bounds(start: date, end: date):
    # Returns list of (week_start_monday, week_end_sunday) that intersect [start, end]
    weeks = []
    # find Monday of the week containing start
    start_monday = start - timedelta(days=start.weekday())
    ws = start_monday
    while ws <= end:
        we = ws + timedelta(days=6)
        weeks.append((ws, we))
        ws = ws + timedelta(days=7)
    return weeks


def _safe_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default


def _safe_int(x, default=None):
    try:
        return int(float(x))
    except Exception:
        return default


def _mean(values):
    if not values:
        return None
    return sum(values) / len(values)


def _is_acceptable_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        # Accept if .org or .gov anywhere in domain or contains 'worldathletics'
        if ".org" in netloc or ".gov" in netloc or "worldathletics" in netloc:
            return True
        return False
    except Exception:
        return False


def _sentence_split(text: str):
    # Simple sentence split on ., !, ?
    # Keep it simple and deterministic
    parts = re.split(r'(?<=[\.\!\?])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "report_exists_and_schema": 0.0,
        "period_correct": 0.0,
        "athlete_info_correct": 0.0,
        "weekly_load_count_and_bounds": 0.0,
        "weekly_aggregates_correct": 0.0,
        "training_spike_flag_present": 0.0,
        "lab_flags_correct": 0.0,
        "doctor_note_points_valid": 0.0,
        "guideline_downloads_and_sources_valid": 0.0,
        "guideline_snippets_valid": 0.0,
        "report_guideline_sources_consistency": 0.0,
        "email_content_valid": 0.0,
    }

    # Paths
    report_path = workspace / "outputs" / "report" / "hamstring_readiness_report.json"
    snippets_path = workspace / "outputs" / "report" / "guideline_snippets.json"
    downloads_dir = workspace / "outputs" / "downloads"
    sources_path = workspace / "outputs" / "logs" / "sources.json"
    email_path = workspace / "outputs" / "communication" / "email_to_doctor.txt"

    # Load report
    report = _read_json(report_path)

    # Baseline schema check
    schema_ok = False
    if isinstance(report, dict):
        required_top_keys = ["athlete", "period_analyzed", "weekly_load", "flags", "guideline_sources_used"]
        if all(k in report for k in required_top_keys):
            athlete_ok = isinstance(report.get("athlete"), dict) and "name" in report["athlete"] and "event" in report["athlete"]
            period_ok = isinstance(report.get("period_analyzed"), dict) and "start" in report["period_analyzed"] and "end" in report["period_analyzed"]
            weekly_ok = isinstance(report.get("weekly_load"), list)
            flags_ok = isinstance(report.get("flags"), dict) and all(k in report["flags"] for k in ["training", "labs", "doctor_note_key_points"])
            sources_ok = isinstance(report.get("guideline_sources_used"), list)
            schema_ok = athlete_ok and period_ok and weekly_ok and flags_ok and sources_ok
    if schema_ok:
        scores["report_exists_and_schema"] = 1.0

    # Load athlete profile for comparison
    athlete_yaml = _parse_simple_yaml(workspace / "input" / "athlete_profile.yaml")
    # Check athlete info
    if schema_ok and isinstance(athlete_yaml, dict):
        expected_name = athlete_yaml.get("name")
        expected_event = athlete_yaml.get("event")
        r_athlete = report.get("athlete", {})
        if r_athlete.get("name") == expected_name and r_athlete.get("event") == expected_event:
            scores["athlete_info_correct"] = 1.0

    # Check period
    expected_start = "2026-04-01"
    expected_end = "2026-04-14"
    if schema_ok:
        pa = report["period_analyzed"]
        if pa.get("start") == expected_start and pa.get("end") == expected_end:
            scores["period_correct"] = 1.0

    # Compute expected weekly aggregates from training_log.csv
    training_rows = _read_csv_dicts(workspace / "input" / "training_log.csv")
    weeks_expected = None
    weekly_expected = None
    if training_rows is not None:
        start_d = _parse_iso_date(expected_start)
        end_d = _parse_iso_date(expected_end)
        weeks_expected = _compute_week_bounds(start_d, end_d)
        # Aggregate
        agg = {}
        for ws, we in weeks_expected:
            agg[(ws, we)] = {"sprints": 0, "jumps": 0, "rpes": []}
        for row in training_rows:
            d = _parse_iso_date(str(row.get("date", "")).strip())
            if d is None:
                continue
            if d < start_d or d > end_d:
                continue
            # find week bucket
            # week start = Monday of that date
            ws = d - timedelta(days=d.weekday())
            we = ws + timedelta(days=6)
            if (ws, we) not in agg:
                # In case the week falls outside due to bounds calculation differences, skip
                continue
            s_m = _safe_int(row.get("sprints_meters"), 0) or 0
            j_c = _safe_int(row.get("jumps_count"), 0) or 0
            rpe = _safe_float(row.get("RPE"), None)
            agg[(ws, we)]["sprints"] += s_m
            agg[(ws, we)]["jumps"] += j_c
            if rpe is not None:
                agg[(ws, we)]["rpes"].append(rpe)
        weekly_expected = []
        for ws, we in weeks_expected:
            r = agg[(ws, we)]
            mean_rpe = _mean(r["rpes"])
            weekly_expected.append({
                "week_start": ws.isoformat(),
                "week_end": we.isoformat(),
                "sprints_meters": r["sprints"],
                "jumps_count": r["jumps"],
                "mean_RPE": mean_rpe if mean_rpe is not None else None
            })

    # Check weekly_load count and bounds
    weekly_load = report.get("weekly_load") if schema_ok else None
    if weekly_expected is not None and isinstance(weekly_load, list):
        # Must match number of overlapping weeks and correct boundaries in order
        try:
            bounds_match = True
            if len(weekly_load) != len(weekly_expected):
                bounds_match = False
            else:
                for i, wexp in enumerate(weekly_expected):
                    wrep = weekly_load[i]
                    if not (wrep.get("week_start") == wexp["week_start"] and wrep.get("week_end") == wexp["week_end"]):
                        bounds_match = False
                        break
            if bounds_match:
                scores["weekly_load_count_and_bounds"] = 1.0
        except Exception:
            pass

    # Check weekly aggregates
    if weekly_expected is not None and isinstance(weekly_load, list) and len(weekly_load) == len(weekly_expected):
        try:
            agg_ok = True
            for i, wexp in enumerate(weekly_expected):
                wrep = weekly_load[i]
                sm = _safe_float(wrep.get("sprints_meters"), None)
                jc = _safe_float(wrep.get("jumps_count"), None)
                mr = _safe_float(wrep.get("mean_RPE"), None)
                if sm is None or jc is None or mr is None:
                    agg_ok = False
                    break
                # strict integer totals for sprints and jumps
                if int(round(sm)) != int(wexp["sprints_meters"]) or int(round(jc)) != int(wexp["jumps_count"]):
                    agg_ok = False
                    break
                # mean within 0.01
                if wexp["mean_RPE"] is None:
                    agg_ok = False
                    break
                if abs(mr - wexp["mean_RPE"]) > 1e-2:
                    agg_ok = False
                    break
            if agg_ok:
                scores["weekly_aggregates_correct"] = 1.0
        except Exception:
            pass

    # Training spike flag presence
    # Compute spikes from expected weekly sprints meters
    if weekly_expected is not None and isinstance(weekly_load, list) and "flags" in (report or {}):
        training_flags = report["flags"].get("training", [])
        spike_exists = False
        prev = None
        for w in weekly_expected:
            curr = w["sprints_meters"]
            if prev is not None and prev > 0:
                inc = (curr - prev) / prev
                if inc >= 0.30:
                    spike_exists = True
                    break
            prev = curr
        if spike_exists and isinstance(training_flags, list) and len(training_flags) >= 1:
            scores["training_spike_flag_present"] = 1.0
        elif (not spike_exists) and (isinstance(training_flags, list) and len(training_flags) == 0):
            scores["training_spike_flag_present"] = 1.0

    # Lab flags correctness: require CK, Ferritin, Vitamin D flagged
    if schema_ok:
        labs_flags = report["flags"].get("labs", [])
        if isinstance(labs_flags, list) and len(labs_flags) >= 3:
            labs_text = " ".join([str(x) for x in labs_flags]).lower()
            ck_ok = ("ck" in labs_text) or ("creatine" in labs_text)
            ferr_ok = "ferritin" in labs_text
            vitd_ok = "vitamin d" in labs_text or "25-oh" in labs_text
            if ck_ok and ferr_ok and vitd_ok:
                scores["lab_flags_correct"] = 1.0

    # Doctor note key points validation
    if schema_ok:
        points = report["flags"].get("doctor_note_key_points")
        if isinstance(points, list) and 2 <= len(points) <= 5:
            combined = " ".join([str(p).lower() for p in points])
            has_sprint_or_95 = ("sprint" in combined) or ("95" in combined)
            has_criteria_related = ("criteria" in combined) or ("strength" in combined) or ("hop" in combined) or ("tenderness" in combined)
            if has_sprint_or_95 and has_criteria_related:
                scores["doctor_note_points_valid"] = 1.0

    # Guideline downloads and sources validation
    downloads_ok = False
    downloaded_files = []
    if downloads_dir.exists() and downloads_dir.is_dir():
        for p in downloads_dir.iterdir():
            if p.is_file() and p.name.startswith("guideline_"):
                downloaded_files.append(p.name)
    # Ensure at least guideline_1.* and guideline_2.* exist
    has_g1 = any(fn.startswith("guideline_1.") for fn in downloaded_files)
    has_g2 = any(fn.startswith("guideline_2.") for fn in downloaded_files)
    sources = _read_json(sources_path)
    sources_valid = False
    if has_g1 and has_g2 and isinstance(sources, list):
        # Build map filename->entry
        entries_by_filename = {}
        valid_entries = True
        for entry in sources:
            if not isinstance(entry, dict):
                valid_entries = False
                break
            for key in ["filename", "title", "publisher", "year", "url"]:
                if key not in entry:
                    valid_entries = False
                    break
            if not valid_entries:
                break
            fn = str(entry.get("filename"))
            title = str(entry.get("title") or "").strip()
            publisher = str(entry.get("publisher") or "").strip()
            year = entry.get("year")
            url = str(entry.get("url") or "").strip()
            # Non-empty title and publisher
            if not title or not publisher or not url:
                valid_entries = False
                break
            # Year best-effort: should be a 4-digit number in plausible range
            try:
                year_int = int(str(year))
                if not (1800 <= year_int <= 2100):
                    valid_entries = False
                    break
            except Exception:
                valid_entries = False
                break
            # URL domain acceptable
            if not _is_acceptable_url(url):
                valid_entries = False
                break
            entries_by_filename[fn] = entry
        # Ensure entries for at least guideline_1.* and guideline_2.* exist
        if valid_entries:
            g1_names = [fn for fn in downloaded_files if fn.startswith("guideline_1.")]
            g2_names = [fn for fn in downloaded_files if fn.startswith("guideline_2.")]
            if g1_names and g2_names:
                if g1_names[0] in entries_by_filename and g2_names[0] in entries_by_filename:
                    sources_valid = True
    if has_g1 and has_g2 and sources_valid:
        downloads_ok = True
    if downloads_ok:
        scores["guideline_downloads_and_sources_valid"] = 1.0

    # Guideline snippets validation
    snippets_ok = False
    snippets_json = _read_json(snippets_path)
    if isinstance(snippets_json, dict) and downloads_ok:
        # Must contain entries for each downloaded file that starts with guideline_
        keys = set(snippets_json.keys())
        have_all = True
        for fn in downloaded_files:
            # only enforce for guideline_* files
            if not fn.startswith("guideline_"):
                continue
            if fn not in keys:
                have_all = False
                break
            entry = snippets_json.get(fn)
            if not isinstance(entry, dict):
                have_all = False
                break
            snippets = entry.get("snippets")
            no_matches = entry.get("no_matches")
            if not isinstance(snippets, list) or not isinstance(no_matches, bool):
                have_all = False
                break
            if len(snippets) == 0 and no_matches is not True:
                have_all = False
                break
            if len(snippets) > 0 and no_matches is not False:
                have_all = False
                break
            # Validate snippet content contains required keywords
            for sn in snippets:
                s = str(sn).lower()
                if "hamstring" not in s:
                    have_all = False
                    break
                if not any(k in s for k in ["rehabilitation", "return", "criteria"]):
                    have_all = False
                    break
            if not have_all:
                break
        if have_all:
            snippets_ok = True
    if snippets_ok:
        scores["guideline_snippets_valid"] = 1.0

    # Cross-reference guideline_sources_used in report
    if schema_ok and downloads_ok and snippets_ok:
        used = report.get("guideline_sources_used")
        if isinstance(used, list) and len(used) >= 2:
            used_set = set([str(x) for x in used])
            # Must be subset of downloaded guideline files
            subset_ok = all(u in downloaded_files for u in used_set)
            # Must also be present in sources.json and snippets_json keys
            sources_fns = set([str(ent.get("filename")) for ent in (sources or []) if isinstance(ent, dict) and "filename" in ent])
            snippets_fns = set(snippets_json.keys())
            in_sources = all(u in sources_fns for u in used_set)
            in_snippets = all(u in snippets_fns for u in used_set)
            if subset_ok and in_sources and in_snippets:
                scores["report_guideline_sources_consistency"] = 1.0

    # Email content validation
    email_text = _read_text(email_path)
    if isinstance(email_text, str):
        # Word count 120–180
        words = re.findall(r"\b\w[\w'-]*\b", email_text)
        wc = len(words)
        # Paragraphs: 2–4 short paragraphs separated by blank lines
        # Split on blank lines
        para_candidates = re.split(r'\n\s*\n', email_text.strip())
        paras = [p for p in para_candidates if p.strip()]
        para_ok = 2 <= len(paras) <= 4
        # Contains analyzed period dates
        period_ok = ("2026-04-01" in email_text) and ("2026-04-14" in email_text)
        # Mentions attachments by filename
        attach_ok = ("hamstring_readiness_report.json" in email_text) and ("guideline_snippets.json" in email_text)
        # Mentions training or lab flags
        flags_mentioned = any(k in email_text.lower() for k in ["ck", "creatine", "ferritin", "vitamin d", "training load", "spike", "increase"])
        if 120 <= wc <= 180 and para_ok and period_ok and attach_ok and flags_mentioned:
            scores["email_content_valid"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()