import json
import os
import re
import sys
from collections import defaultdict

def read_jsonl(path):
    entries = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                    entries.append(obj)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return entries

def get_session_entries(input_sessions_dir):
    # Return list of dicts with date, input, output, cacheRead, cacheWrite, cost
    calls = []
    if not os.path.isdir(input_sessions_dir):
        return calls
    for fname in os.listdir(input_sessions_dir):
        if not fname.endswith(".jsonl"):
            continue
        fpath = os.path.join(input_sessions_dir, fname)
        for obj in read_jsonl(fpath):
            # Extract timestamp and usage
            ts = obj.get("timestamp", "")
            if not ts:
                ts = obj.get("message", {}).get("timestamp", "")
            if not ts or len(ts) < 10:
                continue
            date = ts[:10]
            usage = obj.get("message", {}).get("usage", {})
            if not isinstance(usage, dict):
                usage = {}
            cost = None
            cost_obj = usage.get("cost")
            if isinstance(cost_obj, dict) and "total" in cost_obj:
                try:
                    cost = float(cost_obj.get("total", 0) or 0)
                except Exception:
                    cost = 0.0
            # Only count calls that have a cost entry (per task spec logic)
            if cost is None:
                continue
            def _int(v):
                try:
                    return int(v)
                except Exception:
                    return 0
            calls.append({
                "date": date,
                "input": _int(usage.get("input", 0)),
                "output": _int(usage.get("output", 0)),
                "cacheRead": _int(usage.get("cacheRead", 0)),
                "cacheWrite": _int(usage.get("cacheWrite", 0)),
                "cost": cost
            })
    return calls

