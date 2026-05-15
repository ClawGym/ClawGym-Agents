import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _parse_calendar_yaml(path: Path) -> Optional[Dict[str, bool]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    in_days = False
    days_avail: Dict[str, bool] = {}
    current_day: Optional[str] = None
    day_re = re.compile(r"^\s{2}([A-Za-z]+):\s*$")
    avail_re = re.compile(r"^\s{4}available:\s*(true|false)\s*$", re.IGNORECASE)
    for raw_line in lines:
        line = raw_line.rstrip()
        if not in_days:
            if re.match(r"^\s*days:\s*$", line):
                in_days = True
            continue
        mday = day_re.match(line)
        if mday:
            current_day = mday.group(1)
            continue
        mav = avail_re.match(line)
        if mav and current_day is not None:
            val = mav.group(1).lower() == "true"
            days_avail[current_day] = val
            continue
    if not in_days:
        return None
    return days_avail


def _safe_parse_int(x: Any) -> Optional[int]:
    try:
        if isinstance(x, int):
            return x
        s = str(x).strip()
        if s == "":
            return None
        return int(float(s))
    except Exception:
        return None


def _safe_parse_float(x: Any) -> Optional[float]:
    try:
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _compute_priority_score(weight_map: Dict[str, float], tactical_theme: str, intensity: int, ball_work: int) -> float:
    w = weight_map.get(tactical_theme, 0.0)
    return w * 100.0 + intensity * 10.0 + (5.0 if ball_work == 1 else 0.0)


def _normalize_risk_tags(cell: str) -> List[str]:
    if cell is None:
        return []
    s = str(cell).strip()
    if not s:
        return []
    parts = [p.strip().lower() for p in s.split(";")]
    return [p for p in parts if p]


def _build_eligible_sorted(drills_rows: List[Dict[str, str]], profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    pos_group = profile.get("position_group")
    avoid = [str(a).strip().lower() for a in profile.get("avoid_risks", [])]
    weights = {k: float(v) for k, v in profile.get("veteran_focus_weights", {}).items()}
    eligible: List[Dict[str, Any]] = []
    for row in drills_rows:
        try:
            drill_id = row["drill_id"].strip()
            name = row["name"].strip()
            position_group = row["position_group"].strip()
            intensity = _safe_parse_int(row["intensity"])
            duration_min = _safe_parse_int(row["duration_min"])
            tactical_theme = row["tactical_theme"].strip()
            ball_work = _safe_parse_int(row["ball_work"])
            risk_tags = row.get("risk_tags", "")
        except Exception:
            continue
        if intensity is None or duration_min is None or ball_work is None:
            continue
        if not (position_group == pos_group or position_group == "ALL"):
            continue
        tags = _normalize_risk_tags(risk_tags)
        if any(tag in avoid for tag in tags):
            continue
        priority = _compute_priority_score(weights, tactical_theme, intensity, ball_work)
        eligible.append({
            "drill_id": drill_id,
            "name": name,
            "tactical_theme": tactical_theme,
            "intensity": intensity,
            "duration_min": duration_min,
            "ball_work": ball_work,
            "priority_score": priority,
        })
    eligible.sort(key=lambda d: (
        -float(d["priority_score"]),
        -int(d["intensity"]),
        -int(d["duration_min"]),
        str(d["drill_id"])
    ))
    return eligible


def _day_names() -> List[str]:
    return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _build_expected_schedule(eligible_sorted: List[Dict[str, Any]],
                             calendar_avail: Dict[str, bool],
                             target_weekly_minutes: int,
                             max_daily_minutes: int,
                             sessions_per_day_cap: int) -> Dict[str, Any]:
    schedule_days: List[Dict[str, Any]] = []
    total_scheduled = 0
    idx = 0
    day_order = _day_names()
    for day in day_order:
        available = bool(calendar_avail.get(day, False))
        day_entry = {"day": day, "scheduled_minutes": 0, "drills": []}
        if not available:
            schedule_days.append(day_entry)
            continue
        day_remaining = max_daily_minutes
        sessions = 0
        while True:
            if total_scheduled >= target_weekly_minutes:
                break
            if sessions >= sessions_per_day_cap:
                break
            if idx >= len(eligible_sorted):
                break
            nxt = eligible_sorted[idx]
            dur = int(nxt["duration_min"])
            if total_scheduled + dur > target_weekly_minutes:
                idx = len(eligible_sorted)
                break
            if dur <= day_remaining:
                assignment = {
                    "drill_id": nxt["drill_id"],
                    "name": nxt["name"],
                    "tactical_theme": nxt["tactical_theme"],
                    "duration_min": dur,
                    "priority_score": float(nxt["priority_score"]),
                }
                day_entry["drills"].append(assignment)
                day_entry["scheduled_minutes"] += dur
                total_scheduled += dur
                day_remaining -= dur
                sessions += 1
                idx += 1
            else:
                break
        schedule_days.append(day_entry)
    result = {
        "target_weekly_minutes": target_weekly_minutes,
        "total_scheduled_minutes": total_scheduled,
        "days": schedule_days,
    }
    return result


def _load_inputs(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[Dict[str, Any]], Optional[Dict[str, bool]]]:
    drills_path = workspace / "input" / "drills_catalog.csv"
    profile_path = workspace / "input" / "player_profile.json"
    calendar_path = workspace / "input" / "calendar_constraints.yaml"
    drills_rows = _safe_load_csv(drills_path)
    profile = _safe_load_json(profile_path)
    calendar = _parse_calendar_yaml(calendar_path)
    return drills_rows, profile, calendar


def _load_outputs(workspace: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
    rankings_path = workspace / "output" / "drill_rankings.csv"
    weekly_plan_path = workspace / "output" / "weekly_plan.json"
    rankings_rows_raw = _safe_load_csv(rankings_path)
    rankings_rows: Optional[List[Dict[str, Any]]] = None
    if rankings_rows_raw is not None:
        rankings_rows = []
        for row in rankings_rows_raw:
            try:
                item = {
                    "drill_id": row["drill_id"].strip(),
                    "name": row["name"].strip(),
                    "tactical_theme": row["tactical_theme"].strip(),
                    "intensity": _safe_parse_int(row["intensity"]),
                    "duration_min": _safe_parse_int(row["duration_min"]),
                    "ball_work": _safe_parse_int(row["ball_work"]),
                    "priority_score": _safe_parse_float(row["priority_score"]),
                }
            except Exception:
                item = None
            if item is None or any(v is None for k, v in item.items() if k in ("intensity", "duration_min", "ball_work", "priority_score")):
                rankings_rows = None
                break
            rankings_rows.append(item)
    weekly_plan = _safe_load_json(weekly_plan_path)
    return rankings_rows, weekly_plan


def _check_rankings_header(workspace: Path) -> float:
    path = workspace / "output" / "drill_rankings.csv"
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            exp = ["drill_id", "name", "tactical_theme", "intensity", "duration_min", "ball_work", "priority_score"]
            if header == exp:
                return 1.0
            else:
                return 0.0
    except Exception:
        return 0.0


def _compare_rankings(actual: List[Dict[str, Any]], expected: List[Dict[str, Any]]) -> float:
    if actual is None or expected is None:
        return 0.0
    if len(actual) != len(expected):
        return 0.0
    for a, e in zip(actual, expected):
        if a["drill_id"] != e["drill_id"]:
            return 0.0
        if a["name"] != e["name"]:
            return 0.0
        if a["tactical_theme"] != e["tactical_theme"]:
            return 0.0
        if int(a["intensity"]) != int(e["intensity"]):
            return 0.0
        if int(a["duration_min"]) != int(e["duration_min"]):
            return 0.0
        if int(a["ball_work"]) != int(e["ball_work"]):
            return 0.0
        af = float(a["priority_score"])
        ef = float(e["priority_score"])
        if abs(af - ef) > 1e-6:
            return 0.0
    return 1.0


def _validate_weekly_plan_structure(plan: Dict[str, Any]) -> float:
    if not isinstance(plan, dict):
        return 0.0
    if "target_weekly_minutes" not in plan or "total_scheduled_minutes" not in plan or "days" not in plan:
        return 0.0
    if not isinstance(plan["target_weekly_minutes"], int):
        return 0.0
    if not isinstance(plan["total_scheduled_minutes"], int):
        return 0.0
    days = plan["days"]
    if not isinstance(days, list) or len(days) != 7:
        return 0.0
    expected_days = _day_names()
    for i, day_entry in enumerate(days):
        if not isinstance(day_entry, dict):
            return 0.0
        if day_entry.get("day") != expected_days[i]:
            return 0.0
        sm = day_entry.get("scheduled_minutes")
        dr = day_entry.get("drills")
        if not isinstance(sm, int):
            return 0.0
        if not isinstance(dr, list):
            return 0.0
        for d in dr:
            if not isinstance(d, dict):
                return 0.0
            for key in ("drill_id", "name", "tactical_theme"):
                if key not in d or not isinstance(d[key], str):
                    return 0.0
            if "duration_min" not in d or not isinstance(d["duration_min"], int):
                return 0.0
            if "priority_score" not in d:
                return 0.0
            ps = d["priority_score"]
            if not isinstance(ps, (int, float)):
                return 0.0
        if sm != sum(int(d["duration_min"]) for d in dr):
            return 0.0
    return 1.0


def _cross_check_plan_vs_rankings(plan: Dict[str, Any], rankings: List[Dict[str, Any]]) -> float:
    if plan is None or rankings is None:
        return 0.0
    id_to_score: Dict[str, float] = {}
    for r in rankings:
        id_to_score[r["drill_id"]] = float(r["priority_score"])
    for day in plan.get("days", []):
        for d in day.get("drills", []):
            did = d.get("drill_id")
            ps = float(d.get("priority_score"))
            if did not in id_to_score:
                return 0.0
            if abs(ps - id_to_score[did]) > 1e-6:
                return 0.0
    return 1.0


def _check_schedule_constraints(plan: Dict[str, Any], profile: Dict[str, Any], calendar: Dict[str, bool]) -> float:
    try:
        target = int(profile.get("target_weekly_minutes"))
        max_daily = int(profile.get("max_daily_minutes"))
        cap = int(profile.get("sessions_per_day_cap"))
    except Exception:
        return 0.0
    days = plan.get("days", [])
    if not isinstance(days, list) or len(days) != 7:
        return 0.0
    total = 0
    day_order = _day_names()
    for i, day_entry in enumerate(days):
        day_name = day_order[i]
        available = bool(calendar.get(day_name, False))
        sm = int(day_entry.get("scheduled_minutes", 0))
        drs = day_entry.get("drills", [])
        if not available:
            if sm != 0 or len(drs) != 0:
                return 0.0
        if available:
            if sm > max_daily:
                return 0.0
            if len(drs) > cap:
                return 0.0
            if sm != sum(int(d.get("duration_min", 0)) for d in drs):
                return 0.0
        total += sm
    if total > target:
        return 0.0
    if total < max(target - 15, 0):
        return 0.0
    if plan.get("total_scheduled_minutes") != total:
        return 0.0
    if plan.get("target_weekly_minutes") != target:
        return 0.0
    return 1.0


def _plan_matches_expected(plan: Dict[str, Any], expected: Dict[str, Any]) -> float:
    if plan is None or expected is None:
        return 0.0
    if plan.get("target_weekly_minutes") != expected.get("target_weekly_minutes"):
        return 0.0
    if plan.get("total_scheduled_minutes") != expected.get("total_scheduled_minutes"):
        return 0.0
    p_days = plan.get("days")
    e_days = expected.get("days")
    if not isinstance(p_days, list) or not isinstance(e_days, list) or len(p_days) != len(e_days):
        return 0.0
    for pd, ed in zip(p_days, e_days):
        if pd.get("day") != ed.get("day"):
            return 0.0
        if pd.get("scheduled_minutes") != ed.get("scheduled_minutes"):
            return 0.0
        pdr = pd.get("drills", [])
        edr = ed.get("drills", [])
        if len(pdr) != len(edr):
            return 0.0
        for a, b in zip(pdr, edr):
            if a.get("drill_id") != b.get("drill_id"):
                return 0.0
            if a.get("name") != b.get("name"):
                return 0.0
            if a.get("tactical_theme") != b.get("tactical_theme"):
                return 0.0
            if a.get("duration_min") != b.get("duration_min"):
                return 0.0
            af = float(a.get("priority_score"))
            bf = float(b.get("priority_score"))
            if abs(af - bf) > 1e-6:
                return 0.0
    return 1.0


def _plan_is_prefix_of_ranking(plan: Dict[str, Any], eligible_sorted: List[Dict[str, Any]]) -> float:
    if plan is None or eligible_sorted is None:
        return 0.0
    planned_ids: List[str] = []
    for day in plan.get("days", []):
        for d in day.get("drills", []):
            planned_ids.append(d.get("drill_id"))
    eligible_ids = [d["drill_id"] for d in eligible_sorted]
    if len(planned_ids) > len(eligible_ids):
        return 0.0
    if planned_ids != eligible_ids[:len(planned_ids)]:
        return 0.0
    return 1.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "drill_rankings_exists": 0.0,
        "drill_rankings_header_correct": 0.0,
        "drill_rankings_content_correct": 0.0,
        "weekly_plan_exists": 0.0,
        "weekly_plan_structure_correct": 0.0,
        "weekly_plan_schedule_constraints": 0.0,
        "weekly_plan_cross_check_with_rankings": 0.0,
        "weekly_plan_matches_expected": 0.0,
        "plan_follows_rank_order_prefix": 0.0,
    }

    drills_rows, profile, calendar = _load_inputs(workspace)

    expected_rankings: Optional[List[Dict[str, Any]]] = None
    expected_plan: Optional[Dict[str, Any]] = None
    eligible_sorted: Optional[List[Dict[str, Any]]] = None
    inputs_ok = (drills_rows is not None and isinstance(profile, dict) and isinstance(calendar, dict))
    if inputs_ok:
        eligible_sorted = _build_eligible_sorted(drills_rows, profile)
        expected_rankings = [
            {
                "drill_id": d["drill_id"],
                "name": d["name"],
                "tactical_theme": d["tactical_theme"],
                "intensity": int(d["intensity"]),
                "duration_min": int(d["duration_min"]),
                "ball_work": int(d["ball_work"]),
                "priority_score": float(d["priority_score"]),
            }
            for d in eligible_sorted
        ]
        try:
            target = int(profile.get("target_weekly_minutes"))
            max_daily = int(profile.get("max_daily_minutes"))
            cap = int(profile.get("sessions_per_day_cap"))
        except Exception:
            target = None
            max_daily = None
            cap = None
        if target is not None and max_daily is not None and cap is not None:
            expected_plan = _build_expected_schedule(eligible_sorted, calendar, target, max_daily, cap)

    rankings_rows, weekly_plan = _load_outputs(workspace)
    scores["drill_rankings_exists"] = 1.0 if rankings_rows is not None else 0.0
    scores["weekly_plan_exists"] = 1.0 if isinstance(weekly_plan, dict) else 0.0

    scores["drill_rankings_header_correct"] = _check_rankings_header(workspace) if rankings_rows is not None else 0.0

    if rankings_rows is not None and expected_rankings is not None:
        scores["drill_rankings_content_correct"] = _compare_rankings(rankings_rows, expected_rankings)
    else:
        scores["drill_rankings_content_correct"] = 0.0

    if isinstance(weekly_plan, dict):
        scores["weekly_plan_structure_correct"] = _validate_weekly_plan_structure(weekly_plan)
    else:
        scores["weekly_plan_structure_correct"] = 0.0

    if isinstance(weekly_plan, dict) and rankings_rows is not None:
        scores["weekly_plan_cross_check_with_rankings"] = _cross_check_plan_vs_rankings(weekly_plan, rankings_rows)
    else:
        scores["weekly_plan_cross_check_with_rankings"] = 0.0

    if isinstance(weekly_plan, dict) and isinstance(profile, dict) and isinstance(calendar, dict):
        scores["weekly_plan_schedule_constraints"] = _check_schedule_constraints(weekly_plan, profile, calendar)
    else:
        scores["weekly_plan_schedule_constraints"] = 0.0

    if isinstance(weekly_plan, dict) and expected_plan is not None:
        scores["weekly_plan_matches_expected"] = _plan_matches_expected(weekly_plan, expected_plan)
    else:
        scores["weekly_plan_matches_expected"] = 0.0

    if isinstance(weekly_plan, dict) and eligible_sorted is not None:
        scores["plan_follows_rank_order_prefix"] = _plan_is_prefix_of_ranking(weekly_plan, eligible_sorted)
    else:
        scores["plan_follows_rank_order_prefix"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()