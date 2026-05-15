import json
import sys
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_json_load(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_csv_load(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: v for k, v in row.items()})
            return rows
    except Exception:
        return None


def _strip_quotes(value: str) -> str:
    v = value.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    return v


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for simple nested mappings (no lists).
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    for raw_line in lines:
        # remove comments
        line_wo_comment = raw_line.split("#", 1)[0]
        line = line_wo_comment.rstrip("\r\n")
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        # adjust stack to current indent level
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        current = stack[-1][1]
        if ":" not in line:
            return None
        key_part, val_part = line.lstrip(" ").split(":", 1)
        key = key_part.strip()
        val = val_part.strip()
        if val == "":
            # nested dict begins
            d: Dict[str, Any] = {}
            current[key] = d
            stack.append((indent, d))
        else:
            current[key] = _strip_quotes(val)
    return root


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _parse_cron_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse a simple cron line: MIN HOUR DOM MON DOW CMD...
    Returns dict with minute, hour, dom, mon, dow, cmd or None if invalid.
    """
    parts = line.strip().split()
    if len(parts) < 6:
        return None
    minute = parts[0]
    hour = parts[1]
    dom = parts[2]
    mon = parts[3]
    dow = parts[4]
    cmd = " ".join(parts[5:])
    return {"minute": minute, "hour": hour, "dom": dom, "mon": mon, "dow": dow, "cmd": cmd}


def _load_attendance(path: Path) -> Optional[List[Dict[str, Any]]]:
    rows = _safe_csv_load(path)
    if rows is None:
        return None
    cleaned: List[Dict[str, Any]] = []
    for r in rows:
        try:
            date = (r.get("date") or "").strip()
            gid = (r.get("group_id") or "").strip()
            activity = (r.get("activity") or "").strip()
            headcount_str = (r.get("headcount") or "").strip()
            headcount = int(headcount_str)
            cleaned.append({"date": date, "group_id": gid, "activity": activity, "headcount": headcount})
        except Exception:
            return None
    return cleaned


def _load_roster(path: Path) -> Optional[Dict[str, Dict[str, str]]]:
    data = _safe_json_load(path)
    if data is None or not isinstance(data, dict):
        return None
    groups = data.get("groups")
    if not isinstance(groups, list):
        return None
    mapping: Dict[str, Dict[str, str]] = {}
    for g in groups:
        try:
            gid = g["group_id"]
            name = g["name"]
            leader = g["leader"]
            mapping[gid] = {"group_name": name, "leader": leader}
        except Exception:
            return None
    return mapping


def _latest_date(rows: List[Dict[str, Any]]) -> Optional[str]:
    dates = [r["date"] for r in rows if r.get("date")]
    if not dates:
        return None
    return max(dates)


def _unique_dates_desc(rows: List[Dict[str, Any]]) -> List[str]:
    uniq = sorted({r["date"] for r in rows if r.get("date")}, reverse=True)
    return uniq


def _sum_headcount_on_date(rows: List[Dict[str, Any]], target_date: str) -> int:
    return sum(r["headcount"] for r in rows if r["date"] == target_date)


def _per_group_headcount_on_date(rows: List[Dict[str, Any]], target_date: str, roster_ids: List[str]) -> Dict[str, int]:
    per: Dict[str, int] = {gid: 0 for gid in roster_ids}
    for r in rows:
        if r["date"] == target_date and r["group_id"] in per:
            per[r["group_id"]] += r["headcount"]
    return per


def _top_activities_on_date(rows: List[Dict[str, Any]], target_date: str, top_n: int = 3) -> List[Tuple[str, int]]:
    counts: Dict[str, int] = {}
    for r in rows:
        if r["date"] == target_date:
            counts[r["activity"]] = counts.get(r["activity"], 0) + r["headcount"]
    sorted_items = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return sorted_items[:top_n]


def _prev_date_for_group(rows: List[Dict[str, Any]], group_id: str, before_date: str) -> Optional[str]:
    candidates = sorted({r["date"] for r in rows if r["group_id"] == group_id and r["date"] < before_date})
    if not candidates:
        return None
    return candidates[-1]


def _headcount_for_group_on_date(rows: List[Dict[str, Any]], group_id: str, date: str) -> int:
    return sum(r["headcount"] for r in rows if r["group_id"] == group_id and r["date"] == date)


def _compute_week_over_week(rows: List[Dict[str, Any]], roster_ids: List[str], report_date: str) -> Dict[str, Optional[float]]:
    wow: Dict[str, Optional[float]] = {}
    for gid in roster_ids:
        current = _headcount_for_group_on_date(rows, gid, report_date)
        prev_date = _prev_date_for_group(rows, gid, report_date)
        if prev_date is None:
            wow[gid] = None
        else:
            prev = _headcount_for_group_on_date(rows, gid, prev_date)
            if prev == 0:
                wow[gid] = None
            else:
                pct = (current - prev) / prev * 100.0
                wow[gid] = pct
    return wow


def _unknown_groups(rows: List[Dict[str, Any]], roster_ids: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    roster_set = set(roster_ids)
    for r in rows:
        if r["group_id"] not in roster_set:
            out.append({"date": r["date"], "group_id": r["group_id"], "activity": r["activity"], "headcount": r["headcount"]})
    return out


def _missing_groups_on_date(rows: List[Dict[str, Any]], roster_ids: List[str], date: str) -> List[str]:
    present = {r["group_id"] for r in rows if r["date"] == date}
    missing = [gid for gid in roster_ids if gid not in present]
    return missing


def _compute_rolling(rows: List[Dict[str, Any]], roster: Dict[str, Dict[str, str]], window: int = 4) -> List[Dict[str, Any]]:
    dates_desc = _unique_dates_desc(rows)
    dates_win = dates_desc[:window]
    weeks_counted = len(dates_win)
    by_group: List[Dict[str, Any]] = []
    roster_ids = list(roster.keys())
    for gid in roster_ids:
        total = 0
        for d in dates_win:
            total += _headcount_for_group_on_date(rows, gid, d)
        avg = (total / weeks_counted) if weeks_counted > 0 else 0.0
        by_group.append({
            "group_id": gid,
            "group_name": roster[gid]["group_name"],
            "leader": roster[gid]["leader"],
            "weeks_counted": weeks_counted,
            "total_headcount": total,
            "avg_headcount": avg,
        })
    return by_group


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_schedule_updated": 0.0,
        "config_other_fields_preserved": 0.0,
        "cron_manifest_valid": 0.0,
        "summary_exists_and_structure": 0.0,
        "summary_overall_headcount_correct": 0.0,
        "summary_groups_headcounts_correct": 0.0,
        "summary_week_over_week_correct": 0.0,
        "summary_top_activities_correct": 0.0,
        "summary_data_checks_correct": 0.0,
        "group_stats_csv_correct": 0.0,
        "rolling_4_weeks_csv_correct": 0.0,
    }

    # Load config
    config_path = workspace / "config" / "schedule.yaml"
    yaml_obj = _parse_simple_yaml(config_path) if config_path.exists() else None

    attendance_path = workspace / "input" / "attendance_log.csv"
    roster_path = workspace / "input" / "roster.json"
    rows = _load_attendance(attendance_path) if attendance_path.exists() else None
    roster_map = _load_roster(roster_path) if roster_path.exists() else None

    # 1) Check config schedule and fields
    schedule_correct = False
    if yaml_obj is not None and isinstance(yaml_obj, dict):
        schedule = yaml_obj.get("schedule", {})
        io_cfg = yaml_obj.get("io", {})
        reporting = yaml_obj.get("reporting", {})
        try:
            if schedule.get("day_of_week") == "Saturday" and schedule.get("time") == "18:00":
                schedule_correct = True
                scores["config_schedule_updated"] = 1.0
        except Exception:
            pass
        try:
            # Only award "other fields preserved" if schedule is correctly updated AND other fields match expectations
            other_ok = True
            if schedule.get("timezone") != "local":
                other_ok = False
            if io_cfg.get("attendance_csv") != "input/attendance_log.csv":
                other_ok = False
            if io_cfg.get("roster_json") != "input/roster.json":
                other_ok = False
            if io_cfg.get("output_dir") != "reports/weekly":
                other_ok = False
            if io_cfg.get("ops_dir") != "ops":
                other_ok = False
            rw = reporting.get("rolling_window_weeks")
            if not (rw == "4" or rw == 4):
                other_ok = False
            if reporting.get("report_name_prefix") != "attendance":
                other_ok = False
            if schedule_correct and other_ok:
                scores["config_other_fields_preserved"] = 1.0
        except Exception:
            pass

    # 2) Check cron manifest (must match updated schedule in config)
    cron_path = workspace / "ops" / "weekly_reports.cron"
    cron_text = _read_text(cron_path)
    if cron_text is not None and schedule_correct:
        # Filter to non-empty, non-comment lines
        lines = [ln for ln in (l.strip() for l in cron_text.splitlines()) if ln and not ln.startswith("#")]
        if len(lines) == 1:
            parsed = _parse_cron_line(lines[0])
            if parsed is not None:
                minute = parsed["minute"]
                hour = parsed["hour"]
                dow = parsed["dow"]
                cmd = parsed["cmd"]
                saturday_vals = {"6", "Sat", "SAT", "sat"}
                if minute == "0" and hour == "18" and (dow in saturday_vals):
                    allowed_cmds = {
                        "python tools/generate_reports.py --config config/schedule.yaml",
                        "python3 tools/generate_reports.py --config config/schedule.yaml",
                    }
                    if cmd in allowed_cmds:
                        scores["cron_manifest_valid"] = 1.0

    # If we can't compute expected values, we can't check reports in detail
    latest = None
    roster_ids: List[str] = []
    if rows is not None and roster_map is not None:
        latest = _latest_date(rows)
        roster_ids = list(roster_map.keys())

    if rows is None or roster_map is None or latest is None:
        return scores

    # Compute expected values
    expected_report_date = latest
    overall_headcount = _sum_headcount_on_date(rows, expected_report_date)
    per_group = _per_group_headcount_on_date(rows, expected_report_date, roster_ids)
    wow = _compute_week_over_week(rows, roster_ids, expected_report_date)
    top_acts = _top_activities_on_date(rows, expected_report_date, 3)
    unknowns = _unknown_groups(rows, roster_ids)
    missing_groups = _missing_groups_on_date(rows, roster_ids, expected_report_date)
    rolling = _compute_rolling(rows, roster_map, window=4)

    # 3) Check reports
    weekly_dir = workspace / "reports" / "weekly" / expected_report_date
    summary_path = weekly_dir / "summary.json"
    group_stats_path = weekly_dir / "group_stats.csv"
    rolling_path = workspace / "reports" / "rolling_4_weeks.csv"

    # Summary exists and structure
    summary = _safe_json_load(summary_path) if summary_path.exists() else None
    if isinstance(summary, dict):
        has_fields = (
            isinstance(summary.get("report_date"), str)
            and "generated_at" in summary
            and isinstance(summary.get("totals"), dict)
            and isinstance(summary.get("groups"), list)
            and isinstance(summary.get("top_activities"), list)
            and isinstance(summary.get("data_checks"), dict)
        )
        gen_at = summary.get("generated_at", "")
        if has_fields and isinstance(gen_at, str) and ("T" in gen_at or " " in gen_at):
            scores["summary_exists_and_structure"] = 1.0

        # overall headcount correct
        try:
            if summary.get("report_date") == expected_report_date:
                totals = summary.get("totals", {})
                oh = totals.get("overall_headcount")
                if isinstance(oh, (int, float)) and _float_equal(float(oh), float(overall_headcount)):
                    scores["summary_overall_headcount_correct"] = 1.0
        except Exception:
            pass

        # groups headcounts and week-over-week
        try:
            groups_list = summary.get("groups", [])
            got_groups: Dict[str, Dict[str, Any]] = {}
            for g in groups_list:
                gid = g.get("group_id")
                if gid:
                    got_groups[gid] = g
            all_ok = True
            wow_ok = True
            for gid in roster_ids:
                exp_name = roster_map[gid]["group_name"]
                exp_leader = roster_map[gid]["leader"]
                exp_head = per_group.get(gid, 0)
                entry = got_groups.get(gid)
                if entry is None:
                    all_ok = False
                    wow_ok = False
                    break
                if entry.get("group_name") != exp_name or entry.get("leader") != exp_leader:
                    all_ok = False
                h = entry.get("headcount")
                if not isinstance(h, (int, float)) or not _float_equal(float(h), float(exp_head)):
                    all_ok = False
                exp_wow = wow.get(gid)
                got_wow = entry.get("week_over_week_change_pct")
                if exp_wow is None:
                    if got_wow is not None:
                        wow_ok = False
                else:
                    if not isinstance(got_wow, (int, float)) or not _float_equal(float(got_wow), float(exp_wow)):
                        wow_ok = False
            if all_ok:
                scores["summary_groups_headcounts_correct"] = 1.0
            if wow_ok:
                scores["summary_week_over_week_correct"] = 1.0
        except Exception:
            pass

        # top activities correct
        try:
            expected_top = [{"activity": a, "headcount": c} for a, c in top_acts]
            got_top = summary.get("top_activities", [])
            ok = True
            if len(got_top) != len(expected_top):
                ok = False
            else:
                for i, exp in enumerate(expected_top):
                    gt = got_top[i]
                    if gt.get("activity") != exp["activity"]:
                        ok = False
                        break
                    hc = gt.get("headcount")
                    if not isinstance(hc, (int, float)) or not _float_equal(float(hc), float(exp["headcount"])):
                        ok = False
                        break
            if ok:
                scores["summary_top_activities_correct"] = 1.0
        except Exception:
            pass

        # data checks correct
        try:
            data_checks = summary.get("data_checks", {})
            got_unknowns = data_checks.get("unknown_groups", [])
            got_missing = data_checks.get("missing_groups", [])
            exp_unknown_set = {(u["date"], u["group_id"], u["activity"], int(u["headcount"])) for u in unknowns}
            try:
                got_unknown_set = {(u.get("date"), u.get("group_id"), u.get("activity"), int(u.get("headcount"))) for u in got_unknowns}
            except Exception:
                got_unknown_set = set()
            exp_missing_set = set(missing_groups)
            got_missing_set = set(got_missing if isinstance(got_missing, list) else [])
            if exp_unknown_set == got_unknown_set and exp_missing_set == got_missing_set:
                scores["summary_data_checks_correct"] = 1.0
        except Exception:
            pass

    # group_stats.csv correctness
    gs_rows = _safe_csv_load(group_stats_path) if group_stats_path.exists() else None
    if gs_rows is not None:
        try:
            with group_stats_path.open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
            expected_header = "group_id,group_name,leader,headcount"
            header_ok = (header_line == expected_header)
        except Exception:
            header_ok = False
        content_ok = True
        got_map: Dict[str, Dict[str, Any]] = {}
        for r in gs_rows:
            gid = (r.get("group_id") or "").strip()
            if gid:
                got_map[gid] = r
        for gid in roster_ids:
            r = got_map.get(gid)
            if r is None:
                content_ok = False
                break
            if r.get("group_name") != roster_map[gid]["group_name"]:
                content_ok = False
                break
            if r.get("leader") != roster_map[gid]["leader"]:
                content_ok = False
                break
            try:
                hc = int((r.get("headcount") or "").strip())
            except Exception:
                content_ok = False
                break
            if hc != per_group.get(gid, 0):
                content_ok = False
                break
        if header_ok and content_ok and len(gs_rows) == len(roster_ids):
            scores["group_stats_csv_correct"] = 1.0

    # rolling_4_weeks.csv correctness
    rolling_rows = _safe_csv_load(rolling_path) if rolling_path.exists() else None
    if rolling_rows is not None:
        try:
            with rolling_path.open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
            expected_header = "group_id,group_name,leader,weeks_counted,total_headcount,avg_headcount"
            header_ok = (header_line == expected_header)
        except Exception:
            header_ok = False
        exp_map: Dict[str, Dict[str, Any]] = {r["group_id"]: r for r in rolling}
        got_ok = True
        got_ids: set = set()
        for r in rolling_rows:
            gid = (r.get("group_id") or "").strip()
            if not gid or gid in got_ids:
                got_ok = False
                break
            got_ids.add(gid)
            e = exp_map.get(gid)
            if e is None:
                got_ok = False
                break
            if r.get("group_name") != e["group_name"] or r.get("leader") != e["leader"]:
                got_ok = False
                break
            try:
                weeks = int((r.get("weeks_counted") or "").strip())
                total = int((r.get("total_headcount") or "").strip())
                avg = float((r.get("avg_headcount") or "").strip())
            except Exception:
                got_ok = False
                break
            if weeks != e["weeks_counted"] or total != e["total_headcount"] or (not _float_equal(avg, float(e["avg_headcount"]))):
                got_ok = False
                break
        if header_ok and got_ok and len(rolling_rows) == len(roster_ids):
            scores["rolling_4_weeks_csv_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()