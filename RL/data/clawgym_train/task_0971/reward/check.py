import json
import os
import sys
import csv

def int_or_none(v):
    try:
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int,)):
            return int(v)
        if isinstance(v, float):
            # Only accept floats that are integral
            if abs(v - int(v)) < 1e-9:
                return int(v)
            return None
        if isinstance(v, str):
            v = v.strip().replace(",", "")
            if v == "":
                return None
            return int(float(v))
        return None
    except Exception:
        return None

def metrics_match(d, exp):
    # d: dict containing metrics keys; exp: dict expected ints
    keys = ["input", "output", "cacheRead", "cacheWrite", "totalTokens", "messages"]
    for k in keys:
        dv = int_or_none(d.get(k))
        ev = exp.get(k)
        if dv is None or dv != ev:
            return False
    return True

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, []
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None, []

def find_col_index(header, name):
    try:
        return header.index(name)
    except ValueError:
        return -1

def get_metric_row_values(header, row):
    cols = {}
    for name in ["input", "output", "cacheRead", "cacheWrite", "totalTokens", "messages"]:
        idx = find_col_index(header, name)
        if idx < 0 or idx >= len(row):
            cols[name] = None
        else:
            cols[name] = int_or_none(row[idx])
    return cols

def last_nonempty_line(text):
    for line in reversed(text.splitlines()):
        if line.strip():
            return line
    return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    usage_dir = os.path.join(output_dir, "usage")
    csv_dir = os.path.join(usage_dir, "csv")

    checks = {
        # JSON existence and structure
        "json_exists": False,
        "json_valid": False,
        "json_has_required_keys": False,
        # JSON content checks
        "summary_match": False,
        "by_agent_contains_expected": False,
        "by_model_contains_expected": False,
        "by_day_agent_exact": False,
        "by_session_contains_expected": False,
        "by_day_session_contains_expected": False,
        # CSV existence and exactness
        "summary_csv_match": False,
        "by_day_agent_csv_exact": False,
        "by_agent_csv_exact": False,
        "by_model_csv_exact": False,
        "by_session_csv_exact": False,
        "by_day_session_csv_exact": False,
        # Markdown report checks
        "report_exists": False,
        "report_has_total_tokens": False,
        "report_has_top3_sessions": False,
    }

    expected_summary = {
        "input": 1220,
        "output": 1030,
        "cacheRead": 180,
        "cacheWrite": 30,
        "totalTokens": 2460,
        "messages": 8,
    }

    expected_by_agent = {
        "alpha": {"input": 670, "output": 680, "cacheRead": 150, "cacheWrite": 30, "totalTokens": 1530, "messages": 5},
        "beta":  {"input": 550, "output": 350, "cacheRead": 30,  "cacheWrite": 0,  "totalTokens": 930,  "messages": 3},
    }

    expected_by_model = {
        "openai/gpt-4o": {"input": 400, "output": 400, "cacheRead": 80, "cacheWrite": 0, "totalTokens": 880, "messages": 2},
        "anthropic/claude-3-7": {"input": 200, "output": 300, "cacheRead": 100, "cacheWrite": 20, "totalTokens": 620, "messages": 1},
        "github-copilot/copilot-code": {"input": 400, "output": 100, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 500, "messages": 1},
        "github-copilot/copilot-chat": {"input": 170, "output": 130, "cacheRead": 0, "cacheWrite": 10, "totalTokens": 310, "messages": 2},
        "openai/gpt-4o-mini": {"input": 50, "output": 100, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 150, "messages": 2},
    }

    expected_by_day_agent = {
        "2026-03-14": {
            "alpha": {"input": 420, "output": 280, "cacheRead": 50, "cacheWrite": 10, "totalTokens": 760, "messages": 3}
        },
        "2026-03-15": {
            "alpha": {"input": 250, "output": 400, "cacheRead": 100, "cacheWrite": 20, "totalTokens": 770, "messages": 2},
            "beta":  {"input": 550, "output": 350, "cacheRead": 30,  "cacheWrite": 0,  "totalTokens": 930, "messages": 3},
        },
    }

    expected_sessions = {
        "beta-20260315-X": {
            "transcript": "b1.jsonl",
            "metrics": {"input": 550, "output": 350, "cacheRead": 30, "cacheWrite": 0, "totalTokens": 930, "messages": 3},
        },
        "alpha-20260315-B": {
            "transcript": "s2.jsonl",
            "metrics": {"input": 250, "output": 400, "cacheRead": 100, "cacheWrite": 20, "totalTokens": 770, "messages": 2},
        },
        "alpha-20260314-A": {
            "transcript": "s1.jsonl",
            "metrics": {"input": 420, "output": 280, "cacheRead": 50, "cacheWrite": 10, "totalTokens": 760, "messages": 3},
        },
    }

    # JSON checks
    json_path = os.path.join(usage_dir, "token-usage.json")
    data = None
    if os.path.isfile(json_path):
        checks["json_exists"] = True
        data = load_json(json_path)
        if isinstance(data, dict):
            checks["json_valid"] = True
            required_keys = ["summary", "by_day_agent", "by_agent", "by_model", "by_session", "by_day_session"]
            checks["json_has_required_keys"] = all(k in data for k in required_keys)

            # Summary
            if checks["json_has_required_keys"]:
                if isinstance(data.get("summary"), dict) and metrics_match(data["summary"], expected_summary):
                    checks["summary_match"] = True

                # by_agent: ensure expected agents present with exact metrics
                by_agent = data.get("by_agent")
                if isinstance(by_agent, dict):
                    ok = True
                    for agent, expm in expected_by_agent.items():
                        if agent not in by_agent or not isinstance(by_agent[agent], dict) or not metrics_match(by_agent[agent], expm):
                            ok = False
                            break
                    checks["by_agent_contains_expected"] = ok

                # by_model: ensure all expected model entries present with exact metrics
                by_model = data.get("by_model")
                if isinstance(by_model, dict):
                    ok = True
                    for model_key, expm in expected_by_model.items():
                        if model_key not in by_model or not isinstance(by_model[model_key], dict) or not metrics_match(by_model[model_key], expm):
                            ok = False
                            break
                    checks["by_model_contains_expected"] = ok

                # by_day_agent: must have exactly the two days and exact agent rows for each
                by_day_agent = data.get("by_day_agent")
                if isinstance(by_day_agent, dict):
                    days_set = set(by_day_agent.keys())
                    expected_days_set = set(expected_by_day_agent.keys())
                    if days_set == expected_days_set:
                        exact_ok = True
                        for day, agents in expected_by_day_agent.items():
                            got_agents = by_day_agent.get(day)
                            if not isinstance(got_agents, dict):
                                exact_ok = False
                                break
                            if set(got_agents.keys()) != set(agents.keys()):
                                exact_ok = False
                                break
                            for agent, expm in agents.items():
                                if not isinstance(got_agents.get(agent), dict) or not metrics_match(got_agents[agent], expm):
                                    exact_ok = False
                                    break
                            if not exact_ok:
                                break
                        checks["by_day_agent_exact"] = exact_ok

                # by_session: must include expected sessions with transcript and metrics (may include more)
                by_session = data.get("by_session")
                if isinstance(by_session, dict):
                    ok = True
                    for sess_key, specs in expected_sessions.items():
                        got = by_session.get(sess_key)
                        if not isinstance(got, dict):
                            ok = False
                            break
                        # transcript
                        if str(got.get("transcript", "")) != specs["transcript"]:
                            ok = False
                            break
                        if not metrics_match(got, specs["metrics"]):
                            ok = False
                            break
                    checks["by_session_contains_expected"] = ok

                # by_day_session: must include expected sessions under each day (may include more)
                by_day_session = data.get("by_day_session")
                if isinstance(by_day_session, dict):
                    ok = True
                    # Check required days exist
                    for day in ["2026-03-14", "2026-03-15"]:
                        if day not in by_day_session or not isinstance(by_day_session[day], dict):
                            ok = False
                            break
                    if ok:
                        day_requirements = {
                            "2026-03-14": ["alpha-20260314-A"],
                            "2026-03-15": ["alpha-20260315-B", "beta-20260315-X"],
                        }
                        for day, sess_list in day_requirements.items():
                            day_map = by_day_session[day]
                            for sess_key in sess_list:
                                got = day_map.get(sess_key)
                                specs = expected_sessions[sess_key]
                                if not isinstance(got, dict):
                                    ok = False
                                    break
                                if str(got.get("transcript", "")) != specs["transcript"]:
                                    ok = False
                                    break
                                if not metrics_match(got, specs["metrics"]):
                                    ok = False
                                    break
                            if not ok:
                                break
                    checks["by_day_session_contains_expected"] = ok

    # CSV checks
    summary_csv = os.path.join(csv_dir, "summary.csv")
    if os.path.isfile(summary_csv):
        header, rows = load_csv_rows(summary_csv)
        if header is not None:
            # Must have a single data row whose numeric fields match summary totals
            if len(rows) == 1:
                metric_vals = get_metric_row_values(header, rows[0])
                if all(metric_vals.get(k) == v for k, v in expected_summary.items()):
                    checks["summary_csv_match"] = True

    by_day_agent_csv = os.path.join(csv_dir, "by_day_agent.csv")
    if os.path.isfile(by_day_agent_csv):
        header, rows = load_csv_rows(by_day_agent_csv)
        if header is not None:
            # Expect exactly 3 rows: (2026-03-14, alpha), (2026-03-15, alpha), (2026-03-15, beta)
            # Headers: day, agent, metrics...
            idx_day = find_col_index(header, "day")
            idx_agent = find_col_index(header, "agent")
            if idx_day >= 0 and idx_agent >= 0 and len(rows) == 3:
                mapping = {}
                ok = True
                for r in rows:
                    day = r[idx_day] if idx_day < len(r) else ""
                    agent = r[idx_agent] if idx_agent < len(r) else ""
                    metrics = get_metric_row_values(header, r)
                    mapping[(day, agent)] = metrics
                expected_pairs = []
                for day, agents in expected_by_day_agent.items():
                    for agent, expm in agents.items():
                        expected_pairs.append((day, agent, expm))
                if set((d, a) for d, a, _ in expected_pairs) == set(mapping.keys()):
                    for d, a, expm in expected_pairs:
                        mv = mapping.get((d, a), {})
                        if not all(mv.get(k) == v for k, v in expm.items()):
                            ok = False
                            break
                else:
                    ok = False
                checks["by_day_agent_csv_exact"] = ok

    by_agent_csv = os.path.join(csv_dir, "by_agent.csv")
    if os.path.isfile(by_agent_csv):
        header, rows = load_csv_rows(by_agent_csv)
        if header is not None:
            idx_agent = find_col_index(header, "agent")
            if idx_agent >= 0 and len(rows) == 2:
                mapping = {}
                for r in rows:
                    agent = r[idx_agent] if idx_agent < len(r) else ""
                    mapping[agent] = get_metric_row_values(header, r)
                ok = set(mapping.keys()) == set(expected_by_agent.keys())
                if ok:
                    for agent, expm in expected_by_agent.items():
                        mv = mapping.get(agent, {})
                        if not all(mv.get(k) == v for k, v in expm.items()):
                            ok = False
                            break
                checks["by_agent_csv_exact"] = ok

    by_model_csv = os.path.join(csv_dir, "by_model.csv")
    if os.path.isfile(by_model_csv):
        header, rows = load_csv_rows(by_model_csv)
        if header is not None:
            idx_model = find_col_index(header, "model")
            if idx_model >= 0 and len(rows) == len(expected_by_model):
                mapping = {}
                for r in rows:
                    model_key = r[idx_model] if idx_model < len(r) else ""
                    mapping[model_key] = get_metric_row_values(header, r)
                ok = set(mapping.keys()) == set(expected_by_model.keys())
                if ok:
                    for mk, expm in expected_by_model.items():
                        mv = mapping.get(mk, {})
                        if not all(mv.get(k) == v for k, v in expm.items()):
                            ok = False
                            break
                checks["by_model_csv_exact"] = ok

    by_session_csv = os.path.join(csv_dir, "by_session.csv")
    if os.path.isfile(by_session_csv):
        header, rows = load_csv_rows(by_session_csv)
        if header is not None:
            idx_agent = find_col_index(header, "agent")
            idx_session = find_col_index(header, "sessionKey")
            idx_transcript = find_col_index(header, "transcript")
            if idx_session >= 0 and idx_transcript >= 0 and len(rows) == len(expected_sessions):
                mapping = {}
                ok = True
                for r in rows:
                    sess = r[idx_session] if idx_session < len(r) else ""
                    mapping[sess] = {
                        "agent": (r[idx_agent] if idx_agent >= 0 and idx_agent < len(r) else ""),
                        "transcript": (r[idx_transcript] if idx_transcript < len(r) else ""),
                        "metrics": get_metric_row_values(header, r),
                    }
                if set(mapping.keys()) == set(expected_sessions.keys()):
                    for sk, spec in expected_sessions.items():
                        got = mapping.get(sk, {})
                        if got.get("transcript") != spec["transcript"]:
                            ok = False
                            break
                        mv = got.get("metrics", {})
                        if not all(mv.get(k) == v for k, v in spec["metrics"].items()):
                            ok = False
                            break
                else:
                    ok = False
                checks["by_session_csv_exact"] = ok

    by_day_session_csv = os.path.join(csv_dir, "by_day_session.csv")
    if os.path.isfile(by_day_session_csv):
        header, rows = load_csv_rows(by_day_session_csv)
        if header is not None:
            idx_day = find_col_index(header, "day")
            idx_session = find_col_index(header, "sessionKey")
            idx_transcript = find_col_index(header, "transcript")
            if idx_day >= 0 and idx_session >= 0 and idx_transcript >= 0 and len(rows) == 3:
                mapping = {}
                for r in rows:
                    day = r[idx_day] if idx_day < len(r) else ""
                    sess = r[idx_session] if idx_session < len(r) else ""
                    mapping[(day, sess)] = {
                        "transcript": (r[idx_transcript] if idx_transcript < len(r) else ""),
                        "metrics": get_metric_row_values(header, r),
                    }
                expected_pairs = {
                    ("2026-03-14", "alpha-20260314-A"),
                    ("2026-03-15", "alpha-20260315-B"),
                    ("2026-03-15", "beta-20260315-X"),
                }
                ok = set(mapping.keys()) == expected_pairs
                if ok:
                    for (day, sess) in expected_pairs:
                        spec = expected_sessions[sess]
                        got = mapping.get((day, sess), {})
                        if got.get("transcript") != spec["transcript"]:
                            ok = False
                            break
                        mv = got.get("metrics", {})
                        if not all(mv.get(k) == v for k, v in spec["metrics"].items()):
                            ok = False
                            break
                checks["by_day_session_csv_exact"] = ok

    # Markdown report checks
    report_path = os.path.join(usage_dir, "report.md")
    report_text = ""
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_text = f.read()
        except Exception:
            report_text = ""
        # total tokens present (allow "2460" or "2,460")
        if ("2460" in report_text) or ("2,460" in report_text):
            checks["report_has_total_tokens"] = True
        # Top 3 sessions presence: verify all three session keys appear somewhere
        required_sessions = ["beta-20260315-X", "alpha-20260315-B", "alpha-20260314-A"]
        if all(sk in report_text for sk in required_sessions):
            checks["report_has_top3_sessions"] = True

    # Reward calculation: proportion of checks passed, baseline 0 if no outputs (no-op)
    num_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # If no meaningful outputs exist (json and csv and report missing), reward must be 0.0
    # Already handled by proportion, but ensure exact 0.0 when nothing passed.
    reward = 0.0
    if passed > 0:
        reward = passed / num_checks

    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()