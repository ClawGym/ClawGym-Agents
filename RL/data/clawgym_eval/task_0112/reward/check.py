import json
import csv
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None, None


def _write_json_stdout(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False))


def _isclose(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _parse_int_safe(v: str) -> Optional[int]:
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return None


def _parse_float_safe(v: str) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def _parse_capacity_yaml(path: Path) -> Optional[Tuple[int, Dict[str, int]]]:
    # Minimal YAML parser tailored for the provided simple structure.
    # Expected keys: sprint_length_days: <int>, teams: - name: <str> capacity_story_points: <int>
    if not path.exists():
        return None
    try:
        sprint_length_days: Optional[int] = None
        capacities: Dict[str, int] = {}
        lines = path.read_text(encoding="utf-8").splitlines()
        in_teams = False
        current_team: Optional[Dict[str, str]] = None

        def _commit_current():
            nonlocal current_team
            if current_team is not None:
                name = current_team.get("name")
                cap_str = current_team.get("capacity_story_points")
                if name is not None and cap_str is not None:
                    cap_val = _parse_int_safe(cap_str)
                    if cap_val is not None:
                        capacities[name] = cap_val
            current_team = None

        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("sprint_length_days:"):
                # top-level key
                try:
                    _, val = line.split(":", 1)
                    sprint_length_days = int(val.strip())
                except Exception:
                    return None
            elif line.startswith("teams:"):
                in_teams = True
                continue
            elif in_teams:
                if line.startswith("- "):
                    # Commit previous if exists and start new
                    _commit_current()
                    current_team = {}
                    after_dash = line[2:].strip()
                    if after_dash:
                        # e.g., "name: Alpha"
                        if ":" in after_dash:
                            k, v = after_dash.split(":", 1)
                            current_team[k.strip()] = v.strip()
                else:
                    # indented k: v under current team
                    if current_team is not None and ":" in line:
                        k, v = line.split(":", 1)
                        current_team[k.strip()] = v.strip()
        # commit last team
        _commit_current()
        if sprint_length_days is None:
            return None
        return sprint_length_days, capacities
    except Exception:
        return None


def _load_histories(workspace: Path) -> Optional[Dict[str, dict]]:
    # Returns per-team metrics data.
    # Structure:
    # {
    #   team: {
    #     "types": { type: {"sum": float, "count": int} for completed==1 },
    #     "overall": {"sum": float, "count": int},
    #     "delivery": {"committed": int, "delivered": int}
    #   }
    # }
    teams_data: Dict[str, dict] = {}
    teams_dir = workspace / "input" / "teams"
    if not teams_dir.exists():
        return None
    files = sorted(teams_dir.glob("*_history.csv"))
    if not files:
        return None
    for f in files:
        header, rows = _read_csv_dicts(f)
        if header is None or rows is None:
            return None
        required_cols = {"sprint_id", "team", "ticket_id", "type", "story_points", "committed", "completed", "cycle_time_days"}
        if set(header) != required_cols:
            # Allow extra columns? Spec lists exact columns; enforce strict equality for determinism.
            return None
        for row in rows:
            team = row.get("team")
            typ = row.get("type")
            if team is None or typ is None:
                return None
            committed = _parse_int_safe(row.get("committed", ""))
            completed = _parse_int_safe(row.get("completed", ""))
            ctd = _parse_float_safe(row.get("cycle_time_days", ""))
            if committed is None or completed is None or ctd is None:
                return None
            td = teams_data.setdefault(team, {
                "types": {},
                "overall": {"sum": 0.0, "count": 0},
                "delivery": {"committed": 0, "delivered": 0},
            })
            # Delivery rate counts on committed
            if committed == 1:
                td["delivery"]["committed"] += 1
                if completed == 1:
                    td["delivery"]["delivered"] += 1
            # Cycle time uses only completed==1
            if completed == 1:
                tstats = td["types"].setdefault(typ, {"sum": 0.0, "count": 0})
                tstats["sum"] += ctd
                tstats["count"] += 1
                td["overall"]["sum"] += ctd
                td["overall"]["count"] += 1
    return teams_data


def _compute_expected_metrics(teams_data: Dict[str, dict]) -> List[Dict[str, str]]:
    # Returns list of rows for metrics_summary with strings or floats
    rows: List[Dict[str, str]] = []
    for team in sorted(teams_data.keys()):
        team_entry = teams_data[team]
        delivery_committed = team_entry["delivery"]["committed"]
        delivery_delivered = team_entry["delivery"]["delivered"]
        delivery_rate = (delivery_delivered / delivery_committed) if delivery_committed > 0 else 0.0
        # For each observed type in history
        for typ in sorted(team_entry["types"].keys()):
            tstats = team_entry["types"][typ]
            mean_ct = (tstats["sum"] / tstats["count"]) if tstats["count"] > 0 else 0.0
            rows.append({
                "team": team,
                "type": typ,
                "mean_cycle_time_days": mean_ct,
                "delivery_rate": delivery_rate,
            })
    return rows


def _load_backlog(workspace: Path) -> Optional[List[Dict[str, str]]]:
    path = workspace / "input" / "backlog.csv"
    header, rows = _read_csv_dicts(path)
    if header is None or rows is None:
        return None
    required = ["team", "ticket_id", "type", "story_points", "business_value", "due_in_sprints", "risk"]
    if header != required:
        return None
    return rows


def _compute_predictions_and_selection(
    workspace: Path,
    teams_data: Dict[str, dict],
    sprint_length_days: int,
    capacities: Dict[str, int],
    backlog_rows: List[Dict[str, str]],
) -> List[Dict[str, object]]:
    # Compute per-backlog item metrics and selection per team
    # Prepare mean lookups
    mean_by_team_type: Dict[Tuple[str, str], float] = {}
    mean_by_team: Dict[str, float] = {}
    delivery_rate_by_team: Dict[str, float] = {}

    for team, data in teams_data.items():
        # delivery rate
        committed = data["delivery"]["committed"]
        delivered = data["delivery"]["delivered"]
        delivery_rate_by_team[team] = (delivered / committed) if committed > 0 else 0.0
        # type means
        for typ, stats in data["types"].items():
            if stats["count"] > 0:
                mean_by_team_type[(team, typ)] = stats["sum"] / stats["count"]
        # overall mean
        if data["overall"]["count"] > 0:
            mean_by_team[team] = data["overall"]["sum"] / data["overall"]["count"]

    # Compute scores for each item
    computed_items: List[Dict[str, object]] = []
    for row in backlog_rows:
        team = row["team"]
        ticket_id = row["ticket_id"]
        typ = row["type"]
        sp = _parse_int_safe(row["story_points"])
        bv = _parse_float_safe(row["business_value"])
        due = _parse_int_safe(row["due_in_sprints"])
        if team is None or ticket_id is None or typ is None or sp is None or bv is None or due is None:
            # Skip invalid rows (but per spec assume valid numerics)
            continue
        dr = delivery_rate_by_team.get(team, 0.0)
        predicted_cycle = mean_by_team_type.get((team, typ))
        if predicted_cycle is None:
            predicted_cycle = mean_by_team.get(team, 0.0)
        base_spill = max(0.0, predicted_cycle - float(sprint_length_days)) / float(sprint_length_days)
        p_spill = base_spill + (1.0 - dr) / 2.0
        if p_spill > 1.0:
            p_spill = 1.0
        urgency_bonus = 1.0 if due <= 1 else 0.0
        score = bv + urgency_bonus - 2.0 * p_spill
        score_per_point = score / float(sp) if sp != 0 else float("-inf")
        computed_items.append({
            "team": team,
            "ticket_id": ticket_id,
            "story_points": sp,
            "score": score,
            "score_per_point": score_per_point,
            "predicted_cycle_time": predicted_cycle,
            "p_spill": p_spill,
            "business_value": bv,  # keep for tie-breakers then drop
        })

    # Selection per team (greedy)
    # Group by team
    items_by_team: Dict[str, List[Dict[str, object]]] = {}
    for item in computed_items:
        items_by_team.setdefault(item["team"], []).append(item)

    for team, items in items_by_team.items():
        # Sort with tie-breakers:
        # score_per_point desc, score desc, business_value desc, story_points asc, ticket_id asc
        items.sort(key=lambda x: (
            -float(x["score_per_point"]),
            -float(x["score"]),
            -float(x["business_value"]),
            int(x["story_points"]),
            str(x["ticket_id"]),
        ))
        remaining = capacities.get(team, 0)
        used = 0
        for it in items:
            sp = int(it["story_points"])
            if used + sp <= remaining:
                it["selected"] = 1
                used += sp
            else:
                it["selected"] = 0

    # Flatten back preserving all items; selection flags added; remove business_value from output record
    final_items: List[Dict[str, object]] = []
    for item in computed_items:
        final_items.append({
            "team": item["team"],
            "ticket_id": item["ticket_id"],
            "story_points": int(item["story_points"]),
            "score": float(item["score"]),
            "score_per_point": float(item["score_per_point"]),
            "predicted_cycle_time": float(item["predicted_cycle_time"]),
            "p_spill": float(item["p_spill"]),
            "selected": int(item.get("selected", 0)),
        })
    return final_items


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_file_exists": 0.0,
        "run_invocation_succeeds": 0.0,
        "outputs_exist": 0.0,
        "output_directory_strict_contents": 0.0,
        "metrics_rows_and_values_correct": 0.0,
        "backlog_rows_and_values_correct": 0.0,
        "selection_respects_capacity": 0.0,
    }

    # Check script existence
    script_path = workspace / "tools" / "select_backlog.py"
    if script_path.exists():
        scores["script_file_exists"] = 1.0

    # Try running the script
    ran_ok = False
    if script_path.exists():
        try:
            proc = subprocess.run(
                ["python", str(script_path)],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0:
                ran_ok = True
        except Exception:
            ran_ok = False
    if ran_ok:
        scores["run_invocation_succeeds"] = 1.0

    output_dir = workspace / "output"
    metrics_path = output_dir / "metrics_summary.csv"
    backlog_path = output_dir / "backlog_recommendations.csv"
    if metrics_path.exists() and backlog_path.exists():
        scores["outputs_exist"] = 1.0

    # Check strict output directory contents (only the two expected files)
    if output_dir.exists() and output_dir.is_dir():
        try:
            entries = [p for p in output_dir.iterdir()]
            # Only allow exactly two files, both CSV with exact names
            names = sorted([e.name for e in entries if e.is_file()])
            if names == ["backlog_recommendations.csv", "metrics_summary.csv"] and len(entries) == 2:
                scores["output_directory_strict_contents"] = 1.0
        except Exception:
            pass

    # Load inputs for expected computations
    teams_data = _load_histories(workspace)
    capacity = _parse_capacity_yaml(workspace / "input" / "capacity.yaml")
    backlog_rows = _load_backlog(workspace)
    if teams_data is None or capacity is None or backlog_rows is None:
        # Cannot compute expected; leave relevant checks as 0.0
        return scores

    sprint_length_days, capacities = capacity
    expected_metrics_rows = _compute_expected_metrics(teams_data)
    expected_backlog = _compute_predictions_and_selection(workspace, teams_data, sprint_length_days, capacities, backlog_rows)

    # Validate metrics_summary.csv
    header_m, rows_m = _read_csv_dicts(metrics_path) if metrics_path.exists() else (None, None)
    metrics_ok = False
    if header_m is not None and rows_m is not None:
        if header_m == ["team", "type", "mean_cycle_time_days", "delivery_rate"]:
            # Build mapping by (team, type)
            expected_map: Dict[Tuple[str, str], Tuple[float, float]] = {}
            for r in expected_metrics_rows:
                expected_map[(r["team"], r["type"])] = (float(r["mean_cycle_time_days"]), float(r["delivery_rate"]))
            actual_map: Dict[Tuple[str, str], Tuple[float, float]] = {}
            try:
                for r in rows_m:
                    team = r.get("team")
                    typ = r.get("type")
                    mct = _parse_float_safe(r.get("mean_cycle_time_days", ""))
                    dr = _parse_float_safe(r.get("delivery_rate", ""))
                    if team is None or typ is None or mct is None or dr is None:
                        raise ValueError("Malformed metrics row")
                    actual_map[(team, typ)] = (mct, dr)
                # Compare keys and values
                if set(actual_map.keys()) == set(expected_map.keys()):
                    all_match = True
                    for k in expected_map:
                        emct, edr = expected_map[k]
                        amct, adr = actual_map[k]
                        if not (_isclose(emct, amct) and _isclose(edr, adr)):
                            all_match = False
                            break
                    if all_match:
                        metrics_ok = True
            except Exception:
                metrics_ok = False
    if metrics_ok:
        scores["metrics_rows_and_values_correct"] = 1.0

    # Validate backlog_recommendations.csv
    header_b, rows_b = _read_csv_dicts(backlog_path) if backlog_path.exists() else (None, None)
    backlog_ok = False
    capacity_ok = False
    if header_b is not None and rows_b is not None:
        if header_b == ["team", "ticket_id", "story_points", "score", "score_per_point", "predicted_cycle_time", "p_spill", "selected"]:
            try:
                # Build expected map by (team, ticket_id)
                exp_map: Dict[Tuple[str, str], Dict[str, object]] = {}
                for r in expected_backlog:
                    exp_map[(r["team"], r["ticket_id"])] = r
                # Build actual map
                act_map: Dict[Tuple[str, str], Dict[str, object]] = {}
                for r in rows_b:
                    team = r.get("team")
                    tid = r.get("ticket_id")
                    if team is None or tid is None:
                        raise ValueError("Missing team or ticket_id")
                    sp = _parse_int_safe(r.get("story_points", ""))
                    score = _parse_float_safe(r.get("score", ""))
                    spp = _parse_float_safe(r.get("score_per_point", ""))
                    pct = _parse_float_safe(r.get("predicted_cycle_time", ""))
                    ps = _parse_float_safe(r.get("p_spill", ""))
                    sel = _parse_int_safe(r.get("selected", ""))
                    if None in (sp, score, spp, pct, ps, sel):
                        raise ValueError("Malformed numeric fields")
                    act_map[(team, tid)] = {
                        "team": team,
                        "ticket_id": tid,
                        "story_points": sp,
                        "score": score,
                        "score_per_point": spp,
                        "predicted_cycle_time": pct,
                        "p_spill": ps,
                        "selected": sel,
                    }
                # Ensure same set of items as input backlog.csv
                # Build required set from input/backlog.csv rows
                required_keys = set((r["team"], r["ticket_id"]) for r in backlog_rows)
                if set(act_map.keys()) != required_keys or set(exp_map.keys()) != required_keys:
                    backlog_ok = False
                else:
                    # Compare values for each item
                    all_match = True
                    for key in required_keys:
                        e = exp_map[key]
                        a = act_map[key]
                        if int(e["story_points"]) != int(a["story_points"]):
                            all_match = False
                            break
                        if not _isclose(float(e["score"]), float(a["score"])):
                            all_match = False
                            break
                        if not _isclose(float(e["score_per_point"]), float(a["score_per_point"])):
                            all_match = False
                            break
                        if not _isclose(float(e["predicted_cycle_time"]), float(a["predicted_cycle_time"])):
                            all_match = False
                            break
                        if not _isclose(float(e["p_spill"]), float(a["p_spill"])):
                            all_match = False
                            break
                        if int(e["selected"]) != int(a["selected"]):
                            all_match = False
                            break
                    backlog_ok = all_match
                # Capacity check: sum selected story points per team <= capacity
                cap_valid = True
                selected_sp_by_team: Dict[str, int] = {}
                for key, a in act_map.items():
                    if int(a["selected"]) == 1:
                        selected_sp_by_team[a["team"]] = selected_sp_by_team.get(a["team"], 0) + int(a["story_points"])
                for team, used in selected_sp_by_team.items():
                    cap = capacities.get(team, 0)
                    if used > cap:
                        cap_valid = False
                        break
                capacity_ok = cap_valid
            except Exception:
                backlog_ok = False
                capacity_ok = False
    if backlog_ok:
        scores["backlog_rows_and_values_correct"] = 1.0
    if capacity_ok:
        scores["selection_respects_capacity"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    _write_json_stdout(result)


if __name__ == "__main__":
    main()