def compute_last_two_days_totals(calls):
    # calls: list of dicts with date, usage, cost
    dates = sorted(set(c["date"] for c in calls))
    if not dates:
        return [], {"calls": 0, "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "cost": 0.0}, {}
    last_two = dates[-2:] if len(dates) >= 2 else dates[-1:]
    # Aggregate per-day
    per_day = defaultdict(lambda: {"calls": 0, "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "cost": 0.0})
    for c in calls:
        d = c["date"]
        per_day[d]["calls"] += 1
        per_day[d]["input"] += c["input"]
        per_day[d]["output"] += c["output"]
        per_day[d]["cacheRead"] += c["cacheRead"]
        per_day[d]["cacheWrite"] += c["cacheWrite"]
        per_day[d]["cost"] += c["cost"]
    # Aggregate totals across last two days
    totals = {"calls": 0, "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "cost": 0.0}
    for d in last_two:
        totals["calls"] += per_day[d]["calls"]
        totals["input"] += per_day[d]["input"]
        totals["output"] += per_day[d]["output"]
        totals["cacheRead"] += per_day[d]["cacheRead"]
        totals["cacheWrite"] += per_day[d]["cacheWrite"]
        totals["cost"] += per_day[d]["cost"]
    return last_two, totals, per_day

def parse_cost_report(path, expected):
    """
    expected: dict with keys:
      total_cost_2d (float), percent_2d (int), per_day_costs (dict date->float with 2 decimals),
      counts (dict with calls, input, output, cacheRead ints),
      alerts (dict with over_500k_input, over_5k_output ints),
      dates_all (set of all dates present in input)
    Return dict of booleans for each check.
    """
    checks = {
        "has_cost_report": False,
        "cost_summary_line_ok": False,
        "cost_per_day_lines_ok": False,
        "cost_counts_line_ok": False,
        "cost_alerts_lines_ok": False,
        "cost_recommendations_ok": False
    }
    if not os.path.isfile(path):
        return checks
    checks["has_cost_report"] = True
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines()]
    except Exception:
        return checks
    # Find first non-empty line
    first_non_empty = None
    for ln in lines:
        if ln.strip():
            first_non_empty = ln
            break
    # Summary line format and values
    if first_non_empty:
        m = re.match(r'^COST \(last 2 days\): \$([0-9]+(?:\.[0-9]{2})) \/ \$10\.00 \(([0-9]+)%\)$', first_non_empty)
        if m:
            total_str = m.group(1)
            percent_str = m.group(2)
            try:
                total_val = float(total_str)
            except Exception:
                total_val = None
            try:
                percent_val = int(percent_str)
            except Exception:
                percent_val = None
            # Compare to expected with 2-dec formatting
            exp_total_rounded = float(f"{expected['total_cost_2d']:.2f}")
            exp_percent = expected["percent_2d"]
            if total_val == exp_total_rounded and percent_val == exp_percent:
                checks["cost_summary_line_ok"] = True
    # Per-day lines for each date present in logs
    # Expect lines in form YYYY-MM-DD: $X.XX for all dates present in input
    per_day_ok = True
    needed_dates = sorted(expected["dates_all"])
    found_map = {}
    for ln in lines:
        mm = re.match(r'^(\d{4}-\d{2}-\d{2}): \$([0-9]+(?:\.[0-9]{2}))$', ln.strip())
        if mm:
            d = mm.group(1)
            if d in needed_dates:
                try:
                    v = float(mm.group(2))
                except Exception:
                    v = None
                found_map[d] = v
    for d in needed_dates:
        exp_v = float(f"{expected['per_day_costs'].get(d, 0.0):.2f}")
        v = found_map.get(d)
        if v is None or v != exp_v:
            per_day_ok = False
            break
    checks["cost_per_day_lines_ok"] = per_day_ok
    # Counts line
    counts_ok = False
    exp_counts = expected["counts"]
    for ln in lines:
        mm = re.match(r'^([0-9]+) calls \| ([0-9]+) in \+ ([0-9]+) out \+ ([0-9]+) cached$', ln.strip())
        if mm:
            calls = int(mm.group(1))
            inp = int(mm.group(2))
            out = int(mm.group(3))
            cached = int(mm.group(4))
            if (calls == exp_counts["calls"] and inp == exp_counts["input"]
                and out == exp_counts["output"] and cached == exp_counts["cacheRead"]):
                counts_ok = True
                break
    checks["cost_counts_line_ok"] = counts_ok
    # Alerts lines
    alerts_ok = False
    inp_count = None
    out_count = None
    for ln in lines:
        mm_inp = re.match(r'^over_500k_input: ([0-9]+)$', ln.strip())
        if mm_inp:
            inp_count = int(mm_inp.group(1))
        mm_out = re.match(r'^over_5k_output: ([0-9]+)$', ln.strip())
        if mm_out:
            out_count = int(mm_out.group(1))
    if (inp_count is not None and out_count is not None and
        inp_count == expected["alerts"]["over_500k_input"] and
        out_count == expected["alerts"]["over_5k_output"]):
        alerts_ok = True
    checks["cost_alerts_lines_ok"] = alerts_ok
    # Recommendations section existence and contains Haiku, Sonnet, Opus
    rec_ok = False
    rec_idx = None
    for i, ln in enumerate(lines):
        if "Recommendations" in ln:
            rec_idx = i
            break
    if rec_idx is not None:
        # Gather subsequent lines until next blank or end
        buf = []
        for j in range(rec_idx + 1, len(lines)):
            if not lines[j].strip():
                break
            buf.append(lines[j])
        section_text = "\n".join(buf)
        if ("Haiku" in section_text) and ("Sonnet" in section_text) and ("Opus" in section_text):
            rec_ok = True
    checks["cost_recommendations_ok"] = rec_ok
    return checks

def compute_alerts_for_last_two_days(calls, last_two_dates):
    over_500k_input = 0
    over_5k_output = 0
    for c in calls:
        if c["date"] in last_two_dates:
            if c["input"] > 500000:
                over_500k_input += 1
            if c["output"] > 5000:
                over_5k_output += 1
    return {"over_500k_input": over_500k_input, "over_5k_output": over_5k_output}

def parse_context_report(path, expected_tokens_map, subtotal_expected):
    checks = {
        "has_context_report": False,
        "context_lines_ok": False,
        "context_subtotal_ok": False
    }
    if not os.path.isfile(path):
        return checks
    checks["has_context_report"] = True
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines()]
    except Exception:
        return checks
    # Parse lines of format "<tokens> tokens  <FILENAME> [FLAG]"
    found = {}
    for ln in lines:
        mm = re.match(r'^([0-9]+)\s+tokens\s+([A-Z]+\.md)(?:\s+(TRIM|WARN))?$', ln.strip())
        if mm:
            tokens = int(mm.group(1))
            fname = mm.group(2)
            flag = mm.group(3) if mm.group(3) else ""
            found[fname] = (tokens, flag)
    all_ok = True
    for fname, tok in expected_tokens_map.items():
        if fname not in found:
            all_ok = False
            break
        tokens, flag = found[fname]
        if tokens != tok:
            all_ok = False
            break
        # Check flags
        expected_flag = ""
        if tok > 1000:
            expected_flag = "TRIM"
        elif tok > 500:
            expected_flag = "WARN"
        else:
            expected_flag = ""
        if expected_flag != flag:
            all_ok = False
            break
    checks["context_lines_ok"] = all_ok
    # Check subtotal line
    subtotal_ok = False
    exp_line = f"SUBTOTAL: {subtotal_expected} tokens"
    for ln in lines:
        if ln.strip() == exp_line:
            subtotal_ok = True
            break
    checks["context_subtotal_ok"] = subtotal_ok
    return checks

def estimate_tokens_from_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return len(content) // 4
    except Exception:
        return 0

def extract_wikilinks_from_text(text):
    links = []
    for m in re.finditer(r"\[\[([^\]]+)\]\]", text):
        raw = m.group(1)
        name = raw.split("|", 1)[0].strip()
        if name:
            links.append(name)
    return links

def compute_mindgraph_expectations(input_docs_dir):
    # Return dict: file_nodes_count, link_count, concept_nodes_count
    files = []
    basenames = set()
    if os.path.isdir(input_docs_dir):
        for root, _, fnames in os.walk(input_docs_dir):
            for f in fnames:
                if f.endswith(".md"):
                    fp = os.path.join(root, f)
                    files.append(fp)
                    basenames.add(os.path.splitext(f)[0].lower())
    link_count = 0
    unresolved = set()
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception:
            text = ""
        links = extract_wikilinks_from_text(text)
        link_count += len(links)
        for name in links:
            norm = name.lower()
            if norm not in basenames:
                unresolved.add(norm)
    file_nodes_count = len(files)
    concept_nodes_count = len(unresolved)
    return {
        "file_nodes_count": file_nodes_count,
        "link_count": link_count,
        "concept_nodes_count": concept_nodes_count
    }

def parse_mindgraph_json(path, exp):
    checks = {
        "has_mindgraph": False,
        "mindgraph_keys_ok": False,
        "mindgraph_counts_ok": False,
        "mindgraph_concepts_ok": False
    }
    if not os.path.isfile(path):
        return checks
    checks["has_mindgraph"] = True
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
    except Exception:
        return checks
    # Keys check
    keys_ok = (
        isinstance(data, dict) and
        "nodes" in data and isinstance(data["nodes"], dict) and
        "nameMap" in data and isinstance(data["nameMap"], dict) and
        "nodeCount" in data and isinstance(data["nodeCount"], int) and
        "linkCount" in data and isinstance(data["linkCount"], int)
    )
    checks["mindgraph_keys_ok"] = keys_ok
    counts_ok = False
    concepts_ok = False
    if keys_ok:
        expected_node_count = exp["file_nodes_count"] + exp["concept_nodes_count"]
        if data["nodeCount"] == expected_node_count and data["linkCount"] == exp["link_count"]:
            counts_ok = True
        checks["mindgraph_counts_ok"] = counts_ok
        # Concept presence if unresolved links exist
        if exp["concept_nodes_count"] > 0:
            concepts_ok = data["nodeCount"] > exp["file_nodes_count"]
        else:
            # If no unresolved links, concept requirement passes trivially (no need)
            concepts_ok = True
        checks["mindgraph_concepts_ok"] = concepts_ok
    return checks

def parse_journal_prompt(path, input_prompts_path):
    checks = {
        "has_journal_prompt": False,
        "journal_prompt_ok": False
    }
    if not os.path.isfile(path):
        return checks
    checks["has_journal_prompt"] = True
    # Load expected prompt
    try:
        with open(input_prompts_path, "r", encoding="utf-8", errors="ignore") as f:
            prompts = json.load(f)
    except Exception:
        return checks
    evening = prompts.get("evening", [])
    expected_line = None
    if isinstance(evening, list) and len(evening) >= 3 and isinstance(evening[2], str):
        expected_line = evening[2]
    else:
        # Cannot compute expected without proper input
        return checks
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return checks
    # Check exactly one line with the expected prompt
    lines = [ln.rstrip("\n") for ln in content.splitlines()]
    if len(lines) == 1 and lines[0] == expected_line:
        checks["journal_prompt_ok"] = True
    return checks

def parse_alignment_json(path):
    checks = {
        "has_alignment_json": False,
        "alignment_json_ok": False
    }
    if not os.path.isfile(path):
        return checks
    checks["has_alignment_json"] = True
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
    except Exception:
        return checks
    expected = {"moments_per_day": 1440, "thermal_cap_gw": 15, "block_parity_science": "ODD"}
    if isinstance(data, dict) and data == expected:
        checks["alignment_json_ok"] = True
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks dict with all flags False
    checks = {
        "has_cost_report": False,
        "cost_summary_line_ok": False,
        "cost_per_day_lines_ok": False,
        "cost_counts_line_ok": False,
        "cost_alerts_lines_ok": False,
        "cost_recommendations_ok": False,
        "has_context_report": False,
        "context_lines_ok": False,
        "context_subtotal_ok": False,
        "has_mindgraph": False,
        "mindgraph_keys_ok": False,
        "mindgraph_counts_ok": False,
        "mindgraph_concepts_ok": False,
        "has_journal_prompt": False,
        "journal_prompt_ok": False,
        "has_alignment_json": False,
        "alignment_json_ok": False
    }

    # 1) Cost report checks
    sessions_dir = os.path.join(input_dir, "sessions")
    calls = get_session_entries(sessions_dir)
    last_two_dates, totals_2d, per_day = compute_last_two_days_totals(calls)
    total_cost_2d = totals_2d["cost"]
    percent_2d = int(round((total_cost_2d / 10.0) * 100)) if 10.0 else 0
    per_day_costs = {d: per_day.get(d, {"cost": 0.0})["cost"] for d in sorted(set(c["date"] for c in calls))}
    alerts = compute_alerts_for_last_two_days(calls, set(last_two_dates))
    expected_cost = {
        "total_cost_2d": total_cost_2d,
        "percent_2d": percent_2d,
        "per_day_costs": per_day_costs,
        "counts": {
            "calls": totals_2d["calls"],
            "input": totals_2d["input"],
            "output": totals_2d["output"],
            "cacheRead": totals_2d["cacheRead"]
        },
        "alerts": alerts,
        "dates_all": set(per_day_costs.keys())
    }
    cost_report_path = os.path.join(output_dir, "cost_report.txt")
    cost_checks = parse_cost_report(cost_report_path, expected_cost)
    checks.update(cost_checks)

    # 2) Context bloat check
    workspace_input_dir = os.path.join(input_dir, "workspace")
    always_files = ["SOUL.md", "AGENTS.md", "USER.md", "IDENTITY.md", "TOOLS.md", "HEARTBEAT.md", "MEMORY.md"]
    tokens_map = {}
    for fname in always_files:
        fpath = os.path.join(workspace_input_dir, fname)
        tokens_map[fname] = estimate_tokens_from_file(fpath)
    subtotal_tokens = sum(tokens_map.values())
    context_report_path = os.path.join(output_dir, "context_report.txt")
    context_checks = parse_context_report(context_report_path, tokens_map, subtotal_tokens)
    checks.update(context_checks)

    # 3) Mindgraph index checks
    docs_dir = os.path.join(input_dir, "docs")
    mg_exp = compute_mindgraph_expectations(docs_dir)
    mindgraph_path = os.path.join(output_dir, "mindgraph.json")
    mind_checks = parse_mindgraph_json(mindgraph_path, mg_exp)
    checks.update(mind_checks)

    # 4) Daily journaling prompt
    journal_prompt_path = os.path.join(output_dir, "journal_prompt.md")
    input_prompts_path = os.path.join(input_dir, "prompts.json")
    journal_checks = parse_journal_prompt(journal_prompt_path, input_prompts_path)
    checks.update(journal_checks)

    # 5) Alignment facts JSON
    alignment_path = os.path.join(output_dir, "alignment.json")
    alignment_checks = parse_alignment_json(alignment_path)
    checks.update(alignment_checks)

    # Compute reward: fraction of passed checks, with no-op baseline 0.0
    total_checks = len([k for k in checks.keys() if k not in ("has_cost_report", "has_context_report", "has_mindgraph", "has_journal_prompt", "has_alignment_json")]) + 5
    # Simpler: count all booleans in checks
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = round(passed / len(checks), 4)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()