import json
import os
import sys
import re
import csv
from collections import Counter

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def safe_read_json(path):
    try:
        return True, read_json(path)
    except Exception:
        return False, None

def read_jsonl(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            items.append(json.loads(s))
    return items

def read_jsonl_raw_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f.readlines()]

def read_messages_jsonl(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            obj = json.loads(s)
            items.append(obj)
    return items

def read_times_csv(path):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # normalize keys to strip spaces
            rid = row.get("id") if "id" in row else row.get(" id")
            at = row.get("at") if "at" in row else row.get(" at")
            if rid is None and "id" in row:
                rid = row["id"]
            if at is None and "at" in row:
                at = row["at"]
            if rid is None or at is None:
                # try generic approach
                rid = row.get(list(row.keys())[0])
                at = row.get(list(row.keys())[1]) if len(row.keys()) > 1 else None
            if rid is None or at is None:
                continue
            out.append({"id": str(rid).strip(), "at": str(at).strip()})
    return out

def parse_prefix_and_body(text):
    # Leading prefix: must start with '@' at beginning of string (no leading whitespace)
    # Body is the remainder after the prefix token, trimmed
    if text is None:
        return None, ""
    s = str(text)
    # Do not strip leading whitespace per "leading prefix" semantics; it must be at position 0
    m = re.match(r'^@([A-Za-z]+)\b', s)
    if not m:
        return None, s.strip()
    prefix_token = "@" + m.group(1)
    rest = s[m.end():]
    body = rest.strip()
    return prefix_token, body

def compute_expected_routes(config, messages):
    prefix_map = config.get("prefixMap", {}) if isinstance(config, dict) else {}
    alias_map = config.get("aliasMap", {}) if isinstance(config, dict) else {}
    expected = []
    for msg in messages:
        mid = str(msg.get("id"))
        text = msg.get("text", "")
        prefix, body = parse_prefix_and_body(text)
        status = None
        model = None
        fallback = None
        resolved = None

        if prefix is None:
            # no prefix
            status = "no_prefix"
            resolved = None
            model = None
            fallback = None
        else:
            # resolve alias if present
            canonical = alias_map.get(prefix, prefix)
            # supported if in prefixMap
            if canonical in prefix_map:
                resolved = canonical
                model = prefix_map[canonical].get("model")
                fallback = prefix_map[canonical].get("fallbackModel", None)
                if body == "":
                    status = "switch_only"
                else:
                    status = "ok"
            else:
                # unsupported prefix
                status = "invalid_prefix"
                resolved = None
                model = None
                fallback = None

        entry = {
            "id": mid,
            "prefix": prefix if prefix is not None else None,
            "resolvedPrefix": resolved if resolved is not None else None,
            "body": body if body is not None else "",
            "status": status,
            "model": model if model is not None else None,
            "fallbackModel": fallback if fallback is not None else None,
        }
        expected.append(entry)
    return expected

def parse_time_hm(hhmm):
    # expects "HH:MM"
    parts = hhmm.split(":")
    if len(parts) != 2:
        return None
    h = int(parts[0])
    m = int(parts[1])
    return h * 60 + m

def weekday_to_name_idx(dt):
    # Monday=0 ... Sunday=6
    idx = dt.weekday()
    names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    return names[idx], idx

def parse_iso_datetime(s):
    # Support formats like 2026-03-02T10:00:00+01:00 or 2026-03-02T10:00+01:00
    # Use fromisoformat (Python 3.11 handles these)
    from datetime import datetime
    try:
        return datetime.fromisoformat(s)
    except Exception:
        # Try to append seconds if missing
        try:
            # Insert :00 before timezone if missing seconds
            if "+" in s:
                base, tz = s.split("+", 1)
                if len(base.split(":")) == 2:
                    base = base + ":00"
                return datetime.fromisoformat(base + "+" + tz)
            if "Z" in s and s.endswith("Z"):
                base = s[:-1]
                if len(base.split(":")) == 2:
                    base = base + ":00"
                return datetime.fromisoformat(base + "+00:00")
        except Exception:
            pass
        raise

def time_in_rule(dt, rule):
    # dt: aware or naive; we treat given 'at' as already in schedule timezone – no conversion
    # rule: {days, start, end, enabled, priority, model}
    day_name, _ = weekday_to_name_idx(dt)
    days = [d.lower() for d in (rule.get("days") or [])]
    if day_name not in days:
        return False
    start = parse_time_hm(rule.get("start", "00:00"))
    end = parse_time_hm(rule.get("end", "00:00"))
    if start is None or end is None:
        return False
    minutes = dt.hour * 60 + dt.minute
    if start <= end:
        # normal window: start inclusive, end exclusive
        return start <= minutes < end
    else:
        # overnight: match if time >= start OR time < end
        return (minutes >= start) or (minutes < end)

def compute_expected_schedule(schedule, times_rows):
    rules = schedule.get("rules", []) if isinstance(schedule, dict) else []
    # consider only enabled=true
    enabled_rules = [r for r in rules if r.get("enabled", False)]
    out = []
    for row in times_rows:
        rid = row["id"]
        at_str = row["at"]
        dt = parse_iso_datetime(at_str)
        matches = []
        for r in enabled_rules:
            try:
                if time_in_rule(dt, r):
                    prio = r.get("priority", 0)
                    matches.append((prio, r))
            except Exception:
                continue
        if matches:
            # pick highest priority; if tie, first in original order
            max_prio = max(p for p, _ in matches)
            # find first rule with max_prio in enabled_rules order to ensure determinism
            chosen = None
            for r in enabled_rules:
                if r.get("priority", 0) == max_prio and time_in_rule(dt, r):
                    chosen = r
                    break
            out.append({
                "id": rid,
                "at": at_str,
                "ruleId": chosen.get("id"),
                "model": chosen.get("model"),
            })
        else:
            out.append({
                "id": rid,
                "at": at_str,
                "ruleId": None,
                "model": None,
            })
    return out

def dict_subset_equal(candidate, expected, keys):
    for k in keys:
        if candidate.get(k) != expected.get(k):
            return False
    return True

def compare_routes(candidate_routes, expected_routes):
    # candidate_routes: list of dicts
    # expected_routes: list of dicts
    # Compare by id; allow extra keys in candidate but required ones must match expected
    if not isinstance(candidate_routes, list):
        return False, "routes_not_list"
    if len(candidate_routes) != len(expected_routes):
        return False, "routes_length_mismatch"
    exp_by_id = {e["id"]: e for e in expected_routes}
    cand_by_id = {c.get("id"): c for c in candidate_routes}
    if set(exp_by_id.keys()) != set(cand_by_id.keys()):
        return False, "routes_id_set_mismatch"
    required_keys = ["id", "prefix", "resolvedPrefix", "body", "status", "model", "fallbackModel"]
    for eid, exp in exp_by_id.items():
        c = cand_by_id.get(eid)
        if c is None:
            return False, "missing_id"
        # ensure types: prefix/resolvedPrefix may be None or string
        # Ensure required keys exist
        for k in required_keys:
            if k not in c:
                return False, f"missing_key_{k}"
        # values must match expected exactly for those keys
        for k in required_keys:
            if c.get(k) != exp.get(k):
                return False, f"value_mismatch_{k}"
    return True, "ok"

def compare_schedule(candidate_res, expected_res):
    if not isinstance(candidate_res, list):
        return False, "resolutions_not_list"
    if len(candidate_res) != len(expected_res):
        return False, "resolutions_length_mismatch"
    exp_by_id = {e["id"]: e for e in expected_res}
    cand_by_id = {c.get("id"): c for c in candidate_res}
    if set(exp_by_id.keys()) != set(cand_by_id.keys()):
        return False, "resolutions_id_set_mismatch"
    required_keys = ["id", "at", "ruleId", "model"]
    for eid, exp in exp_by_id.items():
        c = cand_by_id.get(eid)
        if c is None:
            return False, "resolution_missing_id"
        for k in required_keys:
            if k not in c:
                return False, f"resolution_missing_key_{k}"
        for k in required_keys:
            if c.get(k) != exp.get(k):
                return False, f"resolution_value_mismatch_{k}"
    return True, "ok"

def canonicalize_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))

