import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _parse_bool(s: str) -> Optional[bool]:
    if s is None:
        return None
    ss = s.strip().lower()
    if ss in ("true", "yes", "y", "1"):
        return True
    if ss in ("false", "no", "n", "0"):
        return False
    return None


def _parse_number(s: str) -> Optional[float]:
    if s is None:
        return None
    try:
        if "." in s or "e" in s.lower():
            return float(s)
        return float(int(s))
    except Exception:
        return None


def _parse_simple_yaml(text: str) -> Optional[Dict[str, Any]]:
    # Minimal YAML parser for the given constraints.yaml structure.
    # Supports:
    # - key: value
    # - key:
    #       - list items
    # - nested dicts with indentation
    # - quoted strings
    # - numbers and booleans
    def parse_value(val: str) -> Any:
        v = val.strip()
        if v.startswith('"') and v.endswith('"'):
            return v[1:-1]
        if v.startswith("'") and v.endswith("'"):
            return v[1:-1]
        bl = _parse_bool(v)
        if bl is not None:
            return bl
        num = _parse_number(v)
        if num is not None:
            # cast int if it is integer-like
            if abs(num - int(num)) < 1e-12:
                return int(num)
            return num
        return v

    raw_lines = text.splitlines()
    lines: List[Tuple[int, str]] = []
    for raw in raw_lines:
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        content = raw.lstrip(" ")
        lines.append((indent, content))

    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Any]] = [(-1, root)]

    i = 0
    n = len(lines)
    while i < n:
        indent, content = lines[i]
        # Pop to current indent
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1] if stack else root

        if content.startswith("- "):
            # List item
            if not isinstance(parent, list):
                # Invalid structure for our minimal parser
                return None
            item_str = content[2:].strip()
            if ":" in item_str and not (item_str.startswith('"') or item_str.startswith("'")):
                # Could be a dict introduced inline, but for our file we won't need this case.
                key, val = item_str.split(":", 1)
                key = key.strip()
                val = val.strip()
                if val:
                    parent.append({key: parse_value(val)})
                else:
                    new_map: Dict[str, Any] = {}
                    parent.append({key: new_map})
                    # Next line(s) should define nested under this key
                    # Push new_map with current indent
                    stack.append((indent, new_map))
            else:
                parent.append(parse_value(item_str))
            i += 1
            continue

        # Key with colon
        if ":" in content:
            key, val = content.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val:
                if isinstance(parent, dict):
                    parent[key] = parse_value(val)
                else:
                    return None
                i += 1
                continue
            else:
                # Need to determine if next block is list or dict
                # Look ahead
                next_container: Any
                j = i + 1
                # Find next non-empty line with greater indent
                next_is_list = False
                while j < n:
                    ind2, cont2 = lines[j]
                    if ind2 <= indent:
                        break
                    if cont2.strip().startswith("- "):
                        next_is_list = True
                        break
                    else:
                        next_is_list = False
                        break
                if next_is_list:
                    next_container = []
                else:
                    next_container = {}
                if isinstance(parent, dict):
                    parent[key] = next_container
                else:
                    return None
                # Push new container
                stack.append((indent, next_container))
                i += 1
                continue
        else:
            # Bare content not expected
            return None

    return root


def _euclidean_distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _near(a: float, b: float, tol: float = 1e-3) -> bool:
    return abs(a - b) <= tol


def _float_or_zero(s: Any) -> float:
    try:
        return float(s)
    except Exception:
        return 0.0


