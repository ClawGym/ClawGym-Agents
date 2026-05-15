import json
import csv
import re
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple, Optional


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            # Ensure header exists and non-empty
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _compute_today_from_inputs(workspace: Path) -> Optional[date]:
    dates: List[date] = []
    # polls.csv
    polls_path = workspace / "input" / "polls.csv"
    polls = _read_csv_dicts(polls_path)
    if polls is not None:
        for r in polls:
            d = _parse_date(r.get("date", ""))
            if d:
                dates.append(d)
    # field_contacts.csv
    contacts_path = workspace / "input" / "field_contacts.csv"
    contacts = _read_csv_dicts(contacts_path)
    if contacts is not None:
        for r in contacts:
            d = _parse_date(r.get("date", ""))
            if d:
                dates.append(d)
    if not dates:
        return None
    return max(dates)


def _load_inputs(workspace: Path) -> Optional[Dict]:
    target_path = workspace / "input" / "target_counties.csv"
    polls_path = workspace / "input" / "polls.csv"
    contacts_path = workspace / "input" / "field_contacts.csv"
    turnout_path = workspace / "input" / "turnout_baseline.csv"

    targets_rows = _read_csv_dicts(target_path)
    polls_rows = _read_csv_dicts(polls_path)
    contacts_rows = _read_csv_dicts(contacts_path)
    turnout_rows = _read_csv_dicts(turnout_path)

    if targets_rows is None or polls_rows is None or contacts_rows is None or turnout_rows is None:
        return None

    targets = []
    for r in targets_rows:
        c = r.get("county", "").strip()
        if c:
            targets.append(c)
    turnout = {}
    for r in turnout_rows:
        c = r.get("county", "").strip()
        if not c:
            continue
        try:
            turnout[c] = {
                "past_turnout": float(r.get("past_turnout", "")),
                "registration_dem": float(r.get("registration_dem", "")),
                "registration_rep": float(r.get("registration_rep", "")),
                "registration_ind": float(r.get("registration_ind", "")),
            }
        except Exception:
            return None  # malformed numeric in turnout is fatal for computations

    # Normalize polls and contacts
    polls = []
    for r in polls_rows:
        d = _parse_date(r.get("date", ""))
        if d is None:
            return None
        c = r.get("county", "").strip()
        try:
            polls.append({
                "date": d,
                "county": c,
                "sample_size": float(r.get("sample_size", "")),
                "support_gov": float(r.get("support_gov", "")),
                "support_opp": float(r.get("support_opp", "")),
            })
        except Exception:
            return None
    contacts = []
    for r in contacts_rows:
        d = _parse_date(r.get("date", ""))
        if d is None:
            return None
        c = r.get("county", "").strip()
        try:
            contacts.append({
                "date": d,
                "county": c,
                "doors_knocked": float(r.get("doors_knocked", "")),
                "volunteers": float(r.get("volunteers", "")),
            })
        except Exception:
            return None

    return {
        "targets": targets,
        "polls": polls,
        "contacts": contacts,
        "turnout": turnout,
    }


