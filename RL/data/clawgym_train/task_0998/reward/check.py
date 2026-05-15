import json
import os
import sys
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from collections import defaultdict, Counter

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_jsonl(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                items.append(obj)
            except Exception:
                # skip malformed lines
                continue
    return items

def parse_iso8601(ts):
    if ts is None:
        return None
    s = str(ts).strip()
    # Normalize Zulu time
    if s.endswith("Z"):
        s_norm = s[:-1] + "+00:00"
    else:
        s_norm = s
    dt = None
    try:
        dt = datetime.fromisoformat(s_norm)
    except Exception:
        # Try common formats
        fmts = [
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in fmts:
            try:
                dt = datetime.strptime(s, fmt)
                break
            except Exception:
                continue
    if dt is None:
        # Fallback: try to extract date prefix
        if len(s) >= 10:
            try:
                dt = datetime.fromisoformat(s[:10])
            except Exception:
                return None
    return dt

def date_str_from_ts(ts):
    dt = parse_iso8601(ts)
    if dt is None:
        # Fallback to first 10 chars if look like YYYY-MM-DD
        if isinstance(ts, str) and len(ts) >= 10:
            return ts[:10]
        return None
    return dt.date().isoformat()

def month_str_from_ts(ts):
    dt = parse_iso8601(ts)
    if dt is None:
        if isinstance(ts, str) and len(ts) >= 7:
            return ts[:7]
        return None
    return f"{dt.year:04d}-{dt.month:02d}"

def money_add(d1, d2):
    return d1 + d2

def money_quantize_str(d):
    return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def round_float(val, ndigits=4):
    # Use Decimal for precise rounding then cast to float
    try:
        d = Decimal(val)
    except Exception:
        d = Decimal(str(val))
    q = d.quantize(Decimal("1." + "0"*ndigits), rounding=ROUND_HALF_UP)
    return float(q)

def build_expected(workspace_root):
    input_dir = os.path.join(workspace_root, "input")

    # Read inputs
    agents_path = os.path.join(input_dir, "agents.json")
    sessions_path = os.path.join(input_dir, "sessions.json")
    costs_path = os.path.join(input_dir, "costs.jsonl")
    messages_path = os.path.join(input_dir, "messages.jsonl")
    cron_path = os.path.join(input_dir, "cron.json")
    memory_path = os.path.join(input_dir, "memory_files.json")
    logs_path = os.path.join(input_dir, "logs.jsonl")

    agents_data = {}
    if os.path.isfile(agents_path):
        raw = read_json(agents_path)
        # Support dict keyed by id or list with id field
        if isinstance(raw, dict):
            # assume keyed by id
            agents_data = raw
        elif isinstance(raw, list):
            for it in raw:
                if isinstance(it, dict) and "id" in it:
                    agents_data[it["id"]] = it
        else:
            agents_data = {}
    else:
        agents_data = {}

    sessions_data = []
    if os.path.isfile(sessions_path):
        tmp = read_json(sessions_path)
        if isinstance(tmp, list):
            sessions_data = tmp
        elif isinstance(tmp, dict) and "sessions" in tmp and isinstance(tmp["sessions"], list):
            sessions_data = tmp["sessions"]

    costs_data = read_jsonl(costs_path) if os.path.isfile(costs_path) else []
    messages_data = read_jsonl(messages_path) if os.path.isfile(messages_path) else []
    cron_data = read_json(cron_path) if os.path.isfile(cron_path) else []
    memory_data = read_json(memory_path) if os.path.isfile(memory_path) else []
    logs_data = read_jsonl(logs_path) if os.path.isfile(logs_path) else []

    # 1) agents aggregation
    # sessions_count per agent from sessions.json
    sessions_count = Counter()
    for s in sessions_data:
        ag = s.get("agent")
        if ag:
            sessions_count[ag] += 1

    agents_expected = {}
    for agent_id, info in agents_data.items():
        model = info.get("model")
        status = info.get("status")
        context_window = info.get("context_window") or info.get("context_window_tokens") or info.get("context_limit")
        context_used = info.get("context_used_tokens") or info.get("used_tokens") or info.get("context_used")
        try:
            cw = Decimal(str(context_window))
            cu = Decimal(str(context_used))
            ratio = (cu / cw) if cw != 0 else Decimal("0")
        except Exception:
            ratio = Decimal("0")
        ratio_float = float(ratio.quantize(Decimal("1.0000"), rounding=ROUND_HALF_UP))
        # Normalize 4-decimal rounding
        ratio_float = round_float(ratio, 4)
        agents_expected[agent_id] = {
            "model": model if isinstance(model, str) else ("" if model is None else str(model)),
            "status": status if isinstance(status, str) else ("" if status is None else str(status)),
            "sessions_count": int(sessions_count.get(agent_id, 0)),
            "context_used_ratio": ratio_float,
        }

    # 2) costs aggregation
    daily = defaultdict(lambda: Decimal("0"))
    monthly = defaultdict(lambda: Decimal("0"))
    by_model = defaultdict(lambda: Decimal("0"))

    for rec in costs_data:
        # cost_usd could be str or number
        cost_usd = rec.get("cost_usd")
        if cost_usd is None:
            continue
        try:
            cost_val = Decimal(str(cost_usd))
        except Exception:
            continue
        ts = rec.get("ts") or rec.get("timestamp")
        dstr = date_str_from_ts(ts)
        mstr = month_str_from_ts(ts)
        model = rec.get("model")
        if dstr:
            daily[dstr] = money_add(daily[dstr], cost_val)
        if mstr:
            monthly[mstr] = money_add(monthly[mstr], cost_val)
        if model:
            by_model[model] = money_add(by_model[model], cost_val)

    costs_expected = {
        "daily": {k: money_quantize_str(v) for k, v in sorted(daily.items())},
        "monthly": {k: money_quantize_str(v) for k, v in sorted(monthly.items())},
        "by_model": {k: money_quantize_str(v) for k, v in sorted(by_model.items())},
    }

    # 3) activity
    messages_per_day = defaultdict(int)
    tokens_per_day = defaultdict(int)
    for m in messages_data:
        ts = m.get("ts") or m.get("timestamp")
        dstr = date_str_from_ts(ts)
        if not dstr:
            continue
        messages_per_day[dstr] += 1
        tokens = m.get("tokens")
        try:
            tokens_int = int(tokens)
        except Exception:
            tokens_int = 0
        tokens_per_day[dstr] += tokens_int

    token_trend = [{"date": date, "tokens": tokens_per_day[date]} for date in sorted(tokens_per_day.keys())]

    activity_expected = {
        "messages_per_day": {k: messages_per_day[k] for k in sorted(messages_per_day.keys())},
        "token_trend": token_trend,
    }

    # 4) cron
    cron_expected_list = []
    if isinstance(cron_data, dict) and "jobs" in cron_data and isinstance(cron_data["jobs"], list):
        jobs = cron_data["jobs"]
    elif isinstance(cron_data, list):
        jobs = cron_data
    else:
        jobs = []

    for job in jobs:
        name = job.get("name")
        schedule = job.get("schedule")
        runs = job.get("last_runs") or job.get("runs") or []
        # Normalize runs to list
        if not isinstance(runs, list):
            runs = []
        # Find latest
        latest_dt = None
        latest_ts = None
        runs_per_day = defaultdict(int)
        for r in runs:
            dstr = date_str_from_ts(r)
            if dstr:
                runs_per_day[dstr] += 1
            dt = parse_iso8601(r)
            if dt is not None:
                if (latest_dt is None) or (dt > latest_dt):
                    latest_dt = dt
                    latest_ts = r
        cron_expected_list.append({
            "name": name if isinstance(name, str) else ("" if name is None else str(name)),
            "schedule": schedule if isinstance(schedule, str) else ("" if schedule is None else str(schedule)),
            "last_run": latest_ts if latest_ts is not None else "",
            "runs_per_day": {k: runs_per_day[k] for k in sorted(runs_per_day.keys())}
        })

    # 5) memory
    per_agent_file_count = Counter()
    per_agent_total_bytes = defaultdict(int)
    if isinstance(memory_data, dict) and "files" in memory_data and isinstance(memory_data["files"], list):
        mem_files = memory_data["files"]
    elif isinstance(memory_data, list):
        mem_files = memory_data
    else:
        mem_files = []

    for f in mem_files:
        ag = f.get("agent")
        if not ag:
            continue
        per_agent_file_count[ag] += 1
        size = f.get("size_bytes") or f.get("bytes") or 0
        try:
            size_int = int(size)
        except Exception:
            size_int = 0
        per_agent_total_bytes[ag] += size_int

    memory_expected = {
        "per_agent_file_count": dict(per_agent_file_count),
        "per_agent_total_bytes": dict(per_agent_total_bytes),
    }

    # 6) sessions.top_sessions
    sortable_sessions = []
    for s in sessions_data:
        sid = s.get("id")
        ag = s.get("agent")
        mc = s.get("messages_count") if s.get("messages_count") is not None else s.get("message_count")
        try:
            mc_int = int(mc)
        except Exception:
            mc_int = 0
        if sid is None or ag is None:
            continue
        sortable_sessions.append({"id": str(sid), "agent": ag, "messages_count": mc_int})
    # Sort by messages_count desc, tie-break by id asc
    sortable_sessions.sort(key=lambda x: (-x["messages_count"], x["id"]))
    top_sessions = sortable_sessions[:2]
    sessions_expected = {"top_sessions": top_sessions}

    # 7) logs.last_entries
    logs_list = []
    for rec in logs_data:
        ts = rec.get("ts") or rec.get("timestamp")
        ag = rec.get("agent")
        level = rec.get("level")
        message = rec.get("message")
        dt = parse_iso8601(ts)
        if ts is None or dt is None:
            continue
        logs_list.append({
            "ts": ts,
            "agent": ag if isinstance(ag, str) or ag is None else str(ag),
            "level": level if isinstance(level, str) or level is None else str(level),
            "message": message if isinstance(message, str) or message is None else str(message),
            "_dt": dt
        })
    logs_list.sort(key=lambda x: x["_dt"], reverse=True)
    last_entries = [{"ts": r["ts"], "agent": r["agent"], "level": r["level"], "message": r["message"]} for r in logs_list[:5]]
    logs_expected = {"last_entries": last_entries}

    expected = {
        "agents": agents_expected,
        "costs": costs_expected,
        "activity": activity_expected,
        "cron": cron_expected_list,
        "memory": memory_expected,
        "sessions": sessions_expected,
        "logs": logs_expected
    }
    return expected

def keys_exact(d, expected_keys):
    return set(d.keys()) == set(expected_keys)

def check_no_extra_fields_agents(obj):
    # Each agent value must only have: model, status, sessions_count, context_used_ratio
    for aid, v in obj.items():
        if not keys_exact(v, ["model", "status", "sessions_count", "context_used_ratio"]):
            return False
        if not isinstance(v.get("model"), str):
            return False
        if not isinstance(v.get("status"), str):
            return False
        if not isinstance(v.get("sessions_count"), int):
            return False
        # context_used_ratio numeric
        if not isinstance(v.get("context_used_ratio"), (int, float)):
            return False
    return True

def check_costs_structure(obj):
    if not keys_exact(obj, ["daily", "monthly", "by_model"]):
        return False
    # ensure all values are strings with two decimals
    for k in ["daily", "monthly", "by_model"]:
        if not isinstance(obj.get(k), dict):
            return False
        for _, val in obj[k].items():
            if not isinstance(val, str):
                return False
            # must match two decimals
            try:
                d = Decimal(val)
            except Exception:
                return False
            # ensure exactly two decimal places in string representation
            if "." not in val:
                return False
            frac = val.split(".")[1]
            if len(frac) != 2:
                return False
    return True

def check_activity_structure(obj):
    if not keys_exact(obj, ["messages_per_day", "token_trend"]):
        return False
    mpd = obj.get("messages_per_day")
    if not isinstance(mpd, dict):
        return False
    for _, v in mpd.items():
        if not isinstance(v, int):
            return False
    trend = obj.get("token_trend")
    if not isinstance(trend, list):
        return False
    last_date = None
    for item in trend:
        if not keys_exact(item, ["date", "tokens"]):
            return False
        if not isinstance(item["date"], str):
            return False
        if not isinstance(item["tokens"], int):
            return False
        if last_date is not None and item["date"] < last_date:
            return False
        last_date = item["date"]
    return True

def list_to_map_by_name(cron_list):
    m = {}
    for job in cron_list:
        name = job.get("name")
        if isinstance(name, str):
            m[name] = job
    return m

def check_cron_structure(cron_list):
    if not isinstance(cron_list, list):
        return False
    for job in cron_list:
        if not keys_exact(job, ["name", "schedule", "last_run", "runs_per_day"]):
            return False
        if not isinstance(job.get("name"), str):
            return False
        if not isinstance(job.get("schedule"), str):
            return False
        if not isinstance(job.get("last_run"), str):
            return False
        if not isinstance(job.get("runs_per_day"), dict):
            return False
        for _, v in job["runs_per_day"].items():
            if not isinstance(v, int):
                return False
    return True

def check_memory_structure(obj):
    if not keys_exact(obj, ["per_agent_file_count", "per_agent_total_bytes"]):
        return False
    fc = obj.get("per_agent_file_count")
    tb = obj.get("per_agent_total_bytes")
    if not isinstance(fc, dict) or not isinstance(tb, dict):
        return False
    for _, v in fc.items():
        if not isinstance(v, int):
            return False
    for _, v in tb.items():
        if not isinstance(v, int):
            return False
    return True

def check_sessions_structure(obj):
    if not keys_exact(obj, ["top_sessions"]):
        return False
    ts = obj.get("top_sessions")
    if not isinstance(ts, list):
        return False
    if len(ts) != 2:
        return False
    for item in ts:
        if not keys_exact(item, ["id", "agent", "messages_count"]):
            return False
        if not isinstance(item.get("id"), str):
            return False
        if not isinstance(item.get("agent"), str):
            return False
        if not isinstance(item.get("messages_count"), int):
            return False
    # check ordering by messages_count desc then id asc
    a, b = ts[0], ts[1]
    if (a["messages_count"], a["id"]) < (b["messages_count"], b["id"]):
        return False
    return True

def check_logs_structure(obj):
    if not keys_exact(obj, ["last_entries"]):
        return False
    le = obj.get("last_entries")
    if not isinstance(le, list):
        return False
    if len(le) != 5:
        return False
    prev_ts = None
    prev_dt = None
    for item in le:
        if not keys_exact(item, ["ts", "agent", "level", "message"]):
            return False
        if not isinstance(item.get("ts"), str):
            return False
        if not isinstance(item.get("agent"), str):
            return False
        if not isinstance(item.get("level"), str):
            return False
        if not isinstance(item.get("message"), str):
            return False
        dt = parse_iso8601(item["ts"])
        if dt is None:
            return False
        if prev_dt is not None and dt > prev_dt:
            # Must be sorted descending by ts
            return False
        prev_dt = dt
    return True

def deep_equal(a, b):
    return a == b

def compute_and_check(actual, expected):
    checks = {}

    # top-level keys exact
    expected_top_keys = ["agents", "costs", "activity", "cron", "memory", "sessions", "logs"]
    checks["top_keys_exact"] = keys_exact(actual, expected_top_keys)

    # agents
    a_agents = actual.get("agents")
    checks["agents_structure"] = isinstance(a_agents, dict) and check_no_extra_fields_agents(a_agents)
    checks["agents_content_match"] = checks["agents_structure"] and deep_equal(a_agents, expected["agents"])

    # costs
    a_costs = actual.get("costs")
    checks["costs_structure"] = isinstance(a_costs, dict) and check_costs_structure(a_costs)
    checks["costs_content_match"] = checks["costs_structure"] and deep_equal(a_costs, expected["costs"])

    # activity
    a_activity = actual.get("activity")
    checks["activity_structure"] = isinstance(a_activity, dict) and check_activity_structure(a_activity)
    checks["activity_content_match"] = checks["activity_structure"] and deep_equal(a_activity, expected["activity"])

    # cron
    a_cron = actual.get("cron")
    checks["cron_structure"] = check_cron_structure(a_cron) if isinstance(a_cron, list) else False
    if checks["cron_structure"]:
        # Compare as mapping by name
        exp_map = list_to_map_by_name(expected["cron"])
        act_map = list_to_map_by_name(a_cron)
        checks["cron_names_match"] = set(exp_map.keys()) == set(act_map.keys())
        cron_match = True
        if checks["cron_names_match"]:
            for name in exp_map.keys():
                cron_match = cron_match and (act_map[name] == exp_map[name])
        else:
            cron_match = False
        checks["cron_content_match"] = checks["cron_names_match"] and cron_match
    else:
        checks["cron_names_match"] = False
        checks["cron_content_match"] = False

    # memory
    a_memory = actual.get("memory")
    checks["memory_structure"] = isinstance(a_memory, dict) and check_memory_structure(a_memory)
    checks["memory_content_match"] = checks["memory_structure"] and deep_equal(a_memory, expected["memory"])

    # sessions
    a_sessions = actual.get("sessions")
    checks["sessions_structure"] = isinstance(a_sessions, dict) and check_sessions_structure(a_sessions)
    checks["sessions_content_match"] = checks["sessions_structure"] and deep_equal(a_sessions, expected["sessions"])

    # logs
    a_logs = actual.get("logs")
    checks["logs_structure"] = isinstance(a_logs, dict) and check_logs_structure(a_logs)
    checks["logs_content_match"] = checks["logs_structure"] and deep_equal(a_logs, expected["logs"])

    # Aggregate section checks: ensure content matches exactly
    section_checks = [
        checks["top_keys_exact"],
        checks["agents_structure"], checks["agents_content_match"],
        checks["costs_structure"], checks["costs_content_match"],
        checks["activity_structure"], checks["activity_content_match"],
        checks["cron_structure"], checks["cron_names_match"], checks["cron_content_match"],
        checks["memory_structure"], checks["memory_content_match"],
        checks["sessions_structure"], checks["sessions_content_match"],
        checks["logs_structure"], checks["logs_content_match"],
    ]
    all_sections_ok = all(section_checks)
    return checks, all_sections_ok

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    result_path = os.path.join(output_dir, "dashboard_snapshot.json")

    checks = {
        "output_exists": False,
        "valid_json": False,
    }

    # Compute expected from input
    try:
        expected = build_expected(workspace_root)
    except Exception:
        expected = None

    if os.path.isfile(result_path):
        checks["output_exists"] = True
        try:
            with open(result_path, "r", encoding="utf-8") as f:
                actual = json.load(f)
            checks["valid_json"] = isinstance(actual, dict)
        except Exception:
            actual = None
            checks["valid_json"] = False
    else:
        actual = None

    # Default all section checks to False
    section_keys = [
        "top_keys_exact",
        "agents_structure", "agents_content_match",
        "costs_structure", "costs_content_match",
        "activity_structure", "activity_content_match",
        "cron_structure", "cron_names_match", "cron_content_match",
        "memory_structure", "memory_content_match",
        "sessions_structure", "sessions_content_match",
        "logs_structure", "logs_content_match",
    ]
    for k in section_keys:
        checks[k] = False

    all_sections_ok = False
    if checks["output_exists"] and checks["valid_json"] and expected is not None and actual is not None:
        try:
            section_checks, all_sections_ok = compute_and_check(actual, expected)
            checks.update(section_checks)
        except Exception:
            all_sections_ok = False

    # Strict scoring: full credit only if all sections match and structure is correct
    if not checks["output_exists"] or not checks["valid_json"]:
        reward = 0.0
    else:
        reward = 1.0 if all_sections_ok else 0.0

    # Print single JSON object
    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()