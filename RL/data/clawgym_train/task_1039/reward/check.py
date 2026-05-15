import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple, Optional, Any


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            header = reader.fieldnames or []
            return rows, header
    except Exception:
        return None, None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_float(s: Any) -> Optional[float]:
    try:
        if s is None:
            return None
        if isinstance(s, (int, float)):
            return float(s)
        s2 = str(s).strip()
        if s2.lower() in {"", "null", "none", "nan"}:
            return None
        return float(s2)
    except Exception:
        return None


def _parse_int(s: Any) -> Optional[int]:
    try:
        if s is None:
            return None
        if isinstance(s, int):
            return s
        s2 = str(s).strip()
        if s2.lower() in {"", "null", "none", "nan"}:
            return None
        if re.fullmatch(r"[-+]?\d+", s2):
            return int(s2)
        f = float(s2)
        if abs(f - int(round(f))) < 1e-9:
            return int(round(f))
        return None
    except Exception:
        return None


def _approx_equal(a: float, b: float, rel_tol: float = 1e-6, abs_tol: float = 1e-6) -> bool:
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


def _compute_expected_from_input(input_csv_path: Path) -> Optional[Dict[str, Any]]:
    rows, header = _read_csv_dicts(input_csv_path)
    if rows is None:
        return None

    expected_rows = []
    for r in rows:
        d = {
            "date": r.get("date", ""),
            "session_type": r.get("session_type", ""),
            "duration_min": _parse_int(r.get("duration_min")),
            "total_distance_m": _parse_float(r.get("total_distance_m")),
            "high_speed_m": _parse_float(r.get("high_speed_m")),
            "accelerations_ge_2mps2": _parse_int(r.get("accelerations_ge_2mps2")),
            "decelerations_ge_2mps2": _parse_int(r.get("decelerations_ge_2mps2")),
            "RPE": _parse_int(r.get("RPE")),
            "tackles_made": _parse_int(r.get("tackles_made")),
            "tackles_missed": _parse_int(r.get("tackles_missed")),
        }
        if d["duration_min"] is None or d["RPE"] is None:
            return None
        session_load = float(d["duration_min"]) * float(d["RPE"])
        if d["total_distance_m"] is None or d["duration_min"] in (None, 0):
            return None
        meters_per_minute = float(d["total_distance_m"]) / float(d["duration_min"])
        tm = d["tackles_made"] or 0
        tmiss = d["tackles_missed"] or 0
        tsr = None
        if (tm + tmiss) > 0:
            tsr = tm / float(tm + tmiss)
        expected_rows.append({
            "date": d["date"],
            "session_type": d["session_type"],
            "duration_min": d["duration_min"],
            "RPE": d["RPE"],
            "session_load": session_load,
            "total_distance_m": d["total_distance_m"],
            "meters_per_minute": meters_per_minute,
            "high_speed_m": d["high_speed_m"],
            "accelerations_ge_2mps2": d["accelerations_ge_2mps2"],
            "decelerations_ge_2mps2": d["decelerations_ge_2mps2"],
            "tackles_made": d["tackles_made"],
            "tackles_missed": d["tackles_missed"],
            "tackle_success_rate": tsr,
        })

    w1_start = date(2026, 4, 1)
    w1_end = date(2026, 4, 7)
    w2_start = date(2026, 4, 8)
    w2_end = date(2026, 4, 14)

    week1_load = 0.0
    week2_load = 0.0
    total_mpm = 0.0
    count_mpm = 0

    for e in expected_rows:
        total_mpm += e["meters_per_minute"]
        count_mpm += 1
        ed = _parse_date(e["date"])
        if ed is None:
            return None
        if w1_start <= ed <= w1_end:
            week1_load += e["session_load"]
        if w2_start <= ed <= w2_end:
            week2_load += e["session_load"]

    avg_mpm = total_mpm / count_mpm if count_mpm > 0 else 0.0
    target_next = (week1_load + week2_load) / 2.0
    include_speed = avg_mpm < 90.0

    return {
        "rows": expected_rows,
        "week1_load": week1_load,
        "week2_load": week2_load,
        "avg_meters_per_minute": avg_mpm,
        "target_next_week_load": target_next,
        "include_speed_session": include_speed,
        "next_week_range": (date(2026, 4, 15), date(2026, 4, 21)),
    }