def _compute_expected_metrics(workspace: Path) -> Optional[Dict]:
    inputs = _load_inputs(workspace)
    if inputs is None:
        return None
    today = _compute_today_from_inputs(workspace)
    if today is None:
        return None

    targets: List[str] = inputs["targets"]
    polls: List[Dict] = inputs["polls"]
    contacts: List[Dict] = inputs["contacts"]
    turnout: Dict[str, Dict[str, float]] = inputs["turnout"]

    poll_window_start = today - timedelta(days=13)  # inclusive last 14 days
    contact_window_start = today - timedelta(days=6)  # inclusive last 7 days

    per_county = {}
    for county in targets:
        # weighted_margin_14d
        county_polls = [
            p for p in polls
            if p["county"] == county and p["date"] >= poll_window_start and p["date"] <= today
        ]
        if not county_polls:
            return None  # strict: required data missing for a target county
        total_n = sum(p["sample_size"] for p in county_polls)
        if total_n == 0:
            return None
        weighted_sum = sum(p["sample_size"] * ((p["support_gov"] - p["support_opp"])) for p in county_polls)
        weighted_margin_14d = weighted_sum / total_n

        # contacts_per_1k_7d
        county_contacts = [
            c for c in contacts
            if c["county"] == county and c["date"] >= contact_window_start and c["date"] <= today
        ]
        total_doors = sum(c["doors_knocked"] for c in county_contacts)
        base = turnout.get(county)
        if base is None:
            return None
        past_turnout = base.get("past_turnout", 0.0)
        if past_turnout is None or past_turnout == 0:
            return None
        contacts_per_1k_7d = total_doors / (past_turnout / 1000.0)

        # registration_advantage_pct
        rd = base.get("registration_dem", 0.0)
        rr = base.get("registration_rep", 0.0)
        ri = base.get("registration_ind", 0.0)
        denom = rd + rr + ri
        if denom == 0:
            return None
        registration_advantage_pct = ((rd - rr) / denom) * 100.0

        # priority_score
        priority_score = (-weighted_margin_14d) + (0.1 * contacts_per_1k_7d) + (-0.3 * registration_advantage_pct)

        per_county[county] = {
            "weighted_margin_14d": weighted_margin_14d,
            "contacts_per_1k_7d": contacts_per_1k_7d,
            "registration_advantage_pct": registration_advantage_pct,
            "priority_score": priority_score,
            "total_doors_knocked_7d": total_doors,
        }

    # ranking
    ordered = sorted(per_county.items(), key=lambda kv: kv[1]["priority_score"], reverse=True)
    rank = 1
    ranked_order = []
    for county, vals in ordered:
        vals["rank"] = rank
        rank += 1
        ranked_order.append(county)

    # top3
    top3 = [{"county": c, "priority_score": per_county[c]["priority_score"]} for c in ranked_order[:3]]

    # totals for summary
    total_doors_knocked_7d = sum(per_county[c]["total_doors_knocked_7d"] for c in targets)
    avg_priority_score = sum(per_county[c]["priority_score"] for c in targets) / len(targets) if targets else 0.0

    return {
        "today": today,
        "targets": targets,
        "per_county": per_county,
        "ranked_order": ranked_order,
        "top3": top3,
        "total_doors_knocked_7d": total_doors_knocked_7d,
        "avg_priority_score": avg_priority_score,
    }


def _abs_close(a: float, b: float, tol: float = 1e-2) -> bool:
    return abs(a - b) <= tol


def _extract_run_paths_from_log(log_path: Path) -> List[Tuple[Path, Path]]:
    runs: List[Tuple[Path, Path]] = []
    if not log_path.exists():
        return runs
    try:
        text = log_path.read_text(encoding="utf-8")
    except Exception:
        return runs
    for line in text.splitlines():
        # Extract file paths using regex
        csv_matches = re.findall(r'(output/priority/priority_\d{8}_\d{6}\.csv)', line)
        json_matches = re.findall(r'(output/summary/summary_\d{8}_\d{6}\.json)', line)
        if csv_matches and json_matches:
            csv_path = Path(csv_matches[0])
            json_path = Path(json_matches[0])
            runs.append((csv_path, json_path))
    return runs


