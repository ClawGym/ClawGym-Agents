import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # Normalize keys by stripping whitespace
                normalized = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                rows.append(normalized)
            return rows
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_iso8601_z(s: str) -> Optional[datetime]:
    # Expect format like 2025-02-14T07:42:05Z
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _iso8601_z(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_expected_from_inputs(auth_rows: List[Dict[str, str]], staff_rows: List[Dict[str, str]]):
    # Collect events and failure events
    total_events = len(auth_rows)
    failure_rows = [r for r in auth_rows if r.get("event") == "login" and r.get("status") == "failure"]
    total_login_failures = len(failure_rows)

    # Map user -> role, active
    staff_map = {}
    for r in staff_rows:
        staff_map[r.get("username", "")] = {
            "role": r.get("role", ""),
            "active": r.get("active", ""),
        }

    # Failed summary by IP
    ip_to_failures: Dict[str, List[Tuple[datetime, str]]] = {}
    for r in failure_rows:
        ip = r.get("ip", "")
        ts = _parse_iso8601_z(r.get("timestamp", ""))
        user = r.get("username", "")
        if ts is None or not ip:
            continue
        ip_to_failures.setdefault(ip, []).append((ts, user))

    failed_summary_expected = []
    flagged_count = 0
    for ip, lst in ip_to_failures.items():
        times_users = sorted(lst, key=lambda x: x[0])
        times = [t for t, _ in times_users]
        users = [u for _, u in times_users]
        first_seen = _iso8601_z(times[0])
        last_seen = _iso8601_z(times[-1])
        total_failures_ip = len(times)
        unique_users = len(set(users))

        # Compute peak within any rolling 60-minute window (>5 flagged condition)
        peak = 0
        j = 0
        for i in range(len(times)):
            start = times[i]
            # Move j to include all within 60 minutes inclusive of endpoints
            while j < len(times) and (times[j] - start) <= timedelta(minutes=60):
                j += 1
            # window includes i..j-1
            count = j - i
            if count > peak:
                peak = count
        flagged = peak > 5
        if flagged:
            flagged_count += 1

        failed_summary_expected.append({
            "ip": ip,
            "total_failures": total_failures_ip,
            "unique_users": unique_users,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "peak_60min_count": peak,
            "flagged": flagged,
        })

    # Sort expected by ip for deterministic comparison
    failed_summary_expected.sort(key=lambda x: x["ip"])

    # User failures
    user_to_failures: Dict[str, List[datetime]] = {}
    for r in failure_rows:
        user = r.get("username", "")
        ts = _parse_iso8601_z(r.get("timestamp", ""))
        if not user or ts is None:
            continue
        user_to_failures.setdefault(user, []).append(ts)

    user_failures_expected = []
    for user, tlist in user_to_failures.items():
        tlist_sorted = sorted(tlist)
        last_failure_date = tlist_sorted[-1].date().isoformat()
        staff_info = staff_map.get(user, {"role": "", "active": ""})
        user_failures_expected.append({
            "username": user,
            "role": staff_info.get("role", ""),
            "active": staff_info.get("active", ""),
            "failures": len(tlist),
            "last_failure_date": last_failure_date,
        })

    # Include users with at least one login failure (already)
    # Sort by username
    user_failures_expected.sort(key=lambda x: x["username"])

    # Overall stats
    # Hours present in the input/auth_log.csv (based on all events)
    hours_present = set()
    for r in auth_rows:
        ts = _parse_iso8601_z(r.get("timestamp", ""))
        if ts is None:
            continue
        hour_key = ts.replace(minute=0, second=0, microsecond=0)
        hours_present.add(hour_key)
    hours_present_list = sorted(hours_present)
    per_hour_counts = []
    for hour in hours_present_list:
        # Count failures in this hour
        cnt = 0
        for r in failure_rows:
            ts = _parse_iso8601_z(r.get("timestamp", ""))
            if ts is None:
                continue
            if ts.year == hour.year and ts.month == hour.month and ts.day == hour.day and ts.hour == hour.hour:
                cnt += 1
        per_hour_counts.append(cnt)
    if len(hours_present_list) > 0:
        per_hour_failure_mean = sum(per_hour_counts) / float(len(hours_present_list))
        per_hour_failure_max = max(per_hour_counts)
    else:
        per_hour_failure_mean = 0.0
        per_hour_failure_max = 0

    # Unique IPs with failures
    unique_ips_with_failures = len(ip_to_failures)

    # Top IPs by failures: top 3
    ip_counts = []
    for ip, lst in ip_to_failures.items():
        ip_counts.append((ip, len(lst)))
    ip_counts.sort(key=lambda x: (-x[1], x[0]))
    top_ips_by_failures = [{"ip": ip, "count": count} for ip, count in ip_counts[:3]]

    overall_stats_expected = {
        "total_events": total_events,
        "total_login_failures": total_login_failures,
        "unique_ips_with_failures": unique_ips_with_failures,
        "top_ips_by_failures": top_ips_by_failures,
        "per_hour_failure_mean": per_hour_failure_mean,
        "per_hour_failure_max": per_hour_failure_max,
    }

    return failed_summary_expected, user_failures_expected, overall_stats_expected, flagged_count


def _parse_bool_str(s: str) -> Optional[bool]:
    if s is None:
        return None
    s_lower = s.strip().lower()
    if s_lower in ("true", "t", "yes", "1"):
        return True
    if s_lower in ("false", "f", "no", "0"):
        return False
    return None


def _compare_failed_summary(actual_rows: List[Dict[str, str]], expected: List[Dict[str, object]]) -> bool:
    # Required columns and order
    required_cols = ["ip", "total_failures", "unique_users", "first_seen", "last_seen", "peak_60min_count", "flagged"]
    # Verify headers
    header_ok = True
    if not actual_rows:
        return False
    # The DictReader rows do not carry header order; we need a separate check for header order from file parsing.
    # Since we don't have raw header here, we assume that the caller validated header order when loading.
    # We'll proceed to content comparison.

    # Convert actual rows to normalized form with types
    normalized_actual = []
    for r in actual_rows:
        try:
            entry = {
                "ip": r.get("ip", ""),
                "total_failures": int(r.get("total_failures", "").strip()) if r.get("total_failures", "").strip() != "" else None,
                "unique_users": int(r.get("unique_users", "").strip()) if r.get("unique_users", "").strip() != "" else None,
                "first_seen": r.get("first_seen", ""),
                "last_seen": r.get("last_seen", ""),
                "peak_60min_count": int(r.get("peak_60min_count", "").strip()) if r.get("peak_60min_count", "").strip() != "" else None,
                "flagged": _parse_bool_str(r.get("flagged", "")),
            }
        except Exception:
            return False
        normalized_actual.append(entry)

    # Sort both by ip ascending for comparison
    normalized_actual.sort(key=lambda x: x["ip"])
    expected_sorted = sorted(expected, key=lambda x: x["ip"])

    if len(normalized_actual) != len(expected_sorted):
        return False

    for a, e in zip(normalized_actual, expected_sorted):
        for k in ["ip", "total_failures", "unique_users", "first_seen", "last_seen", "peak_60min_count", "flagged"]:
            if a.get(k) != e.get(k):
                return False
    return header_ok


def _compare_user_failures(actual_rows: List[Dict[str, str]], expected: List[Dict[str, object]]) -> bool:
    # Convert actual to normalized typed values
    normalized_actual = []
    for r in actual_rows:
        try:
            entry = {
                "username": r.get("username", ""),
                "role": r.get("role", ""),
                "active": r.get("active", ""),
                "failures": int(r.get("failures", "").strip()) if r.get("failures", "").strip() != "" else None,
                "last_failure_date": r.get("last_failure_date", ""),
            }
        except Exception:
            return False
        normalized_actual.append(entry)

    # Sort by username
    normalized_actual.sort(key=lambda x: x["username"])
    expected_sorted = sorted(expected, key=lambda x: x["username"])

    if len(normalized_actual) != len(expected_sorted):
        return False
    for a, e in zip(normalized_actual, expected_sorted):
        for k in ["username", "role", "active", "failures", "last_failure_date"]:
            if a.get(k) != e.get(k):
                return False
    return True


def _float_close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _check_header_order(path: Path, required_cols: List[str]) -> bool:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return False
            # Strip spaces in header for comparison
            header = [h.strip() for h in header]
            return header == required_cols
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "analyze_script_exists": 0.0,
        "failed_summary_csv_valid": 0.0,
        "user_failures_csv_valid": 0.0,
        "overall_stats_json_valid": 0.0,
        "run_log_contains_command": 0.0,
        "run_log_summary_matches": 0.0,
        "memo_exists": 0.0,
        "memo_word_limit": 0.0,
        "memo_contains_required_actions": 0.0,
        "memo_tone_supportive_non_alarmist": 0.0,
    }

    # Check analyze script exists
    analyze_script = workspace / "scripts" / "analyze_log.py"
    if analyze_script.is_file():
        scores["analyze_script_exists"] = 1.0

    # Load inputs
    auth_csv = workspace / "input" / "auth_log.csv"
    staff_csv = workspace / "input" / "staff_roles.csv"
    auth_rows = _load_csv_rows(auth_csv) if auth_csv.is_file() else None
    staff_rows = _load_csv_rows(staff_csv) if staff_csv.is_file() else None

    expected = None
    if auth_rows is not None and staff_rows is not None:
        try:
            expected = _compute_expected_from_inputs(auth_rows, staff_rows)
        except Exception:
            expected = None

    # Validate reports/failed_summary.csv
    failed_summary_path = workspace / "reports" / "failed_summary.csv"
    if failed_summary_path.is_file() and expected is not None:
        # Check header order strictly
        required_cols_failed = ["ip", "total_failures", "unique_users", "first_seen", "last_seen", "peak_60min_count", "flagged"]
        header_ok = _check_header_order(failed_summary_path, required_cols_failed)
        actual_rows = _load_csv_rows(failed_summary_path)
        if header_ok and actual_rows is not None:
            expected_failed, _, _, _ = expected
            if _compare_failed_summary(actual_rows, expected_failed):
                scores["failed_summary_csv_valid"] = 1.0

    # Validate reports/user_failures.csv
    user_failures_path = workspace / "reports" / "user_failures.csv"
    if user_failures_path.is_file() and expected is not None:
        required_cols_users = ["username", "role", "active", "failures", "last_failure_date"]
        header_ok_users = _check_header_order(user_failures_path, required_cols_users)
        actual_rows = _load_csv_rows(user_failures_path)
        if header_ok_users and actual_rows is not None:
            _, expected_user_failures, _, _ = expected
            if _compare_user_failures(actual_rows, expected_user_failures):
                scores["user_failures_csv_valid"] = 1.0

    # Validate reports/overall_stats.json
    overall_stats_path = workspace / "reports" / "overall_stats.json"
    if overall_stats_path.is_file() and expected is not None:
        actual_json = _load_json_safe(overall_stats_path)
        if isinstance(actual_json, dict):
            _, _, expected_overall, _ = expected
            try:
                conds = []
                conds.append(actual_json.get("total_events") == expected_overall["total_events"])
                conds.append(actual_json.get("total_login_failures") == expected_overall["total_login_failures"])
                conds.append(actual_json.get("unique_ips_with_failures") == expected_overall["unique_ips_with_failures"])
                # top_ips_by_failures
                actual_top = actual_json.get("top_ips_by_failures")
                exp_top = expected_overall["top_ips_by_failures"]
                top_ok = isinstance(actual_top, list) and len(actual_top) == len(exp_top)
                if top_ok:
                    for a, e in zip(actual_top, exp_top):
                        if not isinstance(a, dict) or a.get("ip") != e.get("ip") or a.get("count") != e.get("count"):
                            top_ok = False
                            break
                conds.append(top_ok)
                # per_hour_failure_mean and max
                mean_ok = isinstance(actual_json.get("per_hour_failure_mean"), (int, float)) and _float_close(
                    float(actual_json.get("per_hour_failure_mean")), float(expected_overall["per_hour_failure_mean"])
                )
                max_ok = actual_json.get("per_hour_failure_max") == expected_overall["per_hour_failure_max"]
                conds.append(mean_ok)
                conds.append(max_ok)
                if all(conds):
                    scores["overall_stats_json_valid"] = 1.0
            except Exception:
                pass

    # Validate reports/run.log
    run_log_path = workspace / "reports" / "run.log"
    if run_log_path.is_file():
        content = _read_text_safe(run_log_path) or ""
        # Check contains command with scripts/analyze_log.py
        if "scripts/analyze_log.py" in content:
            scores["run_log_contains_command"] = 1.0
        # Check summary line with expected numbers
        match = None
        for line in content.splitlines():
            m = re.match(r"^\s*Analyzed\s+(\d+)\s+events;\s+(\d+)\s+failures;\s+(\d+)\s+flagged\s+IPs\s*$", line)
            if m:
                match = m
                break
        if match is not None and expected is not None:
            total_events_logged = int(match.group(1))
            failures_logged = int(match.group(2))
            flagged_logged = int(match.group(3))
            _, _, expected_overall, expected_flagged = expected
            if (
                total_events_logged == expected_overall["total_events"]
                and failures_logged == expected_overall["total_login_failures"]
                and flagged_logged == expected_flagged
            ):
                scores["run_log_summary_matches"] = 1.0

    # Validate memo/security_notice.txt
    memo_path = workspace / "memo" / "security_notice.txt"
    if memo_path.is_file():
        scores["memo_exists"] = 1.0
        memo_text = _read_text_safe(memo_path) or ""
        # Word limit under 180 words
        words = re.findall(r"\b\w+\b", memo_text)
        if len(words) <= 180:
            scores["memo_word_limit"] = 1.0
        # Contains required actions:
        text_lower = memo_text.lower()
        has_2fa = ("2fa" in text_lower) or ("two-factor" in text_lower) or ("two factor" in text_lower)
        has_passphrase = ("passphrase" in text_lower)
        has_report = ("report" in text_lower) and (("email" in text_lower) or ("login" in text_lower))
        has_refresher = ("refresher" in text_lower) and ("week" in text_lower)
        if has_2fa and has_passphrase and has_report and has_refresher:
            scores["memo_contains_required_actions"] = 1.0
        # Tone checks: friendly/supportive, not alarmist/blaming
        # Heuristics:
        # - No all-caps words length >=4
        # - Exclamation marks <= 1
        # - No negative words
        # - At least one supportive word
        no_all_caps = re.search(r"\b[A-Z]{4,}\b", memo_text) is None
        few_exclaims = memo_text.count("!") <= 1
        no_negative = not re.search(r"\b(blame|fault|panic|alarm|asap|fire drill|urgent|emergency)\b", text_lower)
        has_supportive = re.search(r"\b(thank|appreciate|support|team|together|care|welcom|learn)\w*\b", text_lower) is not None
        if no_all_caps and few_exclaims and no_negative and has_supportive:
            scores["memo_tone_supportive_non_alarmist"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()