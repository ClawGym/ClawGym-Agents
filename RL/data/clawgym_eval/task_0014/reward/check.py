import json
import csv
import re
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_jsonl(path: Path) -> Optional[List[dict]]:
    rows = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
        return rows
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[dict]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _float_or_none(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


def _close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _parse_markdown_journals(journal_dir: Path) -> Tuple[Dict[str, dict], int]:
    """
    Returns (data_by_date, count_days)
    data_by_date: date -> { 'headache': float, 'dizziness': float, 'fatigue': float, 'diary_screen_time_hours': float }
    """
    data: Dict[str, dict] = {}
    count_days = 0
    if not journal_dir.exists():
        return data, 0
    for md_file in sorted(journal_dir.glob("*.md")):
        text = _safe_read_text(md_file)
        if text is None:
            continue
        date = md_file.stem
        headache = None
        dizziness = None
        fatigue = None
        screen_time = None

        head_m = re.search(r'Headache:\s*([0-9]+(?:\.[0-9]+)?)/10', text, flags=re.IGNORECASE)
        if head_m:
            try:
                headache = float(head_m.group(1))
            except Exception:
                headache = None
        dizzy_m = re.search(r'Dizziness:\s*([0-9]+(?:\.[0-9]+)?)/10', text, flags=re.IGNORECASE)
        if dizzy_m:
            try:
                dizziness = float(dizzy_m.group(1))
            except Exception:
                dizziness = None
        fatigue_m = re.search(r'Fatigue:\s*([0-9]+(?:\.[0-9]+)?)/10', text, flags=re.IGNORECASE)
        if fatigue_m:
            try:
                fatigue = float(fatigue_m.group(1))
            except Exception:
                fatigue = None
        screen_m = re.search(r'Screen time:\s*([0-9]+(?:\.[0-9]+)?)\s*h', text, flags=re.IGNORECASE)
        if screen_m:
            try:
                screen_time = float(screen_m.group(1))
            except Exception:
                screen_time = None

        if date:
            fields = {}
            if headache is not None:
                fields["headache"] = headache
            if dizziness is not None:
                fields["dizziness"] = dizziness
            if fatigue is not None:
                fields["fatigue"] = fatigue
            if screen_time is not None:
                fields["diary_screen_time_hours"] = screen_time
            data.setdefault(date, {}).update(fields)
            count_days += 1
    return data, count_days


def _parse_wearable_csv(csv_path: Path) -> Tuple[Dict[str, dict], int]:
    data: Dict[str, dict] = {}
    rows = _safe_read_csv_dicts(csv_path)
    if rows is None:
        return data, 0
    for r in rows:
        date = r.get("date")
        if not date:
            continue
        sleep = _float_or_none(r.get("sleep_hours"))
        steps_val = r.get("steps")
        steps = None
        try:
            if steps_val is not None and steps_val != "":
                steps = float(steps_val)
        except Exception:
            steps = None
        fields = {}
        if sleep is not None:
            fields["sleep_hours"] = sleep
        if steps is not None:
            fields["steps"] = steps
        data.setdefault(date, {}).update(fields)
    return data, len(rows)


def _parse_checkins_jsonl(jsonl_path: Path) -> Tuple[Dict[str, dict], int]:
    data: Dict[str, dict] = {}
    rows = _safe_read_jsonl(jsonl_path)
    if rows is None:
        return data, 0
    for r in rows:
        date = r.get("date")
        if not date:
            continue
        pcs_overall = r.get("pcs_overall")
        st = r.get("screen_time_hours")
        fields = {}
        try:
            if pcs_overall is not None:
                fields["pcs_overall"] = float(pcs_overall)
        except Exception:
            pass
        try:
            if st is not None:
                fields["checkin_screen_time_hours"] = float(st)
        except Exception:
            pass
        data.setdefault(date, {}).update(fields)
    return data, len(rows)


def _pearson_corr(xs: List[float], ys: List[float]) -> Optional[float]:
    if len(xs) != len(ys):
        return None
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def _moving_average(series_dates: List[str], series_values: List[Optional[float]], window: int) -> List[Tuple[str, float]]:
    result = []
    for i in range(len(series_values)):
        if i + 1 < window:
            continue
        window_vals = series_values[i - window + 1 : i + 1]
        if any(v is None for v in window_vals):
            continue
        avg = sum(window_vals) / window  # type: ignore
        result.append((series_dates[i], avg))
    return result


def _rolling_mean(series: List[Optional[float]], end_index: int, window: int) -> Optional[float]:
    start = end_index - window + 1
    if start < 0:
        return None
    vals = series[start : end_index + 1]
    if len(vals) != window:
        return None
    if any(v is None for v in vals):
        return None
    return sum(vals) / window  # type: ignore


def _compute_expected_from_inputs(workspace: Path):
    md_data, md_count = _parse_markdown_journals(workspace / "input" / "symptom_journal")
    wearable_data, wearable_count = _parse_wearable_csv(workspace / "input" / "wearable" / "metrics.csv")
    checkins_data, checkins_count = _parse_checkins_jsonl(workspace / "input" / "checkins.jsonl")

    union_dates = sorted(set(md_data.keys()) | set(wearable_data.keys()) | set(checkins_data.keys()))
    combined_expected = {}
    for d in union_dates:
        row = {
            "date": d,
            "headache": None,
            "dizziness": None,
            "fatigue": None,
            "pcs_overall": None,
            "diary_screen_time_hours": None,
            "checkin_screen_time_hours": None,
            "sleep_hours": None,
            "steps": None,
        }
        if d in md_data:
            if "headache" in md_data[d]:
                row["headache"] = md_data[d]["headache"]
            if "dizziness" in md_data[d]:
                row["dizziness"] = md_data[d]["dizziness"]
            if "fatigue" in md_data[d]:
                row["fatigue"] = md_data[d]["fatigue"]
            if "diary_screen_time_hours" in md_data[d]:
                row["diary_screen_time_hours"] = md_data[d]["diary_screen_time_hours"]
        if d in checkins_data:
            if "pcs_overall" in checkins_data[d]:
                row["pcs_overall"] = checkins_data[d]["pcs_overall"]
            if "checkin_screen_time_hours" in checkins_data[d]:
                row["checkin_screen_time_hours"] = checkins_data[d]["checkin_screen_time_hours"]
        if d in wearable_data:
            if "sleep_hours" in wearable_data[d]:
                row["sleep_hours"] = wearable_data[d]["sleep_hours"]
            if "steps" in wearable_data[d]:
                row["steps"] = wearable_data[d]["steps"]
        combined_expected[d] = row

    headache_series = [combined_expected[d]["headache"] for d in union_dates]
    dizziness_series = [combined_expected[d]["dizziness"] for d in union_dates]
    fatigue_series = [combined_expected[d]["fatigue"] for d in union_dates]

    ma_headache = _moving_average(union_dates, headache_series, 7)
    ma_dizziness = _moving_average(union_dates, dizziness_series, 7)
    ma_fatigue = _moving_average(union_dates, fatigue_series, 7)

    xs = []
    ys = []
    for d in union_dates:
        h = combined_expected[d]["headache"]
        st = combined_expected[d]["diary_screen_time_hours"]
        if h is not None and st is not None:
            xs.append(st)
            ys.append(h)
    corr_st_headache = _pearson_corr(xs, ys)

    xs2 = []
    ys2 = []
    for d in union_dates:
        h = combined_expected[d]["headache"]
        sl = combined_expected[d]["sleep_hours"]
        if h is not None and sl is not None:
            xs2.append(sl)
            ys2.append(h)
    corr_sleep_headache = _pearson_corr(xs2, ys2)

    change_points = []
    for i in range(len(headache_series)):
        cur_mean = _rolling_mean(headache_series, i, 3)
        prev_mean = _rolling_mean(headache_series, i - 3, 3) if cur_mean is not None else None
        if cur_mean is None or prev_mean is None:
            continue
        if cur_mean - prev_mean >= 1.5:
            change_points.append(union_dates[i])

    inconsistencies = []
    for d in union_dates:
        diary_st = combined_expected[d]["diary_screen_time_hours"]
        checkin_st = combined_expected[d]["checkin_screen_time_hours"]
        if diary_st is not None and checkin_st is not None:
            diff = abs(diary_st - checkin_st)
            if diff > 0.5:
                inconsistencies.append({"date": d, "diary_vs_checkin_screen_time_diff": diff})

    expected = {
        "union_dates": union_dates,
        "combined_expected": combined_expected,
        "moving_averages": {
            "headache_7d": ma_headache,
            "dizziness_7d": ma_dizziness,
            "fatigue_7d": ma_fatigue,
        },
        "correlations": {
            "screen_time_vs_headache": corr_st_headache,
            "sleep_vs_headache": corr_sleep_headache,
        },
        "change_points": change_points,
        "inconsistencies": inconsistencies,
        "coverage_counts": {
            "markdown_days": md_count,
            "wearable_days": wearable_count,
            "checkin_days": checkins_count,
        },
    }
    return expected


def _read_combined_csv(path: Path) -> Optional[List[dict]]:
    rows = _safe_read_csv_dicts(path)
    return rows


def _parse_float_cell(cell: str) -> Optional[float]:
    if cell is None:
        return None
    s = str(cell).strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


def _validate_header(row: dict, expected_fields: List[str]) -> bool:
    return list(row.keys()) == expected_fields


def _load_trend_summary(path: Path) -> Optional[dict]:
    return _safe_read_json(path)


def _find_cli_script_under_tools(workspace: Path) -> bool:
    tools_dir = workspace / "tools"
    if not tools_dir.exists():
        return False
    for p in tools_dir.glob("*.py"):
        if p.is_file():
            return True
    return False


def _read_run_command(workspace: Path) -> Optional[str]:
    path = workspace / "output" / "reports" / "run_command.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def _extract_section(text: str, section_title: str, next_titles: List[str]) -> str:
    idx = text.lower().find(section_title.lower())
    if idx == -1:
        return ""
    after = text[idx + len(section_title):]
    next_idx = len(after)
    for t in next_titles:
        j = after.lower().find(t.lower())
        if j != -1 and j < next_idx:
            next_idx = j
    return after[:next_idx]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "cli_script_under_tools_present": 0.0,
        "run_command_logged": 0.0,
        "combined_csv_present": 0.0,
        "combined_csv_header_correct": 0.0,
        "combined_csv_dates_complete": 0.0,
        "combined_csv_values_correct": 0.0,
        "trend_summary_present": 0.0,
        "moving_averages_correct": 0.0,
        "correlations_correct": 0.0,
        "change_points_correct": 0.0,
        "inconsistencies_correct": 0.0,
        "summary_md_sections_present": 0.0,
        "summary_md_correlations_match": 0.0,
        "summary_md_change_points_match": 0.0,
    }

    expected = _compute_expected_from_inputs(workspace)
    union_dates = expected.get("union_dates", [])
    combined_expected = expected.get("combined_expected", {})

    if _find_cli_script_under_tools(workspace):
        scores["cli_script_under_tools_present"] = 1.0

    run_cmd = _read_run_command(workspace)
    if run_cmd and "tools/" in run_cmd and ".py" in run_cmd:
        scores["run_command_logged"] = 1.0

    combined_path = workspace / "output" / "combined" / "daily_metrics.csv"
    combined_rows = None
    if combined_path.exists():
        scores["combined_csv_present"] = 1.0
        combined_rows = _read_combined_csv(combined_path)
    else:
        combined_rows = None

    expected_fields = [
        "date",
        "headache",
        "dizziness",
        "fatigue",
        "pcs_overall",
        "diary_screen_time_hours",
        "checkin_screen_time_hours",
        "sleep_hours",
        "steps",
    ]

    if combined_rows is not None and len(combined_rows) > 0:
        if _validate_header(combined_rows[0], expected_fields):
            scores["combined_csv_header_correct"] = 1.0

        try:
            produced_dates = [r.get("date", "") for r in combined_rows]
            if set(produced_dates) == set(union_dates):
                scores["combined_csv_dates_complete"] = 1.0
        except Exception:
            pass

        try:
            produced_map = {r.get("date", ""): r for r in combined_rows}
            all_ok = True
            for d in union_dates:
                if d not in produced_map:
                    all_ok = False
                    break
                r = produced_map[d]
                exp = combined_expected.get(d, {})
                for f in expected_fields[1:]:
                    expected_val = exp.get(f)
                    cell = r.get(f, "")
                    got_val = _parse_float_cell(cell)
                    if expected_val is None:
                        if cell is None or str(cell).strip() == "":
                            continue
                        else:
                            all_ok = False
                            break
                    else:
                        if got_val is None:
                            all_ok = False
                            break
                        if not _close(float(expected_val), float(got_val), tol=1e-6):
                            all_ok = False
                            break
                if not all_ok:
                    break
            if all_ok:
                scores["combined_csv_values_correct"] = 1.0
        except Exception:
            pass

    trend_summary_path = workspace / "output" / "reports" / "trend_summary.json"
    ts = None
    if trend_summary_path.exists():
        ts = _load_trend_summary(trend_summary_path)
        if isinstance(ts, dict):
            scores["trend_summary_present"] = 1.0

    if isinstance(ts, dict):
        try:
            ma = ts.get("moving_averages", {})
            exp_ma = expected["moving_averages"]

            def _check_ma(key: str, exp_list: List[Tuple[str, float]]) -> bool:
                obs_list = ma.get(key, [])
                if not isinstance(obs_list, list):
                    return False
                if len(obs_list) != len(exp_list):
                    return False
                obs_map = {}
                for item in obs_list:
                    if not isinstance(item, dict):
                        return False
                    dd = item.get("date")
                    val = item.get("value")
                    if dd is None or val is None:
                        return False
                    obs_map[dd] = float(val)
                for d, v in exp_list:
                    if d not in obs_map:
                        return False
                    if not _close(obs_map[d], v, tol=1e-6):
                        return False
                return True

            ma_ok = (
                _check_ma("headache_7d", exp_ma["headache_7d"]) and
                _check_ma("dizziness_7d", exp_ma["dizziness_7d"]) and
                _check_ma("fatigue_7d", exp_ma["fatigue_7d"])
            )
            if ma_ok:
                scores["moving_averages_correct"] = 1.0
        except Exception:
            pass

        try:
            corr = ts.get("correlations", {})
            exp_corr = expected["correlations"]
            st_h = corr.get("screen_time_vs_headache")
            sl_h = corr.get("sleep_vs_headache")
            corr_ok = (
                st_h is not None and sl_h is not None and
                exp_corr["screen_time_vs_headache"] is not None and
                exp_corr["sleep_vs_headache"] is not None and
                _close(float(st_h), float(exp_corr["screen_time_vs_headache"]), tol=1e-6) and
                _close(float(sl_h), float(exp_corr["sleep_vs_headache"]), tol=1e-6)
            )
            if corr_ok:
                scores["correlations_correct"] = 1.0
        except Exception:
            pass

        try:
            obs_cp = ts.get("change_points", [])
            if isinstance(obs_cp, list):
                obs_cp_set = set([str(x) for x in obs_cp])
                exp_cp_set = set(expected["change_points"])
                if obs_cp_set == exp_cp_set:
                    scores["change_points_correct"] = 1.0
        except Exception:
            pass

        try:
            obs_inc = ts.get("inconsistencies", [])
            if isinstance(obs_inc, list):
                obs_map = {}
                for item in obs_inc:
                    if not isinstance(item, dict):
                        continue
                    dd = item.get("date")
                    diff = item.get("diary_vs_checkin_screen_time_diff")
                    if dd is not None and diff is not None:
                        obs_map[dd] = float(diff)
                exp_list = expected["inconsistencies"]
                exp_map = {e["date"]: e["diary_vs_checkin_screen_time_diff"] for e in exp_list}
                if set(obs_map.keys()) == set(exp_map.keys()):
                    diffs_ok = True
                    for d, v in exp_map.items():
                        if not _close(obs_map[d], v, tol=1e-6):
                            diffs_ok = False
                            break
                    if diffs_ok:
                        scores["inconsistencies_correct"] = 1.0
        except Exception:
            pass

    summary_path = workspace / "output" / "reports" / "summary.md"
    summary_text = _safe_read_text(summary_path) if summary_path.exists() else None
    if summary_text:
        has_sections = (
            "Data coverage" in summary_text and
            "Correlations" in summary_text and
            "Detected change points" in summary_text
        )
        if has_sections:
            scores["summary_md_sections_present"] = 1.0

        try:
            corr_section = _extract_section(summary_text, "Correlations", ["Data coverage", "Detected change points"])
            found_nums = []
            for m in re.finditer(r'[-+]?\d*\.\d+|\d+', corr_section):
                try:
                    found_nums.append(float(m.group(0)))
                except Exception:
                    pass
            exp_st_h = expected["correlations"]["screen_time_vs_headache"]
            exp_sl_h = expected["correlations"]["sleep_vs_headache"]
            corr_match = False
            if exp_st_h is not None and exp_sl_h is not None:
                have_st = any(_close(x, exp_st_h, tol=1e-3) for x in found_nums)
                have_sl = any(_close(x, exp_sl_h, tol=1e-3) for x in found_nums)
                if have_st and have_sl:
                    corr_match = True
            if corr_match:
                scores["summary_md_correlations_match"] = 1.0
        except Exception:
            pass

        try:
            cp_section = _extract_section(summary_text, "Detected change points", ["Data coverage", "Correlations"])
            exp_cps = set(expected["change_points"])
            present_dates = set(re.findall(r'\b\d{4}-\d{2}-\d{2}\b', cp_section))
            if exp_cps.issubset(present_dates):
                scores["summary_md_change_points_match"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()