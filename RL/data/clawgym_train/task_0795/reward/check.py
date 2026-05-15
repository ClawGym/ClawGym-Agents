import json
import sys
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import date


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_simple_yaml_map(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    text = _read_text(path)
    if text is None:
        return None, "cannot_read_file"
    data: Dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            return None, "malformed_line"
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if val == "" or val.lower() in ("null", "~"):
            data[key] = ""
            continue
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        data[key] = val
    return data, None


def _safe_load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _safe_read_csv_rows(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict({k: (v if v is not None else "") for k, v in row.items()}) for row in reader]
        return rows, None
    except Exception as e:
        return None, str(e)


def _parse_iso_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s.strip())
    except Exception:
        return None


def _parse_bool_like(s: str) -> Optional[bool]:
    if s is None:
        return None
    t = str(s).strip().lower()
    if t in ("true", "t", "yes", "y", "1"):
        return True
    if t in ("false", "f", "no", "n", "0"):
        return False
    return None


def _is_blank(s: Optional[str]) -> bool:
    return s is None or str(s).strip() == ""


def _compute_upcoming_issues(schedule_rows: List[Dict[str, str]], club: str, today_d: date) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for row in schedule_rows:
        round_ = (row.get("round") or "").strip()
        date_str = (row.get("date") or "").strip()
        home = (row.get("home_team") or "").strip()
        away = (row.get("away_team") or "").strip()
        venue = (row.get("venue") or "")
        has_ticket_info_raw = row.get("has_ticket_info") or ""
        d = _parse_iso_date(date_str)
        if d is None:
            continue
        if not (home == club or away == club):
            continue
        if d >= today_d:
            missing_fields: List[str] = []
            if _is_blank(venue):
                missing_fields.append("venue")
            has_ticket = _parse_bool_like(has_ticket_info_raw)
            if has_ticket is False:
                missing_fields.append("ticket_info")
            if missing_fields:
                issues.append({
                    "round": round_,
                    "date": date_str,
                    "home_team": home,
                    "away_team": away,
                    "missing_fields": missing_fields
                })
    return issues


def _compute_past_stats_issues(stats_entries: List[Dict[str, Any]], club: str, today_d: date) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for entry in stats_entries:
        try:
            team = entry.get("team", "")
            if team != club:
                continue
            date_str = entry.get("date", "")
            d = _parse_iso_date(date_str)
            if d is None:
                continue
            if not (d < today_d):
                continue
            round_ = entry.get("round", "")
            opponent = entry.get("opponent", "")
            qs = entry.get("quarter_scores", None)
            actual_quarters: Optional[int] = None
            if isinstance(qs, list):
                actual_quarters = len(qs)
            if not (isinstance(qs, list) and len(qs) == 4):
                issues.append({
                    "round": round_,
                    "date": date_str,
                    "opponent": opponent,
                    "issue": "quarter_scores_incomplete",
                    "expected_quarters": 4,
                    "actual_quarters": actual_quarters
                })
            tp_missing = ("total_points" not in entry) or (entry.get("total_points", None) is None)
            if tp_missing:
                issues.append({
                    "round": round_,
                    "date": date_str,
                    "opponent": opponent,
                    "issue": "total_points_missing",
                    "expected_quarters": 4,
                    "actual_quarters": actual_quarters
                })
        except Exception:
            continue
    return issues


def _canonicalize_upcoming_issue(item: Dict[str, Any]) -> Tuple[str, str, str, str, Tuple[str, ...]]:
    missing = item.get("missing_fields", [])
    if not isinstance(missing, list):
        missing = []
    missing_sorted = tuple(sorted([str(x) for x in missing]))
    return (
        str(item.get("round", "")),
        str(item.get("date", "")),
        str(item.get("home_team", "")),
        str(item.get("away_team", "")),
        missing_sorted
    )


