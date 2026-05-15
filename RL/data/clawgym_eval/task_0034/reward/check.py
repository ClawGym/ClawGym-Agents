import json
import sys
import csv
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _parse_number(token: str) -> Any:
    token = token.strip()
    if token == "" or token.lower() in ("null", "none"):
        return None
    try:
        if token.startswith("0") and token != "0" and not token.startswith("0."):
            raise ValueError()
        return int(token)
    except Exception:
        try:
            return float(token)
        except Exception:
            if (token.startswith('"') and token.endswith('"')) or (token.startswith("'") and token.endswith("'")):
                return token[1:-1]
            return token


def _strip_comment(line: str) -> str:
    out = []
    in_single = False
    in_double = False
    for ch in line:
        if ch == "'" and not in_double:
            in_single = not in_single
            out.append(ch)
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
            continue
        if ch == "#" and not in_single and not in_double:
            break
        out.append(ch)
    return "".join(out).rstrip("\n")


def _load_simple_yaml(path: Path) -> Optional[dict]:
    text = _safe_read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    stack: list[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    for raw_line in lines:
        line = _strip_comment(raw_line).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if "\t" in line:
            return None
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        current_dict = stack[-1][1]
        if ":" not in line:
            return None
        key_part, value_part = line.lstrip().split(":", 1)
        key = key_part.strip()
        value = value_part.strip()
        if value == "":
            new_dict: Dict[str, Any] = {}
            current_dict[key] = new_dict
            stack.append((indent, new_dict))
        else:
            current_dict[key] = _parse_number(value)
    return root


def _safe_parse_csv(path: Path) -> Optional[list]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _is_bool_string(val: str) -> bool:
    return val in ("true", "false")


def _parse_iso_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _float_equal(a: float, b: float, eps: float = 1e-6) -> bool:
    return abs(a - b) <= eps


def _weekday_index_from_name(name: str) -> Optional[int]:
    mapping = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    if not isinstance(name, str):
        return None
    return mapping.get(name.strip().lower())


def _compute_week_start(dt: date, week_start_index: int) -> date:
    delta = (dt.weekday() - week_start_index) % 7
    return dt - timedelta(days=delta)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "web_html_saved": 0.0,
        "web_txt_saved": 0.0,
        "limits_json_valid": 0.0,
        "daily_totals_structure": 0.0,
        "daily_totals_values_match": 0.0,
        "weekly_summary_structure": 0.0,
        "weekly_summary_values_match": 0.0,
        "weekly_start_day_alignment": 0.0,
        "report_includes_data_sources": 0.0,
        "report_includes_conversion_assumptions": 0.0,
        "report_includes_extracted_limits": 0.0,
        "report_notes_baseline_vs_extracted": 0.0,
    }

    html_path = workspace / "web" / "niaaa_low_risk.html"
    txt_path = workspace / "web" / "niaaa_low_risk.txt"
    limits_json_path = workspace / "web" / "niaaa_low_risk_limits.json"
    daily_csv_path = workspace / "output" / "daily_totals.csv"
    weekly_csv_path = workspace / "output" / "weekly_summary.csv"
    report_path = workspace / "output" / "report.md"

    html_text = _safe_read_text(html_path)
    if html_text is not None and len(html_text.strip()) > 0:
        if ("niaaa.nih.gov" in html_text) or ("Rethinking Drinking" in html_text) or ("low-risk" in html_text) or ("Low-Risk" in html_text) or ("NIAAA" in html_text):
            scores["web_html_saved"] = 1.0

    txt_text = _safe_read_text(txt_path)
    if txt_text is not None and len(txt_text.strip()) > 0:
        has_digit = any(ch.isdigit() for ch in txt_text)
        if has_digit or ("low-risk" in txt_text.lower()) or ("limit" in txt_text.lower()):
            scores["web_txt_saved"] = 1.0

    limits_obj = _safe_load_json(limits_json_path)
    limits_ok = False
    men_daily = None
    men_weekly = None
    women_daily = None
    women_weekly = None
    if isinstance(limits_obj, dict) and "men" in limits_obj and "women" in limits_obj:
        men = limits_obj.get("men", {})
        women = limits_obj.get("women", {})
        if isinstance(men, dict) and isinstance(women, dict):
            men_daily = men.get("daily")
            men_weekly = men.get("weekly")
            women_daily = women.get("daily")
            women_weekly = women.get("weekly")

            def _is_num(x): return isinstance(x, (int, float)) and not isinstance(x, bool)
            if _is_num(men_daily) and _is_num(men_weekly) and _is_num(women_daily) and _is_num(women_weekly):
                limits_ok = True
    if limits_ok:
        scores["limits_json_valid"] = 1.0

    sd_yaml_path = workspace / "config" / "standard_drinks.yaml"
    baseline_yaml_path = workspace / "config" / "baseline_limits.yaml"
    profile_yaml_path = workspace / "config" / "profile.yaml"
    sd_cfg = _load_simple_yaml(sd_yaml_path) or {}
    baseline_cfg = _load_simple_yaml(baseline_yaml_path) or {}
    profile_cfg = _load_simple_yaml(profile_yaml_path) or {}

    drink_types_cfg = {}
    default_factor = None
    try:
        drink_types_cfg = (sd_cfg.get("drink_types") or {})
        default_factor = (sd_cfg.get("default") or {}).get("standard_drink_per_oz")
    except Exception:
        drink_types_cfg = {}
        default_factor = None
    factors: Dict[str, float] = {}
    if isinstance(drink_types_cfg, dict):
        for k, v in drink_types_cfg.items():
            try:
                factors[str(k).strip().lower()] = float(v.get("standard_drink_per_oz"))
            except Exception:
                continue
    try:
        default_factor = float(default_factor) if default_factor is not None else None
    except Exception:
        default_factor = None

    sex = None
    tz_name = None
    weekly_start_name = None
    try:
        user = (profile_cfg.get("user") or {})
        sex = str(user.get("sex")).strip().lower() if user.get("sex") is not None else None
        tz_name = str(user.get("timezone")).strip() if user.get("timezone") is not None else None
        weekly_start_name = str(user.get("weekly_start_day")).strip() if user.get("weekly_start_day") is not None else None
    except Exception:
        pass
    week_start_index = _weekday_index_from_name(weekly_start_name) if weekly_start_name else None

    sex_key = None
    if isinstance(sex, str):
        if sex in ("male", "man", "m"):
            sex_key = "men"
        elif sex in ("female", "woman", "f"):
            sex_key = "women"
    daily_limit = None
    weekly_limit = None
    if limits_ok and sex_key:
        if sex_key == "men":
            daily_limit = float(men_daily)
            weekly_limit = float(men_weekly)
        else:
            daily_limit = float(women_daily)
            weekly_limit = float(women_weekly)

    drink_log_path = workspace / "input" / "drink_log.csv"
    drink_rows = _safe_parse_csv(drink_log_path) or []

    expected_daily_totals: Dict[str, float] = {}
    expected_exceeded_by_day: Dict[str, bool] = {}
    tzinfo = None
    if tz_name:
        try:
            tzinfo = ZoneInfo(tz_name)
        except Exception:
            tzinfo = None
    for r in drink_rows:
        try:
            d_str = (r.get("date") or "").strip()
            t_str = (r.get("time") or "").strip()
            drink_type = (r.get("drink_type") or "").strip().lower()
            vol_str = (r.get("volume_oz") or "").strip()
            if not d_str or not t_str or not vol_str:
                continue
            dt_naive = datetime.strptime(f"{d_str} {t_str}", "%Y-%m-%d %H:%M")
            if tzinfo is not None:
                dt_local = dt_naive.replace(tzinfo=tzinfo)
            else:
                dt_local = dt_naive
            day_key = dt_local.date().isoformat()
            factor = factors.get(drink_type, default_factor if default_factor is not None else 0.0)
            vol = float(vol_str)
            std_drinks = vol * float(factor)
            expected_daily_totals[day_key] = expected_daily_totals.get(day_key, 0.0) + std_drinks
        except Exception:
            continue
    if daily_limit is not None:
        for d, total in expected_daily_totals.items():
            expected_exceeded_by_day[d] = total > daily_limit

    daily_structure_ok = False
    daily_values_ok = False
    daily_file_rows = _safe_parse_csv(daily_csv_path)
    if isinstance(daily_file_rows, list):
        try:
            with daily_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
        except Exception:
            header = None
        if header == ["date", "total_standard_drinks", "exceeded_daily_limit"]:
            structure_rows_ok = True
            file_map: Dict[str, Tuple[float, str]] = {}
            for row in daily_file_rows:
                d = (row.get("date") or "").strip()
                tsd = (row.get("total_standard_drinks") or "").strip()
                edl = (row.get("exceeded_daily_limit") or "").strip()
                if _parse_iso_date(d) is None:
                    structure_rows_ok = False
                    break
                try:
                    tsd_val = float(tsd)
                except Exception:
                    structure_rows_ok = False
                    break
                if not _is_bool_string(edl):
                    structure_rows_ok = False
                    break
                file_map[d] = (tsd_val, edl)
            if structure_rows_ok:
                daily_structure_ok = True
                if expected_daily_totals:
                    all_match = True
                    for d, expected_total in expected_daily_totals.items():
                        if d not in file_map:
                            all_match = False
                            break
                        got_total, got_exceeded = file_map[d]
                        if not _float_equal(got_total, expected_total, eps=1e-4):
                            all_match = False
                            break
                        if daily_limit is not None:
                            exp_exceeded = "true" if expected_exceeded_by_day.get(d, False) else "false"
                            if got_exceeded != exp_exceeded:
                                all_match = False
                                break
                    if all_match:
                        daily_values_ok = True
                else:
                    daily_values_ok = False
    scores["daily_totals_structure"] = 1.0 if daily_structure_ok else 0.0
    scores["daily_totals_values_match"] = 1.0 if daily_values_ok else 0.0

    expected_weeks: Dict[str, Dict[str, Any]] = {}
    if week_start_index is not None and expected_daily_totals:
        for d_str, total in expected_daily_totals.items():
            d_obj = _parse_iso_date(d_str)
            if d_obj is None:
                continue
            w_start = _compute_week_start(d_obj, week_start_index)
            w_end = w_start + timedelta(days=6)
            wkey = w_start.isoformat()
            if wkey not in expected_weeks:
                expected_weeks[wkey] = {
                    "week_start": w_start,
                    "week_end": w_end,
                    "total_standard_drinks": 0.0,
                    "days_exceeded_daily_limit": 0,
                }
            expected_weeks[wkey]["total_standard_drinks"] += total
            if daily_limit is not None and expected_exceeded_by_day.get(d_str, False):
                expected_weeks[wkey]["days_exceeded_daily_limit"] += 1
        if weekly_limit is not None:
            for _, rec in expected_weeks.items():
                rec["exceeded_weekly_limit"] = rec["total_standard_drinks"] > weekly_limit

    weekly_structure_ok = False
    weekly_values_ok = False
    weekly_alignment_ok = False
    weekly_rows = _safe_parse_csv(weekly_csv_path)
    if isinstance(weekly_rows, list):
        try:
            with weekly_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
        except Exception:
            header = None
        expected_header = [
            "week_start",
            "week_end",
            "total_standard_drinks",
            "avg_daily_standard_drinks",
            "days_exceeded_daily_limit",
            "exceeded_weekly_limit",
        ]
        if header == expected_header:
            structure_rows_ok = True
            alignment_ok = True
            file_weeks: Dict[str, Dict[str, Any]] = {}
            for row in weekly_rows:
                ws = (row.get("week_start") or "").strip()
                we = (row.get("week_end") or "").strip()
                tsd = (row.get("total_standard_drinks") or "").strip()
                ads = (row.get("avg_daily_standard_drinks") or "").strip()
                ded = (row.get("days_exceeded_daily_limit") or "").strip()
                ewl = (row.get("exceeded_weekly_limit") or "").strip()
                ws_date = _parse_iso_date(ws)
                we_date = _parse_iso_date(we)
                if ws_date is None or we_date is None:
                    structure_rows_ok = False
                    break
                if we_date < ws_date:
                    structure_rows_ok = False
                    break
                try:
                    tsd_val = float(tsd)
                    _ = float(ads)
                except Exception:
                    structure_rows_ok = False
                    break
                try:
                    ded_val = int(ded)
                except Exception:
                    structure_rows_ok = False
                    break
                if not _is_bool_string(ewl):
                    structure_rows_ok = False
                    break
                if week_start_index is not None and ws_date.weekday() != week_start_index:
                    alignment_ok = False
                file_weeks[ws] = {
                    "week_start": ws_date,
                    "week_end": we_date,
                    "total_standard_drinks": tsd_val,
                    "days_exceeded_daily_limit": ded_val,
                    "exceeded_weekly_limit": ewl,
                }
            if structure_rows_ok:
                weekly_structure_ok = True
                weekly_alignment_ok = alignment_ok
                if expected_weeks:
                    all_match = True
                    for wkey, exp in expected_weeks.items():
                        if wkey not in file_weeks:
                            all_match = False
                            break
                        got = file_weeks[wkey]
                        if got["week_end"] != exp["week_end"]:
                            all_match = False
                            break
                        if not _float_equal(got["total_standard_drinks"], exp["total_standard_drinks"], eps=1e-4):
                            all_match = False
                            break
                        if got["days_exceeded_daily_limit"] != exp["days_exceeded_daily_limit"]:
                            all_match = False
                            break
                        if weekly_limit is not None:
                            exp_ewl = "true" if exp.get("exceeded_weekly_limit", False) else "false"
                            if got["exceeded_weekly_limit"] != exp_ewl:
                                all_match = False
                                break
                    if all_match:
                        weekly_values_ok = True
                else:
                    weekly_values_ok = False
    scores["weekly_summary_structure"] = 1.0 if weekly_structure_ok else 0.0
    scores["weekly_summary_values_match"] = 1.0 if weekly_values_ok else 0.0
    scores["weekly_start_day_alignment"] = 1.0 if weekly_alignment_ok else 0.0

    report_text = _safe_read_text(report_path) or ""
    if report_text:
        local_ok = all(p in report_text for p in [
            "config/standard_drinks.yaml",
            "config/baseline_limits.yaml",
            "config/profile.yaml",
            "input/drink_log.csv",
        ])
        web_ok = ("web/niaaa_low_risk.html" in report_text) or ("niaaa.nih.gov" in report_text) or ("web/niaaa_low_risk.txt" in report_text)
        if local_ok and web_ok:
            scores["report_includes_data_sources"] = 1.0

        factors_to_find = []
        try:
            if "drink_types" in sd_cfg:
                dt = sd_cfg["drink_types"]
                if isinstance(dt, dict):
                    for _, meta in dt.items():
                        try:
                            factors_to_find.append(str(meta.get("standard_drink_per_oz")))
                        except Exception:
                            pass
            if "default" in sd_cfg:
                try:
                    factors_to_find.append(str(sd_cfg["default"].get("standard_drink_per_oz")))
                except Exception:
                    pass
        except Exception:
            pass
        found_count = 0
        for f in factors_to_find:
            if f and f in report_text:
                found_count += 1
        if found_count >= 3:
            scores["report_includes_conversion_assumptions"] = 1.0

        extracted_ok = False
        if limits_ok:
            nums = [
                str(men_daily), str(men_weekly),
                str(women_daily), str(women_weekly),
            ]
            path_present = "web/niaaa_low_risk_limits.json" in report_text
            nums_present = all(n in report_text for n in nums)
            if path_present and nums_present:
                extracted_ok = True
        if extracted_ok:
            scores["report_includes_extracted_limits"] = 1.0

        baseline_vs_ok = False
        base_men_daily = None
        base_men_weekly = None
        base_women_daily = None
        base_women_weekly = None
        try:
            b = baseline_cfg.get("baseline") or {}
            base_men_daily = (b.get("men") or {}).get("daily")
            base_men_weekly = (b.get("men") or {}).get("weekly")
            base_women_daily = (b.get("women") or {}).get("daily")
            base_women_weekly = (b.get("women") or {}).get("weekly")
        except Exception:
            pass
        diff_exists = None
        if limits_ok and all(x is not None for x in [base_men_daily, base_men_weekly, base_women_daily, base_women_weekly]):
            try:
                diff_exists = (
                    float(base_men_daily) != float(men_daily) or
                    float(base_men_weekly) != float(men_weekly) or
                    float(base_women_daily) != float(women_daily) or
                    float(base_women_weekly) != float(women_weekly)
                )
            except Exception:
                diff_exists = None
        text_lower = report_text.lower()
        mentions_comparison = ("baseline" in text_lower and "extracted" in text_lower)
        if diff_exists is True:
            has_diff_words = ("differ" in text_lower) or ("different" in text_lower) or ("mismatch" in text_lower) or ("not equal" in text_lower)
            baseline_nums_present = all(str(x) in report_text for x in [base_men_daily, base_men_weekly, base_women_daily, base_women_weekly])
            extracted_nums_present = limits_ok and all(str(x) in report_text for x in [men_daily, men_weekly, women_daily, women_weekly])
            if mentions_comparison and (has_diff_words or (baseline_nums_present and extracted_nums_present)):
                baseline_vs_ok = True
        elif diff_exists is False:
            has_match_words = ("no difference" in text_lower) or ("match" in text_lower) or ("same" in text_lower) or ("equal" in text_lower)
            if mentions_comparison and has_match_words:
                baseline_vs_ok = True
        else:
            if mentions_comparison:
                baseline_vs_ok = True
        if baseline_vs_ok:
            scores["report_notes_baseline_vs_extracted"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()