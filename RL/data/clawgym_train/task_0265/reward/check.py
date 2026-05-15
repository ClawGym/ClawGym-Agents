import csv
import json
import re
import sys
from pathlib import Path


def _read_text_safe(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json_safe(p: Path):
    try:
        text = p.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _parse_csv_dicts(p: Path):
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_yaml_value(text: str, key: str):
    # Simple regex to capture scalar values like key: value or key: "value"
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(.+?)\s*$", re.MULTILINE)
    m = pattern.search(text)
    if not m:
        return None
    val = m.group(1).strip()
    val = _strip_quotes(val)
    return val


def _parse_yaml_int(text: str, key: str):
    val = _parse_yaml_value(text, key)
    if val is None:
        return None
    try:
        return int(val)
    except Exception:
        return None


def _parse_yaml_list(text: str, key: str):
    # Parse lists of the form:
    # key:
    #   - item1
    #   - "item2"
    lines = text.splitlines()
    items = []
    start_idx = None
    base_indent = None
    for i, line in enumerate(lines):
        if re.match(rf"^\s*{re.escape(key)}\s*:\s*$", line):
            start_idx = i
            base_indent = len(re.match(r"^(\s*)", line).group(1))
            break
    if start_idx is None:
        return None
    for j in range(start_idx + 1, len(lines)):
        ln = lines[j]
        # Stop if indentation decreases to base or less (new key)
        indent = len(re.match(r"^(\s*)", ln).group(1))
        if indent <= base_indent:
            break
        m = re.match(r"^\s*-\s*(.+?)\s*$", ln)
        if m:
            val = _strip_quotes(m.group(1).strip())
            items.append(val)
    return items


def _parse_preferences_yaml(p: Path) -> dict:
    prefs_text = _read_text_safe(p)
    prefs = {}
    if not prefs_text:
        return prefs
    prefs["run_weekday"] = _parse_yaml_value(prefs_text, "run_weekday")
    prefs["run_time"] = _parse_yaml_value(prefs_text, "run_time")
    prefs["max_items"] = _parse_yaml_int(prefs_text, "max_items")
    prefs["min_duration_sec"] = _parse_yaml_int(prefs_text, "min_duration_sec")
    prefs["max_duration_sec"] = _parse_yaml_int(prefs_text, "max_duration_sec")
    prefs["keywords"] = _parse_yaml_list(prefs_text, "keywords") or []
    prefs["license_allowlist"] = _parse_yaml_list(prefs_text, "license_allowlist") or []
    out_dir = _parse_yaml_value(prefs_text, "output_dir")
    prefs["output_dir"] = out_dir if out_dir else "out/audio"
    return prefs


def _parse_schools_csv(p: Path):
    schools_set = set()
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "school" not in reader.fieldnames or "aliases" not in reader.fieldnames:
                return set()
            for row in reader:
                school = (row.get("school") or "").strip()
                if school:
                    schools_set.add(school)
                aliases = (row.get("aliases") or "").strip()
                if aliases:
                    for alias in aliases.split(";"):
                        alias_s = alias.strip()
                        if alias_s:
                            schools_set.add(alias_s)
        return schools_set
    except Exception:
        return set()


def _cron_get_fields(line: str):
    # Return first five cron fields or None
    parts = line.strip().split()
    if len(parts) < 5:
        return None
    return parts[0:5]


def _weekday_matches(field: str, run_weekday: str) -> bool:
    if not field or not run_weekday:
        return False
    field_l = field.strip().lower()
    day_l = run_weekday.strip().lower()
    day_map_full = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
    day_map_abbr = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
    try:
        day_index = day_map_full.index(day_l)
    except ValueError:
        # unknown day name
        return False
    acceptable_numeric = set()
    # Cron day-of-week: 0-7 where 0 or 7 is Sunday
    # For Monday (index 1), acceptable is '1'
    if day_index == 0:
        acceptable_numeric.update({"0", "7"})
    else:
        acceptable_numeric.add(str(day_index))
    if field_l in acceptable_numeric:
        return True
    # Accept three-letter abbreviations or full day (case-insensitive)
    if field_l == day_map_abbr[day_index] or field_l == day_map_full[day_index]:
        return True
    return False


def _time_matches(min_field: str, hour_field: str, run_time: str) -> bool:
    if not run_time or ":" not in run_time:
        return False
    try:
        hh_str, mm_str = run_time.split(":", 1)
        hh = int(hh_str)
        mm = int(mm_str)
    except Exception:
        return False
    # Accept leading zeros differences: compare integers
    try:
        cron_min = int(min_field)
        cron_hour = int(hour_field)
    except Exception:
        return False
    return (cron_min == mm) and (cron_hour == hh)


def _has_out_log_redirect(line: str) -> bool:
    # Look for > or >> followed by a path starting with out/
    tokens = line.strip().split()
    for i, tok in enumerate(tokens):
        if tok in (">", ">>"):
            if i + 1 < len(tokens):
                nxt = tokens[i + 1]
                if nxt.startswith("out/"):
                    return True
    # Also handle forms like >>out/log.txt (no space), though uncommon
    m = re.search(r"(>>?|2>>?)\s*(out/[^ \t]+)", line)
    if m:
        return True
    return False


def _safe_float(s):
    try:
        return float(s)
    except Exception:
        return None


def _safe_int(s):
    try:
        # floats encoded as strings like "123.0" are invalid for int here
        if isinstance(s, int):
            return s
        if isinstance(s, float):
            return int(s)
        st = str(s).strip()
        if re.match(r"^-?\d+$", st):
            return int(st)
        return None
    except Exception:
        return None


def _all_same(values):
    vals = list(values)
    if not vals:
        return True
    first = vals[0]
    for v in vals[1:]:
        if v != first:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "cron_snippet_present": 0.0,
        "cron_invokes_runner": 0.0,
        "cron_schedule_matches_preferences": 0.0,
        "cron_redirects_to_out_log": 0.0,
        "playlist_csv_structure": 0.0,
        "playlist_json_structure": 0.0,
        "csv_json_count_match": 0.0,
        "csv_json_row_equality": 0.0,
        "max_items_respected": 0.0,
        "license_allowlist_compliance": 0.0,
        "duration_within_bounds": 0.0,
        "no_duplicate_source_identifier": 0.0,
        "ranking_and_rank_sequence": 0.0,
        "matched_fields_validity": 0.0,
        "run_date_consistency_json": 0.0,
        "run_date_folder_exists": 0.0,
        "audio_files_present_for_selected": 0.0,
    }

    # Parse inputs
    prefs_path = workspace / "input" / "preferences.yaml"
    prefs = _parse_preferences_yaml(prefs_path)
    schools_path = workspace / "input" / "schools.csv"
    allowed_school_terms = _parse_schools_csv(schools_path)

    # 1) Script existence
    script_path = workspace / "scripts" / "fetch_playlist.py"
    try:
        if script_path.exists() and script_path.is_file() and script_path.stat().st_size > 0:
            scores["script_exists"] = 1.0
    except Exception:
        pass

    # 2) Cron checks
    cron_path = workspace / "out" / "cron.txt"
    if cron_path.exists():
        try:
            cron_text = _read_text_safe(cron_path)
            # Get non-empty non-comment lines
            lines = [ln for ln in cron_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
            if len(lines) == 1:
                scores["cron_snippet_present"] = 1.0
                cron_line = lines[0].strip()
                # invokes runner
                if ("python3" in cron_line) and ("scripts/fetch_playlist.py" in cron_line):
                    scores["cron_invokes_runner"] = 1.0
                # redirect to out log
                if _has_out_log_redirect(cron_line):
                    scores["cron_redirects_to_out_log"] = 1.0
                # schedule matches preferences
                fields = _cron_get_fields(cron_line)
                run_time = prefs.get("run_time")
                run_weekday = prefs.get("run_weekday")
                if fields and run_time and run_weekday:
                    minute, hour, dom, mon, dow = fields
                    if dom == "*" and mon == "*" and _time_matches(minute, hour, run_time) and _weekday_matches(dow, run_weekday):
                        scores["cron_schedule_matches_preferences"] = 1.0
        except Exception:
            pass

    # 3) Playlist outputs checks
    csv_path = workspace / "out" / "playlist.csv"
    json_path = workspace / "out" / "playlist.json"
    expected_header = [
        "source",
        "identifier",
        "title",
        "duration_sec",
        "file_size_bytes",
        "license",
        "download_url",
        "matched_keyword",
        "matched_school",
        "rank",
    ]

    header, rows = _parse_csv_dicts(csv_path)
    if header is not None and rows is not None:
        # Exact header match
        if header == expected_header:
            scores["playlist_csv_structure"] = 1.0

    json_data = _load_json_safe(json_path)
    json_array = None
    if isinstance(json_data, list):
        json_array = json_data
        # Each element should be dict with required fields (+ run_date)
        ok = True
        for item in json_array:
            if not isinstance(item, dict):
                ok = False
                break
            for k in expected_header:
                if k not in item:
                    ok = False
                    break
            if "run_date" not in item:
                ok = False
                break
        if ok:
            scores["playlist_json_structure"] = 1.0

    # 4) Cross-file consistency and constraints
    if rows is not None and json_array is not None:
        if len(rows) == len(json_array):
            scores["csv_json_count_match"] = 1.0

        # Compare each row to corresponding JSON object
        row_eq_ok = True
        run_dates = []
        for i in range(min(len(rows), len(json_array))):
            r = rows[i]
            j = json_array[i]
            # Compare fields
            # String fields
            for key in ["source", "identifier", "title", "license", "download_url", "matched_keyword", "matched_school"]:
                rv = (r.get(key) or "").strip()
                jv = j.get(key, "")
                if isinstance(jv, str):
                    jv = jv.strip()
                else:
                    # Convert non-string to string for comparison
                    jv = str(jv).strip()
                if rv != jv:
                    row_eq_ok = False
                    break
            if not row_eq_ok:
                break
            # Numeric fields
            for key in ["duration_sec", "file_size_bytes", "rank"]:
                rv = r.get(key)
                jv = j.get(key)
                rv_f = _safe_float(rv)
                jv_f = _safe_float(jv)
                if rv_f is None or jv_f is None:
                    row_eq_ok = False
                    break
                # Exact match for integers (file_size_bytes, rank), tolerance for duration
                if key in ("file_size_bytes", "rank"):
                    if int(rv_f) != int(jv_f):
                        row_eq_ok = False
                        break
                else:
                    if abs(rv_f - jv_f) > 1e-6:
                        row_eq_ok = False
                        break
            if not row_eq_ok:
                break
            # run_date presence
            run_date_val = j.get("run_date")
            if not isinstance(run_date_val, str):
                row_eq_ok = False
                break
            run_dates.append(run_date_val)
        if row_eq_ok and len(rows) == len(json_array):
            scores["csv_json_row_equality"] = 1.0

        # Run date consistency and format
        rd_ok = True
        if json_array:
            # run_dates collected only when row_eq_ok; if not, derive separately
            if not run_dates:
                for item in json_array:
                    rd = item.get("run_date")
                    if not isinstance(rd, str):
                        rd_ok = False
                        break
                    run_dates.append(rd)
            if rd_ok:
                # All same and match YYYY-MM-DD
                if _all_same(run_dates) and re.match(r"^\d{4}-\d{2}-\d{2}$", run_dates[0]):
                    scores["run_date_consistency_json"] = 1.0
        else:
            # Empty array is acceptable, but we can't verify run_date
            pass

        # Max items respected
        max_items = prefs.get("max_items")
        if isinstance(max_items, int):
            if len(rows) <= max_items:
                scores["max_items_respected"] = 1.0

        # License allowlist compliance
        allowlist = set(prefs.get("license_allowlist", []) or [])
        if allowlist:
            ll_ok = True
            for r in rows:
                lic = (r.get("license") or "").strip()
                if lic not in allowlist:
                    ll_ok = False
                    break
            if ll_ok:
                scores["license_allowlist_compliance"] = 1.0

        # Duration within bounds
        min_d = prefs.get("min_duration_sec")
        max_d = prefs.get("max_duration_sec")
        if isinstance(min_d, int) and isinstance(max_d, int):
            d_ok = True
            for r in rows:
                d = _safe_float(r.get("duration_sec"))
                if d is None or not (min_d <= d <= max_d):
                    d_ok = False
                    break
            if d_ok:
                scores["duration_within_bounds"] = 1.0

        # No duplicate (source, identifier)
        seen = set()
        dup = False
        for r in rows:
            key = ((r.get("source") or "").strip(), (r.get("identifier") or "").strip())
            if key in seen:
                dup = True
                break
            seen.add(key)
        if not dup:
            scores["no_duplicate_source_identifier"] = 1.0

        # Ranking and rank sequence: duration desc, then file_size_bytes desc; rank 1..N
        rank_ok = True
        # Extract tuples
        try:
            actual = []
            for r in rows:
                d = _safe_float(r.get("duration_sec"))
                sz = _safe_float(r.get("file_size_bytes"))
                rk = _safe_int(r.get("rank"))
                if d is None or sz is None or rk is None:
                    rank_ok = False
                    break
                actual.append((d, sz, rk))
            if rank_ok:
                # Check rank sequence
                n = len(actual)
                if [rk for (_, _, rk) in actual] != list(range(1, n + 1)):
                    rank_ok = False
                else:
                    # Check sorting
                    # Expected sorted by d desc, then sz desc
                    expected_sorted = sorted([(d, sz) for (d, sz, _) in actual], key=lambda t: (-t[0], -t[1]))
                    actual_pairs = [(d, sz) for (d, sz, _) in actual]
                    if actual_pairs != expected_sorted:
                        rank_ok = False
            if rank_ok:
                scores["ranking_and_rank_sequence"] = 1.0
        except Exception:
            pass

        # Matched fields validity
        keywords = set(prefs.get("keywords", []) or [])
        matched_ok = True
        for r in rows:
            mk = (r.get("matched_keyword") or "").strip()
            ms = (r.get("matched_school") or "").strip()
            if mk and mk not in keywords:
                matched_ok = False
                break
            if ms and ms not in allowed_school_terms:
                matched_ok = False
                break
        if matched_ok:
            scores["matched_fields_validity"] = 1.0

        # Run date folder exists and audio files presence
        run_date_value = None
        if json_array and isinstance(json_array, list) and json_array:
            rd = json_array[0].get("run_date")
            if isinstance(rd, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", rd):
                run_date_value = rd
        base_output_dir = prefs.get("output_dir") or "out/audio"
        if run_date_value:
            out_dir = workspace / base_output_dir / run_date_value
            try:
                if out_dir.exists() and out_dir.is_dir():
                    scores["run_date_folder_exists"] = 1.0
                    # Count files (not directories)
                    files = [p for p in out_dir.iterdir() if p.is_file()]
                    if len(files) >= len(rows):
                        scores["audio_files_present_for_selected"] = 1.0
            except Exception:
                pass
        else:
            # If zero items selected, run_date might be absent; still allow folder check to remain 0
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()