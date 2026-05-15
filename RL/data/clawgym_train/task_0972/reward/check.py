import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(row)
            return rows
    except Exception:
        return None


def _parse_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _safe_int(s: Any) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _safe_float(s: Any) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _numeric_close(a: Any, b: Any, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _get_latest_date_from_csv(records: List[Dict[str, Any]]) -> Optional[date]:
    latest: Optional[date] = None
    for r in records:
        d = _parse_date(r.get("date", ""))
        if d is None:
            return None
        if latest is None or d > latest:
            latest = d
    return latest


def _compute_daily_expected(records: List[Dict[str, Any]], sparring_notes: List[Dict[str, Any]], target_date: date) -> Optional[Dict[str, Any]]:
    # Filter records by target_date
    rows = [r for r in records if _parse_date(r.get("date", "")) == target_date]
    if not rows:
        return None
    rounds_sum = 0
    intensities: List[float] = []
    focus_counts: Dict[str, int] = {}
    for r in rows:
        rounds_val = _safe_int(r.get("rounds"))
        intensity_val = _safe_float(r.get("intensity"))
        focus = r.get("focus_area", "")
        if rounds_val is None or intensity_val is None or not isinstance(focus, str):
            return None
        rounds_sum += rounds_val
        intensities.append(float(intensity_val))
        focus_counts[focus] = focus_counts.get(focus, 0) + 1
    if not intensities:
        return None
    avg_intensity = sum(intensities) / len(intensities)
    avg_intensity_1 = round(avg_intensity, 1)
    # top focus area with tie-break alphabetically
    sorted_focus = sorted(focus_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top_focus_area = sorted_focus[0][0]
    readiness_score = min(100, int(round(avg_intensity * 10 + rounds_sum * 2, 0)))

    # last_spar_result for opponent "gym_rival" with date <= target_date
    last_result = "none"
    latest_spar_date: Optional[date] = None
    for note in sparring_notes:
        if note.get("opponent") != "gym_rival":
            continue
        nd = _parse_date(str(note.get("date", "")))
        if nd is None:
            return None
        if nd <= target_date:
            if latest_spar_date is None or nd > latest_spar_date:
                latest_spar_date = nd
                last_result = str(note.get("result", "none"))

    return {
        "date": target_date.strftime("%Y-%m-%d"),
        "total_rounds": rounds_sum,
        "average_intensity": float(avg_intensity_1),
        "top_focus_area": top_focus_area,
        "readiness_score": int(readiness_score),
        "last_spar_result": last_result,
    }


def _compute_weekly_expected(records: List[Dict[str, Any]], sparring_notes: List[Dict[str, Any]], today: date) -> Optional[Dict[str, Any]]:
    start = today - timedelta(days=6)
    end = today
    window_rows = []
    dates_in_csv: set = set()
    for r in records:
        d = _parse_date(r.get("date", ""))
        if d is None:
            return None
        if start <= d <= end:
            rounds_val = _safe_int(r.get("rounds"))
            intensity_val = _safe_float(r.get("intensity"))
            focus = r.get("focus_area", "")
            if rounds_val is None or intensity_val is None or not isinstance(focus, str):
                return None
            window_rows.append((d, rounds_val, float(intensity_val), focus))
            dates_in_csv.add(d)

    days_counted = len({d for (d, *_rest) in window_rows})
    total_rounds = sum(r for (_d, r, _i, _f) in window_rows)
    intensities = [i for (_d, _r, i, _f) in window_rows]
    if len(intensities) == 0:
        return None
    avg_intensity = round(sum(intensities) / len(intensities), 2)
    focus_breakdown: Dict[str, int] = {}
    for (_d, _r, _i, f) in window_rows:
        focus_breakdown[f] = focus_breakdown.get(f, 0) + 1

    # win_loss_record from sparring_notes opponent == "gym_rival" in window
    wins = losses = draws = 0
    for n in sparring_notes:
        if n.get("opponent") != "gym_rival":
            continue
        nd = _parse_date(str(n.get("date", "")))
        if nd is None:
            return None
        if start <= nd <= end:
            res = str(n.get("result", "")).lower()
            if res == "win":
                wins += 1
            elif res == "loss":
                losses += 1
            elif res == "draw":
                draws += 1

    # best_day_by_rounds: highest sum of rounds; tie by earliest date
    per_day_rounds: Dict[date, int] = {}
    for (d, r, _i, _f) in window_rows:
        per_day_rounds[d] = per_day_rounds.get(d, 0) + r
    if per_day_rounds:
        max_rounds = max(per_day_rounds.values())
        best_dates = sorted([d for d, v in per_day_rounds.items() if v == max_rounds])
        best_day = best_dates[0].strftime("%Y-%m-%d")
    else:
        best_day = start.strftime("%Y-%m-%d")

    iso_year, iso_week, _weekday = today.isocalendar()
    week_str = f"{iso_year}-{iso_week:02d}"

    return {
        "week": week_str,
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
        "days_counted": int(days_counted),
        "total_rounds": int(total_rounds),
        "avg_intensity": float(avg_intensity),
        "focus_area_breakdown": focus_breakdown,
        "win_loss_record": {"wins": int(wins), "losses": int(losses), "draws": int(draws)},
        "best_day_by_rounds": best_day,
    }


def _validate_daily_json(d: Any, expected: Dict[str, Any]) -> Tuple[float, float]:
    """
    Returns (structure_score, value_score) each 0.0-1.0
    """
    required_keys = {"date", "total_rounds", "average_intensity", "top_focus_area", "readiness_score", "last_spar_result"}
    if not isinstance(d, dict):
        return 0.0, 0.0
    keys_ok = set(d.keys()) == required_keys
    structure_score = 1.0 if keys_ok else 0.0
    if not keys_ok:
        return structure_score, 0.0
    # values
    ok = True
    ok = ok and (str(d["date"]) == expected["date"])
    ok = ok and (_safe_int(d["total_rounds"]) == expected["total_rounds"])
    # float compare with 1 decimal
    try:
        ok = ok and (round(float(d["average_intensity"]), 1) == round(float(expected["average_intensity"]), 1))
    except Exception:
        ok = False
    ok = ok and (str(d["top_focus_area"]) == expected["top_focus_area"])
    ok = ok and (_safe_int(d["readiness_score"]) == expected["readiness_score"])
    ok = ok and (str(d["last_spar_result"]) == expected["last_spar_result"])
    return structure_score, (1.0 if ok else 0.0)


def _validate_weekly_json(d: Any, expected: Dict[str, Any]) -> Tuple[float, float]:
    required_keys = {"week", "start_date", "end_date", "days_counted", "total_rounds", "avg_intensity", "focus_area_breakdown", "win_loss_record", "best_day_by_rounds"}
    if not isinstance(d, dict):
        return 0.0, 0.0
    keys_ok = set(d.keys()) == required_keys
    structure_score = 1.0 if keys_ok else 0.0
    if not keys_ok:
        return structure_score, 0.0
    ok = True
    ok = ok and (str(d["week"]) == expected["week"])
    ok = ok and (str(d["start_date"]) == expected["start_date"])
    ok = ok and (str(d["end_date"]) == expected["end_date"])
    ok = ok and (_safe_int(d["days_counted"]) == expected["days_counted"])
    ok = ok and (_safe_int(d["total_rounds"]) == expected["total_rounds"])
    # avg_intensity compare with 2 decimals tolerance
    try:
        ok = ok and (round(float(d["avg_intensity"]), 2) == round(float(expected["avg_intensity"]), 2))
    except Exception:
        ok = False
    # focus_area_breakdown dict equality (exact mapping)
    fab = d.get("focus_area_breakdown")
    if not isinstance(fab, dict):
        ok = False
    else:
        # ensure int values
        fab_norm = {}
        for k, v in fab.items():
            iv = _safe_int(v)
            if iv is None:
                ok = False
                break
            fab_norm[k] = iv
        ok = ok and (fab_norm == expected["focus_area_breakdown"])
    # win_loss_record exact
    wlr = d.get("win_loss_record")
    if not isinstance(wlr, dict):
        ok = False
    else:
        ok = ok and set(wlr.keys()) == {"wins", "losses", "draws"}
        if ok:
            ok = ok and (_safe_int(wlr["wins"]) == expected["win_loss_record"]["wins"])
            ok = ok and (_safe_int(wlr["losses"]) == expected["win_loss_record"]["losses"])
            ok = ok and (_safe_int(wlr["draws"]) == expected["win_loss_record"]["draws"])
    ok = ok and (str(d["best_day_by_rounds"]) == expected["best_day_by_rounds"])
    return structure_score, (1.0 if ok else 0.0)


def _md_contains_values(md_text: str, values: List[str]) -> float:
    if md_text is None:
        return 0.0
    ok = True
    for v in values:
        if v not in md_text:
            ok = False
            break
    return 1.0 if ok else 0.0


def _dm_profanity_free(text: str) -> bool:
    if text is None:
        return False
    # simple profanity list; case-insensitive, word-boundary based
    bad = [
        "fuck", "shit", "bitch", "asshole", "bastard", "crap", "dick", "piss", "fag",
        "cunt", "slut", "whore", "moron", "idiot", "stupid", "dumb", "sucks", "damn"
    ]
    lower = text.lower()
    for w in bad:
        if re.search(rf"\b{re.escape(w)}\b", lower):
            return False
    return True


def _validate_cron_file(text: str) -> Tuple[float, float, float]:
    """
    Returns (file_exists_score, daily_entry_score, weekly_entry_score)
    """
    if text is None:
        return 0.0, 0.0, 0.0
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    daily_ok = False
    weekly_ok = False

    for ln in lines:
        parts = ln.split()
        if len(parts) < 6:
            continue
        minute, hour, dom, month, dow = parts[:5]
        command = " ".join(parts[5:])
        # Check $PWD usage and log append
        uses_pwd = "$PWD" in command
        appends_log = ">>" in command and "output/schedule/cron.log" in command and "$PWD" in command

        # Daily: 0 21 * * * $PWD/scripts/run_report.sh >> $PWD/output/schedule/cron.log
        if minute == "0" and hour == "21" and dom == "*" and month == "*" and dow == "*" and "scripts/run_report.sh" in command and "--weekly" not in command and uses_pwd and appends_log:
            daily_ok = True

        # Weekly: 0 18 * * 0 or 7 or Sun
        if minute == "0" and hour == "18" and dom == "*" and month == "*":
            dow_norm = dow.lower()
            dow_valid = (dow_norm in {"0", "7", "sun"})
            if dow_valid and "scripts/run_report.sh" in command and "--weekly" in command and uses_pwd and appends_log:
                weekly_ok = True

    return 1.0, (1.0 if daily_ok else 0.0), (1.0 if weekly_ok else 0.0)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "run_script_exists_executable": 0.0,
        "daily_json_structure": 0.0,
        "daily_json_values": 0.0,
        "daily_md_includes_values": 0.0,
        "dm_file_exists": 0.0,
        "dm_phrase_length_and_question": 0.0,
        "dm_no_profanity": 0.0,
        "cron_example_exists": 0.0,
        "cron_daily_entry_valid": 0.0,
        "cron_weekly_entry_valid": 0.0,
        "last_run_log_exists": 0.0,
        "last_run_log_includes_today_paths_and_time": 0.0,
        "weekly_json_structure": 0.0,
        "weekly_json_values": 0.0,
        "weekly_md_includes_values": 0.0,
    }

    # Check run script exists and executable
    run_script = workspace / "scripts" / "run_report.sh"
    if run_script.exists():
        try:
            mode = run_script.stat().st_mode
            is_exec = bool(mode & 0o111)
        except Exception:
            is_exec = False
        scores["run_script_exists_executable"] = 1.0 if is_exec else 0.0

    # Inputs
    csv_path = workspace / "input" / "training_log.csv"
    sparring_json_path = workspace / "input" / "sparring_notes.json"
    draft_dm_path = workspace / "input" / "draft_dm.txt"

    records = _load_csv(csv_path)
    sparring_notes = _load_json(sparring_json_path)
    if not isinstance(sparring_notes, list):
        sparring_notes = None

    latest: Optional[date] = None
    if records is not None:
        latest = _get_latest_date_from_csv(records)

    today_str = latest.strftime("%Y-%m-%d") if latest else None

    # Daily outputs
    daily_json_path = workspace / "output" / "daily"
    daily_md_path = workspace / "output" / "daily"
    dm_out_path = workspace / "output" / "dm"

    if today_str is not None and records is not None and sparring_notes is not None:
        exp_daily = _compute_daily_expected(records, sparring_notes, latest)
    else:
        exp_daily = None

    # Validate daily JSON
    if today_str:
        dj_path = daily_json_path / f"summary_{today_str}.json"
        dj = _load_json(dj_path) if dj_path.exists() else None
        if dj is not None and exp_daily is not None:
            struct_score, value_score = _validate_daily_json(dj, exp_daily)
            scores["daily_json_structure"] = struct_score
            scores["daily_json_values"] = value_score

    # Validate daily MD content mirrors values (presence of values)
    if today_str:
        md_path = daily_md_path / f"summary_{today_str}.md"
        md_text = _read_text(md_path)
        if md_text is not None and exp_daily is not None:
            # Check presence of key values as strings
            vals = [
                exp_daily["date"],
                str(exp_daily["total_rounds"]),
                f"{exp_daily['average_intensity']}",
                exp_daily["top_focus_area"],
                str(exp_daily["readiness_score"]),
                exp_daily["last_spar_result"],
            ]
            scores["daily_md_includes_values"] = _md_contains_values(md_text, vals)

    # Validate DM output
    if today_str:
        dm_path = dm_out_path / f"DM_{today_str}.txt"
        if dm_path.exists():
            scores["dm_file_exists"] = 1.0
            dm_text = _read_text(dm_path) or ""
            # includes exact phrase "next spar", ends with "?", under 150 chars
            cond_phrase = "next spar" in dm_text
            cond_qmark = dm_text.strip().endswith("?")
            cond_len = len(dm_text.strip()) < 150
            scores["dm_phrase_length_and_question"] = 1.0 if (cond_phrase and cond_qmark and cond_len) else 0.0
            scores["dm_no_profanity"] = 1.0 if _dm_profanity_free(dm_text) else 0.0

    # Validate cron example
    cron_path = workspace / "output" / "schedule" / "cron_example.txt"
    cron_text = _read_text(cron_path)
    exists_score, daily_score, weekly_score = _validate_cron_file(cron_text)
    scores["cron_example_exists"] = exists_score
    scores["cron_daily_entry_valid"] = daily_score
    scores["cron_weekly_entry_valid"] = weekly_score

    # Validate last_run.log
    last_run_path = workspace / "output" / "last_run.log"
    if last_run_path.exists():
        scores["last_run_log_exists"] = 1.0
        log_text = _read_text(last_run_path) or ""
        # Require "today" date, at least one time-of-day pattern, a mode mention, and exact file paths written
        today_ok = (today_str is not None and today_str in log_text)
        time_ok = bool(re.search(r"\b\d{2}:\d{2}(:\d{2})?\b", log_text))
        # modes executed mention: look for "daily" or "weekly" or "--weekly"
        mode_ok = bool(re.search(r"\b(daily|weekly|--weekly)\b", log_text, flags=re.IGNORECASE))
        # file paths written
        paths_ok_count = 0
        total_required = 3
        if today_str:
            p1 = str((workspace / "output" / "daily" / f"summary_{today_str}.md").as_posix())
            p2 = str((workspace / "output" / "daily" / f"summary_{today_str}.json").as_posix())
            p3 = str((workspace / "output" / "dm" / f"DM_{today_str}.txt").as_posix())
            for p in [p1, p2, p3]:
                if p in log_text:
                    paths_ok_count += 1
        # If weekly files exist, also require their paths to be present in log for bonus completeness
        weekly_paths_ok = True
        if latest is not None:
            iso_year, iso_week, _ = latest.isocalendar()
            wk_json = workspace / "output" / "weekly" / f"week_{iso_year}-{iso_week:02d}.json"
            wk_md = workspace / "output" / "weekly" / f"week_{iso_year}-{iso_week:02d}.md"
            if wk_json.exists() or wk_md.exists():
                # If present, ensure their paths appear in log as well
                wp1 = str(wk_json.as_posix())
                wp2 = str(wk_md.as_posix())
                if wk_json.exists() and wp1 not in log_text:
                    weekly_paths_ok = False
                if wk_md.exists() and wp2 not in log_text:
                    weekly_paths_ok = False
        base_ok = today_ok and time_ok and mode_ok and (paths_ok_count == total_required)
        scores["last_run_log_includes_today_paths_and_time"] = 1.0 if (base_ok and weekly_paths_ok) else 0.0

    # Weekly outputs (optional)
    if latest is not None and records is not None and sparring_notes is not None:
        iso_year, iso_week, _ = latest.isocalendar()
        wk_json_path = workspace / "output" / "weekly" / f"week_{iso_year}-{iso_week:02d}.json"
        wk_md_path = workspace / "output" / "weekly" / f"week_{iso_year}-{iso_week:02d}.md"
        if wk_json_path.exists():
            wk_json = _load_json(wk_json_path)
            exp_weekly = _compute_weekly_expected(records, sparring_notes, latest)
            if wk_json is not None and exp_weekly is not None:
                ws, wv = _validate_weekly_json(wk_json, exp_weekly)
                scores["weekly_json_structure"] = ws
                scores["weekly_json_values"] = wv
        if wk_md_path.exists():
            md_text = _read_text(wk_md_path) or ""
            # Check presence of key weekly fields/values for readability
            exp_weekly = _compute_weekly_expected(records, sparring_notes, latest)
            if exp_weekly is not None:
                values_to_check = [
                    exp_weekly["week"],
                    exp_weekly["start_date"],
                    exp_weekly["end_date"],
                    str(exp_weekly["days_counted"]),
                    str(exp_weekly["total_rounds"]),
                    str(exp_weekly["avg_intensity"]),
                    exp_weekly["best_day_by_rounds"],
                    "wins",
                    "losses",
                    "draws",
                ]
                scores["weekly_md_includes_values"] = _md_contains_values(md_text, values_to_check)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()