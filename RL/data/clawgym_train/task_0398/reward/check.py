import json
import csv
import re
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _strip_bom(s: str) -> str:
    if s and s[0] == "\ufeff":
        return s[1:]
    return s


def parse_csv_dicts_skip_comments(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    # Remove leading BOM and skip comment/blank lines before header
    lines = [_strip_bom(line.rstrip("\n")) for line in text.splitlines()]
    filtered = []
    header_found = False
    for line in lines:
        if not header_found:
            if not line.strip():
                continue
            if line.lstrip().startswith("#"):
                continue
            # First non-comment line is the header
            filtered.append(line)
            header_found = True
        else:
            filtered.append(line)
    if not header_found:
        return None
    try:
        # Use csv.DictReader on the filtered content
        from io import StringIO
        sio = StringIO("\n".join(filtered))
        reader = csv.DictReader(sio)
        rows = []
        for row in reader:
            # Normalize keys stripping whitespace
            normalized = {}
            for k, v in row.items():
                if k is None:
                    continue
                nk = k.strip()
                normalized[nk] = (v.strip() if isinstance(v, str) else v)
            rows.append(normalized)
        return rows
    except Exception:
        return None


def parse_date_string(s: str) -> Optional[date]:
    if not s:
        return None
    s = s.strip()
    # Try YYYY-MM-DD
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        pass
    # Try YYYY/MM/DD
    try:
        return datetime.strptime(s, "%Y/%m/%d").date()
    except Exception:
        pass
    # Try YYYYMMDD
    try:
        if len(s) == 8 and s.isdigit():
            return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    except Exception:
        pass
    return None


def ensure_float(s: str) -> Optional[float]:
    try:
        if s is None or s == "":
            return None
        val = float(s)
        if val != val:  # NaN check
            return None
        return val
    except Exception:
        return None


def parse_nasa_power_csv_timeseries(path: Path) -> Optional[List[Dict[str, object]]]:
    rows = parse_csv_dicts_skip_comments(path)
    if rows is None:
        return None
    timeseries: List[Dict[str, object]] = []
    for row in rows:
        keys_up = {k.upper(): k for k in row.keys()}
        # Identify columns for date
        d: Optional[date] = None
        if "DATE" in keys_up:
            d = parse_date_string(row[keys_up["DATE"]])
        elif "YYYYMMDD" in keys_up:
            d = parse_date_string(row[keys_up["YYYYMMDD"]])
        elif all(k in keys_up for k in ("YEAR", "MO", "DY")):
            y = row[keys_up["YEAR"]]
            m = row[keys_up["MO"]]
            dy = row[keys_up["DY"]]
            try:
                d = date(int(str(y)), int(str(m)), int(str(dy)))
            except Exception:
                d = None
        elif all(k in keys_up for k in ("YEAR", "MONTH", "DAY")):
            y = row[keys_up["YEAR"]]
            m = row[keys_up["MONTH"]]
            dy = row[keys_up["DAY"]]
            try:
                d = date(int(str(y)), int(str(m)), int(str(dy)))
            except Exception:
                d = None
        if d is None:
            return None
        # Identify temperature columns
        if "T2M_MIN" not in keys_up or "T2M_MAX" not in keys_up:
            return None
        tmin = ensure_float(row[keys_up["T2M_MIN"]])
        tmax = ensure_float(row[keys_up["T2M_MAX"]])
        if tmin is None or tmax is None:
            return None
        timeseries.append({"date": d, "tmin": tmin, "tmax": tmax})
    # Sort by date
    timeseries.sort(key=lambda r: r["date"])
    return timeseries


def filter_by_date_range(ts: List[Dict[str, object]], start: date, end: date) -> List[Dict[str, object]]:
    return [r for r in ts if start <= r["date"] <= end]


def compute_daily_gdd(tmin: float, tmax: float, base: float = 5.0) -> float:
    return max(0.0, ((tmax + tmin) / 2.0) - base)


def compute_summary_metrics(ts: List[Dict[str, object]]) -> Optional[Dict[str, float]]:
    if not ts:
        return None
    tmins = [r["tmin"] for r in ts]
    tmaxs = [r["tmax"] for r in ts]
    if not tmins or not tmaxs:
        return None
    total_gdd = sum(compute_daily_gdd(r["tmin"], r["tmax"]) for r in ts)
    avg_tmin = sum(tmins) / len(tmins)
    avg_tmax = sum(tmaxs) / len(tmaxs)
    frost_days = sum(1 for r in ts if r["tmin"] <= 0.0)
    return {
        "total_gdd": total_gdd,
        "avg_tmin": avg_tmin,
        "avg_tmax": avg_tmax,
        "frost_days": float(frost_days),
    }


def compute_sowing_window(ts: List[Dict[str, object]]) -> Optional[Tuple[date, date, float]]:
    if not ts:
        return None
    # earliest date with 5 consecutive days TMIN > 0
    n = len(ts)
    good = [r["tmin"] > 0.0 for r in ts]
    start_idx = None
    for i in range(0, n - 4):
        if all(good[i + j] for j in range(5)):
            start_idx = i
            break
    if start_idx is None:
        return None
    # first occurrence after start_date of 3 consecutive days TMIN <= 0
    freeze_idx = None
    for j in range(start_idx + 1, n - 2):
        if (ts[j]["tmin"] <= 0.0) and (ts[j + 1]["tmin"] <= 0.0) and (ts[j + 2]["tmin"] <= 0.0):
            freeze_idx = j
            break
    if freeze_idx is None:
        end_idx = n - 1
    else:
        end_idx = max(start_idx, freeze_idx - 1)
    # compute gdd_total within [start_idx, end_idx]
    gdd_total = sum(compute_daily_gdd(ts[k]["tmin"], ts[k]["tmax"]) for k in range(start_idx, end_idx + 1))
    return (ts[start_idx]["date"], ts[end_idx]["date"], gdd_total)


def close_enough(a: float, b: float, tol: float = 0.5) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def extract_section(text: str, title: str) -> Optional[str]:
    if text is None:
        return None
    # Find heading that matches title (case-insensitive)
    pattern = re.compile(r'^\s*#{1,6}\s*(.+?)\s*$', re.MULTILINE)
    matches = list(pattern.finditer(text))
    start = None
    end = None
    for idx, m in enumerate(matches):
        heading = m.group(1).strip().lower()
        if heading == title.strip().lower():
            start = m.end()
            # Find next heading
            if idx + 1 < len(matches):
                end = matches[idx + 1].start()
            else:
                end = len(text)
            break
    if start is None or end is None:
        # Try simple search by title as plain text
        simple_pat = re.compile(r'^\s*' + re.escape(title) + r'\s*$', re.IGNORECASE | re.MULTILINE)
        m2 = simple_pat.search(text)
        if not m2:
            return None
        start = m2.end()
        end = len(text)
    return text[start:end]


def count_bullet_items(section_text: Optional[str]) -> int:
    if not section_text:
        return 0
    count = 0
    for line in section_text.splitlines():
        if re.match(r'^\s*[-*]\s+', line):
            count += 1
        elif re.match(r'^\s*\d+[.)]\s+', line):
            count += 1
        elif re.match(r'^\s*•\s+', line):
            count += 1
    return count


def parse_action_items_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = [h.strip() for h in reader.fieldnames] if reader.fieldnames else []
            if headers is None:
                return None
            # Expect exact columns Owner,Task,Due_date
            if len(headers) < 3:
                return None
            # Map case-insensitively to exact keys
            mapping = {}
            for h in headers:
                hl = h.strip().lower()
                if hl == "owner":
                    mapping["Owner"] = h
                elif hl == "task":
                    mapping["Task"] = h
                elif hl == "due_date":
                    mapping["Due_date"] = h
            if set(mapping.keys()) != {"Owner", "Task", "Due_date"}:
                return None
            rows = []
            for row in reader:
                owner = (row.get(mapping["Owner"]) or "").strip()
                task = (row.get(mapping["Task"]) or "").strip()
                due = (row.get(mapping["Due_date"]) or "").strip()
                rows.append({"Owner": owner, "Task": task, "Due_date": due})
            return rows
    except Exception:
        return None


def parse_iso_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "climate_csv_parsed": 0.0,
        "climate_date_coverage_complete": 0.0,
        "commands_recorded_domain_and_tool": 0.0,
        "commands_includes_params_coords_dates": 0.0,
        "gdd_script_present": 0.0,
        "gdd_summary_metrics_match": 0.0,
        "sowing_window_values_match": 0.0,
        "agenda_sections_and_citation": 0.0,
        "agenda_modules_time_and_count": 0.0,
        "agenda_references_sowing_window": 0.0,
        "meeting_notes_sections_and_values": 0.0,
        "action_items_csv_structure_and_roles": 0.0,
        "action_items_due_dates_within_14_days": 0.0,
        "action_items_match_notes": 0.0,
        "bilingual_note_present": 0.0,
        "crop_focus_in_agenda": 0.0,
    }

    # Paths
    nasa_csv_path = workspace / "downloads" / "nasa_power_daily.csv"
    gdd_script_path = workspace / "tools" / "gdd.py"
    gdd_summary_path = workspace / "output" / "gdd_summary.csv"
    sowing_window_path = workspace / "output" / "sowing_window.json"
    agenda_path = workspace / "output" / "workshop_agenda.md"
    notes_path = workspace / "output" / "meeting_notes.md"
    action_items_csv_path = workspace / "output" / "action_items.csv"
    commands_txt_path = workspace / "output" / "commands.txt"

    # Parse NASA CSV
    ts = None
    if nasa_csv_path.is_file():
        ts = parse_nasa_power_csv_timeseries(nasa_csv_path)
        if ts is not None and len(ts) > 0:
            scores["climate_csv_parsed"] = 1.0

    # Date coverage check
    start_range = date(2022, 3, 1)
    end_range = date(2022, 10, 31)
    ts_range = []
    if ts:
        ts_range = filter_by_date_range(ts, start_range, end_range)
        # Check that every date in range is present
        needed_dates = set(start_range + timedelta(days=i) for i in range((end_range - start_range).days + 1))
        present_dates = set(r["date"] for r in ts_range)
        if needed_dates == present_dates:
            scores["climate_date_coverage_complete"] = 1.0

    # Commands checks
    commands_text = safe_read_text(commands_txt_path)
    if commands_text is not None:
        text_lower = commands_text.lower()
        has_domain = "power.larc.nasa.gov" in text_lower
        has_tool = any(t in text_lower for t in ["curl", "wget", "python"])
        if has_domain and has_tool:
            scores["commands_recorded_domain_and_tool"] = 1.0

        has_params = ("t2m_min" in text_lower and "t2m_max" in text_lower)
        has_coords = ("36.6" in commands_text and "101.8" in commands_text)
        has_dates = ("20220301" in commands_text and "20221031" in commands_text) or ("2022-03-01" in commands_text and "2022-10-31" in commands_text)
        if has_params and has_coords and has_dates:
            scores["commands_includes_params_coords_dates"] = 1.0

    # gdd.py present
    if gdd_script_path.is_file():
        scores["gdd_script_present"] = 1.0

    # Compute expected metrics from data
    computed_metrics = None
    computed_window = None
    if ts_range:
        computed_metrics = compute_summary_metrics(ts_range)
        computed_window = compute_sowing_window(ts_range)

    # Validate gdd_summary.csv
    if gdd_summary_path.is_file() and computed_metrics is not None:
        try:
            with gdd_summary_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                # expect columns metric,value
                fieldnames = [fn.strip().lower() for fn in (reader.fieldnames or [])]
                if "metric" in fieldnames and "value" in fieldnames:
                    reported = {}
                    for row in reader:
                        metric = (row.get("metric") or row.get("Metric") or "").strip()
                        value = (row.get("value") or row.get("Value") or "").strip()
                        if metric:
                            reported[metric] = value
                    needed = ["total_gdd", "avg_tmin", "avg_tmax", "frost_days"]
                    ok = True
                    for m in needed:
                        if m not in reported:
                            ok = False
                            break
                    if ok:
                        # Compare values
                        # frost_days as integer
                        rep_frost = ensure_float(reported["frost_days"])
                        comp_frost = computed_metrics["frost_days"]
                        # Other metrics as floats
                        rep_tg = ensure_float(reported["total_gdd"])
                        rep_atn = ensure_float(reported["avg_tmin"])
                        rep_atx = ensure_float(reported["avg_tmax"])
                        ok = (rep_frost is not None and rep_tg is not None and rep_atn is not None and rep_atx is not None)
                        if ok:
                            if int(round(rep_frost)) != int(round(comp_frost)):
                                ok = False
                            if not close_enough(rep_tg, computed_metrics["total_gdd"], tol=0.5):
                                ok = False
                            if not close_enough(rep_atn, computed_metrics["avg_tmin"], tol=0.05):
                                ok = False
                            if not close_enough(rep_atx, computed_metrics["avg_tmax"], tol=0.05):
                                ok = False
                    if ok:
                        scores["gdd_summary_metrics_match"] = 1.0
        except Exception:
            pass

    # Validate sowing_window.json
    sowing_window_json = None
    if sowing_window_path.is_file():
        sowing_window_json = safe_load_json(sowing_window_path)
    if sowing_window_json is not None and computed_window is not None:
        try:
            rep_start = sowing_window_json.get("start_date")
            rep_end = sowing_window_json.get("end_date")
            rep_gdd_total = sowing_window_json.get("gdd_total")
            if isinstance(rep_start, str) and isinstance(rep_end, str) and rep_gdd_total is not None:
                comp_start_str = computed_window[0].isoformat()
                comp_end_str = computed_window[1].isoformat()
                comp_gdd_total = computed_window[2]
                if rep_start == comp_start_str and rep_end == comp_end_str and close_enough(float(rep_gdd_total), comp_gdd_total, tol=0.5):
                    scores["sowing_window_values_match"] = 1.0
        except Exception:
            pass

    # Agenda checks
    agenda_text = safe_read_text(agenda_path)
    if agenda_text is not None:
        # Sections and citation
        has_objectives = extract_section(agenda_text, "Objectives") is not None
        has_outline = extract_section(agenda_text, "Module Outline") is not None
        has_resources = extract_section(agenda_text, "Resources") is not None
        has_schedule = extract_section(agenda_text, "Schedule") is not None
        citation_exact = "NASA POWER daily T2M_MIN/T2M_MAX for 36.6,101.8; 2022-03-01..2022-10-31" in agenda_text
        crop_focus = ("barley" in agenda_text.lower() and "potato" in agenda_text.lower())
        if has_objectives and has_outline and has_resources and has_schedule and citation_exact:
            scores["agenda_sections_and_citation"] = 1.0
        if crop_focus:
            scores["crop_focus_in_agenda"] = 1.0

        # Module time count
        outline_sec = extract_section(agenda_text, "Module Outline")
        module_minutes = []
        if outline_sec:
            for line in outline_sec.splitlines():
                m = re.search(r'(\d+)\s*(?:min|minutes)\b', line, flags=re.IGNORECASE)
                if m:
                    try:
                        mins = int(m.group(1))
                        module_minutes.append(mins)
                    except Exception:
                        pass
        if 3 <= len(module_minutes) <= 5 and sum(module_minutes) == 120:
            scores["agenda_modules_time_and_count"] = 1.0

        # Schedule references sowing window and field demo tied to start_date
        schedule_sec = extract_section(agenda_text, "Schedule") or ""
        start_ok = False
        end_ok = False
        field_demo_ok = False
        if sowing_window_json:
            sd = sowing_window_json.get("start_date")
            ed = sowing_window_json.get("end_date")
            if isinstance(sd, str) and sd in schedule_sec:
                start_ok = True
            if isinstance(ed, str) and ed in schedule_sec:
                end_ok = True
        field_demo_ok = ("field" in schedule_sec.lower() and ("demo" in schedule_sec.lower() or "demonstration" in schedule_sec.lower()))
        if start_ok and end_ok and field_demo_ok:
            scores["agenda_references_sowing_window"] = 1.0

    # Meeting notes checks
    notes_text = safe_read_text(notes_path)
    if notes_text is not None:
        # Sections presence
        sum_sec = extract_section(notes_text, "Summary")
        dec_sec = extract_section(notes_text, "Decisions")
        act_sec = extract_section(notes_text, "Action items")
        sections_present = (sum_sec is not None and dec_sec is not None and act_sec is not None)
        # Summary has start_date, end_date, gdd_total
        summary_has_values = False
        if sum_sec and sowing_window_json:
            sd = sowing_window_json.get("start_date")
            ed = sowing_window_json.get("end_date")
            gt = sowing_window_json.get("gdd_total")
            sd_ok = isinstance(sd, str) and sd in sum_sec
            ed_ok = isinstance(ed, str) and ed in sum_sec
            gt_ok = False
            if isinstance(gt, (int, float)):
                # Look for any number within 0.5 of gt in the Summary section
                nums = re.findall(r'[-+]?\d+(?:\.\d+)?', sum_sec)
                for num in nums:
                    try:
                        if close_enough(float(num), float(gt), tol=0.5):
                            gt_ok = True
                            break
                    except Exception:
                        pass
            summary_has_values = (sd_ok and ed_ok and gt_ok)
        # Decisions at least 3 items
        decisions_count_ok = (count_bullet_items(dec_sec) >= 3) if dec_sec else False
        if sections_present and summary_has_values and decisions_count_ok:
            scores["meeting_notes_sections_and_values"] = 1.0

        # Bilingual note
        if "mandarin" in notes_text.lower() and "tibetan" in notes_text.lower():
            scores["bilingual_note_present"] = 1.0

    # Action items CSV structure and roles
    allowed_roles = {"Lead farmer", "Village committee", "County extension officer"}
    action_items = parse_action_items_csv(action_items_csv_path) if action_items_csv_path.is_file() else None
    if action_items is not None and len(action_items) >= 5:
        owners_ok = all(item["Owner"] in allowed_roles for item in action_items)
        due_format_ok = all(parse_iso_date(item["Due_date"]) is not None for item in action_items)
        if owners_ok and due_format_ok:
            scores["action_items_csv_structure_and_roles"] = 1.0

    # Action items due date constraint within 14 days after start_date
    if action_items is not None and sowing_window_json is not None:
        sd_str = sowing_window_json.get("start_date")
        sd = parse_iso_date(sd_str) if isinstance(sd_str, str) else None
        if sd is not None:
            limit = sd + timedelta(days=14)
            due_ok = True
            for item in action_items:
                d = parse_iso_date(item["Due_date"])
                if d is None or d > limit:
                    due_ok = False
                    break
            if due_ok and len(action_items) >= 5:
                scores["action_items_due_dates_within_14_days"] = 1.0

    # Action items match notes
    if action_items is not None and notes_text is not None:
        act_sec = extract_section(notes_text, "Action items") or ""
        match_ok = True
        for item in action_items:
            owner = item["Owner"]
            task = item["Task"]
            # Check that both owner and task appear in the Action items section
            if (owner.lower() not in act_sec.lower()) or (task.lower() not in act_sec.lower()):
                match_ok = False
                break
        if match_ok and len(action_items) >= 5:
            scores["action_items_match_notes"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()