def _list_matching_files(dir_path: Path, pattern: str) -> List[Path]:
    # pattern as regex on name
    out: List[Path] = []
    if not dir_path.exists():
        return out
    try:
        for p in dir_path.iterdir():
            if p.is_file() and re.fullmatch(pattern, p.name):
                out.append(p)
    except Exception:
        return []
    return out


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "processing_script_present": 0.0,
        "scheduler_script_present": 0.0,
        "schedule_log_runs_at_least_3": 0.0,
        "schedule_log_paths_valid": 0.0,
        "priority_csvs_count_at_least_3": 0.0,
        "summary_jsons_count_at_least_3": 0.0,
        "csv_header_correct": 0.0,
        "csv_order_and_rank_correct": 0.0,
        "csv_values_correct": 0.0,
        "json_summary_fields_correct": 0.0,
        "today_date_derived_from_inputs_correct": 0.0,
        "target_counties_processed_exactly": 0.0,
    }

    # Check script presence
    daily_py = workspace / "bin" / "daily_priority.py"
    daily_sh = workspace / "bin" / "daily_priority.sh"
    if daily_py.exists() or daily_sh.exists():
        scores["processing_script_present"] = 1.0

    schedule_sh = workspace / "bin" / "run_schedule.sh"
    if schedule_sh.exists():
        scores["scheduler_script_present"] = 1.0

    # Count outputs by scanning directories
    priority_dir = workspace / "output" / "priority"
    summary_dir = workspace / "output" / "summary"

    csv_files = _list_matching_files(priority_dir, r"priority_\d{8}_\d{6}\.csv")
    json_files = _list_matching_files(summary_dir, r"summary_\d{8}_\d{6}\.json")

    if len(csv_files) >= 3:
        scores["priority_csvs_count_at_least_3"] = 1.0
    else:
        scores["priority_csvs_count_at_least_3"] = min(len(csv_files) / 3.0, 1.0)

    if len(json_files) >= 3:
        scores["summary_jsons_count_at_least_3"] = 1.0
    else:
        scores["summary_jsons_count_at_least_3"] = min(len(json_files) / 3.0, 1.0)

    # Parse schedule log
    log_path = workspace / "output" / "logs" / "schedule.log"
    runs = _extract_run_paths_from_log(log_path)
    num_runs = len(runs)
    scores["schedule_log_runs_at_least_3"] = 1.0 if num_runs >= 3 else min(num_runs / 3.0, 1.0)

    # Check logged paths exist for the first up to 3 runs
    if runs:
        check_runs = runs[-3:] if len(runs) >= 3 else runs
        valid_count = 0
        for csv_rel, json_rel in check_runs:
            csv_path = (workspace / csv_rel).resolve()
            json_path = (workspace / json_rel).resolve()
            if csv_path.exists() and json_path.exists():
                valid_count += 1
        scores["schedule_log_paths_valid"] = valid_count / len(check_runs) if check_runs else 0.0

    # Compute expected metrics from inputs
    expected = _compute_expected_metrics(workspace)
    # If expected cannot be computed, value-based checks remain 0.0
    if expected is None or runs == []:
        return scores

    targets = expected["targets"]
    expected_per_county = expected["per_county"]
    expected_rank_order = expected["ranked_order"]
    expected_today_str = expected["today"].strftime("%Y-%m-%d")

    # Evaluate CSV and JSON content for up to 3 most recent runs from the log
    check_runs = runs[-3:] if len(runs) >= 3 else runs

    # CSV checks
    header_ok_count = 0
    order_ok_count = 0
    values_ok_total = 0
    values_ok_possible = 0
    targets_ok_count = 0

    expected_header = [
        "county",
        "weighted_margin_14d",
        "contacts_per_1k_7d",
        "registration_advantage_pct",
        "priority_score",
        "rank",
    ]

    for csv_rel, _ in check_runs:
        csv_path = (workspace / csv_rel).resolve()
        rows = _read_csv_dicts(csv_path)
        if rows is None:
            continue
        # Check header: csv.DictReader stores fieldnames attribute; we need to re-open to check exact order
        try:
            with csv_path.open("r", newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader)
        except Exception:
            header = None

        if header == expected_header:
            header_ok_count += 1

        # Check rows count and target counties exactly
        file_counties = [r.get("county", "").strip() for r in rows]
        if set(file_counties) == set(targets) and len(file_counties) == len(targets):
            targets_ok_count += 1

        # Check order and ranks
        # The order must match expected_rank_order exactly
        if file_counties == expected_rank_order:
            # Also verify ranks 1..n
            ranks_ok = True
            for i, r in enumerate(rows, start=1):
                try:
                    rank_val = int(float(str(r.get("rank", "")).strip()))
                except Exception:
                    ranks_ok = False
                    break
                if rank_val != i:
                    ranks_ok = False
                    break
            if ranks_ok:
                order_ok_count += 1

        # Check values for each county
        for r in rows:
            county = r.get("county", "").strip()
            if county not in expected_per_county:
                continue
            exp_vals = expected_per_county[county]
            # Parse numeric fields
            wm = _to_float(str(r.get("weighted_margin_14d", "")).strip())
            cp1k = _to_float(str(r.get("contacts_per_1k_7d", "")).strip())
            reg = _to_float(str(r.get("registration_advantage_pct", "")).strip())
            ps = _to_float(str(r.get("priority_score", "")).strip())
            # For each numeric, compare with tolerance
            ok_flags = []
            for actual, expected_val in [
                (wm, exp_vals["weighted_margin_14d"]),
                (cp1k, exp_vals["contacts_per_1k_7d"]),
                (reg, exp_vals["registration_advantage_pct"]),
                (ps, exp_vals["priority_score"]),
            ]:
                values_ok_possible += 1
                if actual is None:
                    ok_flags.append(False)
                    continue
                ok_flags.append(_abs_close(actual, expected_val, tol=1e-2))
            values_ok_total += sum(1 for x in ok_flags if x)

    scores["csv_header_correct"] = header_ok_count / len(check_runs) if check_runs else 0.0
    scores["csv_order_and_rank_correct"] = order_ok_count / len(check_runs) if check_runs else 0.0
    scores["target_counties_processed_exactly"] = targets_ok_count / len(check_runs) if check_runs else 0.0
    scores["csv_values_correct"] = (values_ok_total / values_ok_possible) if values_ok_possible > 0 else 0.0

    # JSON checks
    json_ok_total = 0
    json_ok_possible = 0
    today_ok_count = 0

    for _, json_rel in check_runs:
        json_path = (workspace / json_rel).resolve()
        data = _safe_load_json(json_path)
        if data is None:
            continue

        # today_date
        json_ok_possible += 1
        if isinstance(data.get("today_date"), str) and data["today_date"] == expected_today_str:
            today_ok_count += 1
            json_ok_total += 1

        # windows
        json_ok_possible += 1
        windows = data.get("windows")
        if isinstance(windows, dict) and windows.get("poll_days") == 14 and windows.get("contact_days") == 7:
            json_ok_total += 1

        # total_target_counties_processed
        json_ok_possible += 1
        ttcp = data.get("total_target_counties_processed")
        if isinstance(ttcp, int) and ttcp == len(targets):
            json_ok_total += 1

        # top3
        json_ok_possible += 1
        top3 = data.get("top3")
        top3_expected = expected["top3"]
        top3_ok = False
        if isinstance(top3, list) and len(top3) <= 3:
            # Compare order and values (county and priority_score within tolerance)
            # Build expected mapping/order
            if len(top3) == len(top3_expected[:len(top3)]):
                local_ok = True
                for i, item in enumerate(top3):
                    if not isinstance(item, dict):
                        local_ok = False
                        break
                    c = item.get("county")
                    ps = item.get("priority_score")
                    exp_c = top3_expected[i]["county"]
                    exp_ps = top3_expected[i]["priority_score"]
                    if c != exp_c or not isinstance(ps, (int, float)) or not _abs_close(float(ps), float(exp_ps), tol=1e-2):
                        local_ok = False
                        break
                top3_ok = local_ok
        if top3_ok:
            json_ok_total += 1

        # total_doors_knocked_7d
        json_ok_possible += 1
        tdoors = data.get("total_doors_knocked_7d")
        if isinstance(tdoors, (int, float)) and _abs_close(float(tdoors), float(expected["total_doors_knocked_7d"]), tol=1e-6):
            json_ok_total += 1

        # average_priority_score
        json_ok_possible += 1
        avg_ps = data.get("average_priority_score")
        if isinstance(avg_ps, (int, float)) and _abs_close(float(avg_ps), float(expected["avg_priority_score"]), tol=1e-4):
            json_ok_total += 1

    scores["json_summary_fields_correct"] = (json_ok_total / json_ok_possible) if json_ok_possible > 0 else 0.0
    scores["today_date_derived_from_inputs_correct"] = today_ok_count / len(check_runs) if check_runs else 0.0

    return scores


def main() -> None:
    import sys
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()