import sys
import json
import csv
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _read_text_lines(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None


def _to_int(val: str) -> Optional[int]:
    try:
        return int(str(val).strip())
    except Exception:
        return None


def _to_float(val: str) -> Optional[float]:
    try:
        return float(str(val).strip())
    except Exception:
        return None


def _float_close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _parse_error_log(lines: List[str]) -> Tuple[Set[int], Dict[str, Dict[str, object]]]:
    excluded_ids: Set[int] = set()
    # error_summary_map: error_type -> {"count": int, "ids": set[int]}
    error_summary_map: Dict[str, Dict[str, object]] = {}
    for line in lines:
        # Consider lines that contain the ERROR level token
        if not re.search(r"\bERROR\b", line):
            continue
        # Extract player_id
        m = re.search(r"player_id=(\d+)", line)
        if not m:
            continue
        pid = int(m.group(1))
        excluded_ids.add(pid)
        # Tokenize by whitespace to get token right after player_id=...
        tokens = line.strip().split()
        error_type = None
        for i, tok in enumerate(tokens):
            if tok.startswith("player_id=") and i + 1 < len(tokens):
                error_type = tokens[i + 1]
                break
        if error_type is None:
            # Fallback: if not found via tokenization, try regex for trailing word
            tail = line[line.find(m.group(0)) + len(m.group(0)) :].strip()
            parts = tail.split()
            if parts:
                error_type = parts[0]
        if error_type is None:
            continue
        if error_type not in error_summary_map:
            error_summary_map[error_type] = {"count": 0, "ids": set()}
        error_summary_map[error_type]["count"] = int(error_summary_map[error_type]["count"]) + 1
        error_summary_map[error_type]["ids"].add(pid)
    return excluded_ids, error_summary_map


def _compute_expected(workspace: Path) -> Tuple[Optional[List[Dict[str, object]]], Optional[Dict[str, Dict[str, object]]], Optional[Set[int]]]:
    # Load inputs
    players_path = workspace / "input" / "players.csv"
    fitness_path = workspace / "input" / "fitness_tests.csv"
    attendance_path = workspace / "input" / "attendance.csv"
    log_path = workspace / "logs" / "hr_import_output.txt"

    players_rows = _read_csv_dicts(players_path)
    fitness_rows = _read_csv_dicts(fitness_path)
    attendance_rows = _read_csv_dicts(attendance_path)
    log_lines = _read_text_lines(log_path)

    if players_rows is None or fitness_rows is None or attendance_rows is None or log_lines is None:
        return None, None, None

    excluded_ids, error_summary_map = _parse_error_log(log_lines)

    # Age filter (14 to 16 inclusive)
    eligible_players: Dict[int, Dict[str, object]] = {}
    for row in players_rows:
        pid = _to_int(row.get("player_id", ""))
        age = _to_int(row.get("age", ""))
        name = row.get("name", "")
        if pid is None or age is None:
            continue
        if 14 <= age <= 16:
            eligible_players[pid] = {"player_id": pid, "name": name, "age": age}

    # Exclude ERROR player_ids
    for pid in list(eligible_players.keys()):
        if pid in excluded_ids:
            eligible_players.pop(pid, None)

    # Build fitness and attendance maps
    fit_map: Dict[int, Dict[str, float]] = {}
    for row in fitness_rows:
        pid = _to_int(row.get("player_id", ""))
        beep = _to_float(row.get("beep_level", ""))
        sprint = _to_float(row.get("sprint_40m_sec", ""))
        if pid is None or beep is None or sprint is None:
            continue
        fit_map[pid] = {"beep_level": beep, "sprint_40m_sec": sprint}

    att_map: Dict[int, Dict[str, float]] = {}
    for row in attendance_rows:
        pid = _to_int(row.get("player_id", ""))
        attended = _to_float(row.get("sessions_attended", ""))
        total = _to_float(row.get("sessions_total", ""))
        if pid is None or attended is None or total is None:
            continue
        att_map[pid] = {"sessions_attended": attended, "sessions_total": total}

    # Join and compute metrics
    cohort: List[Dict[str, object]] = []
    for pid, pdata in eligible_players.items():
        if pid not in fit_map or pid not in att_map:
            continue
        beep = float(fit_map[pid]["beep_level"])
        sprint = float(fit_map[pid]["sprint_40m_sec"])
        attended = float(att_map[pid]["sessions_attended"])
        total = float(att_map[pid]["sessions_total"])
        attendance_rate = (attended / total) if total != 0 else 0.0
        cohort.append({
            "player_id": pid,
            "name": pdata["name"],
            "age": pdata["age"],
            "beep_level": beep,
            "sprint_40m_sec": sprint,
            "attendance_rate": attendance_rate
        })

    if not cohort:
        # No eligible data
        return [], error_summary_map, excluded_ids

    # Normalization ranges over cohort
    beeps = [c["beep_level"] for c in cohort]  # type: ignore
    sprints = [c["sprint_40m_sec"] for c in cohort]  # type: ignore
    min_beep = min(beeps)
    max_beep = max(beeps)
    min_sprint = min(sprints)
    max_sprint = max(sprints)
    beep_range = max_beep - min_beep
    sprint_range = max_sprint - min_sprint

    for c in cohort:
        nb = ((c["beep_level"] - min_beep) / beep_range) if beep_range != 0 else 0.0  # type: ignore
        ns = ((max_sprint - c["sprint_40m_sec"]) / sprint_range) if sprint_range != 0 else 0.0  # type: ignore
        comp = 0.45 * nb + 0.35 * ns + 0.20 * c["attendance_rate"]  # type: ignore
        c["normalized_beep"] = nb
        c["normalized_speed"] = ns
        c["composite_score"] = comp

    # Sort per requirements:
    # - composite_score desc
    # - tie-breakers: faster sprint (asc), then higher attendance_rate, then higher beep_level, then alphabetical by name
    cohort_sorted = sorted(
        cohort,
        key=lambda c: (
            -c["composite_score"],  # type: ignore
            c["sprint_40m_sec"],    # type: ignore
            -c["attendance_rate"],  # type: ignore
            -c["beep_level"],       # type: ignore
            str(c["name"])
        )
    )
    top5 = cohort_sorted[:5]

    expected_top_rows: List[Dict[str, object]] = []
    for c in top5:
        expected_top_rows.append({
            "player_id": c["player_id"],
            "name": c["name"],
            "age": c["age"],
            "attendance_rate": c["attendance_rate"],
            "beep_level": c["beep_level"],
            "sprint_40m_sec": c["sprint_40m_sec"],
            "composite_score": c["composite_score"]
        })

    return expected_top_rows, error_summary_map, excluded_ids


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "top_u16_prospects_structure": 0.0,
        "top_u16_prospects_content": 0.0,
        "ranking_order_strict": 0.0,
        "error_summary_structure": 0.0,
        "error_summary_content": 0.0,
        "exclusion_applied_in_prospects": 0.0,
        "age_filter_applied_in_prospects": 0.0,
    }

    expected_top, expected_error_summary_map, excluded_ids = _compute_expected(workspace)

    # Paths to outputs
    top_path = workspace / "output" / "top_u16_prospects.csv"
    err_path = workspace / "output" / "error_summary.csv"

    # Read actual top prospects file
    actual_top_rows = _read_csv_dicts(top_path)
    header_expected_top = ["player_id", "name", "age", "attendance_rate", "beep_level", "sprint_40m_sec", "composite_score"]

    # Structure check for top_u16_prospects.csv
    if actual_top_rows is not None:
        try:
            with top_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
        except Exception:
            header = None
        if header == header_expected_top and expected_top is not None:
            # Row count must match expected (min(5, eligible))
            if len(actual_top_rows) == len(expected_top):
                scores["top_u16_prospects_structure"] = 1.0

    # Content check for top_u16_prospects.csv
    if scores["top_u16_prospects_structure"] == 1.0 and actual_top_rows is not None and expected_top is not None:
        content_ok = True
        # Compare row by row
        for idx, (act, exp) in enumerate(zip(actual_top_rows, expected_top)):
            # player_id
            act_pid = _to_int(act.get("player_id", ""))
            exp_pid = int(exp["player_id"])
            if act_pid != exp_pid:
                content_ok = False
                break
            # name
            act_name = (act.get("name", "") or "").strip()
            if act_name != str(exp["name"]):
                content_ok = False
                break
            # age
            act_age = _to_int(act.get("age", ""))
            if act_age != int(exp["age"]):
                content_ok = False
                break
            # attendance_rate
            act_att = _to_float(act.get("attendance_rate", ""))
            if act_att is None or not _float_close(act_att, float(exp["attendance_rate"]), tol=1e-3):
                content_ok = False
                break
            # beep_level
            act_beep = _to_float(act.get("beep_level", ""))
            if act_beep is None or not _float_close(act_beep, float(exp["beep_level"]), tol=1e-6):
                content_ok = False
                break
            # sprint_40m_sec
            act_sprint = _to_float(act.get("sprint_40m_sec", ""))
            if act_sprint is None or not _float_close(act_sprint, float(exp["sprint_40m_sec"]), tol=1e-6):
                content_ok = False
                break
            # composite_score
            act_comp = _to_float(act.get("composite_score", ""))
            if act_comp is None or not _float_close(act_comp, float(exp["composite_score"]), tol=1e-3):
                content_ok = False
                break
        if content_ok and len(actual_top_rows) == len(expected_top):
            scores["top_u16_prospects_content"] = 1.0

    # ranking_order_strict (internal consistency with tie-breakers based on provided values)
    if actual_top_rows is not None:
        # Check header
        try:
            with top_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames == header_expected_top:
                    act_rows_typed = []
                    parse_ok = True
                    for r in actual_top_rows:
                        pid = _to_int(r.get("player_id", ""))
                        name = (r.get("name", "") or "").strip()
                        age = _to_int(r.get("age", ""))
                        att = _to_float(r.get("attendance_rate", ""))
                        beep = _to_float(r.get("beep_level", ""))
                        sprint = _to_float(r.get("sprint_40m_sec", ""))
                        comp = _to_float(r.get("composite_score", ""))
                        if None in (pid, age, att, beep, sprint, comp):
                            parse_ok = False
                            break
                        act_rows_typed.append({
                            "player_id": pid,
                            "name": name,
                            "age": age,
                            "attendance_rate": att,
                            "beep_level": beep,
                            "sprint_40m_sec": sprint,
                            "composite_score": comp
                        })
                    if parse_ok:
                        # Compute sorted order according to criteria
                        sorted_rows = sorted(
                            act_rows_typed,
                            key=lambda c: (
                                -c["composite_score"],
                                c["sprint_40m_sec"],
                                -c["attendance_rate"],
                                -c["beep_level"],
                                str(c["name"])
                            )
                        )
                        # Compare sequence equality
                        same_order = True
                        for i in range(len(act_rows_typed)):
                            a = act_rows_typed[i]
                            b = sorted_rows[i]
                            if not (
                                a["player_id"] == b["player_id"]
                                and a["name"] == b["name"]
                                and a["age"] == b["age"]
                                and _float_close(a["attendance_rate"], b["attendance_rate"], tol=1e-6)
                                and _float_close(a["beep_level"], b["beep_level"], tol=1e-6)
                                and _float_close(a["sprint_40m_sec"], b["sprint_40m_sec"], tol=1e-6)
                                and _float_close(a["composite_score"], b["composite_score"], tol=1e-6)
                            ):
                                same_order = False
                                break
                        if same_order:
                            scores["ranking_order_strict"] = 1.0
        except Exception:
            pass

    # error_summary_structure
    error_rows = _read_csv_dicts(err_path)
    header_expected_err = ["error_type", "count", "player_ids"]
    if error_rows is not None:
        try:
            with err_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
        except Exception:
            header = None
        # Check header and that each row has valid count int and player_ids parseable
        if header == header_expected_err:
            structure_ok = True
            for r in error_rows:
                et = (r.get("error_type", "") or "").strip()
                if et == "":
                    structure_ok = False
                    break
                cnt = _to_int(r.get("count", ""))
                if cnt is None or cnt < 0:
                    structure_ok = False
                    break
                # player_ids can be empty string if no IDs? In our case errors have ids, but allow empty == no ids
                pids_str = (r.get("player_ids", "") or "").strip()
                if pids_str != "":
                    parts = pids_str.split(";")
                    # ensure all ints parse
                    for p in parts:
                        if _to_int(p) is None:
                            structure_ok = False
                            break
                    if not structure_ok:
                        break
            if structure_ok:
                scores["error_summary_structure"] = 1.0

    # error_summary_content
    if error_rows is not None and expected_error_summary_map is not None:
        # Build actual map
        actual_map: Dict[str, Dict[str, object]] = {}
        for r in error_rows:
            et = (r.get("error_type", "") or "").strip()
            cnt = _to_int(r.get("count", ""))
            pids_str = (r.get("player_ids", "") or "").strip()
            if et == "" or cnt is None or cnt < 0:
                actual_map = {}
                break
            if pids_str == "":
                pid_list: List[int] = []
            else:
                parts = [p for p in pids_str.split(";") if p != ""]
                pid_list = []
                parse_ok = True
                for p in parts:
                    vi = _to_int(p)
                    if vi is None:
                        parse_ok = False
                        break
                    pid_list.append(vi)
                if not parse_ok:
                    actual_map = {}
                    break
            actual_map[et] = {"count": cnt, "player_ids": pid_list}
        content_ok = True
        # Compare sets of error types
        exp_types = set(expected_error_summary_map.keys())
        act_types = set(actual_map.keys())
        if exp_types != act_types:
            content_ok = False
        else:
            # For each type compare count and player_ids unique ascending
            for et in exp_types:
                exp_count = int(expected_error_summary_map[et]["count"])  # type: ignore
                exp_ids_sorted = sorted(list(expected_error_summary_map[et]["ids"]))  # type: ignore
                act_entry = actual_map.get(et, None)
                if act_entry is None:
                    content_ok = False
                    break
                act_count = int(act_entry["count"])  # type: ignore
                act_ids_list = list(act_entry["player_ids"])  # type: ignore
                # counts must equal
                if act_count != exp_count:
                    content_ok = False
                    break
                # player_ids must be unique and equal set to expected
                if sorted(set(act_ids_list)) != exp_ids_sorted:
                    content_ok = False
                    break
                # Must be in ascending numeric order in the CSV output
                if act_ids_list != sorted(act_ids_list):
                    content_ok = False
                    break
        if content_ok:
            scores["error_summary_content"] = 1.0

    # exclusion_applied_in_prospects
    if actual_top_rows is not None and excluded_ids is not None:
        excl_ok = True
        for r in actual_top_rows:
            pid = _to_int(r.get("player_id", ""))
            if pid is None:
                excl_ok = False
                break
            if pid in excluded_ids:
                excl_ok = False
                break
        if excl_ok:
            scores["exclusion_applied_in_prospects"] = 1.0

    # age_filter_applied_in_prospects
    if actual_top_rows is not None:
        ages_ok = True
        for r in actual_top_rows:
            age = _to_int(r.get("age", ""))
            if age is None or not (14 <= age <= 16):
                ages_ok = False
                break
        if ages_ok:
            scores["age_filter_applied_in_prospects"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()