def compute_expected_audit(expected_routes):
    events = []
    for r in expected_routes:
        status = r["status"]
        if status == "ok":
            events.append({
                "type": "route.success",
                "prefix": r["prefix"],
                "resolvedPrefix": r["resolvedPrefix"],
                "targetModel": r["model"],
            })
        elif status == "switch_only":
            events.append({
                "type": "route.switch_only",
                "prefix": r["prefix"],
                "resolvedPrefix": r["resolvedPrefix"],
                "targetModel": r["model"],
            })
        elif status == "no_prefix":
            events.append({
                "type": "route.skip",
                "reason": "no_prefix",
            })
        elif status == "invalid_prefix":
            events.append({
                "type": "route.failure",
                "prefix": r["prefix"],
                "code": "INVALID_PREFIX",
                "reason": f"Unsupported prefix: {r['prefix']}",
            })
        else:
            # Unknown status: treat as failure (should not happen)
            events.append({
                "type": "route.failure",
                "prefix": r["prefix"],
                "code": "UNKNOWN_STATUS",
                "reason": f"Unexpected status: {status}",
            })
    return events

def compare_audit_log(audit_lines, expected_events):
    # Ignore empty lines but count must match exactly number of messages (non-empty lines)
    non_empty_lines = [ln for ln in audit_lines if ln.strip() != ""]
    if len(non_empty_lines) != len(expected_events):
        return False, "audit_line_count_mismatch"
    # Parse candidate JSON objects
    cand_objs = []
    try:
        for ln in non_empty_lines:
            cand_objs.append(json.loads(ln))
    except Exception:
        return False, "audit_json_parse_error"
    # No extra fields allowed: compare exact objects as sets/multisets
    exp_strs = [canonicalize_json(e) for e in expected_events]
    cand_strs = [canonicalize_json(c) for c in cand_objs]
    exp_counter = Counter(exp_strs)
    cand_counter = Counter(cand_strs)
    if exp_counter != cand_counter:
        return False, "audit_content_mismatch"
    return True, "ok"