def _numbers_in_text(text: str) -> List[float]:
    nums = []
    for m in re.finditer(r"[-+]?\d+(?:\.\d+)?", text):
        try:
            nums.append(float(m.group(0)))
        except Exception:
            continue
    return nums


def _find_between_markers(text: str, start_marker: str, end_marker: str) -> Optional[Tuple[int, int, str]]:
    start_idx = text.find(start_marker)
    end_idx = text.find(end_marker)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return None
    content_start = start_idx + len(start_marker)
    content = text[content_start:end_idx]
    return start_idx, end_idx, content


def _load_plan(path: Path) -> Optional[List[Dict[str, Any]]]:
    data = _load_json(path)
    if not isinstance(data, list):
        return None
    out = []
    for item in data:
        if not isinstance(item, dict):
            return None
        out.append(item)
    return out


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "session_metrics_csv_structure": 0.0,
        "session_metrics_values_correct": 0.0,
        "summary_json_values_correct": 0.0,
        "next_week_plan_structure": 0.0,
        "plan_date_coverage_and_counts": 0.0,
        "plan_inclusion_requirements": 0.0,
        "plan_load_and_sequence_constraints": 0.0,
        "trainingplan_md_updated_and_consistent": 0.0,
        "email_to_coach_references_and_summary": 0.0,
    }

    input_csv = workspace / "input" / "sessions.csv"
    session_metrics_csv = workspace / "output" / "session_metrics.csv"
    summary_json_path = workspace / "output" / "summary.json"
    plan_json_path = workspace / "output" / "next_week_plan.json"
    trainingplan_md_path = workspace / "docs" / "TrainingPlan.md"
    email_txt_path = workspace / "output" / "email_to_coach.txt"

    expected = _compute_expected_from_input(input_csv) if input_csv.exists() else None

    expected_header = [
        "date",
        "session_type",
        "duration_min",
        "RPE",
        "session_load",
        "total_distance_m",
        "meters_per_minute",
        "high_speed_m",
        "accelerations_ge_2mps2",
        "decelerations_ge_2mps2",
        "tackles_made",
        "tackles_missed",
        "tackle_success_rate",
    ]
    rows_out, header_out = _read_csv_dicts(session_metrics_csv) if session_metrics_csv.exists() else (None, None)
    if rows_out is not None and header_out is not None and header_out == expected_header:
        if expected is None:
            scores["session_metrics_csv_structure"] = 1.0
        else:
            if len(rows_out) == len(expected["rows"]):
                scores["session_metrics_csv_structure"] = 1.0
            else:
                scores["session_metrics_csv_structure"] = 0.0
    else:
        scores["session_metrics_csv_structure"] = 0.0

    if expected is not None and rows_out is not None:
        exp_map = {}
        for e in expected["rows"]:
            key = (e["date"], e["session_type"])
            exp_map[key] = e
        ok = True
        if len(rows_out) != len(expected["rows"]):
            ok = False
        else:
            for r in rows_out:
                key = (r.get("date", ""), r.get("session_type", ""))
                e = exp_map.get(key)
                if e is None:
                    ok = False
                    break
                if _parse_int(r.get("duration_min")) != e["duration_min"]:
                    ok = False
                    break
                if _parse_int(r.get("RPE")) != e["RPE"]:
                    ok = False
                    break
                if _parse_float(r.get("total_distance_m")) is None or not _approx_equal(_parse_float(r.get("total_distance_m")), e["total_distance_m"]):
                    ok = False
                    break
                if _parse_float(r.get("high_speed_m")) is None or not _approx_equal(_parse_float(r.get("high_speed_m")), float(e["high_speed_m"])):
                    ok = False
                    break
                if _parse_int(r.get("accelerations_ge_2mps2")) != e["accelerations_ge_2mps2"]:
                    ok = False
                    break
                if _parse_int(r.get("decelerations_ge_2mps2")) != e["decelerations_ge_2mps2"]:
                    ok = False
                    break
                if _parse_int(r.get("tackles_made")) != (e["tackles_made"] or 0):
                    ok = False
                    break
                if _parse_int(r.get("tackles_missed")) != (e["tackles_missed"] or 0):
                    ok = False
                    break
                sl = _parse_float(r.get("session_load"))
                mpm = _parse_float(r.get("meters_per_minute"))
                tsr_str = r.get("tackle_success_rate")
                tsr_val = _parse_float(tsr_str)
                if sl is None or not _approx_equal(sl, e["session_load"]):
                    ok = False
                    break
                if mpm is None or not _approx_equal(mpm, e["meters_per_minute"]):
                    ok = False
                    break
                if e["tackle_success_rate"] is None:
                    if tsr_str is None:
                        pass
                    else:
                        s = str(tsr_str).strip().lower()
                        if s not in {"", "null", "none"}:
                            ok = False
                            break
                else:
                    if tsr_val is None or not _approx_equal(tsr_val, e["tackle_success_rate"]):
                        ok = False
                        break
        scores["session_metrics_values_correct"] = 1.0 if ok else 0.0
    else:
        scores["session_metrics_values_correct"] = 0.0

    if summary_json_path.exists() and expected is not None:
        sj = _load_json(summary_json_path)
        keys_required = {"week1_load", "week2_load", "target_next_week_load", "avg_meters_per_minute", "include_speed_session", "next_week_date_range"}
        if isinstance(sj, dict) and set(sj.keys()) == keys_required:
            ok = True
            try:
                if not _approx_equal(float(sj["week1_load"]), expected["week1_load"]):
                    ok = False
                if not _approx_equal(float(sj["week2_load"]), expected["week2_load"]):
                    ok = False
                if not _approx_equal(float(sj["target_next_week_load"]), expected["target_next_week_load"]):
                    ok = False
                if not _approx_equal(float(sj["avg_meters_per_minute"]), expected["avg_meters_per_minute"]):
                    ok = False
                if bool(sj["include_speed_session"]) != bool(expected["include_speed_session"]):
                    ok = False
                if not isinstance(sj["next_week_date_range"], list) or sj["next_week_date_range"] != ["2026-04-15", "2026-04-21"]:
                    ok = False
            except Exception:
                ok = False
            scores["summary_json_values_correct"] = 1.0 if ok else 0.0
        else:
            scores["summary_json_values_correct"] = 0.0
    else:
        scores["summary_json_values_correct"] = 0.0

    plan = None
    if plan_json_path.exists():
        plan = _load_plan(plan_json_path)
    if plan is not None and isinstance(plan, list) and len(plan) == 7:
        required_keys = {"date", "session_type", "duration_min", "RPE", "planned_load"}
        structure_ok = True
        for item in plan:
            if not required_keys.issubset(set(item.keys())):
                structure_ok = False
                break
            if _parse_date(str(item["date"])) is None:
                structure_ok = False
                break
            if _parse_int(item["duration_min"]) is None or _parse_int(item["RPE"]) is None:
                structure_ok = False
                break
            if _parse_float(item["planned_load"]) is None:
                structure_ok = False
                break
        scores["next_week_plan_structure"] = 1.0 if structure_ok else 0.0
    else:
        scores["next_week_plan_structure"] = 0.0

    if plan is not None:
        range_start, range_end = date(2026, 4, 15), date(2026, 4, 21)
        dates = []
        type_ok = True
        training_days = 0
        rest_days = 0
        allowed_types = {"skills", "conditioning", "contact", "speed", "recovery"}
        for item in plan:
            d = _parse_date(str(item["date"]))
            if d is None or not (range_start <= d <= range_end):
                type_ok = False
                break
            dates.append(d)
            st = str(item["session_type"])
            dur = _parse_int(item["duration_min"])
            rpe = _parse_int(item["RPE"])
            pl = _parse_float(item["planned_load"])
            if st == "Rest":
                rest_days += 1
                if dur != 0 or rpe != 0 or not _approx_equal(pl or 0.0, 0.0):
                    type_ok = False
                    break
            else:
                training_days += 1
                if st not in allowed_types:
                    type_ok = False
                    break
                if dur is None or rpe is None or pl is None or not _approx_equal(float(dur * rpe), pl):
                    type_ok = False
                    break
        if type_ok and len(set(dates)) == 7 and training_days == 5 and rest_days == 2:
            scores["plan_date_coverage_and_counts"] = 1.0
        else:
            scores["plan_date_coverage_and_counts"] = 0.0
    else:
        scores["plan_date_coverage_and_counts"] = 0.0

    inclusion_ok = False
    if plan is not None and summary_json_path.exists():
        sj = _load_json(summary_json_path)
        if isinstance(sj, dict):
            include_speed_required = bool(sj.get("include_speed_session", False))
            types_present = [str(it["session_type"]) for it in plan if str(it["session_type"]) != "Rest"]
            has_skills = "skills" in types_present
            has_conditioning = "conditioning" in types_present
            has_speed = "speed" in types_present
            if has_skills and has_conditioning and ((not include_speed_required) or has_speed):
                inclusion_ok = True
    scores["plan_inclusion_requirements"] = 1.0 if inclusion_ok else 0.0

    seq_ok = False
    if plan is not None and summary_json_path.exists():
        sj = _load_json(summary_json_path)
        if isinstance(sj, dict) and "target_next_week_load" in sj:
            sorted_plan = sorted(plan, key=lambda x: _parse_date(str(x["date"])) or date(1900, 1, 1))
            total_planned = 0.0
            max_load = -1.0
            max_load_date: Optional[date] = None
            max_load_count = 0
            rest_map = {}
            train_flags = []
            for item in sorted_plan:
                d = _parse_date(str(item["date"]))
                st = str(item["session_type"])
                pl = _parse_float(item["planned_load"]) or 0.0
                if st == "Rest":
                    rest_map[d] = True
                    train_flags.append(False)
                else:
                    total_planned += pl
                    train_flags.append(True)
                    if pl > max_load + 1e-9:
                        max_load = pl
                        max_load_date = d
                        max_load_count = 1
                    elif _approx_equal(pl, max_load):
                        max_load_count += 1
            target = _parse_float(sj.get("target_next_week_load"))
            within_10 = False
            if target is not None:
                lower = target * 0.9
                upper = target * 1.1
                within_10 = (total_planned >= lower - 1e-6) and (total_planned <= upper + 1e-6)
            hi_followed_rest = False
            if max_load_date is not None and max_load_count == 1:
                next_day = max_load_date + timedelta(days=1)
                hi_followed_rest = rest_map.get(next_day, False)
            no_long_runs = True
            run_len = 0
            for flag in train_flags:
                if flag:
                    run_len += 1
                    if run_len > 2:
                        no_long_runs = False
                        break
                else:
                    run_len = 0
            if within_10 and hi_followed_rest and no_long_runs:
                seq_ok = True
    scores["plan_load_and_sequence_constraints"] = 1.0 if seq_ok else 0.0

    md_ok = False
    if trainingplan_md_path.exists() and plan is not None:
        md_text = _read_text(trainingplan_md_path)
        if md_text is not None:
            markers = _find_between_markers(md_text, "<!-- NEXT_WEEK_START -->", "<!-- NEXT_WEEK_END -->")
            if markers is not None:
                _, _, segment = markers
                plan_by_date = {str(it["date"]): it for it in plan}
                all_dates = [(date(2026, 4, 15) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
                all_present = True
                lines = [ln.strip() for ln in segment.strip().splitlines() if ln.strip()]
                for dstr in all_dates:
                    it = plan_by_date.get(dstr)
                    if it is None:
                        all_present = False
                        break
                    dur = _parse_int(it.get("duration_min"))
                    rpe = _parse_int(it.get("RPE"))
                    pl = _parse_float(it.get("planned_load"))
                    st = str(it.get("session_type"))
                    found_line = False
                    for ln in lines:
                        if dstr in ln and st in ln and (str(dur) in ln) and (str(rpe) in ln) and (("{:.0f}".format(pl) in ln) or (("{:.2f}".format(pl) in ln)) or (str(pl) in ln)):
                            if ln.startswith(("-", "*", "•", "–")):
                                found_line = True
                                break
                    if not found_line:
                        all_present = False
                        break
                total_planned = 0.0
                for it in plan:
                    if str(it["session_type"]) != "Rest":
                        total_planned += _parse_float(it["planned_load"]) or 0.0
                note_ok = False
                for ln in lines:
                    if "±10%" in ln and ("within" in ln or "Within" in ln):
                        formatted_candidates = {
                            f"{total_planned:.0f}",
                            f"{total_planned:.1f}",
                            f"{total_planned:.2f}",
                            str(total_planned),
                        }
                        if any(fc in ln for fc in formatted_candidates):
                            note_ok = True
                            break
                if all_present and note_ok:
                    md_ok = True
    scores["trainingplan_md_updated_and_consistent"] = 1.0 if md_ok else 0.0

    email_ok = False
    if email_txt_path.exists():
        email_text = _read_text(email_txt_path) or ""
        summary = _load_json(summary_json_path) if summary_json_path.exists() else None
        plan_loaded = _load_plan(plan_json_path) if plan_json_path.exists() else None
        if summary is not None and isinstance(summary, dict) and plan_loaded is not None:
            greet = ("coach" in email_text.lower()) and any(g in email_text for g in ["Hi", "Hello", "Bula", "Talofa", "Bula!"])
            proposes = ("analy" in email_text.lower()) and ("2026-04-15" in email_text and "2026-04-21" in email_text)

            def contains_number_close(target_val: float, tol: float) -> bool:
                nums = _numbers_in_text(email_text)
                for n in nums:
                    if abs(n - target_val) <= tol:
                        return True
                return False

            nums_ok = True
            expected_vals = expected
            if expected_vals is not None:
                nums_ok = (
                    contains_number_close(expected_vals["week1_load"], 0.5)
                    and contains_number_close(expected_vals["week2_load"], 0.5)
                    and contains_number_close(expected_vals["target_next_week_load"], 0.5)
                    and contains_number_close(expected_vals["avg_meters_per_minute"], 0.5)
                )
            else:
                try:
                    nums_ok = (
                        contains_number_close(float(summary["week1_load"]), 0.5)
                        and contains_number_close(float(summary["week2_load"]), 0.5)
                        and contains_number_close(float(summary["target_next_week_load"]), 0.5)
                        and contains_number_close(float(summary["avg_meters_per_minute"]), 0.5)
                    )
                except Exception:
                    nums_ok = False

            speed_bool = bool(summary.get("include_speed_session", False))
            speed_ok = False
            if "speed" in email_text.lower():
                if speed_bool:
                    speed_ok = ("< 90" in email_text) or ("below 90" in email_text.lower()) or ("less than 90" in email_text.lower()) or ("under 90" in email_text.lower()) or ("<90" in email_text.replace(" ", ""))
                else:
                    speed_ok = True

            rest_dates = sorted([_parse_date(str(it["date"])) for it in plan_loaded if str(it["session_type"]) == "Rest"])
            max_pl = -1.0
            max_date = None
            for it in plan_loaded:
                if str(it["session_type"]) != "Rest":
                    pl = _parse_float(it["planned_load"]) or 0.0
                    if pl > max_pl + 1e-9:
                        max_pl = pl
                        max_date = _parse_date(str(it["date"]))
            list_rest_ok = False
            if len(rest_dates) == 2:
                if all(rd and rd.strftime("%Y-%m-%d") in email_text for rd in rest_dates):
                    list_rest_ok = True
            hi_follow_note = False
            if max_date is not None:
                next_d = max_date + timedelta(days=1)
                if (max_date.strftime("%Y-%m-%d") in email_text) and (("follow" in email_text.lower()) or ("next day" in email_text.lower())) and (next_d.strftime("%Y-%m-%d") in email_text):
                    hi_follow_note = True

            refs_ok = all(p in email_text for p in [
                "output/session_metrics.csv",
                "output/summary.json",
                "output/next_week_plan.json",
            ]) and ("docs/TrainingPlan.md" in email_text or "TrainingPlan.md" in email_text) and ("updated" in email_text.lower() or "update" in email_text.lower())

            email_ok = all([greet, proposes, nums_ok, speed_ok, list_rest_ok, hi_follow_note, refs_ok])
    scores["email_to_coach_references_and_summary"] = 1.0 if email_ok else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()