def _int_or_zero(s: Any) -> int:
    try:
        return int(float(s))
    except Exception:
        return 0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "schedule_csv_present_and_columns": 0.0,
        "schedule_days_and_volunteers_coverage": 0.0,
        "schedule_start_end_kohima_and_seq": 0.0,
        "schedule_travel_consistency": 0.0,
        "schedule_session_and_impact_consistency": 0.0,
        "schedule_cumulative_hours_consistency": 0.0,
        "constraint_daily_hours_respected": 0.0,
        "constraint_at_most_once_across_days": 0.0,
        "constraint_max_villages_per_day_per_volunteer": 0.0,
        "constraint_mandatory_villages_covered_when_feasible": 0.0,
        "impact_summary_present_and_structure": 0.0,
        "impact_summary_totals_consistent": 0.0,
        "validation_report_present_and_mentions_checks": 0.0,
        "email_to_volunteers_present_and_sections": 0.0,
    }

    input_dir = workspace / "input"
    output_dir = workspace / "output"

    villages_csv = input_dir / "villages.csv"
    locations_csv = input_dir / "locations.csv"
    volunteers_csv = input_dir / "volunteers.csv"
    constraints_yaml = input_dir / "constraints.yaml"

    schedule_csv = output_dir / "schedule.csv"
    impact_summary_json = output_dir / "impact_summary.json"
    validation_report_txt = output_dir / "validation_report.txt"
    email_txt = output_dir / "email_to_volunteers.txt"

    villages = _safe_read_csv(villages_csv)
    locations = _safe_read_csv(locations_csv)
    volunteers = _safe_read_csv(volunteers_csv)
    constraints_text = _safe_read_text(constraints_yaml)
    constraints = _parse_simple_yaml(constraints_text) if constraints_text else None

    # Prepare mappings if available
    village_info: Dict[str, Dict[str, float]] = {}
    if villages:
        try:
            for row in villages:
                name = row.get("village_name", "").strip()
                if not name:
                    continue
                village_info[name] = {
                    "women_population_estimate": float(row["women_population_estimate"]),
                    "safety_index": float(row["safety_index"]),
                    "session_duration_hours": float(row["session_duration_hours"]),
                    "priority_weight": float(row["priority_weight"]),
                    "district": row.get("district", "").strip(),
                }
        except Exception:
            village_info = {}

    location_coords: Dict[str, Tuple[float, float]] = {}
    if locations:
        try:
            for row in locations:
                nm = row.get("location_name", "").strip()
                x = float(row.get("x_km", "0"))
                y = float(row.get("y_km", "0"))
                if nm:
                    location_coords[nm] = (x, y)
        except Exception:
            location_coords = {}

    volunteer_info: Dict[str, Dict[str, Any]] = {}
    if volunteers:
        try:
            for row in volunteers:
                name = row.get("volunteer_name", "").strip()
                if not name:
                    continue
                speed = float(row.get("speed_kmph", "0"))
                daily_max = float(row.get("daily_max_hours", "0"))
                avail_day1 = _parse_bool(row.get("available_day1", "no"))
                avail_day2 = _parse_bool(row.get("available_day2", "no"))
                volunteer_info[name] = {
                    "speed_kmph": speed,
                    "daily_max_hours": daily_max,
                    "available_day1": bool(avail_day1),
                    "available_day2": bool(avail_day2),
                }
        except Exception:
            volunteer_info = {}

    # Parse constraints
    day_labels: List[str] = []
    must_start_end_at = None
    max_villages_per_day = None
    daily_max_hours_constraint = None
    mandatory_villages: List[str] = []
    if isinstance(constraints, dict):
        try:
            if isinstance(constraints.get("day_labels"), list):
                day_labels = [str(x) for x in constraints.get("day_labels", [])]
            must_start_end_at = constraints.get("must_start_end_at")
            max_villages_per_day = constraints.get("max_villages_per_day_per_volunteer")
            if isinstance(constraints.get("constraints"), dict):
                cst = constraints.get("constraints", {})
                daily_max_hours_constraint = cst.get("daily_max_hours")
                mv = cst.get("mandatory_villages")
                if isinstance(mv, list):
                    mandatory_villages = [str(x) for x in mv]
        except Exception:
            pass

    # Read schedule
    schedule_rows = _safe_read_csv(schedule_csv)
    schedule_ok = False
    required_cols = [
        "day",
        "volunteer",
        "seq",
        "location_name",
        "travel_km_from_prev",
        "travel_hours_from_prev",
        "session_hours",
        "impact_score_for_stop",
        "cumulative_hours",
    ]
    if schedule_rows is not None:
        # Validate header order exactly
        try:
            with schedule_csv.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
            if header == required_cols:
                schedule_ok = True
        except Exception:
            schedule_ok = False

    if schedule_ok:
        scores["schedule_csv_present_and_columns"] = 1.0

    # If schedule ok, perform deeper checks
    used_days = set()
    group_map: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    violations: List[str] = []
    visited_villages_all: List[str] = []

    if schedule_ok:
        # Group by (day, volunteer)
        try:
            # coerce and collect
            for r in schedule_rows:
                day = r.get("day", "").strip()
                volunteer = r.get("volunteer", "").strip()
                used_days.add(day)
                seq = _int_or_zero(r.get("seq"))
                loc = r.get("location_name", "").strip()
                tk = _float_or_zero(r.get("travel_km_from_prev"))
                th = _float_or_zero(r.get("travel_hours_from_prev"))
                sh = _float_or_zero(r.get("session_hours"))
                iscore = _float_or_zero(r.get("impact_score_for_stop"))
                ch = _float_or_zero(r.get("cumulative_hours"))
                row = {
                    "day": day,
                    "volunteer": volunteer,
                    "seq": seq,
                    "location_name": loc,
                    "travel_km_from_prev": tk,
                    "travel_hours_from_prev": th,
                    "session_hours": sh,
                    "impact_score_for_stop": iscore,
                    "cumulative_hours": ch,
                }
                group_map.setdefault((day, volunteer), []).append(row)
            # Sort each group by seq
            for key in group_map:
                group_map[key].sort(key=lambda x: x["seq"])
        except Exception:
            group_map = {}

    # schedule_days_and_volunteers_coverage: ensure all day labels used and each available volunteer has a plan
    if schedule_ok and day_labels and volunteer_info:
        coverage_ok = True
        # Must include exactly those labels
        if set(day_labels) != used_days:
            coverage_ok = False
        # For each day label and each available volunteer, there must be a group present
        for idx, dlabel in enumerate(day_labels, start=1):
            for vname, vinfo in volunteer_info.items():
                avail_key = f"available_day{idx}"
                if vinfo.get(avail_key):
                    if (dlabel, vname) not in group_map:
                        coverage_ok = False
        scores["schedule_days_and_volunteers_coverage"] = 1.0 if coverage_ok else 0.0

    # start/end Kohima and seq checks
    if schedule_ok and must_start_end_at and group_map:
        start_end_ok = True
        seq_ok = True
        for (day, volunteer), rows in group_map.items():
            if not rows:
                start_end_ok = False
                seq_ok = False
                continue
            # Seq starts at 0 and increases by 1
            for i, r in enumerate(rows):
                if r["seq"] != i:
                    seq_ok = False
                    break
            # Start and end at Kohima (must_start_end_at)
            if rows[0]["location_name"] != must_start_end_at:
                start_end_ok = False
            if rows[-1]["location_name"] != must_start_end_at:
                start_end_ok = False
            # For first row, check zeros
            if rows[0]["seq"] != 0 or rows[0]["travel_km_from_prev"] != 0 or rows[0]["travel_hours_from_prev"] != 0 or rows[0]["session_hours"] != 0 or rows[0]["impact_score_for_stop"] != 0 or rows[0]["cumulative_hours"] != 0:
                seq_ok = False
        if start_end_ok and seq_ok:
            scores["schedule_start_end_kohima_and_seq"] = 1.0

    # Travel consistency and session/impact consistency and cumulative hours
    travel_ok = False
    session_impact_ok = False
    cumulative_ok = False
    daily_hours_ok = False
    at_most_once_ok = False
    max_villages_ok = False
    mandatory_ok = False

    if schedule_ok and group_map and location_coords and volunteer_info and village_info:
        travel_ok = True
        session_impact_ok = True
        cumulative_ok = True
        daily_hours_ok = True
        max_villages_ok = True

        visited_set: set = set()
        duplicate_found = False

        for (day, volunteer), rows in group_map.items():
            vinfo = volunteer_info.get(volunteer, {})
            speed = float(vinfo.get("speed_kmph", 0.0))
            # Recompute per group
            prev_loc = None
            prev_cum = 0.0
            villages_count = 0
            for idx, r in enumerate(rows):
                loc = r["location_name"]
                # Record visited villages (non-Kohima)
                if loc != must_start_end_at and loc in village_info:
                    visited_villages_all.append(loc)
                    villages_count += 1
                    if loc in visited_set:
                        duplicate_found = True
                    else:
                        visited_set.add(loc)
                # Travel checks
                if idx == 0:
                    if not _near(r["travel_km_from_prev"], 0.0) or not _near(r["travel_hours_from_prev"], 0.0):
                        travel_ok = False
                else:
                    if prev_loc not in location_coords or loc not in location_coords:
                        travel_ok = False
                    else:
                        dist = _euclidean_distance(location_coords[prev_loc], location_coords[loc])
                        if not _near(r["travel_km_from_prev"], dist, tol=1e-3):
                            travel_ok = False
                        # Travel hours
                        exp_hours = dist / speed if speed > 0 else float("inf")
                        if not _near(r["travel_hours_from_prev"], exp_hours, tol=1e-3):
                            travel_ok = False
                # Session and impact checks
                if loc == must_start_end_at:
                    if not _near(r["session_hours"], 0.0) or not _near(r["impact_score_for_stop"], 0.0):
                        session_impact_ok = False
                else:
                    if loc not in village_info:
                        session_impact_ok = False
                    else:
                        v = village_info[loc]
                        sess = v["session_duration_hours"]
                        if not _near(r["session_hours"], sess, tol=1e-6):
                            session_impact_ok = False
                        impact = v["priority_weight"] * v["women_population_estimate"] * v["safety_index"]
                        if not _near(r["impact_score_for_stop"], impact, tol=1e-3):
                            session_impact_ok = False
                # Cumulative hours
                if idx == 0:
                    if not _near(r["cumulative_hours"], 0.0):
                        cumulative_ok = False
                    prev_cum = r["cumulative_hours"]
                else:
                    expected_cum = prev_cum + r["travel_hours_from_prev"] + r["session_hours"]
                    if not _near(r["cumulative_hours"], expected_cum, tol=1e-3):
                        cumulative_ok = False
                    prev_cum = r["cumulative_hours"]
                prev_loc = loc

            # Max villages per day per volunteer check
            if isinstance(max_villages_per_day, int):
                if villages_count > max_villages_per_day:
                    max_villages_ok = False

            # Daily hours limit
            last_cum = rows[-1]["cumulative_hours"] if rows else 0.0
            personal_limit = float(vinfo.get("daily_max_hours", 0.0))
            limit = personal_limit
            if isinstance(daily_max_hours_constraint, (int, float)):
                limit = min(limit, float(daily_max_hours_constraint)) if limit > 0 else float(daily_max_hours_constraint)
            if last_cum - (limit if limit is not None else 0.0) > 1e-6:
                daily_hours_ok = False

        at_most_once_ok = not duplicate_found

        # Mandatory villages covered if feasible
        # Feasibility: if any available volunteer on any day can do a route K->mandatory->K within limits and max villages per day >=1
        mandatory_ok = True
        feasible_exists = False
        covered_set = set(visited_villages_all)
        for mv in mandatory_villages:
            if mv not in covered_set:
                # Check feasibility for this mv
                if mv in location_coords and must_start_end_at in location_coords and mv in village_info:
                    sess = village_info[mv]["session_duration_hours"]
                    dist = _euclidean_distance(location_coords[must_start_end_at], location_coords[mv])
                    for vname, vinfo in volunteer_info.items():
                        speed = float(vinfo.get("speed_kmph", 0.0))
                        personal_limit = float(vinfo.get("daily_max_hours", 0.0))
                        limit = personal_limit
                        if isinstance(daily_max_hours_constraint, (int, float)):
                            limit = min(limit, float(daily_max_hours_constraint)) if limit > 0 else float(daily_max_hours_constraint)
                        for idx, dlabel in enumerate(day_labels, start=1):
                            if vinfo.get(f"available_day{idx}", False):
                                travel_hours = (2.0 * dist) / speed if speed > 0 else float("inf")
                                total = travel_hours + sess
                                if isinstance(max_villages_per_day, int) and max_villages_per_day >= 1 and total <= limit + 1e-6:
                                    feasible_exists = True
                    # If feasible exists but not covered, violation
                    if feasible_exists:
                        mandatory_ok = False
                else:
                    # Cannot determine feasibility; mark as not feasible and don't penalize
                    pass

        if travel_ok:
            scores["schedule_travel_consistency"] = 1.0
        if session_impact_ok:
            scores["schedule_session_and_impact_consistency"] = 1.0
        if cumulative_ok:
            scores["schedule_cumulative_hours_consistency"] = 1.0
        if daily_hours_ok:
            scores["constraint_daily_hours_respected"] = 1.0
        if at_most_once_ok:
            scores["constraint_at_most_once_across_days"] = 1.0
        if max_villages_ok:
            scores["constraint_max_villages_per_day_per_volunteer"] = 1.0
        if mandatory_ok:
            scores["constraint_mandatory_villages_covered_when_feasible"] = 1.0

    # impact_summary checks
    impact_summary = _safe_read_json(impact_summary_json)
    if impact_summary is not None and isinstance(impact_summary, dict):
        # Structure checks
        has_keys = all(k in impact_summary for k in ["total_impact_score", "per_day_totals", "per_volunteer_totals", "villages_covered", "villages_uncovered", "constraint_checks"])
        structure_ok = has_keys and isinstance(impact_summary.get("per_day_totals"), dict) and isinstance(impact_summary.get("per_volunteer_totals"), dict) and isinstance(impact_summary.get("villages_covered"), list) and isinstance(impact_summary.get("villages_uncovered"), list) and isinstance(impact_summary.get("constraint_checks"), dict)
        if structure_ok:
            scores["impact_summary_present_and_structure"] = 1.0

        # Totals consistency
        totals_ok = False
        if schedule_ok and location_coords and volunteer_info and village_info and structure_ok:
            try:
                # Compute expected totals
                total_impact_expected = 0.0
                per_day_expected: Dict[str, Dict[str, float]] = {d: {"impact": 0.0, "count": 0.0} for d in day_labels} if day_labels else {}
                per_vol_expected: Dict[str, Dict[str, float]] = {v: {"hours": 0.0, "travel_km": 0.0, "session_hours": 0.0, "impact": 0.0} for v in volunteer_info.keys()}
                visited_set = set()
                for (day, volunteer), rows in group_map.items():
                    vinfo = volunteer_info.get(volunteer, {})
                    speed = float(vinfo.get("speed_kmph", 0.0))
                    prev = None
                    last_cum = 0.0
                    for idx, r in enumerate(rows):
                        loc = r["location_name"]
                        tk = r["travel_km_from_prev"]
                        th = r["travel_hours_from_prev"]
                        sh = r["session_hours"]
                        iscore = r["impact_score_for_stop"]
                        if loc != must_start_end_at and loc in village_info:
                            total_impact_expected += iscore
                            if day_labels:
                                if day in per_day_expected:
                                    per_day_expected[day]["impact"] += iscore
                                    per_day_expected[day]["count"] += 1.0
                            per_vol_expected[volunteer]["impact"] += iscore
                            per_vol_expected[volunteer]["session_hours"] += sh
                            visited_set.add(loc)
                        # travel
                        per_vol_expected[volunteer]["travel_km"] += tk
                        # hours
                        # We'll use cumulative on last row instead of summing to avoid rounding accumulation
                        if idx == len(rows) - 1:
                            per_vol_expected[volunteer]["hours"] += r["cumulative_hours"]
                        prev = loc

                # Compare with JSON
                json_total = float(impact_summary.get("total_impact_score", -1))
                totals_ok = _near(json_total, total_impact_expected, tol=1e-3)

                # per_day_totals
                json_pday = impact_summary.get("per_day_totals", {})
                if day_labels:
                    for d in day_labels:
                        if d not in json_pday:
                            totals_ok = False
                        else:
                            day_obj = json_pday[d]
                            # Accept keys 'impact' and 'count'
                            if not (isinstance(day_obj, dict) and "impact" in day_obj and "count" in day_obj):
                                totals_ok = False
                            else:
                                if not _near(float(day_obj["impact"]), per_day_expected[d]["impact"], tol=1e-3):
                                    totals_ok = False
                                if not _near(float(day_obj["count"]), per_day_expected[d]["count"], tol=1e-6):
                                    totals_ok = False

                # per_volunteer_totals
                json_pvol = impact_summary.get("per_volunteer_totals", {})
                for v in volunteer_info.keys():
                    if v not in json_pvol:
                        totals_ok = False
                    else:
                        pobj = json_pvol[v]
                        if not (isinstance(pobj, dict) and all(k in pobj for k in ["hours", "travel_km", "session_hours", "impact"])):
                            totals_ok = False
                        else:
                            if not _near(float(pobj["impact"]), per_vol_expected[v]["impact"], tol=1e-3):
                                totals_ok = False
                            if not _near(float(pobj["session_hours"]), per_vol_expected[v]["session_hours"], tol=1e-3):
                                totals_ok = False
                            if not _near(float(pobj["travel_km"]), per_vol_expected[v]["travel_km"], tol=1e-3):
                                totals_ok = False
                            if not _near(float(pobj["hours"]), per_vol_expected[v]["hours"], tol=1e-3):
                                totals_ok = False

                # villages covered/uncovered
                all_villages = set(village_info.keys())
                covered_json = set(impact_summary.get("villages_covered", []))
                uncovered_json = set(impact_summary.get("villages_uncovered", []))
                if covered_json | uncovered_json != all_villages or covered_json & uncovered_json:
                    totals_ok = False
            except Exception:
                totals_ok = False

        if totals_ok:
            scores["impact_summary_totals_consistent"] = 1.0

    # validation_report checks
    report_text = _safe_read_text(validation_report_txt)
    if report_text is not None:
        report_ok = True
        # Must include references to distances/hours
        lower = report_text.lower()
        if ("km" not in lower and "distance" not in lower) or "hour" not in lower:
            report_ok = False
        # If we identified violations above, report should mention violations
        any_violation = False
        # Derive violations summary based on schedule checks
        if scores["schedule_travel_consistency"] < 1.0 or scores["schedule_session_and_impact_consistency"] < 1.0 or scores["schedule_cumulative_hours_consistency"] < 1.0 or scores["constraint_daily_hours_respected"] < 1.0 or scores["constraint_at_most_once_across_days"] < 1.0 or scores["constraint_max_villages_per_day_per_volunteer"] < 1.0 or scores["constraint_mandatory_villages_covered_when_feasible"] < 1.0:
            any_violation = True
        if any_violation:
            if "violation" not in lower:
                report_ok = False
        else:
            if ("no violation" not in lower) and ("all constraints satisfied" not in lower):
                # Allow phrasing variation but require an explicit clean bill
                report_ok = False
        scores["validation_report_present_and_mentions_checks"] = 1.0 if report_ok else 0.0

    # email_to_volunteers checks
    email_text = _safe_read_text(email_txt)
    if email_text is not None:
        et = email_text
        lines = [ln.strip() for ln in et.splitlines() if ln.strip()]
        has_subject = any(ln.lower().startswith("subject:") for ln in lines)
        mentions_paths = ("output/schedule.csv" in et) and ("output/impact_summary.json" in et)
        mentions_mandatory = True
        if mandatory_villages:
                mentions_mandatory = any(mv in et for mv in mandatory_villages)
        has_bullets = any(ln.startswith(("-", "*")) for ln in lines)
        mentions_days = True if not day_labels else all(d in et for d in day_labels)
        mentions_volunteers = True if not volunteer_info else all(v in et for v in volunteer_info.keys())
        email_ok = has_subject and mentions_paths and mentions_mandatory and has_bullets and mentions_days and mentions_volunteers
        scores["email_to_volunteers_present_and_sections"] = 1.0 if email_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()