def compute_expected_summary(expected_routes, expected_resolutions, model_names):
    # model_names is a set/list of models to count in by_model (from config)
    by_status = {"ok": 0, "switch_only": 0, "no_prefix": 0, "invalid_prefix": 0}
    by_model = {m: 0 for m in model_names}
    for r in expected_routes:
        st = r["status"]
        if st in by_status:
            by_status[st] += 1
        if st in ("ok", "switch_only") and r["model"]:
            if r["model"] in by_model:
                by_model[r["model"]] += 1
            else:
                # include any unexpected model keys too, to allow counting
                by_model[r["model"]] = by_model.get(r["model"], 0) + 1
    with_rule = sum(1 for res in expected_resolutions if res.get("ruleId") is not None)
    no_rule = sum(1 for res in expected_resolutions if res.get("ruleId") is None)
    summary = {
        "total_messages": len(expected_routes),
        "by_status": by_status,
        "by_model": by_model,
        "schedule": {"with_rule": with_rule, "no_rule": no_rule},
    }
    return summary

def compare_summary(candidate_summary, expected_summary):
    if not isinstance(candidate_summary, dict):
        return False, "summary_not_object"
    # Required top-level keys
    for k in ["total_messages", "by_status", "by_model", "schedule"]:
        if k not in candidate_summary:
            return False, f"summary_missing_key_{k}"
    # Compare values
    if candidate_summary["total_messages"] != expected_summary["total_messages"]:
        return False, "summary_total_messages_mismatch"
    # Statuses
    exp_by_status = expected_summary["by_status"]
    cand_by_status = candidate_summary["by_status"]
    for st in ["ok", "switch_only", "no_prefix", "invalid_prefix"]:
        if st not in cand_by_status:
            return False, f"summary_by_status_missing_{st}"
        if cand_by_status[st] != exp_by_status[st]:
            return False, f"summary_by_status_mismatch_{st}"
    # Models: candidate must have at least the models present in expected and counts match for those
    exp_by_model = expected_summary["by_model"]
    cand_by_model = candidate_summary["by_model"]
    for m, cnt in exp_by_model.items():
        if m not in cand_by_model:
            return False, f"summary_by_model_missing_{m}"
        if cand_by_model[m] != cnt:
            return False, f"summary_by_model_mismatch_{m}"
    # Schedule
    if "with_rule" not in candidate_summary["schedule"] or "no_rule" not in candidate_summary["schedule"]:
        return False, "summary_schedule_keys_missing"
    if candidate_summary["schedule"]["with_rule"] != expected_summary["schedule"]["with_rule"]:
        return False, "summary_schedule_with_rule_mismatch"
    if candidate_summary["schedule"]["no_rule"] != expected_summary["schedule"]["no_rule"]:
        return False, "summary_schedule_no_rule_mismatch"
    return True, "ok"

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    cfg_path = os.path.join(input_dir, "router.config.json")
    sched_path = os.path.join(input_dir, "router.schedule.json")
    msgs_path = os.path.join(input_dir, "messages.jsonl")
    times_path = os.path.join(input_dir, "times.csv")

    routes_path = os.path.join(output_dir, "routes.json")
    schedule_res_path = os.path.join(output_dir, "schedule_resolution.json")
    audit_path = os.path.join(output_dir, "audit_log.jsonl")
    summary_path = os.path.join(output_dir, "summary.json")

    # Initialize checks
    checks = {
        "routes_present": False,
        "routes_valid": False,
        "schedule_present": False,
        "schedule_valid": False,
        "audit_present": False,
        "audit_valid": False,
        "summary_present": False,
        "summary_valid": False,
    }

    # Load inputs to compute expected (no positive reward for this alone)
    try:
        cfg_ok, cfg = safe_read_json(cfg_path)
        sched_ok, sched = safe_read_json(sched_path)
        messages = read_messages_jsonl(msgs_path)
        times_rows = read_times_csv(times_path)
    except Exception:
        cfg_ok, cfg = False, {}
        sched_ok, sched = False, {}
        messages = []
        times_rows = []

    # Compute expected artifacts if inputs were loaded
    expected_routes = []
    expected_resolutions = []
    expected_audit = []
    expected_summary = None
    model_names = set()
    if cfg_ok and sched_ok and messages is not None and times_rows is not None:
        expected_routes = compute_expected_routes(cfg, messages)
        expected_resolutions = compute_expected_schedule(sched, times_rows)
        expected_audit = compute_expected_audit(expected_routes)
        # Collect model names from config for by_model keys
        pm = cfg.get("prefixMap", {}) if isinstance(cfg, dict) else {}
        for p in pm.values():
            if isinstance(p, dict) and "model" in p:
                model_names.add(p["model"])
        expected_summary = compute_expected_summary(expected_routes, expected_resolutions, model_names)

    # Validate routes.json
    if os.path.isfile(routes_path):
        checks["routes_present"] = True
        try:
            cand_routes_doc = read_json(routes_path)
            if isinstance(cand_routes_doc, dict) and "routes" in cand_routes_doc and isinstance(expected_routes, list) and expected_routes:
                ok, _ = compare_routes(cand_routes_doc["routes"], expected_routes)
                if ok:
                    checks["routes_valid"] = True
        except Exception:
            pass

    # Validate schedule_resolution.json
    if os.path.isfile(schedule_res_path):
        checks["schedule_present"] = True
        try:
            cand_sched_doc = read_json(schedule_res_path)
            if isinstance(cand_sched_doc, dict) and "resolutions" in cand_sched_doc and isinstance(expected_resolutions, list) and expected_resolutions != []:
                ok, _ = compare_schedule(cand_sched_doc["resolutions"], expected_resolutions)
                if ok:
                    checks["schedule_valid"] = True
            elif isinstance(cand_sched_doc, dict) and "resolutions" in cand_sched_doc and expected_resolutions == []:
                # If no times provided, expect empty
                ok, _ = compare_schedule(cand_sched_doc["resolutions"], expected_resolutions)
                if ok:
                    checks["schedule_valid"] = True
        except Exception:
            pass

    # Validate audit_log.jsonl
    if os.path.isfile(audit_path):
        checks["audit_present"] = True
        try:
            cand_audit_lines = read_jsonl_raw_lines(audit_path)
            if expected_audit is not None:
                ok, _ = compare_audit_log(cand_audit_lines, expected_audit)
                if ok:
                    checks["audit_valid"] = True
        except Exception:
            pass

    # Validate summary.json
    if os.path.isfile(summary_path):
        checks["summary_present"] = True
        try:
            cand_summary = read_json(summary_path)
            if expected_summary is not None:
                ok, _ = compare_summary(cand_summary, expected_summary)
                if ok:
                    checks["summary_valid"] = True
        except Exception:
            pass

    # Compute reward: equal weight for four main validations (routes, schedule, audit, summary)
    main_checks = [
        checks["routes_valid"],
        checks["schedule_valid"],
        checks["audit_valid"],
        checks["summary_valid"],
    ]
    passed = sum(1 for b in main_checks if b)
    reward = passed / 4.0 if any(main_checks) else 0.0

    result = {"reward": reward}
    # Append checks as booleans
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()