def _canonicalize_past_issue(item: Dict[str, Any]) -> Tuple[str, str, str, str, int, Optional[int]]:
    expected_quarters_val = item.get("expected_quarters", 0)
    if isinstance(expected_quarters_val, int):
        expected_quarters = expected_quarters_val
    elif isinstance(expected_quarters_val, str) and expected_quarters_val.isdigit():
        expected_quarters = int(expected_quarters_val)
    else:
        expected_quarters = 0
    actual_quarters_val = item.get("actual_quarters", None)
    if isinstance(actual_quarters_val, int):
        actual_quarters = actual_quarters_val
    else:
        actual_quarters = None
    return (
        str(item.get("round", "")),
        str(item.get("date", "")),
        str(item.get("opponent", "")),
        str(item.get("issue", "")),
        expected_quarters,
        actual_quarters
    )


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_club_correct": 0.0,
        "config_membership_contact_correct": 0.0,
        "config_stats_channel_correct": 0.0,
        "config_today_preserved": 0.0,
        "report_file_valid": 0.0,
        "report_keys_exact": 0.0,
        "report_club_today_match_config": 0.0,
        "report_upcoming_issues_match_expected": 0.0,
        "report_past_stats_issues_match_expected": 0.0,
        "email_membership_header_correct": 0.0,
        "email_membership_body_covers_upcoming_issues": 0.0,
        "stats_channel_header_correct": 0.0,
        "stats_channel_body_covers_past_issues": 0.0,
    }

    # Load config
    config_path = workspace / "input" / "config.yaml"
    config, cfg_err = _parse_simple_yaml_map(config_path)
    if config is None:
        return scores

    club = config.get("club", "")
    today_str = config.get("today", "")
    membership_contact = config.get("membership_contact", "")
    stats_channel = config.get("stats_channel", "")
    today_d = _parse_iso_date(today_str) if isinstance(today_str, str) else None

    # Config checks
    if club == "St Kilda":
        scores["config_club_correct"] = 1.0
    if membership_contact == "membership@saints.test":
        scores["config_membership_contact_correct"] = 1.0
    if stats_channel == "stats-saints-room":
        scores["config_stats_channel_correct"] = 1.0
    # Consider "today preserved" only meaningful when club is correctly updated to St Kilda
    if club == "St Kilda" and isinstance(today_str, str) and today_str == "2024-05-10":
        scores["config_today_preserved"] = 1.0

    # Load inputs for computing expectations
    schedule_rows, _ = _safe_read_csv_rows(workspace / "input" / "schedule.csv")
    stats_entries_raw, _ = _safe_load_json(workspace / "input" / "stats.json")

    if today_d is None or schedule_rows is None or stats_entries_raw is None or not isinstance(stats_entries_raw, list):
        expected_upcoming: List[Dict[str, Any]] = []
        expected_past: List[Dict[str, Any]] = []
    else:
        expected_upcoming = _compute_upcoming_issues(schedule_rows, club, today_d)
        stats_entries: List[Dict[str, Any]] = []
        for e in stats_entries_raw:
            if isinstance(e, dict):
                stats_entries.append(e)
        expected_past = _compute_past_stats_issues(stats_entries, club, today_d)

    # Validate report file
    report_path = workspace / "output" / "missing_data_report.json"
    report_obj, _ = _safe_load_json(report_path)
    if isinstance(report_obj, dict):
        scores["report_file_valid"] = 1.0
        expected_keys = {"club", "today", "upcoming_issues", "past_stats_issues"}
        actual_keys = set(report_obj.keys())
        if actual_keys == expected_keys:
            scores["report_keys_exact"] = 1.0
        if report_obj.get("club", None) == club and report_obj.get("today", None) == today_str:
            scores["report_club_today_match_config"] = 1.0
        rep_upcoming = report_obj.get("upcoming_issues", None)
        if isinstance(rep_upcoming, list):
            exp_can = sorted([_canonicalize_upcoming_issue(x) for x in expected_upcoming])
            rep_can = sorted([_canonicalize_upcoming_issue(x) for x in rep_upcoming])
            if exp_can == rep_can:
                scores["report_upcoming_issues_match_expected"] = 1.0
        rep_past = report_obj.get("past_stats_issues", None)
        if isinstance(rep_past, list):
            exp_can_past = sorted([_canonicalize_past_issue(x) for x in expected_past])
            rep_can_past = sorted([_canonicalize_past_issue(x) for x in rep_past])
            if exp_can_past == rep_can_past:
                scores["report_past_stats_issues_match_expected"] = 1.0

    # Validate email to membership
    email_path = workspace / "output" / "email_membership.txt"
    email_text = _read_text(email_path)
    if isinstance(email_text, str):
        lines = [ln.rstrip("\n") for ln in email_text.splitlines()]
        if len(lines) >= 2:
            expected_to = f"To: {membership_contact}"
            expected_subject = f"Subject: {club} fixture info gaps (as of {today_str})"
            if lines[0].strip() == expected_to and lines[1].strip() == expected_subject:
                scores["email_membership_header_correct"] = 1.0
        if today_d is not None and schedule_rows is not None:
            body = "\n".join(lines[2:]) if len(lines) > 2 else ""
            all_ok = True
            for item in expected_upcoming:
                home = item.get("home_team", "")
                away = item.get("away_team", "")
                opponent = away if home == club else home
                round_ = item.get("round", "")
                dstr = item.get("date", "")
                missing_fields = item.get("missing_fields", [])
                cond_round = round_ in body
                cond_date = dstr in body
                cond_opp = opponent in body
                cond_missing = all(m in body for m in missing_fields if isinstance(m, str))
                if not (cond_round and cond_date and cond_opp and cond_missing):
                    all_ok = False
                    break
            if all_ok:
                scores["email_membership_body_covers_upcoming_issues"] = 1.0

    # Validate message to stats channel
    msg_path = workspace / "output" / "message_stats_channel.txt"
    msg_text = _read_text(msg_path)
    if isinstance(msg_text, str):
        lines = [ln.rstrip("\n") for ln in msg_text.splitlines()]
        if len(lines) >= 1:
            expected_channel = f"Channel: {stats_channel}"
            if lines[0].strip() == expected_channel:
                scores["stats_channel_header_correct"] = 1.0
        if today_d is not None and isinstance(stats_entries_raw, list):
            body = "\n".join(lines[1:]) if len(lines) > 1 else ""
            all_ok = True
            for item in expected_past:
                round_ = item.get("round", "")
                dstr = item.get("date", "")
                opp = item.get("opponent", "")
                issue = item.get("issue", "")
                cond_round = round_ in body
                cond_date = dstr in body
                cond_opp = opp in body
                cond_issue = issue in body
                if not (cond_round and cond_date and cond_opp and cond_issue):
                    all_ok = False
                    break
            if all_ok:
                scores["stats_channel_body_covers_past_issues"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()