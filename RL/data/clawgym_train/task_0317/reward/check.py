import json
import csv
import sys
import math
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _parse_home_yaml(path: Path) -> Optional[dict]:
    """
    Minimal YAML parser for the simple scalar key: value pairs in input/home.yaml.
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    result: Dict[str, object] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Strip quotes if present
        if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
            val = val[1:-1]
        # Try to cast to int or float
        if key in {"home_lat", "home_lng"}:
            try:
                result[key] = float(val)
            except Exception:
                return None
        elif key in {"radius_km", "min_teammates", "top_n"}:
            try:
                result[key] = int(val)
            except Exception:
                try:
                    result[key] = int(float(val))
                except Exception:
                    return None
        elif key in {"my_team", "planning_window"}:
            result[key] = val
        else:
            # ignore unknown keys but keep flexibility
            result[key] = val
    required = ["my_team", "home_lat", "home_lng", "radius_km", "planning_window", "min_teammates", "top_n"]
    if not all(k in result for k in required):
        return None
    return result


def _parse_intel_notes(path: Path) -> Optional[Dict[str, str]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    notes: Dict[str, str] = {}
    for line in text.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("- "):
            # Pattern: - <gym_name>: <note>
            m = re.match(r"-\s*(.+?):\s*(.+)\s*$", line_stripped)
            if m:
                gym_name = m.group(1).strip()
                note = m.group(2).strip()
                notes[gym_name] = note
    return notes


def _to_minutes(hhmm: str) -> Optional[int]:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", hhmm)
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2))
    if h < 0 or h > 23 or mi < 0 or mi > 59:
        return None
    return h * 60 + mi


def _minutes_to_hhmm(minutes: int) -> str:
    minutes = minutes % (24 * 60)
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _compute_availability_boundary_time_and_players(avail: dict, planning_window: str, min_teammates: int) -> Tuple[Optional[str], List[str]]:
    # planning_window format "HH:MM-HH:MM"
    if "-" not in planning_window:
        return None, []
    start_str, end_str = planning_window.split("-", 1)
    start_min = _to_minutes(start_str.strip())
    end_min = _to_minutes(end_str.strip())
    if start_min is None or end_min is None:
        return None, []
    # Generate 30-minute boundaries inclusive of start and end
    boundaries = list(range(start_min, end_min + 1, 30))
    players_info = avail.get("players", []) if isinstance(avail, dict) else []
    def available_at(t: int, player: dict) -> bool:
        wins = player.get("windows", [])
        for w in wins:
            s = _to_minutes(w.get("start", ""))
            e = _to_minutes(w.get("end", ""))
            if s is None or e is None:
                continue
            # Inclusive start and end boundary
            if s <= t <= e:
                return True
        return False
    chosen_time = None
    chosen_players: List[str] = []
    for t in boundaries:
        names = []
        for p in players_info:
            name = p.get("name")
            if not isinstance(name, str):
                continue
            if available_at(t, p):
                names.append(name)
        if len(names) >= min_teammates:
            chosen_time = _minutes_to_hhmm(t)
            chosen_players = sorted(names)
            break
    return chosen_time, chosen_players


def _load_inputs(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[dict], Optional[dict], Optional[Dict[str, str]]]:
    gyms = _safe_load_csv_dicts(workspace / "input" / "gyms.csv")
    availability = _safe_load_json(workspace / "input" / "availability.json")
    home = _parse_home_yaml(workspace / "input" / "home.yaml")
    notes = _parse_intel_notes(workspace / "input" / "intel_notes.md")
    return gyms, availability, home, notes


def _compute_expected_plan(gyms: List[Dict[str, str]], availability: dict, home: dict, notes: Dict[str, str]) -> Tuple[List[Dict[str, object]], Dict[str, Dict[str, object]]]:
    """
    Returns:
      - selected list of gym dicts with computed fields
      - index of gym_id to computed fields
    """
    home_lat = float(home["home_lat"])
    home_lng = float(home["home_lng"])
    radius_km = float(home["radius_km"])
    my_team = str(home["my_team"])
    top_n = int(home["top_n"])

    # compute availability time and players
    rec_time, _ = _compute_availability_boundary_time_and_players(availability, str(home["planning_window"]), int(home["min_teammates"]))

    computed: List[Dict[str, object]] = []
    for row in gyms:
        try:
            lat = float(row["latitude"])
            lng = float(row["longitude"])
            controlling_team = str(row["controlling_team"])
            defenders_count = int(row["defenders_count"])
            turnover_rate = float(row["turnover_rate"])
            gym_id = row["gym_id"]
            gym_name = row["gym_name"]
        except Exception:
            continue
        dist = _haversine_km(home_lat, home_lng, lat, lng)
        if controlling_team == my_team:
            continue
        if dist > radius_km:
            continue
        vulnerability = 0.6 * (10 - defenders_count) + 0.4 * turnover_rate - 0.2 * dist
        note = notes.get(gym_name, "")
        computed.append({
            "gym_id": gym_id,
            "gym_name": gym_name,
            "controlling_team": controlling_team,
            "defenders_count": defenders_count,
            "turnover_rate": turnover_rate,
            "distance_km": dist,
            "vulnerability_score": vulnerability,
            "recommended_arrival_time": rec_time,
            "notes": note,
        })
    # sort
    computed_sorted = sorted(
        computed,
        key=lambda r: (
            -r["vulnerability_score"],
            r["distance_km"],
            r["defenders_count"],
            r["gym_name"],
        ),
    )
    selected = computed_sorted[:top_n]
    index = {r["gym_id"]: r for r in computed_sorted}
    return selected, index


def _parse_plan_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None, None
    if not rows:
        return None, None
    header = rows[0]
    data_rows = []
    for r in rows[1:]:
        if not any(cell.strip() for cell in r):
            continue
        row_dict = {}
        for i, h in enumerate(header):
            row_dict[h] = r[i] if i < len(r) else ""
        data_rows.append(row_dict)
    return header, data_rows


def _extract_last_nonempty_line(text: str) -> str:
    lines = [ln.rstrip("\r\n") for ln in text.splitlines()]
    for ln in reversed(lines):
        if ln.strip():
            return ln.strip()
    return ""


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "compute_script_present": 0.0,
        "plan_csv_structure_and_count": 0.0,
        "plan_filtering_valid": 0.0,
        "plan_values_correct": 0.0,
        "plan_sorting_correct": 0.0,
        "plan_recommended_arrival_time_valid": 0.0,
        "plan_notes_alignment": 0.0,
        "summary_overview_and_counts": 0.0,
        "summary_availability_and_names": 0.0,
        "summary_top_targets_listed": 0.0,
        "summary_method_explained": 0.0,
        "validator_script_present": 0.0,
        "validation_txt_ends_with_valid": 0.0,
    }

    # Check scripts existence
    compute_script = workspace / "scripts" / "compute_plan.py"
    if compute_script.exists():
        scores["compute_script_present"] = 1.0

    validator_script = workspace / "scripts" / "check_plan.py"
    if validator_script.exists():
        scores["validator_script_present"] = 1.0

    # Load inputs
    gyms, availability, home, notes = _load_inputs(workspace)

    plan_path = workspace / "out" / "target_plan.csv"
    header, plan_rows = _parse_plan_csv(plan_path)

    # Structure and count check
    expected_header = [
        "gym_id",
        "gym_name",
        "controlling_team",
        "defenders_count",
        "turnover_rate",
        "distance_km",
        "vulnerability_score",
        "recommended_arrival_time",
        "notes",
    ]
    structure_ok = False
    count_ok = False
    if header is not None and plan_rows is not None and home is not None:
        structure_ok = header == expected_header
        try:
            top_n = int(home["top_n"])
        except Exception:
            top_n = None
        count_ok = (top_n is not None and len(plan_rows) == top_n)
    if structure_ok and count_ok:
        scores["plan_csv_structure_and_count"] = 1.0

    # If inputs and plan rows available, perform deeper checks
    if gyms is not None and availability is not None and home is not None and notes is not None and plan_rows is not None and header is not None and header == expected_header:
        # Build gyms index by gym_id and gym_name for validation
        gyms_by_id = {row["gym_id"]: row for row in gyms}

        # Compute expected plan selection and index
        expected_selected, expected_index = _compute_expected_plan(gyms, availability, home, notes)

        # Plan filtering constraints
        filtering_ok = True
        # Precompute rec_time
        rec_time, rec_players = _compute_availability_boundary_time_and_players(availability, str(home["planning_window"]), int(home["min_teammates"]))
        # derive values from home
        home_lat = float(home["home_lat"])
        home_lng = float(home["home_lng"])
        radius_km = float(home["radius_km"])
        my_team = str(home["my_team"])
        for row in plan_rows:
            gid = row.get("gym_id", "")
            g = gyms_by_id.get(gid)
            if g is None:
                filtering_ok = False
                break
            # check team
            if str(g["controlling_team"]) == my_team:
                filtering_ok = False
                break
            # distance within radius
            try:
                glat = float(g["latitude"])
                glng = float(g["longitude"])
            except Exception:
                filtering_ok = False
                break
            dist = _haversine_km(home_lat, home_lng, glat, glng)
            # Allow small tolerance for rounding
            if dist - float(radius_km) > 0.25:
                filtering_ok = False
                break
        if filtering_ok:
            scores["plan_filtering_valid"] = 1.0

        # Plan values correctness (distance and vulnerability within tolerance)
        values_ok = True
        for row in plan_rows:
            gid = row.get("gym_id", "")
            g = gyms_by_id.get(gid)
            if g is None:
                values_ok = False
                break
            try:
                glat = float(g["latitude"])
                glng = float(g["longitude"])
                defenders = int(g["defenders_count"])
                turnover = float(g["turnover_rate"])
            except Exception:
                values_ok = False
                break
            dist_true = _haversine_km(home_lat, home_lng, glat, glng)
            vuln_true = 0.6 * (10 - defenders) + 0.4 * turnover - 0.2 * dist_true
            try:
                dist_csv = float(row["distance_km"])
                vuln_csv = float(row["vulnerability_score"])
            except Exception:
                values_ok = False
                break
            if abs(dist_csv - dist_true) > 0.3 or abs(vuln_csv - vuln_true) > 0.3:
                values_ok = False
                break
        if values_ok:
            scores["plan_values_correct"] = 1.0

        # Plan sorting correctness
        sorting_ok = True
        # expected order: first top_n expected_selected gym_ids
        expected_ids = [d["gym_id"] for d in expected_selected]
        observed_ids = [r["gym_id"] for r in plan_rows]
        if observed_ids != expected_ids:
            sorting_ok = False
        if sorting_ok:
            scores["plan_sorting_correct"] = 1.0

        # Recommended arrival time correctness: all rows must have same time and match computed
        rat_ok = False
        if rec_time is not None:
            rat_values = {r["recommended_arrival_time"] for r in plan_rows}
            if len(rat_values) == 1 and rec_time in rat_values:
                rat_ok = True
        if rat_ok:
            scores["plan_recommended_arrival_time_valid"] = 1.0

        # Notes alignment correctness
        notes_ok = True
        # Build mapping from gym_name to expected note
        notes_map = notes
        for r in plan_rows:
            gid = r.get("gym_id", "")
            g = gyms_by_id.get(gid)
            if g is None:
                notes_ok = False
                break
            gname = g["gym_name"]
            expected_note = notes_map.get(gname, "")
            actual_note = (r.get("notes", "") or "").strip()
            if (expected_note or "") != actual_note:
                notes_ok = False
                break
        if notes_ok:
            scores["plan_notes_alignment"] = 1.0

        # Summary report checks
        summary_path = workspace / "out" / "summary_report.md"
        summary_text = _safe_read_text(summary_path) or ""
        if summary_text:
            # Overview: total gyms scanned, number within radius and not my_team, and selected top_n
            try:
                total_gyms = len(gyms)
                considered_count = len([1 for row in gyms if (row.get("controlling_team") != my_team and _haversine_km(home_lat, home_lng, float(row["latitude"]), float(row["longitude"])) <= radius_km)])
            except Exception:
                total_gyms = None
                considered_count = None

            overview_ok = True
            if total_gyms is None or considered_count is None:
                overview_ok = False
            else:
                # Check for 'Overview' word and numbers presence
                has_overview_word = re.search(r"\boverview\b", summary_text, flags=re.IGNORECASE) is not None
                has_total = str(total_gyms) in summary_text
                has_considered = str(considered_count) in summary_text
                has_topn = str(int(home["top_n"])) in summary_text
                overview_ok = has_overview_word and has_total and has_considered and has_topn
            if overview_ok:
                scores["summary_overview_and_counts"] = 1.0

            # Availability Summary: chosen recommended_arrival_time and which players are available at that time
            avail_ok = False
            if rec_time is not None:
                # names available at that time
                _, rec_players = _compute_availability_boundary_time_and_players(availability, str(home["planning_window"]), int(home["min_teammates"]))
                if rec_players is None:
                    rec_players = []
                time_present = rec_time in summary_text
                names_present = all(name in summary_text for name in rec_players)
                avail_ok = time_present and names_present
            if avail_ok:
                scores["summary_availability_and_names"] = 1.0

            # Top Targets: ensure each selected gym name appears in summary
            top_targets_ok = True
            for d in expected_selected:
                if d["gym_name"] not in summary_text:
                    top_targets_ok = False
                    break
            if top_targets_ok:
                scores["summary_top_targets_listed"] = 1.0

            # Method: mentions formula and filtering/sorting rules
            method_ok = False
            lower = summary_text.lower()
            has_vuln = ("vulnerability_score" in lower) or ("vulnerability score" in lower)
            has_coeffs = ("0.6" in summary_text and "0.4" in summary_text and "0.2" in summary_text)
            has_sort = ("sort" in lower or "sorted" in lower or "ranking" in lower)
            has_distance = ("haversine" in lower or "distance" in lower)
            has_filter = ("radius" in lower and ("my_team" in summary_text or "my team" in lower))
            method_ok = has_vuln and has_coeffs and has_sort and has_distance and has_filter
            if method_ok:
                scores["summary_method_explained"] = 1.0

    # Validation output check
    validation_path = workspace / "out" / "validation.txt"
    val_text = _safe_read_text(validation_path)
    if val_text is not None:
        last_line = _extract_last_nonempty_line(val_text)
        if last_line == "VALID":
            scores["validation_txt_ends_with_valid"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()