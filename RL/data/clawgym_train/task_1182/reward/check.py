import json
import os
import sys
import csv
from datetime import datetime, timezone, timedelta

def parse_iso8601_utc(ts: str) -> datetime:
    # Normalize common UTC forms to Python's fromisoformat expectations
    if isinstance(ts, str):
        s = ts.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            # If naive, assume UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    # Fallback: try basic parsing without offset
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        # As a last resort, return epoch
        return datetime(1970, 1, 1, tzinfo=timezone.utc)

def to_minified_json(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

def round_to_1(x: float) -> float:
    return float(f"{x:.1f}")

def round_to_2(x: float) -> float:
    return float(f"{x:.2f}")

def is_number(x):
    return isinstance(x, (int, float))

def try_float(s: str):
    try:
        return float(s)
    except Exception:
        return None

def compute_expected(input_dir):
    # Load inputs
    config_path = os.path.join(input_dir, "config.json")
    metrics_path = os.path.join(input_dir, "metrics.json")
    with open(config_path, "r") as f:
        config = json.load(f)
    with open(metrics_path, "r") as f:
        metrics = json.load(f)
    if not isinstance(metrics, list):
        metrics = []

    # Prepare date boundaries
    today_str = config.get("today")
    # Build end of day 23:59:59 UTC
    today_date = datetime.strptime(today_str, "%Y-%m-%d").date()
    end_of_today = datetime(today_date.year, today_date.month, today_date.day, 23, 59, 59, tzinfo=timezone.utc)

    # Parse timestamps and enrich
    parsed = []
    earliest_dt = None
    for e in metrics:
        ts = e.get("timestamp", "")
        dt = parse_iso8601_utc(ts)
        e_dt = dt
        e_date_str = e_dt.date().isoformat()
        parsed.append((e, e_dt, e_date_str))
        if earliest_dt is None or e_dt < earliest_dt:
            earliest_dt = e_dt

    total_all = len(parsed)
    entries_today = [e for (e, e_dt, e_date_str) in parsed if e_date_str == today_str]
    total_today = len(entries_today)

    # Error rate
    errors_today = sum(1 for e in entries_today if e.get("type") == "error")
    error_rate = round_to_1((errors_today / total_today * 100.0) if total_today > 0 else 0.0)

    # Counters sum
    counters_today = {}
    for e in entries_today:
        if e.get("type") == "counter":
            name = e.get("name", "unknown")
            val = e.get("value", None)
            if val is None:
                v = 1.0
            else:
                v = float(val) if is_number(val) else try_float(str(val))
                if v is None:
                    v = 1.0
            counters_today[name] = counters_today.get(name, 0.0) + v

    # Gauges latest by timestamp for today
    gauges_latest_today = {}
    gauges_latest_time = {}
    for (e, e_dt, e_date_str) in parsed:
        if e_date_str != today_str:
            continue
        if e.get("type") == "gauge":
            name = e.get("name", "unknown")
            if (name not in gauges_latest_time) or (e_dt > gauges_latest_time[name]):
                gauges_latest_time[name] = e_dt
                val = e.get("value", 0.0)
                v = float(val) if is_number(val) else (try_float(str(val)) if val is not None else 0.0)
                if v is None:
                    v = 0.0
                gauges_latest_today[name] = v

    # Timers average
    timers_values = {}
    for e in entries_today:
        if e.get("type") == "timer":
            name = e.get("name", "unknown")
            val = e.get("value", 0.0)
            v = float(val) if is_number(val) else (try_float(str(val)) if val is not None else 0.0)
            if v is None:
                v = 0.0
            timers_values.setdefault(name, []).append(v)
    timers_avg_today = {}
    for name, vals in timers_values.items():
        if len(vals) > 0:
            avg = sum(vals) / len(vals)
            timers_avg_today[name] = round_to_2(avg)

    # Top metrics today (by name, across all types)
    name_counts = {}
    for e in entries_today:
        name = e.get("name", "unknown")
        name_counts[name] = name_counts.get(name, 0) + 1
    top_sorted = sorted(name_counts.items(), key=lambda x: (-x[1], x[0]))
    top_metrics_today = [{"name": n, "count": c} for n, c in top_sorted[:5]]

    # Uptime: earliest to end of today
    if earliest_dt is None:
        uptime_str = "0d 0h 0m"
    else:
        delta = end_of_today - earliest_dt
        # Clamp negative to zero
        if delta.total_seconds() < 0:
            total_secs = 0
        else:
            # Floor to minutes
            total_secs = int(delta.total_seconds())
            total_secs = (total_secs // 60) * 60
        days = total_secs // 86400
        rem = total_secs % 86400
        hours = rem // 3600
        minutes = (rem % 3600) // 60
        uptime_str = f"{days}d {hours}h {minutes}m"

    expected = {
        "uptime": uptime_str,
        "total_today": total_today,
        "total_all": total_all,
        "error_rate_today_percent": error_rate,
        "counters_today": counters_today,
        "gauges_latest_today": gauges_latest_today,
        "timers_avg_today": timers_avg_today,
        "top_metrics_today": top_metrics_today,
        # For CSV validation
        "all_entries": metrics,
    }
    return expected

def normalize_value_for_compare(entry_value, csv_value_str):
    # Return normalized tuple for robust equality
    if entry_value is None:
        if csv_value_str == "" or csv_value_str is None:
            return True
        # sometimes "null" could be used, but spec says empty; be strict
        return False
    # If entry_value is numeric
    if is_number(entry_value):
        f = try_float(csv_value_str)
        if f is None:
            return False
        # exact numeric compare with tolerance
        return abs(f - float(entry_value)) <= 1e-9
    # Otherwise compare string
    return str(entry_value) == ("" if csv_value_str is None else csv_value_str)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "summary_exists": False,
        "summary_values_correct": False,
        "csv_exists": False,
        "csv_header_correct": False,
        "csv_count_correct": False,
        "csv_sorted_by_timestamp": False,
        "csv_rows_match_entries": False,
        "dashboard_exists": False,
        "dashboard_has_required_sections": False,
        "dashboard_numbers_match_summary": False,
        "insights_exists": False,
        "insights_has_min_bullets": False,
        "insights_has_recommendation": False,
    }

    # Compute expected from inputs
    try:
        expected = compute_expected(input_dir)
    except Exception:
        expected = None

    # 1) summary.json
    summary_path = os.path.join(output_dir, "summary.json")
    summary_obj = None
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r") as f:
                summary_obj = json.load(f)
            # Validate keys and values if expected available
            if expected is not None and isinstance(summary_obj, dict):
                ok = True
                # Required keys
                req_keys = [
                    "uptime",
                    "total_today",
                    "total_all",
                    "error_rate_today_percent",
                    "counters_today",
                    "gauges_latest_today",
                    "timers_avg_today",
                    "top_metrics_today",
                ]
                if not all(k in summary_obj for k in req_keys):
                    ok = False
                else:
                    if summary_obj["uptime"] != expected["uptime"]:
                        ok = False
                    if int(summary_obj["total_today"]) != int(expected["total_today"]):
                        ok = False
                    if int(summary_obj["total_all"]) != int(expected["total_all"]):
                        ok = False
                    # error rate rounded 1 decimal
                    try:
                        if round_to_1(float(summary_obj["error_rate_today_percent"])) != expected["error_rate_today_percent"]:
                            ok = False
                    except Exception:
                        ok = False
                    # counters
                    exp_c = expected["counters_today"]
                    got_c = summary_obj.get("counters_today", {})
                    if set(exp_c.keys()) != set(got_c.keys()):
                        ok = False
                    else:
                        for k, v in exp_c.items():
                            gv = got_c.get(k)
                            try:
                                if abs(float(gv) - float(v)) > 1e-9:
                                    ok = False
                                    break
                            except Exception:
                                ok = False
                                break
                    # gauges
                    exp_g = expected["gauges_latest_today"]
                    got_g = summary_obj.get("gauges_latest_today", {})
                    if set(exp_g.keys()) != set(got_g.keys()):
                        ok = False
                    else:
                        for k, v in exp_g.items():
                            gv = got_g.get(k)
                            try:
                                if abs(float(gv) - float(v)) > 1e-9:
                                    ok = False
                                    break
                            except Exception:
                                ok = False
                                break
                    # timers
                    exp_t = expected["timers_avg_today"]
                    got_t = summary_obj.get("timers_avg_today", {})
                    if set(exp_t.keys()) != set(got_t.keys()):
                        ok = False
                    else:
                        for k, v in exp_t.items():
                            gv = got_t.get(k)
                            try:
                                if round_to_2(float(gv)) != round_to_2(float(v)):
                                    ok = False
                                    break
                            except Exception:
                                ok = False
                                break
                    # top metrics (up to 5)
                    exp_top = expected["top_metrics_today"]
                    got_top = summary_obj.get("top_metrics_today", [])
                    if not isinstance(got_top, list):
                        ok = False
                    else:
                        # Must match exactly same length and content
                        if len(got_top) != len(exp_top):
                            ok = False
                        else:
                            for i in range(len(exp_top)):
                                gi = got_top[i]
                                ei = exp_top[i]
                                if gi.get("name") != ei.get("name") or int(gi.get("count", -1)) != int(ei.get("count", -2)):
                                    ok = False
                                    break
                checks["summary_values_correct"] = ok
            else:
                checks["summary_values_correct"] = False
        except Exception:
            checks["summary_values_correct"] = False

    # 2) week_export.csv
    csv_path = os.path.join(output_dir, "week_export.csv")
    csv_rows = []
    if os.path.isfile(csv_path):
        checks["csv_exists"] = True
        try:
            with open(csv_path, "r", newline="") as f:
                reader = csv.reader(f)
                all_rows = list(reader)
            if all_rows:
                header = all_rows[0]
                # Expect exact header
                expected_header = ["timestamp", "name", "type", "value", "tags", "message"]
                if header == expected_header:
                    checks["csv_header_correct"] = True
                # Data rows
                data_rows = all_rows[1:]
                csv_rows = data_rows
                # Count check against number of entries
                if expected is not None:
                    exp_entries = expected["all_entries"]
                    if len(data_rows) == len(exp_entries):
                        checks["csv_count_correct"] = True
                    # Sorted by timestamp ascending (lexicographic)
                    if len(data_rows) > 0:
                        ts_list = [row[0] if len(row) > 0 else "" for row in data_rows]
                        if all(ts_list[i] <= ts_list[i+1] for i in range(len(ts_list)-1)):
                            checks["csv_sorted_by_timestamp"] = True
                    # Rows content match (as a multiset, robust to tie order)
                    try:
                        # Build normalized tuples for CSV rows
                        csv_norm = []
                        for row in data_rows:
                            # Pad row to length 6
                            row = (row + [""] * 6)[:6]
                            ts, name, typ, val_s, tags_s, msg_s = row
                            # normalize tags by parsing if not empty
                            tags_ok = None
                            tags_norm = ""
                            if tags_s == "":
                                tags_ok = True
                                tags_norm = ""
                            else:
                                try:
                                    # reject if spaces exist (minified required)
                                    if " " in tags_s or "\t" in tags_s or "\n" in tags_s or "\r" in tags_s:
                                        tags_ok = False
                                    parsed_tags = json.loads(tags_s)
                                    if not isinstance(parsed_tags, dict):
                                        tags_ok = False
                                    else:
                                        tags_ok = True
                                    # For multiset comparison, use parsed dict serialized with sorted keys to stabilize
                                    if tags_ok:
                                        tags_norm = json.dumps(parsed_tags, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
                                except Exception:
                                    tags_ok = False
                            csv_norm.append((ts, name, typ, val_s, tags_ok, tags_norm, msg_s))
                        # Build normalized tuples for expected entries
                        exp_norm = []
                        for e in expected["all_entries"]:
                            ts = e.get("timestamp", "")
                            name = e.get("name", "")
                            typ = e.get("type", "")
                            val = e.get("value", None)
                            tags = e.get("tags", None)
                            msg = e.get("message", "")
                            # tags expected norm
                            if tags is None:
                                tags_ok = True
                                tags_norm = ""
                            else:
                                if isinstance(tags, dict):
                                    tags_ok = True
                                    tags_norm = json.dumps(tags, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
                                else:
                                    # Invalid input tag shape; still normalize
                                    try:
                                        tags_str = json.dumps(tags, separators=(",", ":"), ensure_ascii=False)
                                        # parse back to dict?
                                        parsed = json.loads(tags_str)
                                        if isinstance(parsed, dict):
                                            tags_ok = True
                                            tags_norm = json.dumps(parsed, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
                                        else:
                                            tags_ok = False
                                            tags_norm = ""
                                    except Exception:
                                        tags_ok = False
                                        tags_norm = ""
                            exp_norm.append((ts, name, typ, val, tags_ok, tags_norm, msg))
                        # For multiset compare, convert csv tuples to comparable with value normalized:
                        def to_cmp_rows_csv(norm_rows):
                            out = []
                            for ts, name, typ, val_s, tags_ok, tags_norm, msg_s in norm_rows:
                                out.append((ts, name, typ, ("num", try_float(val_s)) if try_float(val_s) is not None else ("str", val_s if val_s is not None else "")), tags_ok, tags_norm, msg_s if msg_s is not None else "")
                            return out
                        def to_cmp_rows_exp(norm_rows):
                            out = []
                            for ts, name, typ, val, tags_ok, tags_norm, msg in norm_rows:
                                if val is None:
                                    v = ("empty", None)
                                elif is_number(val):
                                    v = ("num", float(val))
                                else:
                                    v = ("str", str(val))
                                out.append((ts, name, typ, v, tags_ok, tags_norm, msg if msg is not None else ""))
                            return out
                        csv_cmp = to_cmp_rows_csv(csv_norm)
                        exp_cmp = to_cmp_rows_exp(exp_norm)
                        # Sort both lists to compare as multisets
                        csv_cmp_sorted = sorted(csv_cmp, key=lambda x: (x[0], x[1], x[2], x[3][0], x[3][1] if x[3][1] is not None else -1e18, x[5], x[6]))
                        exp_cmp_sorted = sorted(exp_cmp, key=lambda x: (x[0], x[1], x[2], x[3][0], x[3][1] if x[3][1] is not None else -1e18, x[5], x[6]))
                        rows_match = True
                        if len(csv_cmp_sorted) != len(exp_cmp_sorted):
                            rows_match = False
                        else:
                            for (cts, cname, ctyp, cval, ctags_ok, ctags_norm, cmsg), (ets, ename, etyp, eval_t, etags_ok, etags_norm, emsg) in zip(csv_cmp_sorted, exp_cmp_sorted):
                                if cts != ets or cname != ename or ctyp != etyp:
                                    rows_match = False
                                    break
                                # value compare
                                if cval[0] != eval_t[0]:
                                    # accept empty in CSV only if entry val is empty
                                    if not (cval[0] == "str" and cval[1] == "" and eval_t[0] == "empty"):
                                        rows_match = False
                                        break
                                else:
                                    if cval[0] == "num":
                                        if abs((cval[1] or 0.0) - (eval_t[1] or 0.0)) > 1e-9:
                                            rows_match = False
                                            break
                                    elif cval[0] == "str":
                                        if (cval[1] or "") != (eval_t[1] or ""):
                                            rows_match = False
                                            break
                                    elif cval[0] == "empty":
                                        # CSV should be empty string for empty
                                        if not (cval[1] is None or cval[1] == 0.0):
                                            pass
                                # tags: both must parse ok and normalized structural equality
                                if not ctags_ok or not etags_ok:
                                    # If entry had no tags, both ok flags should be True and csv should be empty norm
                                    if etags_ok and etags_norm == "" and ctags_norm == "":
                                        pass
                                    else:
                                        rows_match = False
                                        break
                                else:
                                    if ctags_norm != etags_norm:
                                        # compare structurally by parsing both
                                        try:
                                            if json.loads(ctags_norm) != json.loads(etags_norm):
                                                rows_match = False
                                                break
                                        except Exception:
                                            rows_match = False
                                            break
                                # message
                                if (cmsg or "") != (emsg or ""):
                                    rows_match = False
                                    break
                        if rows_match:
                            checks["csv_rows_match_entries"] = True
                    except Exception:
                        checks["csv_rows_match_entries"] = False
        except Exception:
            # leave csv checks as False
            pass

    # 3) dashboard.txt
    dash_path = os.path.join(output_dir, "dashboard.txt")
    dash_text = ""
    if os.path.isfile(dash_path):
        checks["dashboard_exists"] = True
        try:
            with open(dash_path, "r", encoding="utf-8", errors="ignore") as f:
                dash_text = f.read()
            req_labels = [
                "Uptime (est):",
                "Events today:",
                "Events total:",
                "Error rate:",
            ]
            req_sections = [
                "COUNTERS",
                "GAUGES",
                "TIMERS (avg)",
                "TOP METRICS",
                "RECENT ERRORS",
            ]
            has_all = all(label in dash_text for label in req_labels) and all(sec in dash_text for sec in req_sections)
            checks["dashboard_has_required_sections"] = has_all

            # Compare Events today, Events total, Error rate to summary.json
            if summary_obj is not None and expected is not None:
                # Extract values by simple search per line
                etoday_val = None
                etotal_val = None
                erate_val = None
                for line in dash_text.splitlines():
                    ls = line.strip()
                    if ls.startswith("Events today:"):
                        try:
                            etoday_val = int(ls.split("Events today:")[1].strip().split()[0])
                        except Exception:
                            pass
                    elif ls.startswith("Events total:"):
                        try:
                            etotal_val = int(ls.split("Events total:")[1].strip().split()[0])
                        except Exception:
                            pass
                    elif ls.startswith("Error rate:"):
                        try:
                            er = ls.split("Error rate:")[1].strip()
                            if er.endswith("%"):
                                er = er[:-1]
                            erate_val = round_to_1(float(er))
                        except Exception:
                            pass
                ok_nums = True
                try:
                    if etoday_val is None or etotal_val is None or erate_val is None:
                        ok_nums = False
                    else:
                        if int(etoday_val) != int(summary_obj.get("total_today", -1)):
                            ok_nums = False
                        if int(etotal_val) != int(summary_obj.get("total_all", -1)):
                            ok_nums = False
                        s_er = round_to_1(float(summary_obj.get("error_rate_today_percent", -999)))
                        if erate_val != s_er:
                            ok_nums = False
                except Exception:
                    ok_nums = False
                checks["dashboard_numbers_match_summary"] = ok_nums
        except Exception:
            pass

    # 4) insights.md
    ins_path = os.path.join(output_dir, "insights.md")
    if os.path.isfile(ins_path):
        checks["insights_exists"] = True
        try:
            with open(ins_path, "r", encoding="utf-8", errors="ignore") as f:
                ins_text = f.read()
            lines = ins_text.splitlines()
            # Count bullet lines starting with "- " or "* "
            bullets = [ln for ln in lines if ln.strip().startswith("- ") or ln.strip().startswith("* ")]
            if len(bullets) >= 3:
                checks["insights_has_min_bullets"] = True
            # Recommendation paragraph: at least one non-bullet, non-empty line with a period
            non_bullet = [ln for ln in lines if not (ln.strip().startswith("- ") or ln.strip().startswith("* ")) and ln.strip() != ""]
            has_reco = any("." in ln for ln in non_bullet)
            checks["insights_has_recommendation"] = has_reco
        except Exception:
            pass

    # Compute reward: weighted sum of deterministic checks
    weights = {
        "summary_exists": 1.0,
        "summary_values_correct": 4.0,
        "csv_exists": 1.0,
        "csv_header_correct": 1.0,
        "csv_count_correct": 1.0,
        "csv_sorted_by_timestamp": 1.0,
        "csv_rows_match_entries": 3.0,
        "dashboard_exists": 1.0,
        "dashboard_has_required_sections": 1.0,
        "dashboard_numbers_match_summary": 2.0,
        "insights_exists": 1.0,
        "insights_has_min_bullets": 1.0,
        "insights_has_recommendation": 1.0,
    }
    total_weight = sum(weights.values())
    earned = 0.0
    for k, w in weights.items():
        if checks.get(k, False):
            earned += w
    reward = 0.0
    if total_weight > 0:
        reward = earned / total_weight
    # Enforce baseline: if no outputs at all, force 0
    output_present = any(os.path.exists(os.path.join(output_dir, fn)) for fn in ["summary.json", "week_export.csv", "dashboard.txt", "insights.md"])
    if not output_present:
        reward = 0.0

    result = {"reward": max(0.0, min(1.0, reward))}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()